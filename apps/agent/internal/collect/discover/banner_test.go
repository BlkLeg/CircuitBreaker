package discover

import (
	"bytes"
	"context"
	"errors"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"net/netip"
	"strings"
	"sync"
	"testing"
	"time"
	"unicode"
	"unicode/utf8"

	"circuitbreaker.dev/cb-agent/internal/frame"
)

// The wire tests below use a real loopback listener rather than a stub net.Conn: what is under
// test is byte-level behavior on a socket — truncation, a read deadline, and above all the fact
// that nothing is ever written — and a fake Conn would let the implementation satisfy every
// assertion while still speaking HTTP to a real service.

// serveTCP starts a loopback listener that hands every accepted connection to handle, and returns
// the address and port to aim a capture at.
func serveTCP(t *testing.T, handle func(net.Conn)) (netip.Addr, int) {
	t.Helper()
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("listen: %v", err)
	}
	t.Cleanup(func() { _ = listener.Close() })

	go func() {
		for {
			conn, err := listener.Accept()
			if err != nil {
				return
			}
			go func() {
				defer conn.Close()
				handle(conn)
			}()
		}
	}()

	tcpAddr, ok := listener.Addr().(*net.TCPAddr)
	if !ok {
		t.Fatalf("listener address %T is not a *net.TCPAddr", listener.Addr())
	}
	addr, ok := netip.AddrFromSlice(tcpAddr.IP)
	if !ok {
		t.Fatalf("bad listener address %v", tcpAddr.IP)
	}
	return addr.Unmap(), tcpAddr.Port
}

// newTestBanner shortens the read budget. Every timing assertion here is about the *shape* of the
// bound, not its default value, and a 2s default would put a real second on the clock per case.
func newTestBanner(timeout time.Duration) *Banner {
	banner := NewBanner()
	banner.timeout = timeout
	return banner
}

// deadlineConn is a net.Conn that records every read deadline the capture installs, and announces
// when a read is actually in flight.
//
// It exists because banner.go bounds its read two independent ways — the context's deadline copied
// onto the socket, and a watchdog that pushes that deadline into the past when the context is
// cancelled — and the two are behaviorally indistinguishable in the ordinary case, where the
// deadline *is* what the budget expired into. Deleting either mechanism leaves every timing
// assertion in this file passing. The seam is the only place they can be told apart.
//
// net.Pipe under it rather than a loopback socket, because net.Pipe honours read deadlines exactly
// like a real conn while binding no port and starting no goroutine of its own.
type deadlineConn struct {
	net.Conn
	reading chan struct{}

	mu        sync.Mutex
	deadlines []time.Time
}

func newDeadlineConn(inner net.Conn) *deadlineConn {
	return &deadlineConn{Conn: inner, reading: make(chan struct{}, 1)}
}

func (c *deadlineConn) SetReadDeadline(t time.Time) error {
	c.mu.Lock()
	c.deadlines = append(c.deadlines, t)
	c.mu.Unlock()
	return c.Conn.SetReadDeadline(t)
}

func (c *deadlineConn) Read(p []byte) (int, error) {
	select {
	case c.reading <- struct{}{}:
	default:
	}
	return c.Conn.Read(p)
}

func (c *deadlineConn) readDeadlines() []time.Time {
	c.mu.Lock()
	defer c.mu.Unlock()
	return append([]time.Time(nil), c.deadlines...)
}

// silentPipe is a connection that accepts and then says nothing — the normal case for the granted
// HTTP and TLS ports, which wait for a request the collector is forbidden to send.
func silentPipe(t *testing.T) net.Conn {
	t.Helper()
	client, server := net.Pipe()
	t.Cleanup(func() {
		_ = server.Close()
		_ = client.Close()
	})
	return client
}

// dialing returns a dialer that hands the capture exactly this connection.
func dialing(conn net.Conn) func(context.Context, string, string) (net.Conn, error) {
	return func(context.Context, string, string) (net.Conn, error) { return conn, nil }
}

// refuseDial fails the test if the collector opens a socket at all.
func refuseDial(t *testing.T) func(context.Context, string, string) (net.Conn, error) {
	t.Helper()
	return func(_ context.Context, network, address string) (net.Conn, error) {
		t.Errorf("dialed %s %s; the grant does not allow this capture", network, address)
		return nil, errors.New("dial refused by the test")
	}
}

// TestBannerLimitsMatchThePlanAndTheWireContract pins the two numbers plan §1 names for banner
// capture, and pins them at the seam a regression would actually pass through.
//
// The constants are asserted against their literal values because those values are the contract:
// "512 bytes and 2 seconds" is what the task specifies and what the server's payload model was
// sized against. Deriving either from the other side of the wire would make a change to that side
// silently change this one.
//
// The constructor is asserted separately because the constant alone does not reach the wire.
// budget()'s <=0 fallback is the only other thing that reads DefaultBannerTimeout, so a NewBanner
// that installed some other positive timeout would leave every constant assertion here true and
// every real capture wrong.
func TestBannerLimitsMatchThePlanAndTheWireContract(t *testing.T) {
	if MaxBannerBytes != 512 {
		t.Errorf("MaxBannerBytes = %d, want plan §1's 512", MaxBannerBytes)
	}
	if DefaultBannerTimeout != 2*time.Second {
		t.Errorf("DefaultBannerTimeout = %s, want plan §1's 2s", DefaultBannerTimeout)
	}

	// The byte limit may never exceed the rune limit the frame contract enforces on the encoded
	// field. It is safe in this direction only: 512 bytes can never decode to more than 512 runes,
	// so a capture that respects MaxBannerBytes cannot produce a banner the server rejects — while
	// a capture allowed to read more could produce one that does, and the frame carrying it would
	// be dropped, losing a whole host finding over a greeting.
	if MaxBannerBytes > frame.MaxDiscoveryBannerRune {
		t.Errorf("MaxBannerBytes = %d exceeds frame.MaxDiscoveryBannerRune = %d; a legal capture could produce an illegal finding",
			MaxBannerBytes, frame.MaxDiscoveryBannerRune)
	}

	if got := NewBanner().budget(); got != DefaultBannerTimeout {
		t.Errorf("NewBanner().budget() = %s, want DefaultBannerTimeout %s", got, DefaultBannerTimeout)
	}
	if got := NewBanner().timeout; got != DefaultBannerTimeout {
		t.Errorf("NewBanner().timeout = %s, want DefaultBannerTimeout %s — the constant has to be installed, not merely declared",
			got, DefaultBannerTimeout)
	}
	// And a Banner built with no timeout at all still gets the documented bound rather than none:
	// the same direction every other zero in this package falls.
	if got := (&Banner{}).budget(); got != DefaultBannerTimeout {
		t.Errorf("a zero Banner's budget = %s, want the documented %s rather than no bound", got, DefaultBannerTimeout)
	}
}

func TestBannerCaptureStopsAtTheByteLimit(t *testing.T) {
	addr, port := serveTCP(t, func(conn net.Conn) {
		_, _ = conn.Write(bytes.Repeat([]byte("A"), 8*MaxBannerBytes))
	})

	banner := newTestBanner(2*time.Second).Capture(
		context.Background(), addr, port, Options{TCPPorts: []int{port}})

	if len(banner) != MaxBannerBytes {
		t.Fatalf("captured %d bytes, want exactly %d", len(banner), MaxBannerBytes)
	}
	if strings.Trim(banner, "A") != "" {
		t.Errorf("captured unexpected content: %q", banner)
	}
}

func TestBannerCaptureReadsAGreetingSplitAcrossSegments(t *testing.T) {
	// A greeting that arrives in two flights must be captured whole. Taking whatever the first
	// Read happens to return would make the stored banner a function of TCP segmentation, so the
	// same service would be recorded differently on two runs.
	addr, port := serveTCP(t, func(conn net.Conn) {
		_, _ = conn.Write([]byte("220-mail.example.com ESMTP\r\n"))
		time.Sleep(50 * time.Millisecond)
		_, _ = conn.Write([]byte("220 ready\r\n"))
	})

	banner := newTestBanner(2*time.Second).Capture(
		context.Background(), addr, port, Options{TCPPorts: []int{port}})

	if banner != "220-mail.example.com ESMTP 220 ready" {
		t.Fatalf("captured %q, want the whole greeting", banner)
	}
}

func TestBannerCaptureStopsAtTheReadDeadline(t *testing.T) {
	held := make(chan struct{})
	defer close(held)
	// A service that accepts and then says nothing is the normal case for the granted HTTP and
	// TLS ports: they wait for a request the collector is forbidden to send.
	addr, port := serveTCP(t, func(net.Conn) { <-held })

	start := time.Now()
	banner := newTestBanner(150*time.Millisecond).Capture(
		context.Background(), addr, port, Options{TCPPorts: []int{port}})
	elapsed := time.Since(start)

	if banner != "" {
		t.Errorf("captured %q from a silent service, want no banner", banner)
	}
	if elapsed < 150*time.Millisecond {
		t.Errorf("returned after %s, before the read budget elapsed", elapsed)
	}
	if elapsed > 2*time.Second {
		t.Errorf("returned after %s; the read budget did not bound the capture", elapsed)
	}
}

func TestBannerCaptureStopsOnContextCancellation(t *testing.T) {
	held := make(chan struct{})
	defer close(held)
	addr, port := serveTCP(t, func(net.Conn) { <-held })

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// The capture runs off the test goroutine so a read that observes only its own deadline fails
	// here in seconds rather than sitting on the 30s budget below — the pattern
	// TestReverseDNSIsBounded already uses. Asserting the elapsed time inline would still report
	// the failure, but only after half a minute, which is how a lost bound gets mistaken for a
	// slow machine.
	done := make(chan string, 1)
	go func() {
		// A budget far longer than any job would allow: cancellation, not the deadline, has to be
		// what ends this read. Plan §7 requires discovery to stop quickly on cancellation or a
		// grant change, and the whole banner budget is longer than one host timeout.
		done <- newTestBanner(30*time.Second).Capture(ctx, addr, port, Options{TCPPorts: []int{port}})
	}()

	// Long enough for the connect and the first blocking read; the cancel below is what has to end
	// them.
	time.Sleep(30 * time.Millisecond)
	cancel()

	select {
	case banner := <-done:
		if banner != "" {
			t.Errorf("captured %q, want no banner", banner)
		}
	case <-time.After(3 * time.Second):
		t.Fatal("Capture did not return within three seconds of cancellation; the read is bounded only by its own 30s deadline")
	}
}

// TestBannerCaptureInstallsTheReadDeadlineFromItsBudget pins the first of the two bounds on the
// read: the context's deadline is copied onto the socket.
//
// It has to be asserted at the seam. Every timing test in this file would pass just as well with
// this mechanism deleted, because the cancellation watchdog fires at the same instant the budget
// expires and pushes the deadline into the past itself — so the two are indistinguishable from the
// outside, and the only test of the copy is that the copy happened.
func TestBannerCaptureInstallsTheReadDeadlineFromItsBudget(t *testing.T) {
	// A budget nothing here comes close to reaching, so the only way a deadline lands on the socket
	// is the copy under test. A budget the capture ran out of would be indistinguishable from the
	// watchdog's own SetReadDeadline(time.Now()).
	const budget = 5 * time.Second
	const seamSlack = 250 * time.Millisecond

	recorder := newDeadlineConn(greetingConn("SSH-2.0-OpenSSH_9.6"))
	banner := newTestBanner(budget)
	banner.dial = dialing(recorder)

	start := time.Now()
	got := banner.Capture(context.Background(), mustParseAddr(t, "10.20.0.5"), 22,
		Options{TCPPorts: []int{22}})

	// Without this the assertions below could hold on a capture that never read at all.
	if got != "SSH-2.0-OpenSSH_9.6" {
		t.Fatalf("captured %q, want the greeting the connection volunteered", got)
	}

	deadlines := recorder.readDeadlines()
	if len(deadlines) == 0 {
		t.Fatal("the capture installed no read deadline, so a silent service would be bounded only by whatever the socket defaults to")
	}
	// The first one is the copy. A later one may or may not be recorded: Capture cancels its own
	// context on the way out, which can race the watchdog into one final SetReadDeadline.
	if over := deadlines[0].Sub(start.Add(budget)); over > seamSlack || over < -seamSlack {
		t.Errorf("the read deadline is %s from start+%s, want the context's own deadline", over, budget)
	}
}

// TestBannerCaptureCancellationPushesTheReadDeadlineIntoThePast pins the second bound, the one the
// deadline copy cannot provide: a read deadline bounds the wait but cannot observe cancellation,
// and the banner budget is longer than a whole host timeout. Without the watchdog, cancelling a
// dispatch would still cost DefaultBannerTimeout per capture in flight.
func TestBannerCaptureCancellationPushesTheReadDeadlineIntoThePast(t *testing.T) {
	const budget = 30 * time.Second

	recorder := newDeadlineConn(silentPipe(t))
	banner := newTestBanner(budget)
	banner.dial = dialing(recorder)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	done := make(chan string, 1)
	go func() {
		done <- banner.Capture(ctx, mustParseAddr(t, "10.20.0.5"), 22, Options{TCPPorts: []int{22}})
	}()

	// Cancelling only once a read is genuinely in flight, so the test cannot pass by racing ahead of
	// the read it is meant to interrupt.
	select {
	case <-recorder.reading:
	case <-time.After(3 * time.Second):
		t.Fatal("the capture never read from the connection")
	}
	cancelledAt := time.Now()
	cancel()

	select {
	case banner := <-done:
		if banner != "" {
			t.Errorf("captured %q from a silent service, want no banner", banner)
		}
	case <-time.After(3 * time.Second):
		t.Fatalf("Capture did not return within three seconds of cancellation; the read is bounded only by its %s deadline", budget)
	}

	// And the mechanism, not just the outcome: on cancellation the socket's deadline is *moved* from
	// the far end of the budget to roughly now, which is what unblocks a read already parked on it.
	// Closing the connection would do it too, but would race Capture's own deferred Close.
	//
	// "Roughly now" rather than "strictly in the past" because the watchdog installs time.Now(),
	// which is a few microseconds after the cancellation it reacted to. The bound that matters is
	// the distance from the budget it replaced: watchdogSlack is two orders of magnitude smaller.
	const watchdogSlack = 500 * time.Millisecond
	deadlines := recorder.readDeadlines()
	if len(deadlines) == 0 {
		t.Fatal("the capture installed no read deadline at all")
	}
	last := deadlines[len(deadlines)-1]
	if moved := last.Sub(cancelledAt); moved > watchdogSlack {
		t.Errorf("the last read deadline is still %s out after the cancellation, want it moved to roughly now: the parked read was never unblocked",
			moved)
	}
}

func TestBannerCaptureStripsControlAndInvalidUTF8(t *testing.T) {
	cases := []struct {
		name string
		wire []byte
		want string
	}{
		{
			name: "ssh greeting loses its line ending",
			wire: []byte("SSH-2.0-OpenSSH_9.6p1 Ubuntu-3\r\n"),
			want: "SSH-2.0-OpenSSH_9.6p1 Ubuntu-3",
		},
		{
			name: "multi line smtp greeting stays readable",
			wire: []byte("220-mail.example.com ESMTP\r\n220 ready\r\n"),
			want: "220-mail.example.com ESMTP 220 ready",
		},
		{
			name: "terminal escapes are neutralised",
			wire: []byte("\x1b[31mALERT\x1b[0m"),
			want: "[31mALERT [0m",
		},
		{
			name: "invalid utf8 bytes are dropped without joining their neighbours",
			wire: []byte("Server\xff\xfe ready"),
			want: "Server ready",
		},
		{
			name: "a banner of nothing but control bytes captures nothing",
			wire: []byte("\x00\x01\x02\x07\x7f"),
			want: "",
		},
		{
			name: "printable non-ascii text survives",
			wire: []byte("Grüße ✓"),
			want: "Grüße ✓",
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			addr, port := serveTCP(t, func(conn net.Conn) { _, _ = conn.Write(tc.wire) })

			banner := newTestBanner(2*time.Second).Capture(
				context.Background(), addr, port, Options{TCPPorts: []int{port}})

			if banner != tc.want {
				t.Fatalf("captured %q, want %q", banner, tc.want)
			}
			if !utf8.ValidString(banner) {
				t.Errorf("captured invalid UTF-8: %q", banner)
			}
			for _, r := range banner {
				if unicode.IsControl(r) {
					t.Errorf("captured control rune %U in %q", r, banner)
				}
			}
		})
	}
}

func TestBannerCaptureTruncationLeavesValidUTF8(t *testing.T) {
	// The byte limit lands in the middle of the final rune. Storing the leading byte on its own
	// would put an invalid UTF-8 sequence into ScanResult.banner, which is rendered in the review
	// queue and re-encoded as JSON on the way there.
	wire := append(bytes.Repeat([]byte("a"), MaxBannerBytes-1), []byte("€")...)
	addr, port := serveTCP(t, func(conn net.Conn) { _, _ = conn.Write(wire) })

	banner := newTestBanner(2*time.Second).Capture(
		context.Background(), addr, port, Options{TCPPorts: []int{port}})

	if !utf8.ValidString(banner) {
		t.Fatalf("captured invalid UTF-8: %q", banner)
	}
	if banner != strings.Repeat("a", MaxBannerBytes-1) {
		t.Fatalf("captured %d bytes ending %q, want the split rune dropped", len(banner), banner[len(banner)-1:])
	}
}

func TestBannerCaptureSkipsAPortTheGrantDoesNotList(t *testing.T) {
	banner := NewBanner()
	banner.dial = refuseDial(t)

	got := banner.Capture(context.Background(), mustParseAddr(t, "192.168.10.24"), 8080,
		Options{TCPPorts: []int{22, 443}})

	if got != "" {
		t.Fatalf("captured %q from an ungranted port", got)
	}
}

func TestBannerCaptureSkipsWhenTCPConnectIsNotSelected(t *testing.T) {
	banner := NewBanner()
	banner.dial = refuseDial(t)

	got := banner.Capture(context.Background(), mustParseAddr(t, "192.168.10.24"), 22,
		Options{Methods: []string{MethodICMP}, TCPPorts: []int{22}})

	if got != "" {
		t.Fatalf("captured %q for a request that did not select %s", got, MethodTCPConnect)
	}
}

func TestBannerCaptureNeverWritesToTheConnection(t *testing.T) {
	var mu sync.Mutex
	var sent []byte
	done := make(chan struct{})

	addr, port := serveTCP(t, func(conn net.Conn) {
		defer close(done)
		_ = conn.SetReadDeadline(time.Now().Add(2 * time.Second))
		// Read until the collector closes: whatever arrives before EOF is everything it said.
		read, _ := io.ReadAll(conn)
		mu.Lock()
		sent = read
		mu.Unlock()
	})

	newTestBanner(150*time.Millisecond).Capture(
		context.Background(), addr, port, Options{TCPPorts: []int{port}})

	select {
	case <-done:
	case <-time.After(3 * time.Second):
		t.Fatal("the listener never saw the connection close")
	}

	mu.Lock()
	defer mu.Unlock()
	if len(sent) != 0 {
		t.Fatalf("the capture wrote %d bytes to the target: %q", len(sent), sent)
	}
}

func TestBannerCaptureDoesNotSpeakHTTPOrFollowARedirect(t *testing.T) {
	var mu sync.Mutex
	var requests []*http.Request

	// Plan §7: no HTTP redirect is followed and no application-level authenticated request is
	// made. A handler that is never entered proves both at once — there is no first request to
	// redirect and no header to carry a credential.
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		requests = append(requests, r.Clone(context.Background()))
		mu.Unlock()
		http.SetCookie(w, &http.Cookie{Name: "session", Value: "s3cret"})
		w.Header().Set("Location", "/moved")
		w.WriteHeader(http.StatusFound)
	}))
	defer server.Close()

	addr, port := splitHostPort(t, strings.TrimPrefix(server.URL, "http://"))

	banner := newTestBanner(150*time.Millisecond).Capture(
		context.Background(), addr, port, Options{TCPPorts: []int{port}})

	mu.Lock()
	defer mu.Unlock()
	for i, request := range requests {
		t.Errorf("request %d: %s %s auth=%q cookie=%q", i, request.Method, request.URL,
			request.Header.Get("Authorization"), request.Header.Get("Cookie"))
	}
	if len(requests) != 0 {
		t.Fatalf("the capture issued %d HTTP requests, want 0", len(requests))
	}
	if banner != "" {
		t.Fatalf("captured %q from a server that answers only when asked", banner)
	}
}

func splitHostPort(t *testing.T, hostPort string) (netip.Addr, int) {
	t.Helper()
	addrPort, err := netip.ParseAddrPort(hostPort)
	if err != nil {
		t.Fatalf("bad test server address %q: %v", hostPort, err)
	}
	return addrPort.Addr().Unmap(), int(addrPort.Port())
}
