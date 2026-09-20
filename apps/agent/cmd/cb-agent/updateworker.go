// The daemon's serialized self-update worker: everything `cb-agent` does
// between receiving a server `update` instruction and re-exec'ing into the
// new binary, moved off the link's event-loop goroutine.
//
// Same package as daemon.go — a file boundary, not an API one. The link's
// Options.OnUpdate is the enqueue boundary this worker sits behind; the
// worker's status reports cross back to the link through a channel the
// event loop drains, so the one-writer rule and sequence ownership never
// move off the event-loop goroutine.

package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"os"
	"sync"
	"sync/atomic"
	"syscall"
	"time"

	"circuitbreaker.dev/cb-agent/internal/config"
	"circuitbreaker.dev/cb-agent/internal/link"
	"circuitbreaker.dev/cb-agent/internal/update"
)

// updateStatusQueueDepth is the buffer depth of the channel the update worker
// reports through and every runOnce drains (link.Options.UpdateStatusFrames).
//
// Four is the smallest depth that makes "the worker never blocks on the
// channel" structural rather than hopeful: one update reports at most a
// started+terminal pair, the worker executes at most one job at a time, and a
// second instruction is only accepted once the first finished — so two jobs'
// worth of events is the most that can ever be pending. A send beyond capacity
// would mean a bug elsewhere, and report() is ctx-guarded so even that
// degenerates to a dropped status rather than a deadlock.
const updateStatusQueueDepth = 4

// errUpdateInProgress is the deterministic refusal the enqueue boundary
// returns while an update is queued or running. The exact
// wording is the contract: runOnce reports it verbatim as the failed
// update's error text, the backend stores it on the agent timeline, and
// cmd/cb-agent's worker tests assert it.
var errUpdateInProgress = errors.New("update already in progress")

// updateJob is one validated server instruction plus everything the worker
// needs to execute it (the update-job type). The payload is parsed at the
// enqueue boundary, not here: the link's TypeUpdate arm must return to its
// select loop immediately, so validation belongs to the boundary that can
// refuse the instruction synchronously, and the worker then works from a
// value it knows parsed.
type updateJob struct {
	instr update.Instruction
}

// updateWorker is the daemon's single serialized update executor. One
// worker, one in-flight job, one pending slot behind it (jobC's capacity-1
// queue): a second instruction that arrives while one is queued or
// running is refused with errUpdateInProgress rather than applied
// concurrently — a second swap racing the first could interleave marker
// writes and symlink repointing against each other, and both instructions
// re-exec, so the loser's process replacement is undefined.
type updateWorker struct {
	ctx      context.Context
	cfg      *config.Config
	stateDir string
	jobC     chan updateJob
	statusC  chan link.UpdateStatusEvent

	// busy is the serialize gate: true from the moment an instruction is
	// accepted until its job finishes executing — deliberately wider than
	// jobC's occupancy, because a dequeued job leaves the queue empty while
	// still mid-flight, and a second instruction accepted in that window
	// would not be "refused while running" but queued behind it.
	// Atomic CAS in enqueue: exactly one instruction is admitted between
	// idle states, queue slot or not.
	busy atomic.Bool

	// inFlightVersion names the instruction `busy` is currently gating.
	//
	// A refusal has to say *which* refusal it is. The server delivers every
	// update twice by design (an immediate control-frame push and a
	// Redis-queued entry the link poll picks up), so a second instruction for
	// the version already running is routine and the running attempt owns the
	// outcome. A second instruction for a *different* version is genuinely
	// dropped work the server is still waiting on. Only the first may be
	// reported as anything other than a failure — see link.ErrUpdateAlreadyRunning.
	//
	// Written under the same CAS that sets `busy`, so it is never read for an
	// instruction that was not admitted.
	inFlightVersion atomic.Value // string

	// execute performs one whole update (download, verify, marker, swap,
	// persist outcome, report, re-exec). A construction-time seam, for the
	// same reason watchForRollback takes reExec as a parameter: tests must
	// be able to block the update's goroutine — the exact case the
	// heartbeat-during-update regression test needs — and observe its
	// cancellation, without replacing the production sequence. Captured
	// synchronously at construction so the worker goroutine never races a
	// test restoring it (same pattern as startDaemonState's seams).
	execute func(ctx context.Context, job updateJob, report func(link.UpdateStatusEvent) error, exec func() error) error

	// exec replaces the process image once an update lands. A seam so tests
	// can assert the re-exec happened without their own process image being
	// replaced. Production passes syscall.Exec against installedBinaryPath.
	exec func() error

	wg sync.WaitGroup
}

// newUpdateWorker builds the daemon's worker. statusC is the same channel
// handed to link.Run as Options.UpdateStatusFrames — the worker is its only
// producer and the link's event loop its only consumer, which is the entire
// single-writer story for update.status frames.
func newUpdateWorker(ctx context.Context, cfg *config.Config, stateDir string, statusC chan link.UpdateStatusEvent) *updateWorker {
	w := &updateWorker{
		ctx:      ctx,
		cfg:      cfg,
		stateDir: stateDir,
		jobC:     make(chan updateJob, 1),
		statusC:  statusC,
	}
	w.execute = w.executeUpdate
	w.exec = func() error {
		return syscall.Exec(installedBinaryPath, os.Args, os.Environ())
	}
	return w
}

// start launches the worker goroutine. Exactly once, from runDaemon, before
// link.Run: the worker must exist before any connection can deliver an
// instruction to it.
func (w *updateWorker) start() {
	w.wg.Add(1)
	go w.run()
}

// stop waits for the worker goroutine to exit. Bounded by the worker's ctx —
// a job mid-download aborts through its context-aware HTTP request,
// and the remaining local steps are sub-second — so shutdown never waits
// out downloadTimeout for a stalled response.
func (w *updateWorker) stop() {
	w.wg.Wait()
}

// enqueue is the link's Options.OnUpdate: validate the raw instruction,
// queue it, return. Called on the link's event-loop goroutine, so it must
// never block: the select is bounded by jobC's capacity (a full queue is a
// refusal, not a wait) and by ctx (a shutdown refuses new work).
func (w *updateWorker) enqueue(payload json.RawMessage) error {
	var instr update.Instruction
	if err := json.Unmarshal(payload, &instr); err != nil {
		return fmt.Errorf("update: malformed instruction: %w", err)
	}
	// ctx first, so a stopped worker's answer is deterministic: once the
	// daemon is shutting down no instruction is ever admitted, not even
	// into a queue slot nobody will drain (“stop accepting new work
	// when the parent context is cancelled”).
	if err := w.ctx.Err(); err != nil {
		return fmt.Errorf("update worker is stopping: %w", err)
	}
	// busy before the queue: a job that has been dequeued for execution
	// still has the worker occupied even though jobC is empty, and the
	// refusal must cover "queued or running" exactly. CAS makes the
	// check-and-admit one atomic step, so two instructions arriving
	// together cannot both win.
	if !w.busy.CompareAndSwap(false, true) {
		running, _ := w.inFlightVersion.Load().(string)
		if running != "" && running == instr.Version {
			// The dual-delivery duplicate. Not dropped work: the attempt
			// already running will report its own terminal outcome.
			return link.ErrUpdateAlreadyRunning
		}
		return errUpdateInProgress
	}
	w.inFlightVersion.Store(instr.Version)
	select {
	case w.jobC <- updateJob{instr: instr}:
		return nil
	case <-w.ctx.Done():
		w.busy.Store(false)
		return fmt.Errorf("update worker is stopping: %w", w.ctx.Err())
	default:
		// Unreachable while busy gates admission (jobC holds one job and
		// busy is cleared only after that job finished), but a send must
		// never block the event loop — refuse rather than wait.
		w.busy.Store(false)
		return errUpdateInProgress
	}
}

// report hands one status event to whatever runOnce is currently draining.
// ctx-guarded: the capacity argument in updateStatusQueueDepth's doc
// comment is why an unguarded send cannot hang in practice, but a shutdown
// racing a full channel must still exit the worker rather than park it
// forever — and a dropped status is recoverable precisely because terminal
// outcomes are durable.
func (w *updateWorker) report(ctx context.Context, evt link.UpdateStatusEvent) error {
	select {
	case w.statusC <- evt:
		return nil
	case <-ctx.Done():
		return ctx.Err()
	}
}

// run is the worker loop: one job at a time, forever, until ctx is
// cancelled. Nothing here writes to a socket or a marker file — that
// is all execute's.
func (w *updateWorker) run() {
	defer w.wg.Done()
	for {
		select {
		case <-w.ctx.Done():
			return
		case job := <-w.jobC:
			// The "update queued" observability line: the version is
			// the one operator-facing fact, and it is all that is logged —
			// never the payload, URL, or anything derived from them.
			log.Printf("cb-agent: update to %s accepted — executing off the link's event loop", job.instr.Version)
			err := w.execute(w.ctx, job, func(evt link.UpdateStatusEvent) error {
				return w.report(w.ctx, evt)
			}, w.exec)
			// busy stays set for exactly the life of the job (see enqueue):
			// cleared here, not in execute, so a test seam that
			// returns early cannot leave the worker stuck refusing work.
			w.busy.Store(false)
			if err != nil {
				if w.ctx.Err() != nil {
					// The "canceled" line: shutdown raced the update.
					// Not a failure — nothing further is owed to the
					// server, which re-issues the instruction after
					// restart.
					log.Printf("cb-agent: update to %s canceled by shutdown: %v", job.instr.Version, err)
					continue
				}
				// execute has already reported the user-facing failure
				// itself; this is the daemon-side record of the same fact.
				log.Printf("cb-agent: update to %s failed: %v", job.instr.Version, err)
			}
		}
	}
}

// executeUpdate is the update sequence itself. Its contract with runOnce is a
// channel: report() queues update.status events the event loop transmits,
// exec() replaces the process image on success (and never returns), and a
// non-nil return means the update did not land.
//
// Ordering rules that must not change: the trust policy is resolved once per
// update; the rollback marker is written before the swap; MarkSwapped is the
// transition that records the actual previous version and the confirmation
// deadline; and the pending outcome is persisted before the live succeeded
// send, so process replacement cannot discard the status before the backend
// receives it.
func (w *updateWorker) executeUpdate(
	ctx context.Context, job updateJob, report func(link.UpdateStatusEvent) error, exec func() error,
) error {
	instr := job.instr

	sendFailed := func(err error) {
		if rErr := report(link.UpdateStatusEvent{Version: instr.Version, Phase: "failed", ErrMsg: err.Error()}); rErr != nil {
			log.Printf("cb-agent: send failed update.status: %v", rErr)
		}
	}

	if err := report(link.UpdateStatusEvent{Version: instr.Version, Phase: "started"}); err != nil {
		log.Printf("cb-agent: send started update.status: %v", err)
	}
	// Resolved once and reused for the signature fetch below: two calls
	// could straddle an inbound tls.pin.rotate and fetch the binary and
	// its signature under different trust policies.
	trust := link.ResolveTrust(w.cfg, w.stateDir)
	tmpPath, err := update.Download(ctx, w.cfg, trust, instr)
	if err != nil {
		if ctx.Err() != nil {
			// Shutdown canceled the download mid-flight. Not a
			// failed update — nothing was installed, no marker was
			// written, no status is owed, and the server re-issues the
			// instruction once the daemon is back.
			log.Printf("cb-agent: update to %s canceled during download: %v", instr.Version, err)
			return err
		}
		sendFailed(err)
		return err
	}
	// Everything below is fast, non-interruptible local work, so this is
	// the one remaining cancellation checkpoint: a shutdown that lands
	// post-download must not write a marker or swap a binary into a process
	// that is on its way out. A cancellation landing *after* this
	// check still ends safely mid-sequence — the existing crash semantics
	// (pending-swap / pending-confirm marker states, the rollback window)
	// are exactly the machinery that handles an interrupted update, and a
	// half-finished shutdown is indistinguishable from a crash.
	if ctx.Err() != nil {
		os.Remove(tmpPath)
		log.Printf("cb-agent: update to %s canceled by shutdown before install", instr.Version)
		return ctx.Err()
	}
	if err := update.VerifySHA256(tmpPath, instr.SHA256); err != nil {
		os.Remove(tmpPath)
		sendFailed(err)
		return err
	}
	// The SHA-256 above proves only that the download matches what
	// the *server* said. That is worth nothing against a compromised
	// server, which can serve any binary along with a matching digest.
	// The detached signature is checked against a key embedded at build
	// time, which the server cannot influence.
	//
	// Placed before WriteMarker deliberately: a refused update must
	// leave no rollback marker behind, because nothing was installed.
	sigPath, sigErr := update.DownloadSignature(ctx, w.cfg, trust, instr)
	if sigPath != "" {
		defer os.Remove(sigPath)
	}
	verifyErr := sigErr
	if verifyErr == nil {
		verifyErr = update.VerifySignature(tmpPath, sigPath)
	}
	switch update.UpdateDecision(verifyErr, update.SignatureEnforced()) {
	case update.DecisionRefuse:
		os.Remove(tmpPath)
		sendFailed(verifyErr)
		return verifyErr
	case update.DecisionWarn:
		log.Printf("cb-agent: WARNING: update to %s was installed without a "+
			"verified signature (%v). Set CB_AGENT_UPDATE_ENFORCE_SIGNATURE=1 to "+
			"refuse instead; see `make agent-signing-key` if this build has no "+
			"embedded key.", instr.Version, verifyErr)
	}
	// The rollback marker must be durably written *before* the
	// binary is actually replaced, not after. If a crash lands between
	// these two steps, the marker still correctly names the version
	// that was about to be installed — a recoverable state, since the
	// swap never ran and there's nothing to roll back. Writing the
	// marker only after a successful Swap would instead let a crash in
	// that window leave a replaced (and possibly broken) binary running
	// with no marker at all — no rollback safety net.
	if err := update.WriteMarker(w.stateDir, instr.Version); err != nil {
		os.Remove(tmpPath)
		sendFailed(err)
		return err
	}
	prevVersionDir, err := update.Swap(tmpPath, instr.Version, w.stateDir)
	if err != nil {
		// The swap never happened — clear the marker rather than
		// leaving a stale one that would (harmlessly, but pointlessly)
		// send a future restart into a rollback attempt against a
		// version that was never installed.
		if clearErr := update.ClearMarker(w.stateDir); clearErr != nil {
			log.Printf("cb-agent: %v", clearErr)
		}
		sendFailed(err)
		return err
	}
	// Swap succeeded — durably transition the marker from phasePendingSwap to
	// phasePendingConfirm and record prevVersionDir (see update.MarkSwapped) so a
	// restart's watchForRollback can trust which version directory is genuinely
	// this update's own backup, not a stale one from an earlier, already-confirmed
	// update. The swap has already happened and cannot be undone from here, so a
	// failure is logged rather than treated as a failed update: it costs this
	// update its rollback safety net, not correctness.
	//
	// The deadline is stamped here, not at process start, so it measures from the
	// swap itself and survives the crash-loop an update that breaks connectivity
	// produces — see update.RollbackIfExpired.
	if err := update.MarkSwapped(w.stateDir, instr.Version, prevVersionDir, time.Now().Add(rollbackWindow)); err != nil {
		log.Printf("cb-agent: %v — update to %s already installed but will not be protected by the rollback window", err, instr.Version)
	}
	// persist the succeeded outcome *before* attempting the
	// live send. A successful local WebSocket write is not an
	// acknowledgement from the server, and re-exec replaces the process
	// image immediately after this — so without the record, a connection
	// drop in that exact window discards the status with no process left
	// to retry it. The re-exec'd process reports this record after its
	// first accepted hello.ack and clears it only after that send
	// succeeds, exactly as the rollback report has always done.
	if err := update.WritePendingOutcome(w.stateDir, instr.Version, "succeeded"); err != nil {
		// The persistence error is logged explicitly, never hidden
		// — but the update itself did land, so this is not a failure
		// status and must never become one. Only the replay net is
		// missing; the live send below is still the primary path.
		log.Printf("cb-agent: persisting pending update outcome: %v — the succeeded status will not be replayed if this send is lost", err)
	}
	if err := report(link.UpdateStatusEvent{Version: instr.Version, Phase: "succeeded"}); err != nil {
		log.Printf("cb-agent: send succeeded update.status: %v", err)
	}
	log.Printf("cb-agent: updated to %s — re-executing", instr.Version)
	if d := resolveReExecDelay(); d > 0 {
		// The test-only delay stays bounded against shutdown: ctx wins,
		// so a SIGTERM during the window still stops the daemon rather
		// than waiting it out.
		select {
		case <-time.After(d):
		case <-ctx.Done():
			return ctx.Err()
		}
	}
	return exec()
}
