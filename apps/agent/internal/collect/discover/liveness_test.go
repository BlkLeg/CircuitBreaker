package discover

import (
	"context"
	"errors"
	"fmt"
	"net"
	"net/netip"
	"runtime"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"circuitbreaker.dev/cb-agent/internal/collect/probe"
)

// ---------------------------------------------------------------------------
// Fakes. Nothing in this file may touch the kernel: an ICMP socket needs
// ping_group_range to cover the test runner's GID, and a real dial would make
// the concurrency and timeout assertions depend on whoever's LAN is nearby.
// ---------------------------------------------------------------------------

// overlap counts calls that are in flight at the same time and remembers the high-water mark.
// It is how "max_concurrent_hosts is never exceeded" is asserted: the bound is only observable
// from inside the work, because the sweep releases a slot the instant a host finishes.
type overlap struct {
	mu      sync.Mutex
	current int
	high    int
	total   int
}

func newOverlap() *overlap { return &overlap{} }

func (o *overlap) enter() {
	o.mu.Lock()
	defer o.mu.Unlock()
	o.current++
	o.total++
	if o.current > o.high {
		o.high = o.current
	}
}

func (o *overlap) leave() {
	o.mu.Lock()
	defer o.mu.Unlock()
	o.current--
}

func (o *overlap) peak() int {
	o.mu.Lock()
	defer o.mu.Unlock()
	return o.high
}

func (o *overlap) inFlight() int {
	o.mu.Lock()
	defer o.mu.Unlock()
	return o.current
}

func (o *overlap) calls() int {
	o.mu.Lock()
	defer o.mu.Unlock()
	return o.total
}

type echoCall struct {
	dst     netip.Addr
	seq     int
	timeout time.Duration
}

// stubEcho stands in for one open probe.EchoSession.
type stubEcho struct {
	mu     sync.Mutex
	calls  []echoCall
	closed int
	reply  func(ctx context.Context, dst netip.Addr) (bool, error)
}

func (s *stubEcho) Ping(ctx context.Context, dst netip.Addr, seq int, timeout time.Duration) (time.Duration, bool, error) {
	s.mu.Lock()
	s.calls = append(s.calls, echoCall{dst: dst, seq: seq, timeout: timeout})
	reply := s.reply
	s.mu.Unlock()
	if reply == nil {
		return 0, false, nil
	}
	ok, err := reply(ctx, dst)
	return 0, ok, err
}

func (s *stubEcho) Close() error {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.closed++
	return nil
}

func (s *stubEcho) sent() []echoCall {
	s.mu.Lock()
	defer s.mu.Unlock()
	return append([]echoCall(nil), s.calls...)
}

// stubNet is the whole network stack this package is allowed to reach, in one place.
type stubNet struct {
	openErr   error
	openCalls atomic.Int64
	session   *stubEcho

	dialMu    sync.Mutex
	dialed    []string
	dialCtx   []context.Context
	dialReply func(ctx context.Context, address string) error
}

func (n *stubNet) open(string) (probe.EchoSession, error) {
	n.openCalls.Add(1)
	if n.openErr != nil {
		return nil, n.openErr
	}
	return n.session, nil
}

func (n *stubNet) dial(ctx context.Context, _, address string) (net.Conn, error) {
	n.dialMu.Lock()
	n.dialed = append(n.dialed, address)
	n.dialCtx = append(n.dialCtx, ctx)
	reply := n.dialReply
	n.dialMu.Unlock()
	if reply == nil {
		return nil, errors.New("connection refused")
	}
	if err := reply(ctx, address); err != nil {
		return nil, err
	}
	return openStubConn(), nil
}

func (n *stubNet) addresses() []string {
	n.dialMu.Lock()
	defer n.dialMu.Unlock()
	return append([]string(nil), n.dialed...)
}

func (n *stubNet) contexts() []context.Context {
	n.dialMu.Lock()
	defer n.dialMu.Unlock()
	return append([]context.Context(nil), n.dialCtx...)
}

// openStubConn returns a net.Conn the sweep can only close. net.Pipe is deliberate: it starts no
// goroutine of its own, so it cannot show up in the leak assertion below.
func openStubConn() net.Conn {
	client, server := net.Pipe()
	_ = server.Close()
	return client
}

func newTestLiveness(stub *stubNet) *Liveness {
	live := NewLiveness()
	live.open = stub.open
	live.dial = stub.dial
	return live
}

func testAddrs(t *testing.T, count int) []netip.Addr {
	t.Helper()
	out := make([]netip.Addr, 0, count)
	for i := 0; i < count; i++ {
		addr, err := netip.ParseAddr(fmt.Sprintf("10.20.%d.%d", i/250, i%250+1))
		if err != nil {
			t.Fatalf("bad generated address: %v", err)
		}
		out = append(out, addr)
	}
	return out
}

func mustParseAddr(t *testing.T, s string) netip.Addr {
	t.Helper()
	addr, err := netip.ParseAddr(s)
	if err != nil {
		t.Fatalf("bad test address %q: %v", s, err)
	}
	return addr
}

// collector accumulates emitted hosts and fails the test if Sweep ever calls back from two
// goroutines at once — callers build one frame per finding, and a callback that needed its own
// lock would put that burden on every caller.
type collector struct {
	t     *testing.T
	mu    sync.Mutex
	busy  atomic.Bool
	hosts []LiveHost
}

func (c *collector) emit(host LiveHost) {
	if !c.busy.CompareAndSwap(false, true) {
		c.t.Error("Sweep called the emit callback concurrently")
	}
	c.mu.Lock()
	c.hosts = append(c.hosts, host)
	c.mu.Unlock()
	c.busy.Store(false)
}

func (c *collector) collected() []LiveHost {
	c.mu.Lock()
	defer c.mu.Unlock()
	return append([]LiveHost(nil), c.hosts...)
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

func TestSweepNeverExceedsMaxConcurrentHosts(t *testing.T) {
	const limit = 6

	t.Run("icmp", func(t *testing.T) {
		busy := newOverlap()
		stub := &stubNet{session: &stubEcho{reply: func(context.Context, netip.Addr) (bool, error) {
			busy.enter()
			defer busy.leave()
			time.Sleep(2 * time.Millisecond)
			return true, nil
		}}}
		sink := &collector{t: t}

		summary, err := newTestLiveness(stub).Sweep(
			context.Background(),
			testAddrs(t, 60),
			Options{Methods: []string{MethodICMP}, HostTimeout: time.Second, MaxConcurrentHosts: limit},
			sink.emit,
		)
		if err != nil {
			t.Fatalf("Sweep: %v", err)
		}
		if summary.AddressesScanned != 60 || summary.HostsFound != 60 {
			t.Fatalf("summary = %+v, want 60 scanned and 60 found", summary)
		}
		if peak := busy.peak(); peak > limit {
			t.Fatalf("%d hosts were probed at once, want at most %d", peak, limit)
		}
		// Without this the assertion above passes trivially on a sweep that never overlaps
		// anything — a serial implementation would look perfectly bounded.
		if peak := busy.peak(); peak < 2 {
			t.Fatalf("peak concurrency %d: the sweep never ran two hosts at once, so the bound is untested", peak)
		}
	})

	t.Run("tcp_connect", func(t *testing.T) {
		busy := newOverlap()
		stub := &stubNet{dialReply: func(context.Context, string) error {
			busy.enter()
			defer busy.leave()
			time.Sleep(2 * time.Millisecond)
			return nil
		}}
		sink := &collector{t: t}

		// One granted port, so one dial per host: any overlap counted here is host overlap.
		summary, err := newTestLiveness(stub).Sweep(
			context.Background(),
			testAddrs(t, 60),
			Options{
				Methods:            []string{MethodTCPConnect},
				TCPPorts:           []int{443},
				HostTimeout:        time.Second,
				MaxConcurrentHosts: limit,
			},
			sink.emit,
		)
		if err != nil {
			t.Fatalf("Sweep: %v", err)
		}
		if summary.HostsFound != 60 {
			t.Fatalf("summary = %+v, want 60 found", summary)
		}
		if peak := busy.peak(); peak > limit || peak < 2 {
			t.Fatalf("peak concurrency %d, want between 2 and %d", peak, limit)
		}
	})
}

func TestSweepHonorsHostTimeout(t *testing.T) {
	const hostTimeout = 60 * time.Millisecond

	t.Run("passes the budget to both checks", func(t *testing.T) {
		stub := &stubNet{session: &stubEcho{}}
		if _, err := newTestLiveness(stub).Sweep(
			context.Background(),
			[]netip.Addr{mustParseAddr(t, "10.20.0.5")},
			Options{TCPPorts: []int{80}, HostTimeout: hostTimeout, MaxConcurrentHosts: 4},
			nil,
		); err != nil {
			t.Fatalf("Sweep: %v", err)
		}

		sent := stub.session.sent()
		if len(sent) != 1 {
			t.Fatalf("got %d echoes, want exactly one per host", len(sent))
		}
		if sent[0].timeout != hostTimeout {
			t.Fatalf("echo timeout = %s, want the host budget %s", sent[0].timeout, hostTimeout)
		}
		contexts := stub.contexts()
		if len(contexts) != 1 {
			t.Fatalf("got %d dials, want one per granted port", len(contexts))
		}
		deadline, ok := contexts[0].Deadline()
		if !ok {
			t.Fatal("the dial context carried no deadline, so a hung connect would run to the job deadline")
		}
		if remaining := time.Until(deadline); remaining > hostTimeout {
			t.Fatalf("dial deadline is %s away, want at most the host budget %s", remaining, hostTimeout)
		}
	})

	// The budget one address gets is SHARED between its echo and every one of its connects
	// (Options.HostTimeout's own doc, and the single context.WithTimeout in probeHost). Two granted
	// ports below is what makes that observable: under a per-check budget the same request would
	// take three budgets rather than one, and each connect would be handed a deadline a whole
	// budget later than the address started.
	t.Run("the budget is shared by the echo and every connect, not spent per check", func(t *testing.T) {
		const grantedPorts = 2

		stub := &stubNet{
			// The echo consumes the whole address budget before a single connect is attempted. That
			// ordering is the discriminator: a shared budget leaves the connects nothing, while a
			// per-check budget would hand each of them a fresh one.
			session: &stubEcho{reply: func(ctx context.Context, _ netip.Addr) (bool, error) {
				<-ctx.Done()
				return false, nil
			}},
			dialReply: func(ctx context.Context, _ string) error {
				<-ctx.Done()
				return ctx.Err()
			},
		}
		started := time.Now()
		summary, err := newTestLiveness(stub).Sweep(
			context.Background(),
			testAddrs(t, 4),
			Options{TCPPorts: []int{80, 443}, HostTimeout: hostTimeout, MaxConcurrentHosts: 4},
			nil,
		)
		elapsed := time.Since(started)
		if err != nil {
			t.Fatalf("Sweep: %v", err)
		}
		if summary.HostsFound != 0 || summary.AddressesScanned != 4 {
			t.Fatalf("summary = %+v, want 4 scanned and none found", summary)
		}
		if elapsed < hostTimeout {
			t.Fatalf("the sweep returned in %s, sooner than the %s budget it was supposed to wait", elapsed, hostTimeout)
		}
		// Four hosts under a concurrency of four is *one* budget's worth of work, not one per
		// check. The bound is under two budgets so an implementation that gave the echo and the
		// connects a budget each — three in series here — cannot pass it, while still leaving a
		// whole budget of slack for the -race scheduler.
		// Errorf, not Fatalf: the deadline seam below is an independent fact about the same sweep,
		// and stopping here would leave the sharper of the two assertions unreached.
		if elapsed >= 2*hostTimeout {
			t.Errorf("the sweep took %s, at least two of its %s budgets: the address budget is being spent per check",
				elapsed, hostTimeout)
		}

		// The timing bound above is the coarse half; this is the exact seam. Every connect of one
		// address is handed the address's own deadline, which is at most one budget from the moment
		// the sweep started — not one budget from the moment the connect was attempted.
		contexts := stub.contexts()
		if len(contexts) != 4*grantedPorts {
			t.Fatalf("got %d dials, want one per granted port per address (%d)", len(contexts), 4*grantedPorts)
		}
		for i, dialCtx := range contexts {
			deadline, ok := dialCtx.Deadline()
			if !ok {
				t.Fatalf("dial %d carried no deadline, so a hung connect would run to the job deadline", i)
			}
			// sharedBudgetSlack absorbs the few milliseconds between the sweep starting and an
			// address being dispatched. A per-check budget would miss by a whole hostTimeout, which
			// is an order of magnitude more.
			const sharedBudgetSlack = 20 * time.Millisecond
			if over := deadline.Sub(started.Add(hostTimeout)); over > sharedBudgetSlack {
				t.Errorf("dial %d's deadline is %s past start+%s, want the address's own shared budget",
					i, over, hostTimeout)
			}
		}
	})
}

// leakedWorkerLifetime is how long a cancelled host's goroutine stays alive in the stub below,
// after its context is done. goroutineSettleWindow — the whole time the leak assertion is willing
// to wait for the count to come to rest — is deliberately a small fraction of it.
//
// That ratio is the entire load-bearing part of the assertion. A settle window longer than this
// lifetime waits a real leak out: the leaked workers finish while the poll loop is still polling,
// the count drops to where it started, and the test reports success about a Sweep that returned
// with eight sockets still open.
const (
	leakedWorkerLifetime  = 150 * time.Millisecond
	goroutineSettleWindow = 30 * time.Millisecond
	goroutineSettleStep   = 3 * time.Millisecond
)

func TestSweepStopsOnCancellationWithoutLeakingGoroutines(t *testing.T) {
	// A budget far longer than the test's patience: if cancellation were implemented by simply
	// letting the in-flight hosts time out, this test would take ten seconds, not milliseconds.
	const hostTimeout = 10 * time.Second
	// The concurrency below, named so the at-return assertion can say how many goroutines a lost
	// join would have left behind.
	const concurrency = 8

	before := runtime.NumGoroutine()

	probing := make(chan struct{}, 1)
	busy := newOverlap()
	stub := &stubNet{
		session: &stubEcho{reply: func(ctx context.Context, _ netip.Addr) (bool, error) {
			busy.enter()
			defer busy.leave()
			select {
			case probing <- struct{}{}:
			default:
			}
			<-ctx.Done()
			// A real check does not vanish the instant its context is cancelled — a socket still
			// has to come back and be closed. The delay is what makes an unjoined worker
			// observable below; without it a leaked goroutine would finish during the assertion.
			time.Sleep(leakedWorkerLifetime)
			return false, nil
		}},
		dialReply: func(ctx context.Context, _ string) error {
			<-ctx.Done()
			return ctx.Err()
		},
	}

	ctx, cancel := context.WithCancel(context.Background())
	type outcome struct {
		summary SweepSummary
		err     error
		elapsed time.Duration
		// atReturn is runtime.NumGoroutine() sampled in the same statement sequence as Sweep's
		// return, before anything has had a chance to settle. A leaked host is still sleeping at
		// that instant; a joined one has already been told to stop.
		atReturn int
	}
	done := make(chan outcome, 1)
	go func() {
		started := time.Now()
		summary, err := newTestLiveness(stub).Sweep(
			ctx,
			testAddrs(t, 500),
			Options{TCPPorts: []int{80, 443}, HostTimeout: hostTimeout, MaxConcurrentHosts: concurrency},
			nil,
		)
		done <- outcome{summary: summary, err: err, elapsed: time.Since(started), atReturn: runtime.NumGoroutine()}
	}()

	select {
	case <-probing:
	case <-time.After(5 * time.Second):
		cancel()
		t.Fatal("no host was probed within five seconds")
	}
	cancel()

	var got outcome
	select {
	case got = <-done:
	case <-time.After(2 * time.Second):
		t.Fatal("Sweep did not return within two seconds of cancellation")
	}
	if got.elapsed >= hostTimeout {
		t.Fatalf("Sweep took %s, longer than the %s host budget it should have collapsed", got.elapsed, hostTimeout)
	}
	if !errors.Is(got.err, context.Canceled) {
		t.Fatalf("err = %v, want context.Canceled", got.err)
	}
	if got.summary.AddressesScanned >= 500 {
		t.Fatalf("scanned %d of 500 addresses: cancellation did not stop the sweep starting new hosts", got.summary.AddressesScanned)
	}

	// Sweep must join its workers, not merely stop starting new ones. Measured at the moment it
	// returns, because a leaked host finishes on its own a moment later and would otherwise be
	// indistinguishable from a joined one.
	//
	// Errorf rather than Fatalf: the goroutine assertions below are independent facts about the
	// same return, and stopping here would leave them unreached — which is exactly how a
	// backstop stops being one.
	if running := busy.inFlight(); running != 0 {
		t.Errorf("Sweep returned while %d hosts were still probing", running)
	}
	if busy.calls() == 0 {
		t.Fatal("no host was probed at all, so nothing about cancellation was exercised")
	}

	// The goroutine count is the backstop for everything the counter above cannot see: the
	// per-port dial goroutines, and anything a future check spawns. Nothing else in this package
	// has an assertion like this.
	//
	// The at-return sample is the loose half. A joined Sweep can still be a few goroutines above
	// `before` at the instant it returns — its workers have been released but the runtime has not
	// finished reaping them — so the tolerance has to cover one wave of them. It catches the
	// catastrophic shape: a Sweep that dispatched far past its concurrency, or that spawned a
	// goroutine per address.
	if leakBound := before + 1 + 2*concurrency; got.atReturn > leakBound {
		t.Errorf("Sweep returned with %d goroutines running (started from %d, bound %d): far more than one wave of workers is still alive",
			got.atReturn, before, leakBound)
	}
	// And this is the tight half. Within goroutineSettleWindow — a fraction of
	// leakedWorkerLifetime — every worker of a joined Sweep is gone, while every worker of a
	// leaked one is still sleeping. A longer window would wait the leak out and assert nothing.
	if after := settledGoroutines(t, before, goroutineSettleWindow); after > before {
		t.Errorf("goroutine count went from %d to %d within %s of the sweep returning; its workers outlived it",
			before, after, goroutineSettleWindow)
	}
}

// settledGoroutines waits up to window for the runtime's goroutine count to come to rest at or
// below want, then reports it. The wait exists because a goroutine that has returned is not
// immediately gone from the count, which would make a bare before/after comparison flaky rather
// than wrong.
//
// window is a parameter rather than a constant because its size is the whole assertion: it must be
// long enough for a goroutine that has already returned to disappear, and short enough that a
// goroutine still doing work cannot finish inside it. See goroutineSettleWindow.
func settledGoroutines(t *testing.T, want int, window time.Duration) int {
	t.Helper()
	deadline := time.Now().Add(window)
	count := runtime.NumGoroutine()
	for count > want && time.Now().Before(deadline) {
		time.Sleep(goroutineSettleStep)
		count = runtime.NumGoroutine()
	}
	return count
}

func TestSweepDegradesToTCPConnectWhenICMPIsUnavailable(t *testing.T) {
	// What a host whose net.ipv4.ping_group_range does not cover the agent's GID actually
	// returns. It is a host-wide condition, not a per-target one.
	openErr := errors.New("listen ip4:icmp: socket: operation not permitted")
	stub := &stubNet{
		openErr: openErr,
		dialReply: func(_ context.Context, address string) error {
			if strings.HasSuffix(address, ":22") && strings.HasPrefix(address, "10.20.0.1:") {
				return nil
			}
			return errors.New("connection refused")
		},
	}
	sink := &collector{t: t}

	summary, err := newTestLiveness(stub).Sweep(
		context.Background(),
		testAddrs(t, 20),
		Options{TCPPorts: []int{22, 443}, HostTimeout: 200 * time.Millisecond, MaxConcurrentHosts: 4},
		sink.emit,
	)
	// The whole point: a host that cannot send ICMP still runs the job.
	if err != nil {
		t.Fatalf("Sweep failed the job over an unavailable ICMP socket: %v", err)
	}
	if !summary.ICMPUnavailable {
		t.Fatal("summary.ICMPUnavailable is false, so the caller cannot report the degradation")
	}
	if !strings.Contains(summary.ICMPReason, "operation not permitted") {
		t.Fatalf("summary.ICMPReason = %q, want the socket error the operator has to act on", summary.ICMPReason)
	}
	// The latch stops the sweep re-attempting a host-wide failure once per address. Its window is
	// one wave of concurrent hosts — the four that were already past the check when the first
	// failure landed — so the bound is the concurrency, not one. Twenty would mean no latch.
	if opens := stub.openCalls.Load(); opens < 1 || opens > 4 {
		t.Fatalf("the ICMP socket was opened %d times across 20 hosts, want at most the concurrency of 4", opens)
	}

	hosts := sink.collected()
	if len(hosts) != 1 {
		t.Fatalf("got %d hosts, want the single one with an open port", len(hosts))
	}
	if got := hosts[0].Address.String(); got != "10.20.0.1" {
		t.Fatalf("host address = %s, want 10.20.0.1", got)
	}
	if len(hosts[0].Evidence) != 1 || hosts[0].Evidence[0] != MethodTCPConnect {
		t.Fatalf("evidence = %v, want only %q", hosts[0].Evidence, MethodTCPConnect)
	}
	if len(hosts[0].OpenPorts) != 1 || hosts[0].OpenPorts[0] != 22 {
		t.Fatalf("open ports = %v, want [22]", hosts[0].OpenPorts)
	}
	if summary.HostsFound != 1 || summary.AddressesScanned != 20 {
		t.Fatalf("summary = %+v, want 20 scanned and 1 found", summary)
	}
}

func TestSweepReportsEvidencePerHost(t *testing.T) {
	live := mustParseAddr(t, "10.20.0.1")
	pingOnly := mustParseAddr(t, "10.20.0.2")
	silent := mustParseAddr(t, "10.20.0.3")

	stub := &stubNet{
		session: &stubEcho{reply: func(_ context.Context, dst netip.Addr) (bool, error) {
			return dst == live || dst == pingOnly, nil
		}},
		dialReply: func(_ context.Context, address string) error {
			switch address {
			case "10.20.0.1:443", "10.20.0.1:22":
				return nil
			}
			return errors.New("connection refused")
		},
	}
	sink := &collector{t: t}

	summary, err := newTestLiveness(stub).Sweep(
		context.Background(),
		[]netip.Addr{live, pingOnly, silent},
		Options{TCPPorts: []int{443, 22}, HostTimeout: 200 * time.Millisecond, MaxConcurrentHosts: 2},
		sink.emit,
	)
	if err != nil {
		t.Fatalf("Sweep: %v", err)
	}
	if summary.ICMPUnavailable {
		t.Fatal("summary reports ICMP unavailable on a sweep whose socket opened cleanly")
	}

	byAddress := map[netip.Addr]LiveHost{}
	for _, host := range sink.collected() {
		byAddress[host.Address] = host
	}
	if _, reported := byAddress[silent]; reported {
		t.Fatal("a host that answered neither check was emitted as a finding")
	}
	if got := len(byAddress); got != 2 {
		t.Fatalf("got %d hosts, want 2", got)
	}
	if got := byAddress[pingOnly].Evidence; len(got) != 1 || got[0] != MethodICMP {
		t.Fatalf("ping-only evidence = %v, want [%s]", got, MethodICMP)
	}
	if got := byAddress[pingOnly].OpenPorts; len(got) != 0 {
		t.Fatalf("ping-only open ports = %v, want none", got)
	}
	if got := byAddress[live].Evidence; len(got) != 2 || got[0] != MethodICMP || got[1] != MethodTCPConnect {
		t.Fatalf("evidence = %v, want [%s %s] in that order", got, MethodICMP, MethodTCPConnect)
	}
	// Ascending, not the granted order: the finding's open_ports list is read by people.
	if got := byAddress[live].OpenPorts; len(got) != 2 || got[0] != 22 || got[1] != 443 {
		t.Fatalf("open ports = %v, want [22 443]", got)
	}
	if summary.HostsFound != 2 || summary.AddressesScanned != 3 {
		t.Fatalf("summary = %+v, want 3 scanned and 2 found", summary)
	}
}

func TestSweepRunsOnlyTheGrantedMethods(t *testing.T) {
	stub := &stubNet{
		session:   &stubEcho{reply: func(context.Context, netip.Addr) (bool, error) { return true, nil }},
		dialReply: func(context.Context, string) error { return nil },
	}
	sink := &collector{t: t}

	if _, err := newTestLiveness(stub).Sweep(
		context.Background(),
		[]netip.Addr{mustParseAddr(t, "10.20.0.1")},
		Options{
			Methods:            []string{MethodTCPConnect},
			TCPPorts:           []int{80},
			HostTimeout:        200 * time.Millisecond,
			MaxConcurrentHosts: 2,
		},
		sink.emit,
	); err != nil {
		t.Fatalf("Sweep: %v", err)
	}
	if opens := stub.openCalls.Load(); opens != 0 {
		t.Fatalf("the ICMP socket was opened %d times for a request that did not select %q", opens, MethodICMP)
	}

	stub = &stubNet{
		session:   &stubEcho{reply: func(context.Context, netip.Addr) (bool, error) { return true, nil }},
		dialReply: func(context.Context, string) error { return nil },
	}
	if _, err := newTestLiveness(stub).Sweep(
		context.Background(),
		[]netip.Addr{mustParseAddr(t, "10.20.0.1")},
		Options{
			Methods:            []string{MethodICMP},
			TCPPorts:           []int{80},
			HostTimeout:        200 * time.Millisecond,
			MaxConcurrentHosts: 2,
		},
		sink.emit,
	); err != nil {
		t.Fatalf("Sweep: %v", err)
	}
	if dialed := stub.addresses(); len(dialed) != 0 {
		t.Fatalf("dialed %v for a request that did not select %q", dialed, MethodTCPConnect)
	}
}
