package probe

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"circuitbreaker.dev/cb-agent/internal/frame"
	"circuitbreaker.dev/cb-agent/internal/netscope"
)

// stubChecker stands in for the real ICMP/TCP/HTTP/DNS checkers Tasks 17-19 add. It records
// every invocation so a test can assert a check was never *started* — which is what "rejected
// without dialing" means when the dialing itself lives one layer down.
type stubChecker struct {
	mu    sync.Mutex
	calls []stubCall

	// block, when non-nil, holds Check until it is closed or the run's context ends. It is how
	// a test pins a slot as occupied, and how cancellation gets something to interrupt.
	block chan struct{}
	// started, when non-nil, receives one host per Check entry. Buffer it generously: a test
	// that stops reading must not wedge the runtime.
	started chan string
	// returned, when non-nil, receives one error per Check exit.
	returned chan error

	// delay, when non-zero, holds Check for that long *inside* the in-flight window, which is
	// what makes a concurrency peak observable without any test-side coordination.
	delay time.Duration

	outcome Outcome
	err     error

	inFlight    int32
	maxInFlight int32
}

type stubCall struct {
	host   string
	config string
}

func (s *stubChecker) Check(ctx context.Context, host string, cfg json.RawMessage) (Outcome, error) {
	current := atomic.AddInt32(&s.inFlight, 1)
	defer atomic.AddInt32(&s.inFlight, -1)
	for {
		peak := atomic.LoadInt32(&s.maxInFlight)
		if current <= peak || atomic.CompareAndSwapInt32(&s.maxInFlight, peak, current) {
			break
		}
	}

	s.mu.Lock()
	s.calls = append(s.calls, stubCall{host: host, config: string(cfg)})
	s.mu.Unlock()

	if s.started != nil {
		select {
		case s.started <- host:
		default:
		}
	}

	err := s.err
	if s.delay > 0 {
		select {
		case <-time.After(s.delay):
		case <-ctx.Done():
			err = ctx.Err()
		}
	}
	if s.block != nil {
		select {
		case <-s.block:
		case <-ctx.Done():
			err = ctx.Err()
		}
	}
	if s.returned != nil {
		select {
		case s.returned <- err:
		default:
		}
	}
	if err != nil {
		return Outcome{}, err
	}
	return s.outcome, nil
}

func (s *stubChecker) hosts() []string {
	s.mu.Lock()
	defer s.mu.Unlock()
	out := make([]string, 0, len(s.calls))
	for _, call := range s.calls {
		out = append(out, call.host)
	}
	return out
}

func (s *stubChecker) configs() []string {
	s.mu.Lock()
	defer s.mu.Unlock()
	out := make([]string, 0, len(s.calls))
	for _, call := range s.calls {
		out = append(out, call.config)
	}
	return out
}

// testScope is a single directly connected /24 — the agent may reach 10.20.0.0/24 and nothing
// else, so 8.8.8.8 is the canonical out-of-scope destination in every test below.
func testScope() netscope.Scope {
	return netscope.Derive(
		[]netscope.InterfaceFacts{{
			Name:  "eth0",
			Flags: []string{"up", "broadcast"},
			Addrs: []string{"10.20.0.5/24"},
		}},
		netscope.Config{},
	)
}

const (
	inScopeHost      = "10.20.0.9"
	otherInScopeHost = "10.20.0.10"
	outOfScopeHost   = "8.8.8.8"
)

// newTestRuntime builds a started runtime whose only checker is checker, registered under every
// check type so a test can pick any. out is buffered unless the caller overrides it.
func newTestRuntime(t *testing.T, checker Checker, mutate ...func(*Options)) (*Runtime, chan frame.Frame) {
	t.Helper()
	out := make(chan frame.Frame, 512)
	rt := newTestRuntimeWithOut(t, checker, out, mutate...)
	return rt, out
}

func newTestRuntimeWithOut(t *testing.T, checker Checker, out chan frame.Frame, mutate ...func(*Options)) *Runtime {
	t.Helper()
	opts := Options{
		Checkers: map[string]Checker{
			CheckTypeICMP: checker,
			CheckTypeTCP:  checker,
			CheckTypeHTTP: checker,
			CheckTypeDNS:  checker,
		},
		Scope:         testScope(),
		MaxConcurrent: 4,
		Resolve: func(context.Context, string) ([]string, error) {
			return nil, errors.New("probe test: no test may reach the real resolver")
		},
	}
	for _, m := range mutate {
		m(&opts)
	}
	rt := New(out, opts)
	ctx, cancel := context.WithCancel(context.Background())
	t.Cleanup(cancel)
	rt.Start(ctx)
	t.Cleanup(rt.Stop)
	return rt
}

func assignPayload(t *testing.T, runID, checkType, host string, mutate ...func(*frame.ProbeAssignPayload)) json.RawMessage {
	t.Helper()
	now := time.Now().UTC()
	payload := frame.ProbeAssignPayload{
		RunID:       runID,
		MonitorID:   42,
		CheckType:   checkType,
		Host:        host,
		Config:      json.RawMessage(`{}`),
		ScheduledAt: now,
		DeadlineAt:  now.Add(20 * time.Second),
	}
	for _, m := range mutate {
		m(&payload)
	}
	data, err := json.Marshal(payload)
	if err != nil {
		t.Fatalf("marshal assignment: %v", err)
	}
	return data
}

func cancelPayload(t *testing.T, runID, reason string) json.RawMessage {
	t.Helper()
	data, err := json.Marshal(frame.ProbeCancelPayload{RunID: runID, Reason: reason})
	if err != nil {
		t.Fatalf("marshal cancellation: %v", err)
	}
	return data
}

// nextFrame reads one frame of the given type, skipping (and returning) nothing else.
func nextFrameOfType(t *testing.T, out <-chan frame.Frame, typ string, timeout time.Duration) frame.Frame {
	t.Helper()
	deadline := time.After(timeout)
	for {
		select {
		case f := <-out:
			if f.Type == typ {
				return f
			}
		case <-deadline:
			t.Fatalf("no %s frame within %s", typ, timeout)
		}
	}
}

func nextResult(t *testing.T, out <-chan frame.Frame, timeout time.Duration) (frame.Frame, frame.ProbeResultPayload) {
	t.Helper()
	f := nextFrameOfType(t, out, frame.TypeProbeResult, timeout)
	var payload frame.ProbeResultPayload
	if err := json.Unmarshal(f.Payload, &payload); err != nil {
		t.Fatalf("decode probe.result payload: %v", err)
	}
	return f, payload
}

// TestProbeRuntime_HandlerReturnsImmediatelyAndDoesNotBlockTheCaller is the whole reason the
// runtime exists. link.runOnce's inbound switch shares one goroutine with the websocket writer,
// the heartbeat ticker, the rekey ticker and the spool-drain ticker, so an Assign that waited on
// a checker — or on whoever is reading the data-frame channel — would stall heartbeats past the
// server's 60s dead-link deadline and tear the link down.
func TestProbeRuntime_HandlerReturnsImmediatelyAndDoesNotBlockTheCaller(t *testing.T) {
	checker := &stubChecker{block: make(chan struct{}), started: make(chan string, 16)}
	defer close(checker.block)

	// Unbuffered and never read: the result consumer is as stuck as the checker is.
	out := make(chan frame.Frame)
	rt := newTestRuntimeWithOut(t, checker, out, func(o *Options) { o.MaxConcurrent = 2 })

	start := time.Now()
	for i := 0; i < 10; i++ {
		if err := rt.Assign(assignPayload(t, fmt.Sprintf("%032x", i), CheckTypeTCP, inScopeHost)); err != nil {
			t.Fatalf("Assign(%d) error = %v", i, err)
		}
	}
	if elapsed := time.Since(start); elapsed > 250*time.Millisecond {
		t.Fatalf("10 Assign calls took %s — the handler must validate and enqueue only", elapsed)
	}

	// And the checkers really are running (i.e. the fast return was not a refusal).
	select {
	case <-checker.started:
	case <-time.After(2 * time.Second):
		t.Fatal("no checker was ever started")
	}
}

// TestProbeRuntime_RespectsMaxConcurrentFromTheGrant pins §2's per-agent concurrency limit,
// which the `remote_probe` grant's max_concurrent carries (default 20, range 1-100).
func TestProbeRuntime_RespectsMaxConcurrentFromTheGrant(t *testing.T) {
	checker := &stubChecker{outcome: Outcome{Up: true, Msg: "ok"}, delay: 25 * time.Millisecond}

	rt, out := newTestRuntime(t, checker, func(o *Options) { o.MaxConcurrent = 3 })

	const assignments = 12
	for i := 0; i < assignments; i++ {
		if err := rt.Assign(assignPayload(t, fmt.Sprintf("%032x", i), CheckTypeTCP, inScopeHost)); err != nil {
			t.Fatalf("Assign(%d) error = %v", i, err)
		}
	}
	for i := 0; i < assignments; i++ {
		if _, payload := nextResult(t, out, 5*time.Second); payload.Outcome != OutcomeCompleted {
			t.Fatalf("result %d outcome = %q, want %q", i, payload.Outcome, OutcomeCompleted)
		}
	}

	peak := atomic.LoadInt32(&checker.maxInFlight)
	if peak > 3 {
		t.Fatalf("peak concurrency = %d, want <= 3", peak)
	}
	if peak < 2 {
		t.Fatalf("peak concurrency = %d — the runtime never ran two checks at once", peak)
	}
}

// TestProbeRuntime_QueueOfOneHundredIsBoundedAndOverflowReturnsRejected pins §2: an agent holds
// at most 100 assignments, and capacity exhaustion is *reported* — a silent drop leaves the
// backend waiting out the run's whole deadline for a result that was never coming.
func TestProbeRuntime_QueueOfOneHundredIsBoundedAndOverflowReturnsRejected(t *testing.T) {
	checker := &stubChecker{block: make(chan struct{}), started: make(chan string, 4)}
	defer close(checker.block)

	rt, out := newTestRuntime(t, checker, func(o *Options) { o.MaxConcurrent = 1 })

	// One assignment occupies the single slot. Waiting for the checker to actually enter makes
	// the queue accounting below exact rather than racy.
	if err := rt.Assign(assignPayload(t, fmt.Sprintf("%032x", 0), CheckTypeTCP, inScopeHost)); err != nil {
		t.Fatalf("Assign(first) error = %v", err)
	}
	select {
	case <-checker.started:
	case <-time.After(2 * time.Second):
		t.Fatal("the first assignment never started")
	}

	for i := 1; i <= QueueCapacity; i++ {
		if err := rt.Assign(assignPayload(t, fmt.Sprintf("%032x", i), CheckTypeTCP, inScopeHost)); err != nil {
			t.Fatalf("Assign(%d) error = %v — the queue must hold %d assignments", i, err, QueueCapacity)
		}
	}

	overflowID := fmt.Sprintf("%032x", QueueCapacity+1)
	err := rt.Assign(assignPayload(t, overflowID, CheckTypeTCP, inScopeHost))
	if !errors.Is(err, ErrQueueFull) {
		t.Fatalf("Assign(overflow) error = %v, want ErrQueueFull", err)
	}

	_, payload := nextResult(t, out, 2*time.Second)
	if payload.RunID != overflowID {
		t.Fatalf("result run_id = %q, want the overflowing assignment %q", payload.RunID, overflowID)
	}
	if payload.Outcome != OutcomeRejected {
		t.Fatalf("outcome = %q, want %q", payload.Outcome, OutcomeRejected)
	}
	if payload.Up {
		t.Fatal("a rejected assignment must never claim the target is up")
	}
	if len(payload.Samples) != 0 {
		t.Fatalf("samples = %v, want none — only a completed outcome describes the target", payload.Samples)
	}
}

// TestProbeRuntime_CancelBeforeExecutionEmitsCancelledOutcome — a queued assignment that is
// cancelled must never reach a checker, and must still close its run out.
func TestProbeRuntime_CancelBeforeExecutionEmitsCancelledOutcome(t *testing.T) {
	checker := &stubChecker{block: make(chan struct{}), started: make(chan string, 4)}
	defer close(checker.block)

	rt, out := newTestRuntime(t, checker, func(o *Options) { o.MaxConcurrent = 1 })

	runningID := fmt.Sprintf("%032x", 1)
	queuedID := fmt.Sprintf("%032x", 2)
	if err := rt.Assign(assignPayload(t, runningID, CheckTypeTCP, inScopeHost)); err != nil {
		t.Fatalf("Assign(running) error = %v", err)
	}
	select {
	case <-checker.started:
	case <-time.After(2 * time.Second):
		t.Fatal("the first assignment never started")
	}
	if err := rt.Assign(assignPayload(t, queuedID, CheckTypeTCP, otherInScopeHost)); err != nil {
		t.Fatalf("Assign(queued) error = %v", err)
	}

	if err := rt.Cancel(cancelPayload(t, queuedID, "monitor_paused")); err != nil {
		t.Fatalf("Cancel() error = %v", err)
	}

	_, payload := nextResult(t, out, 2*time.Second)
	if payload.RunID != queuedID {
		t.Fatalf("result run_id = %q, want the cancelled assignment %q", payload.RunID, queuedID)
	}
	if payload.Outcome != OutcomeCancelled {
		t.Fatalf("outcome = %q, want %q", payload.Outcome, OutcomeCancelled)
	}
	if payload.Msg != "cancelled: monitor_paused" {
		t.Fatalf("msg = %q, want %q", payload.Msg, "cancelled: monitor_paused")
	}
	for _, host := range checker.hosts() {
		if host == otherInScopeHost {
			t.Fatal("the cancelled assignment reached a checker")
		}
	}
}

// TestProbeRuntime_CancelDuringExecutionStopsTheCheckerAndEmitsCancelled — cancellation reaches
// an in-flight check through its context, and the result it produces is `cancelled`, never a
// target-down `completed`.
func TestProbeRuntime_CancelDuringExecutionStopsTheCheckerAndEmitsCancelled(t *testing.T) {
	checker := &stubChecker{
		block:    make(chan struct{}),
		started:  make(chan string, 4),
		returned: make(chan error, 4),
	}
	defer close(checker.block)

	rt, out := newTestRuntime(t, checker, func(o *Options) { o.MaxConcurrent = 1 })

	runID := fmt.Sprintf("%032x", 7)
	if err := rt.Assign(assignPayload(t, runID, CheckTypeHTTP, inScopeHost)); err != nil {
		t.Fatalf("Assign() error = %v", err)
	}
	select {
	case <-checker.started:
	case <-time.After(2 * time.Second):
		t.Fatal("the assignment never started")
	}

	if err := rt.Cancel(cancelPayload(t, runID, "monitor_deleted")); err != nil {
		t.Fatalf("Cancel() error = %v", err)
	}

	select {
	case err := <-checker.returned:
		if !errors.Is(err, context.Canceled) {
			t.Fatalf("checker returned %v, want context.Canceled — cancellation must reach the checker's context", err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("the checker was never stopped")
	}

	_, payload := nextResult(t, out, 2*time.Second)
	if payload.Outcome != OutcomeCancelled {
		t.Fatalf("outcome = %q, want %q", payload.Outcome, OutcomeCancelled)
	}
	if payload.Msg != "cancelled: monitor_deleted" {
		t.Fatalf("msg = %q, want %q", payload.Msg, "cancelled: monitor_deleted")
	}
}

// TestProbeRuntime_DeadlineExceededEmitsExecutionErrorNotTargetDown — the agent running out of
// time says nothing about the target. Reporting DOWN here would invent an outage out of a slow
// or blocked agent, and would raise an alert for it.
func TestProbeRuntime_DeadlineExceededEmitsExecutionErrorNotTargetDown(t *testing.T) {
	t.Run("deadline passes mid-check", func(t *testing.T) {
		checker := &stubChecker{block: make(chan struct{}), started: make(chan string, 4)}
		defer close(checker.block)
		rt, out := newTestRuntime(t, checker)

		runID := fmt.Sprintf("%032x", 11)
		assignment := assignPayload(t, runID, CheckTypeICMP, inScopeHost, func(p *frame.ProbeAssignPayload) {
			p.DeadlineAt = time.Now().UTC().Add(150 * time.Millisecond)
		})
		if err := rt.Assign(assignment); err != nil {
			t.Fatalf("Assign() error = %v", err)
		}

		_, payload := nextResult(t, out, 3*time.Second)
		if payload.Outcome != OutcomeExecutionError {
			t.Fatalf("outcome = %q, want %q", payload.Outcome, OutcomeExecutionError)
		}
		if payload.Up {
			t.Fatal("up = true on an execution error")
		}
		if len(payload.Samples) != 0 {
			t.Fatalf("samples = %v, want none — an execution error must not touch monitor state", payload.Samples)
		}
	})

	t.Run("deadline already passed on arrival", func(t *testing.T) {
		checker := &stubChecker{}
		rt, out := newTestRuntime(t, checker)

		runID := fmt.Sprintf("%032x", 12)
		assignment := assignPayload(t, runID, CheckTypeICMP, inScopeHost, func(p *frame.ProbeAssignPayload) {
			p.DeadlineAt = time.Now().UTC().Add(-time.Second)
		})
		if err := rt.Assign(assignment); err != nil {
			t.Fatalf("Assign() error = %v", err)
		}

		_, payload := nextResult(t, out, 3*time.Second)
		if payload.Outcome != OutcomeExecutionError {
			t.Fatalf("outcome = %q, want %q", payload.Outcome, OutcomeExecutionError)
		}
		if hosts := checker.hosts(); len(hosts) != 0 {
			t.Fatalf("checker was invoked %v for an assignment that was already past its deadline", hosts)
		}
	})
}

// TestProbeRuntime_OutOfScopeAssignmentIsRejectedWithoutDialing is the agent-side half of the
// independent-enforcement invariant: a backend-approved assignment whose destination is outside
// *this agent's own* derived scope is still refused here, before anything touches the network.
func TestProbeRuntime_OutOfScopeAssignmentIsRejectedWithoutDialing(t *testing.T) {
	checker := &stubChecker{outcome: Outcome{Up: true}}
	rt, out := newTestRuntime(t, checker)

	runID := fmt.Sprintf("%032x", 21)
	if err := rt.Assign(assignPayload(t, runID, CheckTypeTCP, outOfScopeHost)); err != nil {
		t.Fatalf("Assign() error = %v", err)
	}

	_, payload := nextResult(t, out, 2*time.Second)
	if payload.Outcome != OutcomeRejected {
		t.Fatalf("outcome = %q, want %q", payload.Outcome, OutcomeRejected)
	}
	want := fmt.Sprintf("destination %s is outside the agent's approved scope", outOfScopeHost)
	if payload.Msg != want {
		t.Fatalf("msg = %q, want %q", payload.Msg, want)
	}
	if payload.Up {
		t.Fatal("a rejected assignment must never claim the target is up")
	}
	if hosts := checker.hosts(); len(hosts) != 0 {
		t.Fatalf("checker was invoked %v — an out-of-scope destination must never be dialed", hosts)
	}
}

// TestProbeRuntime_OutOfScopeAssignmentEmitsCapabilityViolation — a refusal is also reported, so
// a backend and agent that disagree about scope are visible on the agent's timeline instead of
// looking like a flaky monitor.
func TestProbeRuntime_OutOfScopeAssignmentEmitsCapabilityViolation(t *testing.T) {
	checker := &stubChecker{}
	rt, out := newTestRuntime(t, checker)

	if err := rt.Assign(assignPayload(t, fmt.Sprintf("%032x", 22), CheckTypeICMP, outOfScopeHost)); err != nil {
		t.Fatalf("Assign() error = %v", err)
	}

	f := nextFrameOfType(t, out, frame.TypeCapabilityViolation, 2*time.Second)
	var payload struct {
		FrameType string `json:"frame_type"`
		Reason    string `json:"reason"`
	}
	if err := json.Unmarshal(f.Payload, &payload); err != nil {
		t.Fatalf("decode capability.violation payload: %v", err)
	}
	if payload.FrameType != frame.TypeProbeAssign {
		t.Fatalf("frame_type = %q, want %q", payload.FrameType, frame.TypeProbeAssign)
	}
	if payload.Reason != netscope.ReasonOutOfScope {
		t.Fatalf("reason = %q, want the evaluator's own %q", payload.Reason, netscope.ReasonOutOfScope)
	}
}

// TestProbeRuntime_ResultsAreEmittedOnTheDataFrameChannel — results and violations are data
// frames, so they spool through an outage instead of being lost. Sending either through
// link.Options.ControlFrames would be silently dropped while disconnected; sending a control
// frame through DataFrames panics in link's assertDataFrame. Both are avoided by construction:
// the runtime has exactly one output channel and everything it puts there is a data frame.
func TestProbeRuntime_ResultsAreEmittedOnTheDataFrameChannel(t *testing.T) {
	checker := &stubChecker{outcome: Outcome{Up: true, Msg: "port 80 open in 1.0ms"}}
	rt, out := newTestRuntime(t, checker)

	if err := rt.Assign(assignPayload(t, fmt.Sprintf("%032x", 31), CheckTypeTCP, inScopeHost)); err != nil {
		t.Fatalf("Assign(in scope) error = %v", err)
	}
	if err := rt.Assign(assignPayload(t, fmt.Sprintf("%032x", 32), CheckTypeTCP, outOfScopeHost)); err != nil {
		t.Fatalf("Assign(out of scope) error = %v", err)
	}

	deadline := time.After(3 * time.Second)
	seen := map[string]bool{}
	for len(seen) < 2 {
		select {
		case f := <-out:
			if !frame.IsDataFrame(f.Type) {
				t.Fatalf("the runtime emitted %q, which link classifies as a control frame", f.Type)
			}
			seen[f.Type] = true
		case <-deadline:
			t.Fatalf("saw only %v", seen)
		}
	}
	if !seen[frame.TypeProbeResult] || !seen[frame.TypeCapabilityViolation] {
		t.Fatalf("frame types seen = %v", seen)
	}
}

// TestProbeRuntime_AssignmentSecretsAreNeverPersistedOrLogged pins D-10: probe.assign carries the
// monitor's full validated config, credentials included. The agent holds it in memory for the
// life of the run and nowhere else — not in a log line, not echoed in probe.result, and not
// retained after the run closes.
func TestProbeRuntime_AssignmentSecretsAreNeverPersistedOrLogged(t *testing.T) {
	const secret = "s3cr3t-monitor-password"
	const token = "bearer-tok3n-value"

	var logs bytes.Buffer
	originalWriter := log.Writer()
	originalFlags := log.Flags()
	log.SetOutput(&logs)
	log.SetFlags(0)
	defer func() {
		log.SetOutput(originalWriter)
		log.SetFlags(originalFlags)
	}()

	checker := &stubChecker{outcome: Outcome{Up: true, Msg: "200 in 12.0ms"}}
	rt, out := newTestRuntime(t, checker)

	runID := fmt.Sprintf("%032x", 41)
	assignment := assignPayload(t, runID, CheckTypeHTTP, inScopeHost, func(p *frame.ProbeAssignPayload) {
		p.Config = json.RawMessage(fmt.Sprintf(
			`{"url":"http://%s/healthz","auth_type":"basic","username":"probe","password":%q,"token":%q}`,
			inScopeHost, secret, token))
	})
	if err := rt.Assign(assignment); err != nil {
		t.Fatalf("Assign() error = %v", err)
	}

	f, payload := nextResult(t, out, 3*time.Second)
	if payload.Outcome != OutcomeCompleted {
		t.Fatalf("outcome = %q, want %q", payload.Outcome, OutcomeCompleted)
	}

	// The checker really did receive the credentials — otherwise this test would pass for the
	// wrong reason (an agent that simply drops the config authenticates nothing).
	configs := checker.configs()
	if len(configs) != 1 || !strings.Contains(configs[0], secret) {
		t.Fatalf("checker configs = %v, want the assignment's config carrying the credential", configs)
	}

	encoded, err := frame.Encode(f)
	if err != nil {
		t.Fatalf("Encode() error = %v", err)
	}
	for _, needle := range []string{secret, token} {
		if bytes.Contains(encoded, []byte(needle)) {
			t.Fatalf("probe.result frame carries the assignment credential %q", needle)
		}
		if strings.Contains(logs.String(), needle) {
			t.Fatalf("agent logs carry the assignment credential %q:\n%s", needle, logs.String())
		}
	}

	// And nothing retains it once the run closes.
	waitFor(t, 2*time.Second, func() bool { return rt.OpenRuns() == 0 })
}

// TestProbeRuntime_RunIDIsEchoedVerbatim — the run id is the server-minted token a result is
// posted against and the only identifier the backend authenticates a result by. Re-deriving,
// normalizing or re-casing it would make every result unmatchable.
func TestProbeRuntime_RunIDIsEchoedVerbatim(t *testing.T) {
	checker := &stubChecker{outcome: Outcome{Up: true, Msg: "ok"}}
	rt, out := newTestRuntime(t, checker)

	const runID = "3f9c1a7be04d42a1b8e6c05d7f1a2b3c"
	assignment := assignPayload(t, runID, CheckTypeDNS, inScopeHost, func(p *frame.ProbeAssignPayload) {
		p.MonitorID = 4711
	})
	if err := rt.Assign(assignment); err != nil {
		t.Fatalf("Assign() error = %v", err)
	}

	_, payload := nextResult(t, out, 3*time.Second)
	if payload.RunID != runID {
		t.Fatalf("run_id = %q, want %q", payload.RunID, runID)
	}
	if payload.MonitorID != 4711 {
		t.Fatalf("monitor_id = %d, want 4711", payload.MonitorID)
	}
	if payload.FinishedAt.Before(payload.StartedAt) {
		t.Fatalf("finished_at %s precedes started_at %s", payload.FinishedAt, payload.StartedAt)
	}
}

// TestProbeRuntime_HostnameTargetIsScopeCheckedAgainstEveryResolvedAddress — the DNS-rebinding
// half of the scope contract, at the runtime layer: a resolver that answers with one in-scope
// and one out-of-scope address must not buy a check.
func TestProbeRuntime_HostnameTargetIsScopeCheckedAgainstEveryResolvedAddress(t *testing.T) {
	checker := &stubChecker{outcome: Outcome{Up: true}}
	rt, out := newTestRuntime(t, checker, func(o *Options) {
		o.Resolve = func(context.Context, string) ([]string, error) {
			return []string{inScopeHost, outOfScopeHost}, nil
		}
	})

	if err := rt.Assign(assignPayload(t, fmt.Sprintf("%032x", 51), CheckTypeHTTP, "app.internal.example.com")); err != nil {
		t.Fatalf("Assign() error = %v", err)
	}

	_, payload := nextResult(t, out, 3*time.Second)
	if payload.Outcome != OutcomeRejected {
		t.Fatalf("outcome = %q, want %q", payload.Outcome, OutcomeRejected)
	}
	if hosts := checker.hosts(); len(hosts) != 0 {
		t.Fatalf("checker was invoked %v despite an out-of-scope resolved address", hosts)
	}
}

// TestProbeRuntime_UnsupportedCheckTypeIsRejectedRatherThanIgnored — an assignment this build
// cannot run still closes its run out, so the backend does not wait out the whole deadline.
func TestProbeRuntime_UnsupportedCheckTypeIsRejectedRatherThanIgnored(t *testing.T) {
	checker := &stubChecker{}
	rt, out := newTestRuntime(t, checker, func(o *Options) {
		o.Checkers = map[string]Checker{CheckTypeTCP: checker}
	})

	runID := fmt.Sprintf("%032x", 61)
	err := rt.Assign(assignPayload(t, runID, "icmp", inScopeHost))
	if !errors.Is(err, ErrUnsupportedCheckType) {
		t.Fatalf("Assign() error = %v, want ErrUnsupportedCheckType", err)
	}
	_, payload := nextResult(t, out, 2*time.Second)
	if payload.RunID != runID || payload.Outcome != OutcomeRejected {
		t.Fatalf("result = %q/%q, want %q/%q", payload.RunID, payload.Outcome, runID, OutcomeRejected)
	}
}

// TestProbeRuntime_CheckerFailureIsAnExecutionErrorNotTargetDown — a checker returns an error
// only when it could not perform the probe at all (§5's `icmp_unavailable` case). Target failure
// is an Outcome with Up false, which is a completely different monitor-state input.
func TestProbeRuntime_CheckerFailureIsAnExecutionErrorNotTargetDown(t *testing.T) {
	checker := &stubChecker{err: errors.New("icmp socket unavailable: operation not permitted")}
	rt, out := newTestRuntime(t, checker)

	if err := rt.Assign(assignPayload(t, fmt.Sprintf("%032x", 71), CheckTypeICMP, inScopeHost)); err != nil {
		t.Fatalf("Assign() error = %v", err)
	}
	_, payload := nextResult(t, out, 3*time.Second)
	if payload.Outcome != OutcomeExecutionError {
		t.Fatalf("outcome = %q, want %q", payload.Outcome, OutcomeExecutionError)
	}
	if payload.Msg != "icmp socket unavailable: operation not permitted" {
		t.Fatalf("msg = %q", payload.Msg)
	}
	if payload.Up {
		t.Fatal("up = true on an execution error")
	}
}

// TestProbeRuntime_CompletedOutcomeCarriesTheCheckerSamplesUnchanged — the runtime is a
// scheduler, not a second collector: whatever the parity-tested checkers produce reaches the
// wire byte-for-byte.
func TestProbeRuntime_CompletedOutcomeCarriesTheCheckerSamplesUnchanged(t *testing.T) {
	checker := &stubChecker{outcome: Outcome{
		Up: false,
		Samples: []frame.ProbeSample{
			{Metric: "avail", Value: 0, ErrorReason: "http_error"},
		},
		Msg:     "request failed: ConnectTimeout",
		Details: map[string]any{"tls": map[string]any{"days_remaining": 61}},
	}}
	rt, out := newTestRuntime(t, checker)

	if err := rt.Assign(assignPayload(t, fmt.Sprintf("%032x", 81), CheckTypeHTTP, inScopeHost)); err != nil {
		t.Fatalf("Assign() error = %v", err)
	}
	_, payload := nextResult(t, out, 3*time.Second)
	if payload.Outcome != OutcomeCompleted {
		t.Fatalf("outcome = %q, want %q", payload.Outcome, OutcomeCompleted)
	}
	if payload.Up {
		t.Fatal("up = true, want the checker's own false")
	}
	if len(payload.Samples) != 1 || payload.Samples[0].Metric != "avail" || payload.Samples[0].ErrorReason != "http_error" {
		t.Fatalf("samples = %+v", payload.Samples)
	}
	if payload.Details == nil {
		t.Fatal("details were dropped")
	}
	if payload.Msg != "request failed: ConnectTimeout" {
		t.Fatalf("msg = %q", payload.Msg)
	}
}

// TestProbeRuntime_MessageIsBoundedAtTwoThousandCharacters — the ingest handler rejects an
// oversized message outright, so a checker that produces one must be truncated here rather than
// have its whole result thrown away server-side.
func TestProbeRuntime_MessageIsBoundedAtTwoThousandCharacters(t *testing.T) {
	checker := &stubChecker{outcome: Outcome{Up: true, Msg: strings.Repeat("x", MaxMsgChars+500)}}
	rt, out := newTestRuntime(t, checker)

	if err := rt.Assign(assignPayload(t, fmt.Sprintf("%032x", 91), CheckTypeHTTP, inScopeHost)); err != nil {
		t.Fatalf("Assign() error = %v", err)
	}
	_, payload := nextResult(t, out, 3*time.Second)
	if len([]rune(payload.Msg)) != MaxMsgChars {
		t.Fatalf("msg length = %d, want %d", len([]rune(payload.Msg)), MaxMsgChars)
	}
}

// TestProbeRuntime_DisableCancelsEverythingAndRefusesNewAssignments — the agent-side half of a
// revoked or disabled `remote_probe` grant (Task 20 calls this from onCapabilitiesSet).
func TestProbeRuntime_DisableCancelsEverythingAndRefusesNewAssignments(t *testing.T) {
	checker := &stubChecker{block: make(chan struct{}), started: make(chan string, 4)}
	defer close(checker.block)

	rt, out := newTestRuntime(t, checker, func(o *Options) { o.MaxConcurrent = 1 })

	runID := fmt.Sprintf("%032x", 101)
	if err := rt.Assign(assignPayload(t, runID, CheckTypeTCP, inScopeHost)); err != nil {
		t.Fatalf("Assign() error = %v", err)
	}
	select {
	case <-checker.started:
	case <-time.After(2 * time.Second):
		t.Fatal("the assignment never started")
	}

	rt.Disable("capability_disabled")

	_, payload := nextResult(t, out, 2*time.Second)
	if payload.Outcome != OutcomeCancelled {
		t.Fatalf("outcome = %q, want %q", payload.Outcome, OutcomeCancelled)
	}

	err := rt.Assign(assignPayload(t, fmt.Sprintf("%032x", 102), CheckTypeTCP, inScopeHost))
	if !errors.Is(err, ErrNotEnabled) {
		t.Fatalf("Assign() after Disable error = %v, want ErrNotEnabled", err)
	}

	// Configure re-enables, which is how a re-granted capability comes back without a restart.
	rt.Configure(testScope(), 7)
	if err := rt.Assign(assignPayload(t, fmt.Sprintf("%032x", 103), CheckTypeTCP, inScopeHost)); err != nil {
		t.Fatalf("Assign() after Configure error = %v", err)
	}
}

// TestProbeRuntime_DuplicateRunIDIsRefusedWithoutClosingTheRunningRun — a redelivered assignment
// must not produce a second result for a run that is already in flight, or the backend would
// close a run whose real result is still coming.
func TestProbeRuntime_DuplicateRunIDIsRefusedWithoutClosingTheRunningRun(t *testing.T) {
	checker := &stubChecker{block: make(chan struct{}), started: make(chan string, 4)}
	defer close(checker.block)

	rt, out := newTestRuntime(t, checker, func(o *Options) { o.MaxConcurrent = 1 })

	runID := fmt.Sprintf("%032x", 111)
	if err := rt.Assign(assignPayload(t, runID, CheckTypeTCP, inScopeHost)); err != nil {
		t.Fatalf("Assign() error = %v", err)
	}
	select {
	case <-checker.started:
	case <-time.After(2 * time.Second):
		t.Fatal("the assignment never started")
	}

	if err := rt.Assign(assignPayload(t, runID, CheckTypeTCP, inScopeHost)); !errors.Is(err, ErrDuplicateRun) {
		t.Fatalf("Assign(duplicate) error = %v, want ErrDuplicateRun", err)
	}
	select {
	case f := <-out:
		t.Fatalf("a duplicate assignment emitted %s — the in-flight run must stay open", f.Type)
	case <-time.After(250 * time.Millisecond):
	}
}

func waitFor(t *testing.T, timeout time.Duration, cond func() bool) {
	t.Helper()
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		if cond() {
			return
		}
		time.Sleep(5 * time.Millisecond)
	}
	t.Fatalf("condition still false after %s", timeout)
}
