package discover

import (
	"context"
	"net"
	"net/netip"
	"strconv"
	"strings"
	"time"
	"unicode"
)

const (
	// MaxBannerBytes is how much of a greeting is ever read off the wire. It is counted in bytes
	// while frame.MaxDiscoveryBannerRune bounds the encoded field in runes, which is the safe way
	// round: 512 bytes can never decode to more than 512 runes, so a capture that respects this
	// limit cannot produce a field the server rejects.
	MaxBannerBytes = 512

	// DefaultBannerTimeout is the whole budget for one capture — connect and read together.
	// Plan §1 allows banners only under strict byte and time limits, and a granted port that
	// accepts and then waits for a request it will never get is the common case, not the
	// exception: 443 and 8443 behave exactly that way.
	DefaultBannerTimeout = 2 * time.Second
)

// Banner captures the greeting a service sends unprompted on connect (plan §1).
//
// It never writes to the connection. That is the whole design: the moment discovery sends a
// request it is speaking an application protocol, and plan §7 forbids following a redirect or
// making an application-level authenticated request in v1. Reading only what a service volunteers
// keeps this to one TCP handshake with no credential, no header and no URL anywhere in it — see
// the import guard in imports_test.go, which keeps an HTTP client out of this package entirely.
type Banner struct {
	dial    func(ctx context.Context, network, address string) (net.Conn, error)
	timeout time.Duration
}

func NewBanner() *Banner {
	dialer := &net.Dialer{}
	return &Banner{dial: dialer.DialContext, timeout: DefaultBannerTimeout}
}

// Capture returns the port's banner, or "" when there is not one worth reporting.
//
// Like ReverseDNS.Lookup this returns no error: a refused connection, a silent service and an
// unreadable greeting are all "this port volunteered nothing", and none of them says anything
// about the host that the open-port evidence has not already said.
func (b *Banner) Capture(ctx context.Context, addr netip.Addr, port int, opts Options) string {
	// A port the grant does not list is never touched, not even to be read from. The backend
	// clamps discovery.request against the grant, but the agent checks its own effective grant
	// immediately before each target connection (plan §7) — two independent checks so a backend
	// bug cannot widen what an agent actually connects to. A banner is also strictly less than
	// what the connect check already did, so a port outside the set has no path here at all.
	if !opts.wants(MethodTCPConnect) || !opts.allowsPort(port) {
		return ""
	}

	ctx, cancel := context.WithTimeout(ctx, b.budget())
	defer cancel()

	conn, err := b.dial(ctx, "tcp", net.JoinHostPort(addr.String(), strconv.Itoa(port)))
	if err != nil {
		return ""
	}
	defer conn.Close()

	return sanitizeBanner(b.read(ctx, conn))
}

// read pulls at most MaxBannerBytes off the connection within the remaining budget.
func (b *Banner) read(ctx context.Context, conn net.Conn) []byte {
	if deadline, ok := ctx.Deadline(); ok {
		_ = conn.SetReadDeadline(deadline)
	}

	// The read deadline bounds the wait but cannot observe cancellation, and the banner budget is
	// longer than a whole host timeout. Without this, cancelling a dispatch would still take up
	// to DefaultBannerTimeout per capture in flight, and plan §7 requires discovery to stop
	// quickly on cancellation or a grant change. Moving the deadline into the past unblocks the
	// read in place; closing the connection here would race the deferred Close above.
	stop := make(chan struct{})
	defer close(stop)
	go func() {
		select {
		case <-ctx.Done():
			_ = conn.SetReadDeadline(time.Now())
		case <-stop:
		}
	}()

	buf := make([]byte, MaxBannerBytes)
	read := 0
	// Reading until the buffer fills rather than taking whatever the first Read returns: a
	// greeting split across two segments would otherwise be recorded as half a line, making the
	// stored banner a function of TCP segmentation. The loop always ends — on EOF, on the
	// deadline, or on the byte limit.
	for read < len(buf) {
		n, err := conn.Read(buf[read:])
		read += n
		if err != nil {
			break
		}
	}
	return buf[:read]
}

func (b *Banner) budget() time.Duration {
	if b.timeout <= 0 {
		return DefaultBannerTimeout
	}
	return b.timeout
}

// sanitizeBanner turns raw wire bytes into a value that is safe to store, log and render.
//
// The bytes are whatever an unknown service on an untrusted network chose to send, and they end
// up in ScanResult.banner, which the review queue renders and the agent's own logs may quote.
// Two rules do all the work:
//
//   - Invalid UTF-8 is dropped outright. It is both a hostile encoding trick and the ordinary
//     result of cutting at MaxBannerBytes, which lands mid-rune often enough to matter.
//   - Anything not printable becomes a space, which neutralises a NUL, an ANSI escape, and a CR
//     that would forge a second line in a log. They collapse rather than vanish so a multi-line
//     SMTP greeting stays readable instead of being glued into one unreadable token.
//
// Neither rule can lengthen the value, so the result is still within MaxBannerBytes.
func sanitizeBanner(raw []byte) string {
	valid := strings.ToValidUTF8(string(raw), "")
	printable := strings.Map(func(r rune) rune {
		if unicode.IsPrint(r) {
			return r
		}
		return ' '
	}, valid)
	return strings.Join(strings.Fields(printable), " ")
}
