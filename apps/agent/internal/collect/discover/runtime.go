package discover

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"net/netip"
	"strings"
	"sync"
	"time"

	"circuitbreaker.dev/cb-agent/internal/capability"
	"circuitbreaker.dev/cb-agent/internal/frame"
	"circuitbreaker.dev/cb-agent/internal/netscope"
)

// The refusal and failure codes the runtime owns, alongside validate.go's. Like those they travel
// as the terminal summary's error_code and become ScanJob.error_reason, so they are constants.
//
// ErrorCodeDeadlineExceeded is deliberately not ErrorCodeDeadlinePassed: the validator's code says
// the request was already stale when it arrived, which is a server scheduling problem, while this
// one says the agent held a live request until its deadline ran out, which is an agent problem.
// One code for both would make the two indistinguishable in exactly the incident where the
// difference decides who is at fault.
const (
	ErrorCodeValidationUnavailable = "validation_unavailable"
	ErrorCodeCapabilityDisabled    = "capability_disabled"
	ErrorCodeDeadlineExceeded      = "deadline_exceeded"
	ErrorCodeQueueFull             = "queue_full"
)

// Errors Request returns. They are sentinels because link logs them and Task 14's daemon wiring
// distinguishes them; except for the two below that cannot be reported any other way, the
// corresponding terminal summary is emitted regardless, so no caller has to translate one into a
// frame.
//
// ErrMalformedRequest and ErrDuplicateDispatch are the two that produce no frame at all. A request
// with no usable dispatch id is unaddressable — every summary is keyed by it — and a duplicate's
// summary would close a dispatch whose real terminal frame is still coming, finalizing the job on
// a rejection.
var (
	ErrMalformedRequest  = errors.New("discover: malformed discovery.request")
	ErrDuplicateDispatch = errors.New("discover: a dispatch with this id is already in flight")
	ErrNotEnabled        = errors.New("discover: local_discovery is not enabled on this agent")
	ErrRejected          = errors.New("discover: the request was refused")
	ErrQueueFull         = errors.New("discover: the dispatch queue is full")
)

// DispatchQueueCapacity bounds how many requests one agent holds. Past it a request is refused
// rather than dropped, for the same reason probe.QueueCapacity is: the backend would otherwise
// wait out the dispatch deadline for a summary that was never coming.
//
// It is small because a dispatch is a whole scan rather than a single check, and the backend
// leases one job to an agent at a time; a deep queue here would only mean requests aging out
// while they wait.
const DispatchQueueCapacity = 16

// findingBufferSize is the hand-off between the scan goroutines that produce findings — the
// dispatcher and its enrichment workers — and the single pump that forwards them to the outbound
// data-frame channel. A terminal summary produced *outside* a scan does not travel through it: see
// terminalBacklog for why that one frame can neither be dropped here nor waited on.
const findingBufferSize = 128

// RuntimeOptions configures a Runtime. Every collector has a working default; Validate does not,
// and a Runtime without one scans nothing. Defaulting that the other way would make a wiring
// mistake indistinguishable from an approval.
//
// Validate and Scope are the *initial* authorization, and installing them here still does not
// enable execution: a Runtime refuses every request until Configure applies a grant. They exist so
// that a Runtime is never observable in a state where it would scan against a validator it was not
// given.
type RuntimeOptions struct {
	Validate   Validator
	Scope      netscope.Scope
	Liveness   *Liveness
	ReverseDNS *ReverseDNS
	Banner     *Banner
	// Neighbors is the kernel neighbor-cache read, injected so a test never reaches netlink.
	Neighbors func(context.Context) ([]Neighbor, error)
	// Now is the finding clock. Defaults to time.Now().UTC(), matching the frame timestamps.
	Now func() time.Time
}

// Runtime owns one agent's discovery execution (plan §4).
//
// The shape differs from probe.Runtime in the one way that matters: a probe assignment produces
// exactly one result, while a dispatch produces N host findings *plus* exactly one terminal
// summary. The summary is what closes the job server-side, so it is emitted on every path a
// dispatch can leave by — completion, refusal, cancellation, an expired deadline — and never
// twice.
//
// Safe for concurrent use: Request and Cancel are called from link's inbound goroutine, Configure
// and Disable from the capability-set path, and the scan runs on its own goroutines.
type Runtime struct {
	out      chan<- frame.Frame
	findings chan frame.Frame
	// terminals holds the summaries produced off the scan goroutines, which may not be dropped
	// under back-pressure and may not be waited on where they are produced.
	terminals *terminalBacklog
	queue     chan *dispatch

	liveness  *Liveness
	resolver  *ReverseDNS
	banner    *Banner
	neighbors func(context.Context) ([]Neighbor, error)
	now       func() time.Time

	mu       sync.Mutex
	validate Validator
	scope    netscope.Scope
	// enabled starts false and only Configure sets it. There is deliberately no Enable that
	// skips installing a scope and a validator, because "enabled" and "holds a grant" have to be
	// the same fact for the fail-closed default to mean anything.
	enabled bool
	open    map[string]*dispatch

	stopMu sync.Mutex
	cancel context.CancelFunc
}

// dispatchState tracks one request through the queue, so a cancellation can tell "not started
// yet" (close it out here and now — nothing will ever run it) from "running" (cancel the context
// and let the scan report what it managed to observe first).
type dispatchState int

const (
	dispatchQueued dispatchState = iota
	dispatchRunning
	dispatchDone
)

type dispatch struct {
	req    frame.DiscoveryRequestPayload
	ctx    context.Context
	cancel context.CancelFunc

	mu           sync.Mutex
	state        dispatchState
	cancelled    bool
	cancelReason string
}

// scanResult is everything the terminal summary needs from a finished dispatch.
type scanResult struct {
	outcome   string
	errorCode string
	// notes are the degradations an operator has to be told about — a neighbor cache that could
	// not be read, an ICMP socket that could not be opened. They are joined into msg rather than
	// failing the scan, because each one is a missing source of evidence rather than a missing
	// answer.
	notes            []string
	hostsFound       int
	addressesScanned int
}

// NewRuntime builds a Runtime writing findings to out. out must be link.Options.DataFrames, never
// ControlFrames: discovery.finding is a data frame, so it spools through an outage instead of
// being dropped while disconnected — which is the whole reason finding ids are replay-stable.
//
// The returned Runtime is disabled: it refuses every request with ErrorCodeCapabilityDisabled
// until Configure installs a grant, and Start only brings up the dispatcher and the pump.
// Construction is not authorization — plan §7 requires an agent to scan nothing until the server
// grants `local_discovery`, and a constructor that enabled itself would leave that guarantee
// resting on whether every caller happened to check the grant first. main.go's
// applyDiscoveryConfig runs at startup and on every capabilities.set, so a granted agent is
// enabled before its first request either way.
func NewRuntime(out chan<- frame.Frame, opts RuntimeOptions) *Runtime {
	r := &Runtime{
		out:       out,
		findings:  make(chan frame.Frame, findingBufferSize),
		terminals: newTerminalBacklog(),
		queue:     make(chan *dispatch, DispatchQueueCapacity),
		liveness:  opts.Liveness,
		resolver:  opts.ReverseDNS,
		banner:    opts.Banner,
		neighbors: opts.Neighbors,
		now:       opts.Now,
		validate:  opts.Validate,
		scope:     opts.Scope,
		open:      map[string]*dispatch{},
	}
	if r.liveness == nil {
		r.liveness = NewLiveness()
	}
	if r.resolver == nil {
		r.resolver = NewReverseDNS()
	}
	if r.banner == nil {
		r.banner = NewBanner()
	}
	if r.neighbors == nil {
		r.neighbors = Neighbors
	}
	if r.now == nil {
		r.now = func() time.Time { return time.Now().UTC() }
	}
	return r
}

// Start brings up the dispatcher and the finding pump. Calling it twice replaces the previous
// pair; Stop cancels them and cancels every open dispatch.
func (r *Runtime) Start(ctx context.Context) {
	r.Stop()
	runCtx, cancel := context.WithCancel(ctx)
	r.stopMu.Lock()
	r.cancel = cancel
	r.stopMu.Unlock()
	go r.dispatchLoop(runCtx)
	go r.pump(runCtx)
}

// Stop halts the workers and cancels every dispatch still open, closing each of them out with a
// `cancelled` summary. It is safe to call on a Runtime that was never started.
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

// Configure installs a freshly derived scope and a validator built from the current grant, and
// enables execution. It is the only thing that enables a Runtime — a fresh one is disabled — so
// this is both the first grant and every later change to it: nothing restarts, and the next
// request is judged against the new authorization.
//
// It does not cancel anything. A grant change that *invalidates* live work is D-16's scope-version
// path, which the server drives with an explicit discovery.cancel per dispatch, because only the
// server knows which jobs it has already closed.
func (r *Runtime) Configure(scope netscope.Scope, validate Validator) {
	r.mu.Lock()
	r.scope = scope
	r.validate = validate
	r.enabled = true
	r.mu.Unlock()
}

// Disable refuses further requests and cancels every dispatch in flight. Plan §7 requires
// discovery to stop quickly on a grant change, and a revoked agent or a disabled local_discovery
// grant must stop scanning now rather than at the end of the current job deadline.
func (r *Runtime) Disable(reason string) {
	r.mu.Lock()
	r.enabled = false
	r.mu.Unlock()
	r.cancelAll(reason)
}

// OpenDispatches reports how many requests are queued or running. Exported for the daemon's status
// file and for the test that proves a refused duplicate was never recorded.
func (r *Runtime) OpenDispatches() int {
	r.mu.Lock()
	defer r.mu.Unlock()
	return len(r.open)
}

// Request validates and enqueues one `discovery.request` payload. It never dials, never resolves
// and never blocks on a consumer — link's inbound switch shares one goroutine with the heartbeat
// ticker, so a handler that scanned inline would stall heartbeats past the server's dead-link
// deadline and tear down the link the findings have to travel back over.
//
// A refusal is reported twice over: as the returned error, which link logs, and as a terminal
// `rejected` summary, which closes the job server-side instead of leaving it to expire.
func (r *Runtime) Request(payload json.RawMessage) error {
	var req frame.DiscoveryRequestPayload
	if err := json.Unmarshal(payload, &req); err != nil {
		return fmt.Errorf("%w: %v", ErrMalformedRequest, err)
	}
	// The dispatch id is checked before anything else because it is the only field whose absence
	// makes the refusal itself unreportable. The shape test is validate.go's, not a second copy:
	// a request that fails it produces no frame, so the validator would never get to name it.
	if !validDispatchID(req.DispatchID) {
		return fmt.Errorf("%w: dispatch_id %q is not %d lowercase hex characters",
			ErrMalformedRequest, req.DispatchID, dispatchIDLength)
	}

	ctx, cancel := context.WithCancel(context.Background())
	entry := &dispatch{req: req, ctx: ctx, cancel: cancel}

	r.mu.Lock()
	if _, exists := r.open[req.DispatchID]; exists {
		r.mu.Unlock()
		cancel()
		return fmt.Errorf("%w: %s", ErrDuplicateDispatch, req.DispatchID)
	}
	enabled, validate, scope := r.enabled, r.validate, r.scope
	// The entry is recorded before the verdict so two requests carrying the same dispatch id
	// cannot both pass validation and both run; a refusal removes it again below.
	r.open[req.DispatchID] = entry
	r.mu.Unlock()

	// Before the validator, and before the request has been read for anything but its id: an
	// agent with no grant is not entitled to an opinion about the request's contents. The code is
	// distinct from ErrorCodeValidationUnavailable below because the two are different failures —
	// this one says the server has not authorized discovery on this agent, that one says the agent
	// could not judge the request at all — and D-4 maps them to different job error_reasons.
	if !enabled {
		return r.refuse(entry, ErrNotEnabled, ErrorCodeCapabilityDisabled,
			"local_discovery is not enabled on this agent")
	}
	if validate == nil {
		return r.refuse(entry, ErrRejected, ErrorCodeValidationUnavailable,
			"this agent has no discovery validator installed and will scan nothing")
	}
	if rejection := validate(req, scope); rejection.Rejected() {
		return r.refuse(entry, ErrRejected, rejection.Code, rejection.Msg)
	}

	select {
	case r.queue <- entry:
		return nil
	default:
		return r.refuse(entry, ErrQueueFull, ErrorCodeQueueFull,
			fmt.Sprintf("the agent's discovery queue is full (%d dispatches)", DispatchQueueCapacity))
	}
}

// Cancel applies one best-effort `discovery.cancel` payload (plan §4). An unknown dispatch id is
// not an error: cancellation races completion by design, and the backend rejects a late finding
// independently.
func (r *Runtime) Cancel(payload json.RawMessage) error {
	var cancellation frame.DiscoveryCancelPayload
	if err := json.Unmarshal(payload, &cancellation); err != nil {
		return fmt.Errorf("discover: malformed discovery.cancel: %w", err)
	}
	if cancellation.DispatchID == "" {
		return errors.New("discover: cancellation carries no dispatch id")
	}
	r.mu.Lock()
	entry := r.open[cancellation.DispatchID]
	r.mu.Unlock()
	if entry == nil {
		return nil
	}
	r.cancelDispatch(entry, cancellation.Reason)
	return nil
}

// cancelDispatch stops one dispatch. A queued one is closed out here and now — nothing else will
// ever look at it, and waiting for the dispatcher to reach it would leave the job hanging for the
// rest of its deadline. A running one is interrupted through its context and summarised by the
// scan itself, so the hosts it already found are still reported.
func (r *Runtime) cancelDispatch(entry *dispatch, reason string) {
	entry.mu.Lock()
	entry.cancelled = true
	entry.cancelReason = reason
	entry.mu.Unlock()
	entry.cancel()

	// claimTerminal is what sorts the two cases: it succeeds only for a dispatch nobody has
	// started, so a running one falls through to its own scan rather than being closed out twice.
	if entry.claimTerminal() {
		r.forget(entry.req.DispatchID)
		r.emitTerminal(r.summaryFrame(entry.req, scanResult{
			outcome: frame.DiscoveryOutcomeCancelled,
			notes:   []string{cancelledMsg(reason)},
		}))
	}
}

func (r *Runtime) cancelAll(reason string) {
	r.mu.Lock()
	entries := make([]*dispatch, 0, len(r.open))
	for _, entry := range r.open {
		entries = append(entries, entry)
	}
	r.mu.Unlock()
	for _, entry := range entries {
		r.cancelDispatch(entry, reason)
	}
}

func cancelledMsg(reason string) string {
	if reason == "" {
		return "cancelled"
	}
	return "cancelled: " + reason
}

// refuse emits the single terminal summary a request that never started work is allowed to
// produce, and returns the sentinel wrapped with the same message so the log line and the wire
// agree. Nothing before this point has touched the network, which is the property the refusal
// tests assert directly.
func (r *Runtime) refuse(entry *dispatch, sentinel error, code, msg string) error {
	r.forget(entry.req.DispatchID)
	entry.cancel()
	// A Disable racing this request may already have closed the dispatch out as cancelled, and a
	// second terminal frame would finalize the job twice — once on a refusal it never suffered.
	if entry.claimTerminal() {
		r.emitTerminal(r.summaryFrame(entry.req, scanResult{
			outcome:   frame.DiscoveryOutcomeRejected,
			errorCode: code,
			notes:     []string{msg},
		}))
	}
	return fmt.Errorf("%w: %s", sentinel, msg)
}

func (r *Runtime) forget(dispatchID string) {
	r.mu.Lock()
	delete(r.open, dispatchID)
	r.mu.Unlock()
}

func (r *Runtime) currentScope() netscope.Scope {
	r.mu.Lock()
	defer r.mu.Unlock()
	return r.scope
}

// dispatchLoop runs queued dispatches one at a time.
//
// Serial on purpose: max_concurrent_hosts is the bound the grant places on how many addresses this
// agent probes at once, and running two dispatches side by side would multiply it by a number
// nobody granted. The backend leases one job per agent anyway, so the queue exists to absorb a
// racing re-dispatch rather than to overlap work.
func (r *Runtime) dispatchLoop(ctx context.Context) {
	for {
		select {
		case <-ctx.Done():
			return
		case entry := <-r.queue:
			r.execute(ctx, entry)
		}
	}
}

// pump forwards findings and parked terminal summaries to the outbound data-frame channel. It is
// the only writer to out, and it is a separate goroutine precisely so a slow or disconnected
// consumer cannot reach back into link's inbound goroutine through Request or Cancel.
//
// The two sources are separate arms rather than one queue because only one of them is allowed to
// drop a frame when it fills. Splitting them costs no ordering: a dispatch closed through the
// backlog never ran, so that summary is the only frame it ever produces — claimTerminal succeeds
// only while a dispatch is still queued — and a running dispatch's summary rides the same findings
// buffer as its own host findings, behind them.
func (r *Runtime) pump(ctx context.Context) {
	// Said out loud on the way out: a summary still parked when the pump stops is a scan job the
	// server has to expire, and silence would read as a frame lost in transit instead.
	defer r.reportUnsentTerminals()
	for {
		select {
		case <-ctx.Done():
			return
		case <-r.terminals.wake:
			if !r.drainTerminals(ctx) {
				return
			}
		case f := <-r.findings:
			if !r.forward(ctx, f) {
				return
			}
		}
	}
}

// drainTerminals empties the backlog oldest-first, reporting false when the runtime stopped
// mid-send. It drains to empty rather than one frame per wake-up because the wake signal is
// coalesced: a producer whose token found the channel already full is relying on this pass to pick
// its frame up.
func (r *Runtime) drainTerminals(ctx context.Context) bool {
	for {
		f, ok := r.terminals.next()
		if !ok {
			return true
		}
		if !r.forward(ctx, f) {
			r.terminals.requeue(f)
			return false
		}
	}
}

// forward is the pump's one send to out. Waiting here is the entire point of the pump: it is the
// runtime's own goroutine and the wait is bounded by the runtime context, so no producer — least of
// all link's inbound goroutine — ever waits on the consumer itself.
func (r *Runtime) forward(ctx context.Context, f frame.Frame) bool {
	select {
	case r.out <- f:
		return true
	case <-ctx.Done():
		return false
	}
}

func (r *Runtime) reportUnsentTerminals() {
	if depth := r.terminals.depth(); depth > 0 {
		log.Printf("discover: the finding pump stopped with %d terminal summaries still queued; "+
			"the scan jobs behind them close on the server's dispatch deadline instead", depth)
	}
}

// execute runs one dispatch to completion and emits exactly one summary for it.
func (r *Runtime) execute(runCtx context.Context, entry *dispatch) {
	if !entry.begin() {
		// Cancelled while it sat in the queue: cancelDispatch already closed it out.
		return
	}
	defer entry.cancel()
	defer r.forget(entry.req.DispatchID)

	result := r.scan(runCtx, entry)

	// Cancellation outranks whatever the scan produced. A sweep interrupted mid-flight returns a
	// context error, which would otherwise read as an execution error and misreport a deliberate
	// stop as an agent fault. The counts are kept: the hosts found before the stop were still
	// observed, and the summary says how far the scan got.
	if reason, cancelled := entry.cancellation(); cancelled {
		result.outcome = frame.DiscoveryOutcomeCancelled
		result.errorCode = ""
		result.notes = append([]string{cancelledMsg(reason)}, result.notes...)
	}
	r.deliver(runCtx, r.summaryFrame(entry.req, result))
}

// scan performs one dispatch's work: expand the targets, read the kernel's existing knowledge,
// sweep, and emit one host finding per address that answered.
func (r *Runtime) scan(runCtx context.Context, entry *dispatch) scanResult {
	req := entry.req

	// The one deadline the runtime owns itself. The validator refuses a request that was already
	// stale on arrival; this covers a dispatch that sat in the queue until its deadline ran out,
	// and it is an execution error rather than a silent drop because the job has to close either
	// way. It is checked before the neighbor cache so an expired dispatch performs no work at all.
	if now := r.now(); !req.DeadlineAt.After(now) {
		return scanResult{
			outcome:   frame.DiscoveryOutcomeExecutionError,
			errorCode: ErrorCodeDeadlineExceeded,
			notes: []string{fmt.Sprintf("deadline_at %s had already passed when the dispatch reached the scanner",
				req.DeadlineAt.UTC().Format(time.RFC3339))},
		}
	}
	ctx, cancel := context.WithDeadline(entry.ctx, req.DeadlineAt)
	defer cancel()

	opts := requestOptions(req)
	addrs := targetAddresses(r.currentScope(), req.Targets)

	neighbors, notes := r.neighborCache(ctx, opts, addrs)

	pipe := r.newPipeline(runCtx, ctx, req, opts, neighbors)
	// Sweep's error is kept rather than discarded. Its only source is ctx.Err(), and this ctx has
	// exactly two ways to end early — the dispatch being cancelled, and the deadline above running
	// out mid-sweep. The second one has no other signal at all: the pre-sweep check cannot see it,
	// the counts look like an ordinary small result, and dropping the error here is what would
	// report a quarter-scanned /24 as outcome="completed".
	summary, sweepErr := r.liveness.Sweep(ctx, addrs, opts, pipe.report)

	// An address the kernel already knows about but that answered nothing is still a host: the
	// neighbor cache is one of plan §1's four methods and the only one that needs no reply. This
	// runs after the sweep so a host that answered is reported once, with both sources of evidence
	// on one finding, and is skipped entirely on cancellation — an address the scan never reached
	// is not something it observed.
	if ctx.Err() == nil {
		for _, addr := range addrs {
			if _, known := neighbors[addr]; known {
				pipe.report(LiveHost{Address: addr})
			}
		}
	}
	pipe.close()

	if summary.ICMPUnavailable {
		// A degradation, never a failure: the sweep still ran on TCP connect alone, and an agent
		// with no unprivileged ICMP privileges must still be able to discover.
		notes = append(notes, "the unprivileged ICMP socket was unavailable, so only TCP connect was used: "+
			summary.ICMPReason)
	}

	result := scanResult{
		outcome:          frame.DiscoveryOutcomeCompleted,
		notes:            notes,
		hostsFound:       pipe.count(),
		addressesScanned: summary.AddressesScanned,
	}
	// A deadline that ran out mid-sweep is an execution error, not a completion. It is the same code
	// the pre-sweep check uses because it is the same fault — the agent held a live request until its
	// deadline ran out — and the counts are *retained* rather than zeroed: the hosts observed before
	// the deadline were still observed, and the job keeps them and stays reviewable. Only the
	// outcome changes, which is what tells the operator the coverage is partial.
	//
	// Nothing is done here about context.Canceled. Cancellation is entry.cancellation()'s to report
	// and execute() overrides this result with it, so a cancel that raced the deadline reports
	// `cancelled` — which is the truthful answer, because the operator stopped the scan.
	if errors.Is(sweepErr, context.DeadlineExceeded) {
		result.outcome = frame.DiscoveryOutcomeExecutionError
		result.errorCode = ErrorCodeDeadlineExceeded
		result.notes = append(result.notes, fmt.Sprintf(
			"deadline_at %s ran out mid-sweep: %d of %d addresses were scanned",
			req.DeadlineAt.UTC().Format(time.RFC3339), summary.AddressesScanned, len(addrs)))
	}
	return result
}

// neighborCache reads the kernel's neighbor cache once per dispatch and keeps only the entries
// this request was asked about.
//
// A failure degrades rather than failing the scan: plan §1 lists the cache as one of four methods,
// and a kernel that will not give one up must not cost the operator the ICMP and TCP results. The
// reason is carried into the summary's msg so the operator learns why the MAC addresses are
// missing instead of concluding the LAN has none.
func (r *Runtime) neighborCache(ctx context.Context, opts Options, addrs []netip.Addr) (map[netip.Addr]Neighbor, []string) {
	if !opts.wants(MethodNeighborCache) {
		return nil, nil
	}
	entries, err := r.neighbors(ctx)
	if err != nil {
		return nil, []string{"the kernel neighbor cache could not be read: " + err.Error()}
	}

	wanted := make(map[netip.Addr]bool, len(addrs))
	for _, addr := range addrs {
		wanted[addr] = true
	}
	cache := make(map[netip.Addr]Neighbor, len(entries))
	for _, entry := range entries {
		// The kernel knows about addresses this dispatch was not asked about — other subnets, the
		// default gateway, whatever the agent itself last spoke to. Reporting one would be a
		// finding for an address nobody authorized scanning.
		if addr := entry.IP.Unmap(); wanted[addr] {
			cache[addr] = entry
		}
	}
	return cache, nil
}

// requestOptions turns one request into the collector bounds every method reads.
//
// The two ceilings are capability's own, not a second opinion: they are the widest values the
// server's normalizer can ever put in a grant, so clamping to them cannot narrow anything a
// legitimate request asked for, while a request that names more concurrency than any grant could
// hold is a backend bug this agent must not act on — max_concurrent_hosts multiplies directly into
// open sockets.
func requestOptions(req frame.DiscoveryRequestPayload) Options {
	concurrency := req.MaxConcurrentHosts
	if concurrency > capability.MaxDiscoveryHosts {
		concurrency = capability.MaxDiscoveryHosts
	}
	timeoutMS := req.HostTimeoutMS
	if timeoutMS > capability.MaxDiscoveryHostTimeoutMS {
		timeoutMS = capability.MaxDiscoveryHostTimeoutMS
	}
	return Options{
		Methods:            req.Methods,
		TCPPorts:           req.TCPPorts,
		HostTimeout:        time.Duration(timeoutMS) * time.Millisecond,
		MaxConcurrentHosts: concurrency,
	}
}

// targetAddresses expands the request's prefixes into the addresses that will actually be probed.
//
// Every address goes through netscope, the one scope evaluator, even though the validator already
// approved the whole prefix through NetworkInScope. The two questions are genuinely different: a
// prefix can be entirely in scope while individual addresses inside it are not, and the subnet
// directed broadcast is exactly that case — netscope refuses it because it is only recognizable
// against the enclosing network. Enumeration is the only thing done here; the CIDR opinion stays
// where the package doc says it lives.
//
// A refused address is skipped silently rather than reported as a capability violation: the
// backend approved the prefix, and the addresses this drops are the ones it was never asking
// about.
func targetAddresses(scope netscope.Scope, targets []string) []netip.Addr {
	seen := map[netip.Addr]bool{}
	var addrs []netip.Addr
	for _, target := range targets {
		prefix, err := netip.ParsePrefix(strings.TrimSpace(target))
		if err != nil {
			// Unparseable prefixes are the validator's refusal to make, and it has already made
			// it. Skipping here keeps a malformed entry from being read as "scan everything".
			continue
		}
		// Next() returns the zero Addr when it runs off the end of the address space, and
		// Contains rejects that, so the loop terminates on the last address of ::/0 as well.
		for addr := prefix.Masked().Addr(); prefix.Contains(addr); addr = addr.Next() {
			// Unmap so an IPv4-mapped prefix yields the same address a v4 prefix would, which is
			// what keeps a target named both ways from being scanned twice.
			candidate := addr.Unmap()
			if seen[candidate] {
				continue
			}
			seen[candidate] = true
			if decision := netscope.Evaluate(scope, candidate.String(), nil); !decision.Allowed {
				continue
			}
			addrs = append(addrs, candidate)
		}
	}
	return addrs
}

// pipeline turns live hosts into discovery.finding frames.
//
// It exists because Liveness.Sweep calls its emit callback under the lock every host shares, so
// the callback must be cheap: doing the PTR lookup and the banner captures there would serialise
// the whole sweep behind one slow resolver. The workers are bounded by the same
// max_concurrent_hosts the sweep is, because enrichment is the same shape of work as a probe —
// one bounded connect per port and one bounded query — against the same set of hosts.
type pipeline struct {
	rt        *Runtime
	runCtx    context.Context
	scanCtx   context.Context
	req       frame.DiscoveryRequestPayload
	opts      Options
	neighbors map[netip.Addr]Neighbor

	hosts   chan LiveHost
	workers sync.WaitGroup

	mu       sync.Mutex
	reported map[netip.Addr]bool
	found    int
}

func (r *Runtime) newPipeline(runCtx, scanCtx context.Context, req frame.DiscoveryRequestPayload, opts Options, neighbors map[netip.Addr]Neighbor) *pipeline {
	p := &pipeline{
		rt:        r,
		runCtx:    runCtx,
		scanCtx:   scanCtx,
		req:       req,
		opts:      opts,
		neighbors: neighbors,
		hosts:     make(chan LiveHost, opts.concurrency()),
		reported:  map[netip.Addr]bool{},
	}
	for i := 0; i < opts.concurrency(); i++ {
		p.workers.Add(1)
		go p.work()
	}
	return p
}

// report queues one host for enrichment. The second report for an address is dropped, which is
// what lets the sweep and the neighbor-cache pass both offer the same host without producing two
// findings for it — and, because the finding id is a digest of the address, without producing two
// rows the server would have to reconcile.
//
// The send blocks when every worker is busy. That is deliberate back-pressure: dropping a finding
// would leave the summary claiming a host count it never delivered. It cannot wedge, because a
// worker's whole budget is one bounded lookup plus one bounded capture per open port.
func (p *pipeline) report(host LiveHost) {
	p.mu.Lock()
	if p.reported[host.Address] {
		p.mu.Unlock()
		return
	}
	p.reported[host.Address] = true
	p.found++
	p.mu.Unlock()

	p.hosts <- host
}

func (p *pipeline) count() int {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.found
}

// close stops accepting hosts and waits for the ones already queued. Joining before the summary is
// built is what guarantees the terminal frame is last: the backend finalizes the job on the first
// terminal frame it sees, so a host finding arriving after it would be rejected as late.
func (p *pipeline) close() {
	close(p.hosts)
	p.workers.Wait()
}

func (p *pipeline) work() {
	defer p.workers.Done()
	for host := range p.hosts {
		p.rt.deliver(p.runCtx, p.rt.findingFrame(p.req.DispatchID, p.enrich(host)))
	}
}

// enrich adds everything that is not liveness evidence: the MAC the kernel already had, the PTR
// name, and one banner per open port.
//
// None of it can fail the finding. A host that answered a connect is a host whether or not it has
// a name or volunteers a greeting, and the address, MAC and ports are what the backend matches on.
func (p *pipeline) enrich(host LiveHost) frame.DiscoveryFindingPayload {
	payload := frame.DiscoveryFindingPayload{
		DispatchID: p.req.DispatchID,
		ScanJobID:  p.req.ScanJobID,
		FindingID:  findingID(p.req.DispatchID, frame.DiscoveryKindHost, host.Address.String()),
		Kind:       frame.DiscoveryKindHost,
		ObservedAt: p.rt.now(),
		IPAddress:  host.Address.String(),
		Hostname:   p.rt.resolver.Lookup(p.scanCtx, host.Address, p.opts),
	}
	// The cache is named first because it is evidence the kernel already held before this scan
	// touched anything; the sweep's own evidence follows in the order it ran.
	if neighbor, known := p.neighbors[host.Address]; known {
		payload.Evidence = append(payload.Evidence, MethodNeighborCache)
		payload.MACAddress = neighbor.MAC
	}
	payload.Evidence = append(payload.Evidence, host.Evidence...)

	for _, port := range host.OpenPorts {
		payload.OpenPorts = append(payload.OpenPorts, frame.DiscoveryOpenPort{
			Port:     port,
			Protocol: "tcp",
			Banner:   p.rt.banner.Capture(p.scanCtx, host.Address, port, p.opts),
		})
	}
	return payload
}

// findingID is the digest that makes spool replay idempotent.
//
// It is deliberately not collect.SampleID(), which is random per call: the server's
// uq_scan_results_job_finding is an idempotency key rather than a race only because a batch
// replayed after an outage collides with the rows it already wrote. dispatch, kind and address are
// exactly the three fields that identify a finding within a job — kind is in the digest so a
// dispatch's summary cannot collide with the host finding for an empty address.
func findingID(dispatchID, kind, address string) string {
	digest := sha256.Sum256([]byte(dispatchID + "|" + kind + "|" + address))
	return hex.EncodeToString(digest[:])
}

// summaryFrame builds the one terminal finding that closes a dispatch.
func (r *Runtime) summaryFrame(req frame.DiscoveryRequestPayload, result scanResult) frame.Frame {
	hosts, scanned := result.hostsFound, result.addressesScanned
	return r.findingFrame(req.DispatchID, frame.DiscoveryFindingPayload{
		DispatchID: req.DispatchID,
		ScanJobID:  req.ScanJobID,
		FindingID:  findingID(req.DispatchID, frame.DiscoveryKindSummary, ""),
		Kind:       frame.DiscoveryKindSummary,
		ObservedAt: r.now(),
		Terminal:   true,
		Outcome:    result.outcome,
		// Both counts are always set, even at zero: they are pointers on the wire, and a refusal
		// that omitted them would read as "unknown" rather than as the "nothing was scanned" it
		// is.
		HostsFound:       &hosts,
		AddressesScanned: &scanned,
		Msg:              boundMsg(strings.Join(result.notes, "; ")),
		ErrorCode:        result.errorCode,
	})
}

func (r *Runtime) findingFrame(dispatchID string, payload frame.DiscoveryFindingPayload) frame.Frame {
	data, err := json.Marshal(payload)
	if err != nil {
		// Nothing here is unencodable, so this is a bug rather than a condition; the alternative
		// is a panic on the dispatcher goroutine, which would take the agent down.
		log.Printf("discover: encoding a %s finding for dispatch %s failed: %v", payload.Kind, dispatchID, err)
		return frame.Frame{}
	}
	return frame.Frame{Type: frame.TypeDiscoveryFinding, TS: payload.ObservedAt, Payload: data}
}

// terminalBacklog parks the terminal summaries produced outside a scan until the pump can send
// them.
//
// A dispatch's terminal summary is the frame that closes the scan job, so losing one is the
// hanging-job failure this collector exists to prevent: the server would wait out the whole
// dispatch deadline and then close the job with the wrong reason. Unlike a host finding, it may not
// be dropped just because the finding buffer is full.
//
// It equally may not be *waited* on where it is produced. refuse and cancelDispatch run on link's
// inbound goroutine — Request and Cancel are bound under an enqueue-only contract, see
// link.Options.OnDiscoveryRequest — and that goroutine also drives the heartbeat, the rekey and the
// drain tickers. Worse, link's runOnce reads inbound frames and Options.DataFrames from the *same*
// select, so for as long as a request handler runs nobody is draining the channel the summary has
// to leave by: a blocking send there would not be slow, it would be a deadlock until the read
// deadline fired.
//
// So the producer only appends and the pump does the waiting, bounded by the runtime context. The
// backlog is a slice rather than a second buffered channel because a fixed bound would drop in
// exactly the burst it exists for — refusals arriving back-to-back on that one goroutine, none of
// them forwardable until the last of them returns. What it holds is one small frame per dispatch
// that never started work, produced only by that goroutine and by Disable/Stop, so there is nothing
// here for an unbounded queue to run away with.
type terminalBacklog struct {
	mu      sync.Mutex
	pending []frame.Frame
	// wake carries at most one token, because the pump drains the backlog to empty per wake-up: a
	// token that cannot be added is always one whose work the token already in flight will do.
	// Signalling *after* the append is what makes that safe — a drain pass that found the backlog
	// empty has already consumed its token, so the next append's own token gets through.
	wake chan struct{}
}

func newTerminalBacklog() *terminalBacklog {
	return &terminalBacklog{wake: make(chan struct{}, 1)}
}

// add parks one frame and wakes the pump. It never blocks and never drops.
func (b *terminalBacklog) add(f frame.Frame) {
	b.mu.Lock()
	b.pending = append(b.pending, f)
	b.mu.Unlock()
	b.signal()
}

// next takes the oldest parked frame, reporting false when there is none.
func (b *terminalBacklog) next() (frame.Frame, bool) {
	b.mu.Lock()
	defer b.mu.Unlock()
	if len(b.pending) == 0 {
		return frame.Frame{}, false
	}
	f := b.pending[0]
	b.pending = b.pending[1:]
	return f, true
}

// requeue puts a frame the pump could not send back at the head, so the shutdown report counts it
// and a Start following that Stop sends it in order rather than behind whatever arrives next.
func (b *terminalBacklog) requeue(f frame.Frame) {
	b.mu.Lock()
	b.pending = append([]frame.Frame{f}, b.pending...)
	b.mu.Unlock()
	b.signal()
}

func (b *terminalBacklog) depth() int {
	b.mu.Lock()
	defer b.mu.Unlock()
	return len(b.pending)
}

func (b *terminalBacklog) signal() {
	select {
	case b.wake <- struct{}{}:
	default:
	}
}

// emitTerminal hands a dispatch's one terminal summary to the pump from outside its scan — a
// refusal, or a cancellation that arrived before the dispatcher reached it. It is the counterpart
// to deliver, which the scan goroutines use for their findings and for their own summary: this one
// can neither wait for room nor drop the frame, so it parks it. See terminalBacklog.
func (r *Runtime) emitTerminal(f frame.Frame) {
	if f.Type == "" {
		// findingFrame already logged the encoding failure; there is no frame to park.
		return
	}
	r.terminals.add(f)
}

// deliver hands one frame to the pump from a scan goroutine, waiting for room. Waiting rather than
// dropping is the point: the summary's counts describe findings that were actually sent, so a
// dropped host finding would make the terminal frame lie about the scan. Only Stop can end the
// wait, and a frame lost that way is one the agent was shutting down under anyway.
func (r *Runtime) deliver(ctx context.Context, f frame.Frame) {
	if f.Type == "" {
		return
	}
	select {
	case r.findings <- f:
		return
	default:
	}
	select {
	case r.findings <- f:
	case <-ctx.Done():
		log.Printf("discover: dropped a %s frame — the agent stopped before it could be sent", f.Type)
	}
}

// boundMsg keeps the summary inside the wire limit the server's model enforces. The message
// carries a kernel error string and a server-supplied cancellation reason, neither of which this
// agent bounds anywhere else, and a summary rejected for length would leave the job unfinalized.
func boundMsg(msg string) string {
	runes := []rune(msg)
	if len(runes) <= frame.MaxDiscoveryMsgRunes {
		return msg
	}
	return string(runes[:frame.MaxDiscoveryMsgRunes])
}

// begin claims a queued dispatch for execution, reporting false when a cancellation got there
// first.
func (d *dispatch) begin() bool {
	d.mu.Lock()
	defer d.mu.Unlock()
	if d.state != dispatchQueued {
		return false
	}
	d.state = dispatchRunning
	return true
}

// claimTerminal claims the right to emit this dispatch's one terminal summary from outside its
// scan, and succeeds exactly once. Every path that closes a dispatch without running it — a
// refusal, a cancellation, a Disable, a Stop — goes through it, because they can race each other:
// two of them emitting would hand the backend two terminal frames for one job, and it finalizes on
// the first. A dispatch already running is left alone; its scan owns the summary.
func (d *dispatch) claimTerminal() bool {
	d.mu.Lock()
	defer d.mu.Unlock()
	if d.state != dispatchQueued {
		return false
	}
	d.state = dispatchDone
	return true
}

func (d *dispatch) cancellation() (string, bool) {
	d.mu.Lock()
	defer d.mu.Unlock()
	return d.cancelReason, d.cancelled
}
