package probe

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"net/netip"
	"strconv"
	"strings"
	"time"

	"circuitbreaker.dev/cb-agent/internal/frame"
	"circuitbreaker.dev/cb-agent/internal/netscope"
)

// The collector-side defaults from collectors/net.py::collect_tcp. They are the collector's
// `params.get(key, default)` values, not the pydantic schema's: schemas/monitor.py persists
// `model_dump(exclude_unset=True)`, so a stored config is usually sparse and the collector's
// defaults are what a server-executed check actually used.
const (
	defaultTCPPort    = 80
	defaultTCPTimeout = 1 * time.Second
)

// ErrOutOfScope is what a checker returns when a destination it was about to connect to is not
// inside the agent's approved scope.
//
// It is an *execution* error rather than a target result: the check never happened, so the
// monitor keeps its last known state instead of being told the target is down. The runtime's own
// pre-dial refusal is the one that emits `rejected` plus a capability violation; this one covers
// the window after it, where a name can resolve to something else.
var ErrOutOfScope = errors.New("probe: the destination is outside the agent's approved scope")

// dialFunc is the checker's single point of contact with the network stack, injected so no test
// opens a socket. It matches net.Dialer.DialContext.
type dialFunc func(ctx context.Context, network, address string) (net.Conn, error)

// tcpChecker mirrors collectors/net.py::collect_tcp.
type tcpChecker struct {
	scope   func() netscope.Scope
	resolve Resolver
	dial    dialFunc
	now     func() time.Time
}

func newTCPChecker(deps Deps) Checker {
	dialer := &net.Dialer{}
	return &tcpChecker{
		scope:   deps.Scope,
		resolve: deps.Resolve,
		dial:    dialer.DialContext,
		now:     time.Now,
	}
}

// tcpConfig is the slice of the monitor's config this check reads. Everything else the server
// sent — credentials included — is ignored and never copied anywhere.
type tcpConfig struct {
	Ports   []int    `json:"ports"`
	Port    *int     `json:"port"`
	Timeout *float64 `json:"timeout"`
}

// ports mirrors `params.get("ports") or [params.get("port", 80)]`: an absent *or empty* list
// falls back to the single port, because an empty list is falsy in Python.
func (c tcpConfig) ports() []int {
	if len(c.Ports) > 0 {
		return c.Ports
	}
	if c.Port != nil {
		return []int{*c.Port}
	}
	return []int{defaultTCPPort}
}

func (c tcpConfig) timeout() time.Duration {
	if c.Timeout == nil {
		return defaultTCPTimeout
	}
	return time.Duration(*c.Timeout * float64(time.Second))
}

func (c *tcpChecker) Check(ctx context.Context, host string, cfg json.RawMessage) (Outcome, error) {
	var config tcpConfig
	if err := decodeCheckConfig(cfg, &config); err != nil {
		return Outcome{}, err
	}

	// Scope first, then dial: nothing below may run against an address this agent was never
	// authorized to reach.
	addrs, err := resolveInScope(ctx, c.scope, c.resolve, host)
	if err != nil {
		return Outcome{}, err
	}

	ports := config.ports()
	timeout := config.timeout()
	for _, port := range ports {
		// The backend times the whole socket.create_connection call, which itself walks every
		// address getaddrinfo returned, so the clock starts once per port and not once per
		// candidate address.
		started := c.now()
		for _, addr := range addrs {
			if err := ctx.Err(); err != nil {
				return Outcome{}, err
			}
			conn, dialErr := c.dialOnce(ctx, addr, port, timeout)
			if dialErr != nil {
				continue
			}
			latency := roundTo(millis(c.now().Sub(started)), 2)
			_ = conn.Close()
			return Outcome{
				Up: true,
				Samples: []frame.ProbeSample{
					{Metric: "avail", Value: 1},
					{Metric: "latency_ms", Value: latency},
				},
				Msg: fmt.Sprintf("port %d open in %sms", port, formatPythonFloat(latency)),
			}, nil
		}
	}

	// A refused or timed-out connection is a real observation of the target, so this is a
	// completed check reporting DOWN — never an execution error. collect_tcp emits the bare
	// avail sample here: no latency, and no per-sample error_reason.
	return Outcome{
		Up:      false,
		Samples: []frame.ProbeSample{{Metric: "avail", Value: 0}},
		Msg:     fmt.Sprintf("no reachable port in %s", formatPythonIntList(ports)),
	}, nil
}

func (c *tcpChecker) dialOnce(ctx context.Context, addr netip.Addr, port int, timeout time.Duration) (net.Conn, error) {
	dialCtx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	return c.dial(dialCtx, "tcp", net.JoinHostPort(addr.String(), strconv.Itoa(port)))
}

// ---------------------------------------------------------------------------
// Helpers shared by every checker in this package.
// ---------------------------------------------------------------------------

// resolveInScope turns a target host into the ordered list of addresses a checker may connect
// to, refusing the whole target unless every answer is in scope.
//
// The runtime already judged the assignment's host before any checker ran. Doing it again here
// is deliberate: between the two checks a name can resolve to something else, and the answer
// that matters is the one we are about to connect to. "Every answer" is the rebinding rule — a
// name is only as safe as its worst address.
func resolveInScope(ctx context.Context, scope func() netscope.Scope, resolve Resolver, host string) ([]netip.Addr, error) {
	answers := []string{host}
	if _, err := netip.ParseAddr(host); err != nil {
		if resolve == nil {
			return nil, fmt.Errorf("probe: no resolver is configured for %s", host)
		}
		found, resolveErr := resolve(ctx, host)
		if resolveErr != nil {
			return nil, fmt.Errorf("probe: could not resolve %s: %w", host, resolveErr)
		}
		answers = found
	}

	effective := netscope.Scope{}
	if scope != nil {
		effective = scope()
	}
	if decision := netscope.Evaluate(effective, host, answers); !decision.Allowed {
		refused := host
		if decision.Address != "" {
			refused = decision.Address
		}
		return nil, fmt.Errorf("%w: %s (%s)", ErrOutOfScope, refused, decision.Reason)
	}

	addrs := make([]netip.Addr, 0, len(answers))
	for _, answer := range answers {
		addr, err := netip.ParseAddr(strings.TrimSpace(answer))
		if err != nil {
			return nil, fmt.Errorf("probe: %s resolved to an unusable address %q", host, answer)
		}
		// Collapse IPv4-mapped IPv6 exactly as netscope.parseAddress does, so the address that
		// was judged is byte-for-byte the address that gets dialled.
		addrs = append(addrs, addr.Unmap())
	}
	if len(addrs) == 0 {
		return nil, fmt.Errorf("probe: %s resolved to no addresses", host)
	}
	return addrs, nil
}

// decodeCheckConfig reads the keys a checker cares about out of the server's validated monitor
// config. An absent config is an empty one: the stored params are sparse by construction.
func decodeCheckConfig(cfg json.RawMessage, into any) error {
	if len(cfg) == 0 {
		return nil
	}
	if err := json.Unmarshal(cfg, into); err != nil {
		return fmt.Errorf("probe: the assignment's config could not be read: %w", err)
	}
	return nil
}

// millis converts a duration to milliseconds the way the backend's collectors measure them.
func millis(d time.Duration) float64 {
	return float64(d) / float64(time.Millisecond)
}

// roundTo is Python's round(value, places) for finite floats: strconv rounds the exact binary
// value to the requested number of decimal digits, resolving ties to even, which is what
// CPython's float.__round__ does. Formatting and re-parsing is not a detour — it is the only way
// to get that rule without reimplementing it.
func roundTo(value float64, places int) float64 {
	rounded, err := strconv.ParseFloat(strconv.FormatFloat(value, 'f', places, 64), 64)
	if err != nil {
		return value
	}
	return rounded
}

// formatPythonFloat renders a float the way an f-string does. Python's repr always keeps a
// decimal point, so a mean of 20 prints as "20.0" — and the collector's message strings, which
// operators read and tests match, carry that trailing zero.
func formatPythonFloat(value float64) string {
	text := strconv.FormatFloat(value, 'f', -1, 64)
	if !strings.Contains(text, ".") {
		text += ".0"
	}
	return text
}

// formatPythonIntList renders a list of ints the way Python renders one inside an f-string.
func formatPythonIntList(values []int) string {
	parts := make([]string, 0, len(values))
	for _, value := range values {
		parts = append(parts, strconv.Itoa(value))
	}
	return "[" + strings.Join(parts, ", ") + "]"
}
