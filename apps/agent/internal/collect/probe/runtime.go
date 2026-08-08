// Package probe executes server-assigned monitor checks on the agent (§5 of
// plans/2026-08-04-cbi-agent-slice3-remote-probe.md).
//
// The backend stays the authoritative scheduler: it decides what is due, mints a run id, and
// pushes exactly one fully-specified `probe.assign` control frame per check. This package holds
// no schedule of its own — it queues assignments, runs at most max_concurrent of them at a time,
// honors deadlines and `probe.cancel`, and emits exactly one `probe.result` data frame per run.
//
// The load-bearing constraint is where Assign runs. link.runOnce's inbound switch shares one
// goroutine with the websocket writer, the heartbeat ticker, the rekey ticker and the spool-drain
// ticker, and its `incoming` channel is unbuffered. A handler that probed inline would stall
// heartbeats (20s interval) past the server's 60s dead-link deadline and tear down the very link
// the result has to travel back over. So Assign and Cancel validate and enqueue only: no dialing,
// no resolving, no blocking on a consumer, no waiting on a checker.
//
// Scope is enforced here as well as server-side, and that duplication is the point (§3): a
// backend-approved assignment whose destination is outside *this agent's own* derived scope is
// still refused, before anything touches the network. The evaluator is internal/netscope, shared
// with the backend and pinned to one corpus — this package must never grow a CIDR opinion of its
// own.
package probe

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"net"
	"net/netip"
	"sync"
	"time"

	"circuitbreaker.dev/cb-agent/internal/frame"
	"circuitbreaker.dev/cb-agent/internal/netscope"
)

// QueueCapacity is §2's bound on how many assignments one agent holds. Past it, an assignment is
// *rejected* rather than dropped: the backend would otherwise wait out the run's entire deadline
// for a result that was never coming, and the operator would see a silent gap instead of a
// capacity problem.
const QueueCapacity = 100

// The two result bounds the ingest handler enforces as the first thing it does. Applying them
// here as well is not redundancy for its own sake: a result that trips either is rejected
// wholesale server-side, so a checker producing an over-long message would lose an otherwise
// perfectly good target observation.
const (
	MaxMsgChars     = 2000
	MaxDetailsBytes = 64 << 10
)

// The closed outcome set (§4). Only OutcomeCompleted says anything about the target; the other
// three preserve its last known state, which is why none of them ever carries samples.
const (
	OutcomeCompleted      = "completed"
	OutcomeExecutionError = "execution_error"
	OutcomeCancelled      = "cancelled"
	OutcomeRejected       = "rejected"
)

// maxRunIDLength bounds an id that is otherwise echoed verbatim into a frame. The server mints
// 32 lowercase hex characters; this is not a shape check (re-deriving or normalizing the id
// would make the result unmatchable) but a ceiling on what a compromised or buggy sender can
// make this agent carry around.
const maxRunIDLength = 64

// resolveTimeout bounds the one name lookup the runtime itself performs — the pre-dial scope
// check for a hostname target. Checkers do their own resolving with their own monitor-configured
// timeouts; this one exists only so a black-holed resolver cannot pin a concurrency slot for the
// whole deadline.
const resolveTimeout = 5 * time.Second

// slotPollInterval is how often the dispatcher re-reads max_concurrent while it is waiting for a
// free slot. Completion signals it directly (see releaseSlot), so this only covers the other
// direction: a grant that *raises* the limit takes effect within one poll instead of waiting for
// an in-flight check to finish.
const slotPollInterval = 20 * time.Millisecond

// resultBufferSize is the hand-off between the goroutines that produce results (the link
// goroutine for a synchronous refusal, one worker per in-flight check) and the single pump that
// forwards them to the outbound data-frame channel. Sized above QueueCapacity plus the maximum
// grantable concurrency so a stalled consumer never reaches back into a caller.
const resultBufferSize = 2 * QueueCapacity

// Errors Assign returns. They are sentinels because link logs them and Task 20's daemon wiring
// distinguishes them; the corresponding probe.result is emitted regardless, so the caller never
// has to translate one into a frame.
var (
	ErrQueueFull            = errors.New("probe: the assignment queue is full")
	ErrNotEnabled           = errors.New("probe: remote_probe is not enabled on this agent")
	ErrDuplicateRun         = errors.New("probe: a run with this id is already in flight")
	ErrUnsupportedCheckType = errors.New("probe: unsupported check type")
	ErrMalformedAssignment  = errors.New("probe: malformed assignment")
)

// Options configures a Runtime. Every field has a working default except the checker set in
// production, which is built from the registry when Checkers is nil.
type Options struct {
	// Checkers overrides the registry wholesale, keyed by check type. Tests inject stubs
	// through it; production leaves it nil.
	Checkers map[string]Checker
	// Scope is the agent's effective scope at construction time. Configure replaces it live.
	Scope netscope.Scope
	// MaxConcurrent is the grant's max_concurrent (1-100, default 20). Values below 1 are
	// clamped up rather than treated as "unlimited".
	MaxConcurrent int
	// Resolve is the name lookup used for the pre-dial scope check. Defaults to the system
	// resolver.
	Resolve Resolver
	// Now is the result clock. Defaults to time.Now().UTC().
	Now func() time.Time
}

// DefaultMaxConcurrent mirrors capability.DefaultRemoteProbeConfig().MaxConcurrent. It is
// restated rather than imported so this package does not depend on internal/capability — Task
// 20's daemon wiring is what reads the grant and calls Configure.
const DefaultMaxConcurrent = 20

// Runtime owns one agent's probe execution. Safe for concurrent use: Assign and Cancel are
// called from link's inbound goroutine, Configure and Disable from the capability-set path, and
// the workers run on their own goroutines.
type Runtime struct {
	out      chan<- frame.Frame
	results  chan frame.Frame
	queue    chan *run
	checkers map[string]Checker
	resolve  Resolver
	now      func() time.Time

	// slotFreed carries a completion signal to a dispatcher that is waiting on capacity. Cap 1
	// and sent to non-blockingly: it is a wake-up, not a queue.
	slotFreed chan struct{}

	mu            sync.Mutex
	scope         netscope.Scope
	maxConcurrent int
	enabled       bool
	inFlight      int
	runs          map[string]*run

	stopMu sync.Mutex
	cancel context.CancelFunc
}

// runState tracks one assignment through the queue. It exists so a cancellation can tell "not
// started yet" (close the run out immediately — nothing will ever run it) from "in flight"
// (cancel the context and let the worker report what the checker did with it).
type runState int

const (
	runQueued runState = iota
	runRunning
	runDone
)

type run struct {
	assign frame.ProbeAssignPayload
	ctx    context.Context
	cancel context.CancelFunc

	mu           sync.Mutex
	state        runState
	cancelled    bool
	cancelReason string
}

// result is one finished run's outcome, ready to become a probe.result payload.
type result struct {
	outcome string
	up      bool
	samples []frame.ProbeSample
	msg     string
	details map[string]any
}

// New builds a Runtime writing results to out. out must be link.Options.DataFrames, never
// ControlFrames: probe.result is a data frame, so it spools through an outage instead of being
// dropped while disconnected, and link's assertDataFrame panics on a control frame sent the
// other way.
//
// The returned Runtime accepts assignments immediately — Start only brings up the workers.
func New(out chan<- frame.Frame, opts Options) *Runtime {
	r := &Runtime{
		out:           out,
		results:       make(chan frame.Frame, resultBufferSize),
		queue:         make(chan *run, QueueCapacity),
		resolve:       opts.Resolve,
		now:           opts.Now,
		slotFreed:     make(chan struct{}, 1),
		scope:         opts.Scope,
		maxConcurrent: clampConcurrency(opts.MaxConcurrent),
		enabled:       true,
		runs:          map[string]*run{},
	}
	if r.resolve == nil {
		r.resolve = func(ctx context.Context, host string) ([]string, error) {
			return net.DefaultResolver.LookupHost(ctx, host)
		}
	}
	if r.now == nil {
		r.now = func() time.Time { return time.Now().UTC() }
	}
	r.checkers = opts.Checkers
	if r.checkers == nil {
		r.checkers = NewCheckers(Deps{Scope: r.currentScope, Resolve: r.resolve})
	}
	return r
}

func clampConcurrency(n int) int {
	if n <= 0 {
		return DefaultMaxConcurrent
	}
	return n
}

// Start brings up the dispatcher and the result pump. Calling it twice replaces the previous
// pair; Stop cancels them and cancels every outstanding run.
func (r *Runtime) Start(ctx context.Context) {
	r.Stop()
	runCtx, cancel := context.WithCancel(ctx)
	r.stopMu.Lock()
	r.cancel = cancel
	r.stopMu.Unlock()
	go r.dispatch(runCtx)
	go r.pump(runCtx)
}

// Stop halts the workers and cancels every run still open, which closes each of them out with a
// `cancelled` result if the pump is still draining. It is safe to call on a Runtime that was
// never started.
func (r *Runtime) Stop() {
	r.stopMu.Lock()
	cancel := r.cancel
	r.cancel = nil
	r.stopMu.Unlock()
	if cancel != nil {
		cancel()
	}
	r.cancelAll("agent_stopping")
}

// Configure installs a new effective scope and concurrency limit, and (re-)enables execution.
// This is the whole of Task 20's grant-change path: nothing needs restarting, and a raised
// concurrency limit is picked up by the dispatcher within one slotPollInterval.
func (r *Runtime) Configure(scope netscope.Scope, maxConcurrent int) {
	r.mu.Lock()
	r.scope = scope
	r.maxConcurrent = clampConcurrency(maxConcurrent)
	r.enabled = true
	r.mu.Unlock()
}

// Disable refuses further assignments and cancels every run in flight — a revoked agent or a
// disabled `remote_probe` grant must stop probing immediately, not at the end of the current
// deadline.
func (r *Runtime) Disable(reason string) {
	r.mu.Lock()
	r.enabled = false
	r.mu.Unlock()
	r.cancelAll(reason)
}

// OpenRuns reports how many assignments are queued or in flight. Exported for the daemon's
// status file and for the test that proves an assignment's credentials are not retained past
// its run.
func (r *Runtime) OpenRuns() int {
	r.mu.Lock()
	defer r.mu.Unlock()
	return len(r.runs)
}

// Assign validates and enqueues one `probe.assign` payload. It never dials, never resolves and
// never blocks on a consumer — see the package doc for why that is not an optimization.
//
// A refusal is reported twice over: as the returned error, which link logs, and as a `rejected`
// probe.result, which closes the run out server-side instead of leaving it to expire.
func (r *Runtime) Assign(payload json.RawMessage) error {
	var assign frame.ProbeAssignPayload
	if err := json.Unmarshal(payload, &assign); err != nil {
		return fmt.Errorf("%w: %v", ErrMalformedAssignment, err)
	}
	// Nothing below this point can be reported to the server without a run id, so a missing or
	// implausible one is the single case that produces no result frame at all.
	if assign.RunID == "" || len(assign.RunID) > maxRunIDLength {
		return fmt.Errorf("%w: run_id must be 1-%d characters", ErrMalformedAssignment, maxRunIDLength)
	}
	if assign.Host == "" {
		return r.refuse(assign, ErrMalformedAssignment, "assignment carries no destination host")
	}
	if assign.DeadlineAt.IsZero() {
		return r.refuse(assign, ErrMalformedAssignment, "assignment carries no deadline")
	}
	if _, ok := r.checkers[assign.CheckType]; !ok {
		return r.refuse(assign, ErrUnsupportedCheckType,
			fmt.Sprintf("check type %q is not supported by this agent", assign.CheckType))
	}

	r.mu.Lock()
	if !r.enabled {
		r.mu.Unlock()
		return r.refuse(assign, ErrNotEnabled, "remote_probe is not enabled on this agent")
	}
	if _, exists := r.runs[assign.RunID]; exists {
		r.mu.Unlock()
		// Deliberately no result: emitting one would close a run whose real result is still
		// coming, handing the monitor a rejection instead of its observation.
		return fmt.Errorf("%w: %s", ErrDuplicateRun, assign.RunID)
	}
	// The run context is created here rather than at execution time so a cancel arriving while
	// the assignment is still queued has something to act on.
	ctx, cancel := context.WithCancel(context.Background())
	entry := &run{assign: assign, ctx: ctx, cancel: cancel}
	r.runs[assign.RunID] = entry
	r.mu.Unlock()

	select {
	case r.queue <- entry:
		return nil
	default:
		r.forget(assign.RunID)
		cancel()
		return r.refuse(assign, ErrQueueFull,
			fmt.Sprintf("agent probe queue is full (%d assignments)", QueueCapacity))
	}
}

// Cancel applies one best-effort `probe.cancel` payload (§4). An unknown run id is not an error:
// cancellation races completion by design, and the backend stays authoritative either way.
func (r *Runtime) Cancel(payload json.RawMessage) error {
	var cancel frame.ProbeCancelPayload
	if err := json.Unmarshal(payload, &cancel); err != nil {
		return fmt.Errorf("probe: malformed cancellation: %w", err)
	}
	if cancel.RunID == "" {
		return errors.New("probe: cancellation carries no run id")
	}
	r.mu.Lock()
	entry := r.runs[cancel.RunID]
	r.mu.Unlock()
	if entry == nil {
		return nil
	}
	r.cancelRun(entry, cancel.Reason)
	return nil
}

// cancelRun stops one run. A queued run is closed out here and now — nothing else will ever look
// at it, and waiting for the dispatcher to reach it would leave the backend hanging for the rest
// of the deadline. A running one is interrupted through its context and reported by its own
// worker, so the checker gets to unwind first.
func (r *Runtime) cancelRun(entry *run, reason string) {
	entry.mu.Lock()
	entry.cancelled = true
	entry.cancelReason = reason
	state := entry.state
	if state == runQueued {
		entry.state = runDone
	}
	entry.mu.Unlock()

	entry.cancel()
	if state == runQueued {
		r.forget(entry.assign.RunID)
		r.finish(entry, result{outcome: OutcomeCancelled, msg: cancelledMsg(reason)}, r.now())
	}
}

func (r *Runtime) cancelAll(reason string) {
	r.mu.Lock()
	entries := make([]*run, 0, len(r.runs))
	for _, entry := range r.runs {
		entries = append(entries, entry)
	}
	r.mu.Unlock()
	for _, entry := range entries {
		r.cancelRun(entry, reason)
	}
}

func cancelledMsg(reason string) string {
	if reason == "" {
		return "cancelled"
	}
	return "cancelled: " + reason
}

// refuse emits a `rejected` result for an assignment that never entered the queue and returns
// the sentinel wrapped with the same message, so the log line and the wire agree.
func (r *Runtime) refuse(assign frame.ProbeAssignPayload, sentinel error, msg string) error {
	now := r.now()
	r.finish(&run{assign: assign}, result{outcome: OutcomeRejected, msg: msg}, now)
	return fmt.Errorf("%w: %s", sentinel, msg)
}

func (r *Runtime) forget(runID string) {
	r.mu.Lock()
	delete(r.runs, runID)
	r.mu.Unlock()
}

func (r *Runtime) currentScope() netscope.Scope {
	r.mu.Lock()
	defer r.mu.Unlock()
	return r.scope
}

// dispatch pulls assignments off the queue as capacity allows. One goroutine per running check,
// started only once a slot is free, is what enforces §2's per-agent concurrency limit.
func (r *Runtime) dispatch(ctx context.Context) {
	for {
		if !r.waitForSlot(ctx) {
			return
		}
		select {
		case <-ctx.Done():
			return
		case entry := <-r.queue:
			r.mu.Lock()
			r.inFlight++
			r.mu.Unlock()
			go func() {
				defer r.releaseSlot()
				r.execute(entry)
			}()
		}
	}
}

func (r *Runtime) waitForSlot(ctx context.Context) bool {
	for {
		r.mu.Lock()
		free := r.inFlight < r.maxConcurrent
		r.mu.Unlock()
		if free {
			return true
		}
		select {
		case <-ctx.Done():
			return false
		case <-r.slotFreed:
		case <-time.After(slotPollInterval):
		}
	}
}

func (r *Runtime) releaseSlot() {
	r.mu.Lock()
	r.inFlight--
	r.mu.Unlock()
	select {
	case r.slotFreed <- struct{}{}:
	default:
	}
}

// pump forwards results to the outbound data-frame channel. It is the only writer to out, and it
// is a separate goroutine precisely so a slow or disconnected consumer cannot reach back into
// link's inbound goroutine through Assign.
func (r *Runtime) pump(ctx context.Context) {
	for {
		select {
		case <-ctx.Done():
			return
		case f := <-r.results:
			select {
			case r.out <- f:
			case <-ctx.Done():
				return
			}
		}
	}
}

// execute runs one assignment to completion and emits exactly one result for it.
func (r *Runtime) execute(entry *run) {
	if !entry.begin() {
		// Cancelled while it sat in the queue: cancelRun already closed it out.
		return
	}
	defer entry.cancel()
	defer r.forget(entry.assign.RunID)

	started := r.now()
	res := r.runCheck(entry, started)

	// Cancellation outranks whatever the check produced. A checker interrupted mid-flight
	// typically returns a context error, which would otherwise read as an execution error and
	// misreport a deliberate stop as an agent fault.
	if reason, cancelled := entry.cancellation(); cancelled {
		res = result{outcome: OutcomeCancelled, msg: cancelledMsg(reason)}
	}
	r.finish(entry, res, started)
}

// runCheck performs the scope check, the deadline check and the check itself, in that order —
// the ordering is the security property: nothing resolves or dials until scope has passed.
func (r *Runtime) runCheck(entry *run, started time.Time) result {
	assign := entry.assign
	host := assign.Host

	resolved, err := r.resolveForScope(entry.ctx, host)
	if err != nil {
		return result{
			outcome: OutcomeExecutionError,
			msg:     fmt.Sprintf("could not resolve destination %s: %v", host, err),
		}
	}
	if decision := netscope.Evaluate(r.currentScope(), host, resolved); !decision.Allowed {
		// A name that resolves to nothing is an agent-side failure, not a scope violation: the
		// destination was never judged, so reporting it as one would both mislead the operator
		// and record a capability violation the assignment never committed.
		if decision.Reason == netscope.ReasonUnresolvedHostname {
			return result{
				outcome: OutcomeExecutionError,
				msg:     fmt.Sprintf("could not resolve destination %s", host),
			}
		}
		refused := host
		if decision.Address != "" {
			refused = decision.Address
		}
		r.emitCapabilityViolation(decision.Reason)
		return result{
			outcome: OutcomeRejected,
			msg:     fmt.Sprintf("destination %s is outside the agent's approved scope", refused),
		}
	}

	if !assign.DeadlineAt.After(started) {
		return result{
			outcome: OutcomeExecutionError,
			msg:     "the assignment's deadline had already passed when it reached the checker",
		}
	}
	ctx, cancel := context.WithDeadline(entry.ctx, assign.DeadlineAt)
	defer cancel()

	checker, ok := r.checkers[assign.CheckType]
	if !ok {
		return result{
			outcome: OutcomeRejected,
			msg:     fmt.Sprintf("check type %q is not supported by this agent", assign.CheckType),
		}
	}

	outcome, checkErr := checker.Check(ctx, host, assign.Config)
	switch {
	case errors.Is(checkErr, context.DeadlineExceeded):
		return result{
			outcome: OutcomeExecutionError,
			msg:     fmt.Sprintf("the check did not finish before its %s deadline", assign.DeadlineAt.Format(time.RFC3339)),
		}
	case checkErr != nil:
		// The checker could not perform the probe at all (§5's `icmp_unavailable` case). This
		// says nothing about the target, so the monitor keeps its last known state.
		return result{outcome: OutcomeExecutionError, msg: checkErr.Error()}
	}
	return result{
		outcome: OutcomeCompleted,
		up:      outcome.Up,
		samples: outcome.Samples,
		msg:     outcome.Msg,
		details: outcome.Details,
	}
}

// resolveForScope returns the addresses a hostname target must be judged by. An IP literal needs
// none — netscope judges it directly — and returning nil for one keeps the "a name is only as
// safe as its worst answer" rule from silently degrading into "no answers, so allowed".
func (r *Runtime) resolveForScope(ctx context.Context, host string) ([]string, error) {
	if _, err := netip.ParseAddr(host); err == nil {
		return nil, nil
	}
	lookupCtx, cancel := context.WithTimeout(ctx, resolveTimeout)
	defer cancel()
	return r.resolve(lookupCtx, host)
}

// finish emits the single probe.result frame this run is allowed to produce.
func (r *Runtime) finish(entry *run, res result, started time.Time) {
	payload := frame.ProbeResultPayload{
		RunID:      entry.assign.RunID,
		MonitorID:  entry.assign.MonitorID,
		Outcome:    res.outcome,
		StartedAt:  started,
		FinishedAt: r.now(),
		Msg:        boundMsg(res.msg),
	}
	// Only a completed check describes the target. Carrying samples or an up flag on any other
	// outcome would feed the monitor state machine an observation nobody made.
	if res.outcome == OutcomeCompleted {
		payload.Up = res.up
		payload.Samples = res.samples
		payload.Details = boundDetails(res.details)
	}
	data, err := json.Marshal(payload)
	if err != nil {
		log.Printf("probe: encoding the result for run %s failed: %v", entry.assign.RunID, err)
		return
	}
	r.emit(frame.Frame{Type: frame.TypeProbeResult, TS: payload.FinishedAt, Payload: data})
}

// emitCapabilityViolation reports a refusal the backend did not predict — the two ends disagreed
// about this agent's scope. The payload shape is the corpus's: frame_type plus the evaluator's
// own machine-readable reason, and nothing about the destination, which belongs in the run's
// audit row rather than in a capability event.
func (r *Runtime) emitCapabilityViolation(reason string) {
	data, err := json.Marshal(struct {
		FrameType string `json:"frame_type"`
		Reason    string `json:"reason"`
	}{FrameType: frame.TypeProbeAssign, Reason: reason})
	if err != nil {
		return
	}
	r.emit(frame.Frame{Type: frame.TypeCapabilityViolation, TS: r.now(), Payload: data})
}

// emit hands one frame to the pump. Non-blocking by construction: every caller is either link's
// inbound goroutine or a worker holding a concurrency slot, and neither may wait on whoever is
// reading the data-frame channel. The buffer is sized so this cannot happen in practice, so a
// drop is logged as the anomaly it would be.
func (r *Runtime) emit(f frame.Frame) {
	select {
	case r.results <- f:
	default:
		log.Printf("probe: dropped a %s frame — the result buffer is full", f.Type)
	}
}

func boundMsg(msg string) string {
	runes := []rune(msg)
	if len(runes) <= MaxMsgChars {
		return msg
	}
	return string(runes[:MaxMsgChars])
}

// boundDetails drops details the ingest handler would reject the whole result for. Losing audit
// metadata is strictly better than losing the target observation it was attached to.
func boundDetails(details map[string]any) map[string]any {
	if details == nil {
		return nil
	}
	encoded, err := json.Marshal(details)
	if err != nil {
		log.Printf("probe: dropping unencodable result details: %v", err)
		return nil
	}
	if len(encoded) > MaxDetailsBytes {
		log.Printf("probe: dropping %d bytes of result details — the limit is %d", len(encoded), MaxDetailsBytes)
		return nil
	}
	return details
}

// begin claims a queued run for execution, reporting false when a cancellation got there first.
func (e *run) begin() bool {
	e.mu.Lock()
	defer e.mu.Unlock()
	if e.state != runQueued {
		return false
	}
	e.state = runRunning
	return true
}

func (e *run) cancellation() (string, bool) {
	e.mu.Lock()
	defer e.mu.Unlock()
	return e.cancelReason, e.cancelled
}
