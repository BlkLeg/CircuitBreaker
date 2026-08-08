package probe

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"net/netip"
	"os"
	"time"

	"golang.org/x/net/icmp"
	"golang.org/x/net/ipv4"
	"golang.org/x/net/ipv6"

	"circuitbreaker.dev/cb-agent/internal/frame"
	"circuitbreaker.dev/cb-agent/internal/netscope"
)

// The collector-side defaults from collectors/net.py::collect_icmp — its own
// `params.get(key, default)` values, not the pydantic schema's. schemas/monitor.py persists
// `model_dump(exclude_unset=True)`, so a stored config is usually sparse and these are what a
// server-executed check actually used.
const (
	defaultICMPPacketCount = 5
	defaultICMPTimeout     = 1500 * time.Millisecond
)

// icmpPayload is the body of every echo request. Fixed and meaningless: nothing in the result
// depends on it, and it must never carry anything from the assignment.
var icmpPayload = []byte("cb-agent-probe")

// ErrICMPUnavailable reports that this host cannot send unprivileged datagram ICMP at all —
// typically because net.ipv4.ping_group_range does not cover the agent's GID.
//
// It is the agent-side counterpart of the backend collector's `icmp_unavailable` branch, and the
// one place this package deliberately *diverges* from it: the backend reports up=False there,
// which on an agent would mark every monitor on a misconfigured host DOWN. Here it is an
// execution error, so the monitor keeps its last known state. Task 20's readiness evaluator
// reports `probe.icmp = unavailable` off the same condition. The agent still ships with no
// CAP_NET_RAW and this must not become a reason to add it.
var ErrICMPUnavailable = errors.New("probe: unprivileged datagram ICMP is unavailable on this host")

// icmpSession is one open unprivileged-ICMP socket. Injected so no test reaches the kernel.
type icmpSession interface {
	// Ping sends one echo request and waits up to timeout for its reply. ok=false means the
	// deadline passed with no answer, which is packet loss and not a failure; a non-nil error
	// means the probe could not be performed at all.
	Ping(ctx context.Context, dst netip.Addr, seq int, timeout time.Duration) (rtt time.Duration, ok bool, err error)
	Close() error
}

// icmpOpener opens an echo session on "udp4" or "udp6".
type icmpOpener func(network string) (icmpSession, error)

// icmpChecker mirrors collectors/net.py::collect_icmp.
type icmpChecker struct {
	scope   func() netscope.Scope
	resolve Resolver
	open    icmpOpener
}

func newICMPChecker(deps Deps) Checker {
	return &icmpChecker{scope: deps.Scope, resolve: deps.Resolve, open: listenUnprivilegedICMP}
}

// icmpConfig is the slice of the monitor's config this check reads.
type icmpConfig struct {
	PacketCount *int     `json:"packet_count"`
	Timeout     *float64 `json:"timeout"`
}

func (c icmpConfig) count() int {
	if c.PacketCount == nil {
		return defaultICMPPacketCount
	}
	return *c.PacketCount
}

func (c icmpConfig) timeout() time.Duration {
	if c.Timeout == nil {
		return defaultICMPTimeout
	}
	return time.Duration(*c.Timeout * float64(time.Second))
}

func (c *icmpChecker) Check(ctx context.Context, host string, cfg json.RawMessage) (Outcome, error) {
	var config icmpConfig
	if err := decodeCheckConfig(cfg, &config); err != nil {
		return Outcome{}, err
	}

	// Scope before socket: an out-of-scope target must not even cause a listen.
	addrs, err := resolveInScope(ctx, c.scope, c.resolve, host)
	if err != nil {
		return Outcome{}, err
	}
	dst := addrs[0]

	network := "udp4"
	if dst.Is6() {
		network = "udp6"
	}
	session, err := c.open(network)
	if err != nil {
		return Outcome{}, fmt.Errorf("%w: %v", ErrICMPUnavailable, err)
	}
	defer session.Close()

	count := config.count()
	timeout := config.timeout()
	latencies := make([]float64, 0, count)
	lost := 0
	for seq := 0; seq < count; seq++ {
		if err := ctx.Err(); err != nil {
			return Outcome{}, err
		}
		rtt, replied, pingErr := session.Ping(ctx, dst, seq, timeout)
		if pingErr != nil {
			// The echo could not be sent or the socket failed. That says nothing about the
			// target, so it is an execution error rather than loss.
			return Outcome{}, fmt.Errorf("probe: the ICMP echo to %s could not be sent: %w", dst, pingErr)
		}
		if !replied {
			lost++
			continue
		}
		// The backend rounds each individual RTT to three places before it ever reaches the
		// aggregates, so min and max are rounded values even though they are reported raw.
		latencies = append(latencies, roundTo(millis(rtt), 3))
	}

	lossPct := 100.0
	if count != 0 {
		lossPct = roundTo(float64(lost)/float64(count)*100, 2)
	}
	up := len(latencies) > 0
	samples := []frame.ProbeSample{
		{Metric: "avail", Value: boolValue(up)},
		{Metric: "packet_loss_pct", Value: lossPct},
	}
	if !up {
		return Outcome{
			Up:      false,
			Samples: samples,
			Msg:     fmt.Sprintf("100%% packet loss (%d probes)", count),
		}, nil
	}

	mean := roundTo(sum(latencies)/float64(len(latencies)), 3)
	low, high := minMax(latencies)
	samples = append(samples,
		frame.ProbeSample{Metric: "latency_ms", Value: mean},
		frame.ProbeSample{Metric: "latency_min_ms", Value: low},
		frame.ProbeSample{Metric: "latency_max_ms", Value: high},
		frame.ProbeSample{Metric: "jitter_ms", Value: icmpJitter(latencies)},
	)
	return Outcome{
		Up:      true,
		Samples: samples,
		Msg:     fmt.Sprintf("%sms avg, %s%% loss", formatPythonFloat(mean), formatPythonFloat(lossPct)),
	}, nil
}

// icmpJitter mirrors collectors/net.py::_jitter: the mean absolute difference between successive
// latencies, three places, and exactly 0.0 for fewer than two samples.
func icmpJitter(latencies []float64) float64 {
	if len(latencies) < 2 {
		return 0
	}
	total := 0.0
	for i := 1; i < len(latencies); i++ {
		total += abs(latencies[i] - latencies[i-1])
	}
	return roundTo(total/float64(len(latencies)-1), 3)
}

func sum(values []float64) float64 {
	total := 0.0
	for _, value := range values {
		total += value
	}
	return total
}

func minMax(values []float64) (float64, float64) {
	low, high := values[0], values[0]
	for _, value := range values[1:] {
		if value < low {
			low = value
		}
		if value > high {
			high = value
		}
	}
	return low, high
}

func abs(value float64) float64 {
	if value < 0 {
		return -value
	}
	return value
}

func boolValue(value bool) float64 {
	if value {
		return 1
	}
	return 0
}

// ---------------------------------------------------------------------------
// The real socket. Unprivileged datagram ICMP only — the agent ships without
// CAP_NET_RAW and nothing here may assume otherwise.
// ---------------------------------------------------------------------------

type datagramICMPSession struct {
	conn *icmp.PacketConn
	// v6 selects the ICMPv6 message type and the protocol number ParseMessage is given. Reading
	// an ICMPv6 reply as ICMPv4 silently never matches, so this is not cosmetic.
	v6 bool
	id int
}

func listenUnprivilegedICMP(network string) (icmpSession, error) {
	address := "0.0.0.0"
	if network == "udp6" {
		address = "::"
	}
	conn, err := icmp.ListenPacket(network, address)
	if err != nil {
		return nil, err
	}
	// The kernel rewrites the echo id on a datagram socket, so this is only a hint for anyone
	// reading a packet capture; replies are matched on sequence number and peer address.
	return &datagramICMPSession{conn: conn, v6: network == "udp6", id: os.Getpid() & 0xffff}, nil
}

func (s *datagramICMPSession) Close() error { return s.conn.Close() }

func (s *datagramICMPSession) Ping(ctx context.Context, dst netip.Addr, seq int, timeout time.Duration) (time.Duration, bool, error) {
	request := icmp.Message{
		Type: icmp.Type(ipv4.ICMPTypeEcho),
		Code: 0,
		Body: &icmp.Echo{ID: s.id, Seq: seq, Data: icmpPayload},
	}
	protocol := protocolICMP
	if s.v6 {
		request.Type = ipv6.ICMPTypeEchoRequest
		protocol = protocolICMPv6
	}
	encoded, err := request.Marshal(nil)
	if err != nil {
		return 0, false, err
	}

	deadline := time.Now().Add(timeout)
	if ctxDeadline, ok := ctx.Deadline(); ok && ctxDeadline.Before(deadline) {
		deadline = ctxDeadline
	}
	if err := s.conn.SetDeadline(deadline); err != nil {
		return 0, false, err
	}
	// A cancelled run must stop within the cancellation, not within the packet timeout, so
	// cancellation collapses the read deadline instead of waiting it out.
	watchDone := make(chan struct{})
	defer close(watchDone)
	go func() {
		select {
		case <-ctx.Done():
			_ = s.conn.SetReadDeadline(time.Now())
		case <-watchDone:
		}
	}()

	started := time.Now()
	if _, err := s.conn.WriteTo(encoded, &net.UDPAddr{IP: dst.AsSlice()}); err != nil {
		return 0, false, err
	}

	buf := make([]byte, 1500)
	for {
		n, peer, err := s.conn.ReadFrom(buf)
		if err != nil {
			var netErr net.Error
			if errors.As(err, &netErr) && netErr.Timeout() {
				if ctxErr := ctx.Err(); ctxErr != nil {
					return 0, false, ctxErr
				}
				return 0, false, nil // silence past the deadline is loss, not a failure
			}
			return 0, false, err
		}
		if !peerMatches(peer, dst) {
			continue
		}
		reply, err := icmp.ParseMessage(protocol, buf[:n])
		if err != nil {
			continue
		}
		if reply.Type != ipv4.ICMPTypeEchoReply && reply.Type != ipv6.ICMPTypeEchoReply {
			continue
		}
		echo, ok := reply.Body.(*icmp.Echo)
		if !ok || echo.Seq != seq {
			continue
		}
		return time.Since(started), true, nil
	}
}

// The IANA protocol numbers icmp.ParseMessage needs. golang.org/x/net/internal/iana is internal,
// so they are restated here rather than vendored around.
const (
	protocolICMP   = 1
	protocolICMPv6 = 58
)

func peerMatches(peer net.Addr, dst netip.Addr) bool {
	udp, ok := peer.(*net.UDPAddr)
	if !ok {
		return false
	}
	addr, ok := netip.AddrFromSlice(udp.IP)
	if !ok {
		return false
	}
	return addr.Unmap() == dst.Unmap()
}
