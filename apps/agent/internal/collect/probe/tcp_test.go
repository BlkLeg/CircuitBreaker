package probe

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"reflect"
	"sync"
	"syscall"
	"testing"
	"time"

	"circuitbreaker.dev/cb-agent/internal/frame"
	"circuitbreaker.dev/cb-agent/internal/netscope"
)

// ---------------------------------------------------------------------------
// Fixtures. The TCP checker's only contact with the network is its dialer and
// its resolver, and both are replaced here — nothing below opens a socket.
// ---------------------------------------------------------------------------

func tcpTestScope() netscope.Scope {
	networks := []string{"10.0.0.0/24", "fd00:abcd::/64"}
	return netscope.Scope{Networks: networks, DirectNetworks: networks, Version: "tcp-test"}
}

func tcpTestResolver(hosts map[string][]string) Resolver {
	return func(_ context.Context, host string) ([]string, error) {
		answers, ok := hosts[host]
		if !ok {
			return nil, fmt.Errorf("no test answer for %q", host)
		}
		return answers, nil
	}
}

// tcpClock is a hand-wound clock. Latency is measured by the checker as the gap between two
// reads of it, and only the dialer advances it, so every asserted latency below is exact.
type tcpClock struct {
	mu sync.Mutex
	at time.Time
}

func (c *tcpClock) now() time.Time {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.at
}

func (c *tcpClock) advance(d time.Duration) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.at = c.at.Add(d)
}

// tcpDialCost is what one connection attempt "takes". 12.3456 ms rounds to 12.35 at the
// backend's two places, so it also pins the rounding.
const tcpDialCost = 12345600 * time.Nanosecond

type fakeTCPDialer struct {
	mu    sync.Mutex
	calls []string
	open  map[string]bool
	err   error
	clock *tcpClock
}

func (d *fakeTCPDialer) dial(_ context.Context, network, address string) (net.Conn, error) {
	d.mu.Lock()
	d.calls = append(d.calls, network+"/"+address)
	open := d.open[address]
	failure := d.err
	d.mu.Unlock()

	d.clock.advance(tcpDialCost)
	if open {
		client, server := net.Pipe()
		_ = server.Close()
		return client, nil
	}
	if failure != nil {
		return nil, failure
	}
	return nil, &net.OpError{Op: "dial", Net: network, Err: syscall.ECONNREFUSED}
}

func (d *fakeTCPDialer) dialled() []string {
	d.mu.Lock()
	defer d.mu.Unlock()
	return append([]string(nil), d.calls...)
}

func newTestTCPChecker(dialer *fakeTCPDialer, hosts map[string][]string) *tcpChecker {
	checker, ok := newTCPChecker(Deps{Scope: tcpTestScope, Resolve: tcpTestResolver(hosts)}).(*tcpChecker)
	if !ok {
		panic("newTCPChecker no longer returns *tcpChecker")
	}
	checker.dial = dialer.dial
	checker.now = dialer.clock.now
	return checker
}

func newTestTCPDialer(open ...string) *fakeTCPDialer {
	reachable := make(map[string]bool, len(open))
	for _, address := range open {
		reachable[address] = true
	}
	return &fakeTCPDialer{open: reachable, clock: &tcpClock{at: time.Unix(1754500000, 0).UTC()}}
}

// ---------------------------------------------------------------------------
// Parity with collectors/net.py::collect_tcp.
// ---------------------------------------------------------------------------

func TestTCP_PortsAreTriedInOrderAndFirstSuccessWins(t *testing.T) {
	dialer := newTestTCPDialer("10.0.0.5:443", "10.0.0.5:80")
	checker := newTestTCPChecker(dialer, nil)

	outcome, err := checker.Check(context.Background(), "10.0.0.5", json.RawMessage(`{"ports":[22,443,80]}`))
	if err != nil {
		t.Fatalf("Check: %v", err)
	}
	want := []string{"tcp/10.0.0.5:22", "tcp/10.0.0.5:443"}
	if got := dialer.dialled(); !reflect.DeepEqual(got, want) {
		t.Fatalf("dialled %v, want %v — the list is tried in order and stops at the first success", got, want)
	}
	if !outcome.Up {
		t.Error("up = false, want true")
	}
	if outcome.Msg != "port 443 open in 12.35ms" {
		t.Errorf("msg = %q, want %q", outcome.Msg, "port 443 open in 12.35ms")
	}
}

func TestTCP_SuccessSamplesAreAvailAndLatencyOnly(t *testing.T) {
	dialer := newTestTCPDialer("10.0.0.5:80")
	checker := newTestTCPChecker(dialer, nil)

	outcome, err := checker.Check(context.Background(), "10.0.0.5", json.RawMessage(`{}`))
	if err != nil {
		t.Fatalf("Check: %v", err)
	}
	want := []frame.ProbeSample{{Metric: "avail", Value: 1}, {Metric: "latency_ms", Value: 12.35}}
	if !reflect.DeepEqual(outcome.Samples, want) {
		t.Fatalf("samples = %+v, want %+v", outcome.Samples, want)
	}
	if outcome.Details != nil {
		t.Errorf("details = %v, want nil (collect_tcp never sets details)", outcome.Details)
	}
}

func TestTCP_FailureEmitsAvailZeroWithNoLatencySampleAndNoErrorReason(t *testing.T) {
	dialer := newTestTCPDialer()
	checker := newTestTCPChecker(dialer, nil)

	outcome, err := checker.Check(context.Background(), "10.0.0.5", json.RawMessage(`{"ports":[80,443]}`))
	if err != nil {
		t.Fatalf("Check: %v", err)
	}
	want := []frame.ProbeSample{{Metric: "avail", Value: 0}}
	if !reflect.DeepEqual(outcome.Samples, want) {
		t.Fatalf("samples = %+v, want exactly %+v — collect_tcp emits no latency and no error_reason on failure", outcome.Samples, want)
	}
	if outcome.Up {
		t.Error("up = true, want false")
	}
}

func TestTCP_MessageStringsMatchBackendExactly(t *testing.T) {
	t.Run("open port", func(t *testing.T) {
		checker := newTestTCPChecker(newTestTCPDialer("10.0.0.5:8080"), nil)
		outcome, err := checker.Check(context.Background(), "10.0.0.5", json.RawMessage(`{"port":8080}`))
		if err != nil {
			t.Fatalf("Check: %v", err)
		}
		if outcome.Msg != "port 8080 open in 12.35ms" {
			t.Errorf("msg = %q, want %q", outcome.Msg, "port 8080 open in 12.35ms")
		}
	})

	t.Run("default port list", func(t *testing.T) {
		// params.get("ports") or [params.get("port", 80)] — a sparse config becomes [80], and
		// Python renders that list into the message with its own repr.
		checker := newTestTCPChecker(newTestTCPDialer(), nil)
		outcome, err := checker.Check(context.Background(), "10.0.0.5", json.RawMessage(`{}`))
		if err != nil {
			t.Fatalf("Check: %v", err)
		}
		if outcome.Msg != "no reachable port in [80]" {
			t.Errorf("msg = %q, want %q", outcome.Msg, "no reachable port in [80]")
		}
	})

	t.Run("several ports", func(t *testing.T) {
		checker := newTestTCPChecker(newTestTCPDialer(), nil)
		outcome, err := checker.Check(context.Background(), "10.0.0.5", json.RawMessage(`{"ports":[443,80,8080]}`))
		if err != nil {
			t.Fatalf("Check: %v", err)
		}
		if outcome.Msg != "no reachable port in [443, 80, 8080]" {
			t.Errorf("msg = %q, want %q", outcome.Msg, "no reachable port in [443, 80, 8080]")
		}
	})

	t.Run("empty port list falls back to the default", func(t *testing.T) {
		checker := newTestTCPChecker(newTestTCPDialer(), nil)
		outcome, err := checker.Check(context.Background(), "10.0.0.5", json.RawMessage(`{"ports":[]}`))
		if err != nil {
			t.Fatalf("Check: %v", err)
		}
		if outcome.Msg != "no reachable port in [80]" {
			t.Errorf("msg = %q, want %q", outcome.Msg, "no reachable port in [80]")
		}
	})
}

// TestTCP_ConnectionRefusedIsTargetDownNotExecutionError is the counterpart to the ICMP rule:
// a refused connection is a real observation of the target, so it must reach the state machine
// as DOWN and not be swallowed as an agent fault.
func TestTCP_ConnectionRefusedIsTargetDownNotExecutionError(t *testing.T) {
	dialer := newTestTCPDialer()
	dialer.err = &net.OpError{Op: "dial", Net: "tcp", Err: syscall.ECONNREFUSED}
	checker := newTestTCPChecker(dialer, nil)

	outcome, err := checker.Check(context.Background(), "10.0.0.5", json.RawMessage(`{"port":80}`))
	if err != nil {
		t.Fatalf("Check returned %v; connection refused is a target failure, not an execution error", err)
	}
	if outcome.Up {
		t.Error("up = true, want false")
	}
	if got := outcome.Samples[0]; got.Metric != "avail" || got.Value != 0 || got.ErrorReason != "" {
		t.Errorf("first sample = %+v, want avail=0 with no error_reason", got)
	}
}

func TestTCP_EveryCandidateAddressIsScopeCheckedBeforeDialing(t *testing.T) {
	t.Run("one bad answer refuses the whole name", func(t *testing.T) {
		dialer := newTestTCPDialer("10.0.0.5:80", "8.8.8.8:80")
		checker := newTestTCPChecker(dialer, map[string][]string{
			"rebound.internal": {"10.0.0.5", "8.8.8.8"},
		})

		_, err := checker.Check(context.Background(), "rebound.internal", json.RawMessage(`{"port":80}`))
		if !errors.Is(err, ErrOutOfScope) {
			t.Fatalf("error = %v, want ErrOutOfScope", err)
		}
		if got := dialer.dialled(); len(got) != 0 {
			t.Errorf("dialled %v, want nothing: scope is judged before the first connect", got)
		}
	})

	t.Run("every in-scope answer is tried", func(t *testing.T) {
		dialer := newTestTCPDialer("10.0.0.7:80")
		checker := newTestTCPChecker(dialer, map[string][]string{
			"dual.internal": {"10.0.0.6", "10.0.0.7"},
		})

		outcome, err := checker.Check(context.Background(), "dual.internal", json.RawMessage(`{"port":80}`))
		if err != nil {
			t.Fatalf("Check: %v", err)
		}
		want := []string{"tcp/10.0.0.6:80", "tcp/10.0.0.7:80"}
		if got := dialer.dialled(); !reflect.DeepEqual(got, want) {
			t.Fatalf("dialled %v, want %v", got, want)
		}
		if !outcome.Up {
			t.Error("up = false, want true once one answer connected")
		}
	})

	t.Run("special-use answers are refused whatever the grant says", func(t *testing.T) {
		dialer := newTestTCPDialer("127.0.0.1:80")
		checker := newTestTCPChecker(dialer, map[string][]string{
			"loop.internal": {"127.0.0.1"},
		})

		_, err := checker.Check(context.Background(), "loop.internal", json.RawMessage(`{"port":80}`))
		if !errors.Is(err, ErrOutOfScope) {
			t.Fatalf("error = %v, want ErrOutOfScope", err)
		}
		if got := dialer.dialled(); len(got) != 0 {
			t.Errorf("dialled %v, want nothing", got)
		}
	})
}

func TestTCP_DefaultTimeoutIsOneSecond(t *testing.T) {
	// collect_tcp's own default, not pydantic's: the stored config is sparse.
	dialer := newTestTCPDialer()
	var seen time.Duration
	checker := newTestTCPChecker(dialer, nil)
	inner := checker.dial
	checker.dial = func(ctx context.Context, network, address string) (net.Conn, error) {
		if deadline, ok := ctx.Deadline(); ok {
			seen = time.Until(deadline).Round(100 * time.Millisecond)
		}
		return inner(ctx, network, address)
	}

	if _, err := checker.Check(context.Background(), "10.0.0.5", json.RawMessage(`{}`)); err != nil {
		t.Fatalf("Check: %v", err)
	}
	if seen != time.Second {
		t.Errorf("dial deadline = %v, want the collector default of 1s", seen)
	}
}
