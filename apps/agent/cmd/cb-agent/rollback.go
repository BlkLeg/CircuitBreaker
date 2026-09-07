// Update rollback: the guard that puts the previous binary back when a new one
// starts but never reaches a hello-acked connection.
//
// Split out of main.go, which held the whole command in one 1,844-line file.
// Same package, so nothing about the build or the symbols changed.

package main

import (
	"log"
	"os"
	"strconv"
	"time"

	"circuitbreaker.dev/cb-agent/internal/logging"
	"circuitbreaker.dev/cb-agent/internal/update"
)

// rollbackWindow is how long runDaemon, after resuming with a pending update
// marker (internal/update.WriteMarker), waits for a successful hello.ack-
// gated OnConnected (Task 4) to clear that marker before concluding the
// update never confirmed and rolling back to the previous binary. A var, not
// a const, so tests can shrink it rather than waiting out the production
// value — mirrors internal/link's stabilityWindow/rekeyInterval pattern.
var rollbackWindow = 2 * time.Minute

// reExecDelayEnvOverride is a narrowly-scoped, test-only escape hatch,
// mirroring internal/link's rekeyIntervalEnvOverride: if set to a positive
// integer number of milliseconds, onUpdate sleeps that long immediately
// before re-exec'ing into the newly-swapped binary. It exists solely so the
// Docker E2E harness (apps/agent/e2e) can reliably win the race against a
// freshly re-exec'd process reconnecting and self-confirming an update
// before the test's own docker-network-disconnect trigger can land — on a
// local Docker bridge network, re-exec-to-hello.ack routinely completes in
// well under 100ms, faster than an external log-poll-then-subprocess-spawn
// trigger can reliably beat. No production deployment path (the install
// script, systemd unit, or any documented config) ever sets this variable;
// when it is unset, as in every real deployment, onUpdate re-execs
// immediately, exactly as it always has.
const reExecDelayEnvOverride = "CB_AGENT_TEST_PRE_REEXEC_DELAY_MS"

// resolveReExecDelay reads reExecDelayEnvOverride. Split out from inline use
// purely so a unit test can call it directly without depending on process
// env at the actual call site.
func resolveReExecDelay() time.Duration {
	if v := os.Getenv(reExecDelayEnvOverride); v != "" {
		if ms, err := strconv.Atoi(v); err == nil && ms > 0 {
			return time.Duration(ms) * time.Millisecond
		}
	}
	return 0
}

// installedBinaryPath is the stable, root-owned symlink systemd's
// ExecStart and an operator's interactive shell use
// (/etc/systemd/system/cb-agent.service, agent_install.py's install
// script) — see specs/2026-08-05-cb-agent-self-update-fix-design.md.
// Self-update never touches this path directly; it only ever re-points
// {stateDir}/current, the middle symlink this one points through.
const installedBinaryPath = "/usr/local/bin/cb-agent"

// rollbackExpiredUpdate is runDaemon's startup half of the rollback safety
// net: it restores the previous binary when the marker on disk names an update
// that was swapped in but never confirmed before its deadline, then re-execs
// into it.
//
// It is the durable counterpart to watchForRollback. That one covers the live
// case — the agent is up, enrolled and talking, but a post-update hello.ack
// never lands — and cannot cover the case where the update itself is what
// severed the connection, because it is spawned after a fatal enroll.Run and
// its window is an in-process sleep that a restart resets. This one is
// evaluated from disk before any network call, so a crash-looping agent
// converges on a rollback rather than looping on a broken build forever.
//
// reExec is a parameter for the same reason watchForRollback takes one: so a
// test can observe the decision without replacing its own process image.
func rollbackExpiredUpdate(stateDir, currentLink string, now time.Time, reExec func() error) {
	rolledBackFrom, err := update.RollbackIfExpired(stateDir, currentLink, now)
	if err != nil {
		log.Printf("cb-agent: %v", err)
		return
	}
	if rolledBackFrom == "" {
		return
	}
	log.Printf("cb-agent: update to %s never confirmed before its rollback deadline — rolled back, re-executing", rolledBackFrom)
	if err := reExec(); err != nil {
		logging.Errorf("cb-agent: re-exec after rollback failed: %v", err)
	}
}

// watchForRollback waits up to rollbackWindow for the update marker naming
// pendingVersion to be cleared — which onConnected (wired in runDaemon)
// does exactly once, the moment a post-update connection reaches an
// accepted hello.ack (Task 4's OnConnected gating, not merely a completed
// Noise handshake). If the marker is still present and still names
// pendingVersion once the window elapses, the update never confirmed:
// watchForRollback re-points currentLink back to the marker's recorded
// prevVersionDir (update.Rollback), persists a rollback report for the next
// connection to send (this process has no live link to report over —
// that's exactly why it's rolling back), clears the marker, and re-execs
// via reExec.
//
// If the marker is still present but was never confirmed to have reached
// phasePendingConfirm (update.ReadMarker's swapped == false), then
// update.Swap never actually ran for this attempt — most likely a crash
// landed between WriteMarker and Swap in onUpdate. There is nothing to roll
// back: currentLink was never re-pointed, and prevVersionDir (if the marker
// even carries one) belongs to some earlier, already-confirmed update, not
// this one — using it here would silently downgrade a healthy running
// binary to a stale, unrelated version. The marker is simply cleared and
// the abandoned attempt logged.
//
// reExec is a parameter rather than a direct syscall.Exec call so tests can
// observe a rollback decision without actually replacing the test binary's
// process image; runDaemon passes a closure that does call syscall.Exec.
func watchForRollback(stateDir, currentLink, pendingVersion string, window time.Duration, reExec func() error) {
	time.Sleep(window)

	v, prevVersionDir, swapped, stillPresent, err := update.ReadMarker(stateDir)
	if err != nil {
		log.Printf("cb-agent: %v", err)
		return
	}
	if !stillPresent || v != pendingVersion {
		// Cleared by onConnected (confirmed) or superseded by a newer
		// update's marker — either way, this window's job is done.
		return
	}
	if !swapped {
		log.Printf("cb-agent: update to %s never completed its binary swap (crashed before Swap ran) — nothing to roll back, clearing marker", pendingVersion)
		if err := update.ClearMarker(stateDir); err != nil {
			log.Printf("cb-agent: %v", err)
		}
		return
	}

	log.Printf("cb-agent: update to %s did not confirm within %s — rolling back", pendingVersion, window)
	if err := update.Rollback(currentLink, prevVersionDir); err != nil {
		// Rollback failed (empty prevVersionDir, a symlink error, ...): the
		// marker must still be cleared here. Leaving it in place
		// would re-arm this exact same doomed rollback attempt on every
		// subsequent restart, forever, until some unrelated hello.ack
		// eventually clears it via the normal success path — a permanently
		// stuck retry loop for no benefit, since there is nothing further
		// waiting on the marker either way: the currently-running binary is
		// whatever it already is regardless of whether the marker is
		// cleared now or later.
		logging.Errorf("cb-agent: rollback failed: %v — clearing marker to avoid a permanently stuck retry loop", err)
		if clearErr := update.ClearMarker(stateDir); clearErr != nil {
			log.Printf("cb-agent: %v", clearErr)
		}
		return
	}
	// This process has no live /link connection to report the rollback over
	// (that's precisely why it's rolling back) — persist it so the process
	// re-exec'd below, once it reconnects, sends the
	// update.status(rolled_back) frame (see
	// internal/update.WriteRollbackReport's doc comment).
	if err := update.WriteRollbackReport(stateDir, pendingVersion); err != nil {
		log.Printf("cb-agent: %v", err)
	}
	if err := update.ClearMarker(stateDir); err != nil {
		log.Printf("cb-agent: %v", err)
	}
	if err := reExec(); err != nil {
		logging.Errorf("cb-agent: re-exec after rollback failed: %v", err)
	}
}
