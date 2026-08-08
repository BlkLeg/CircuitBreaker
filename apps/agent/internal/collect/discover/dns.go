package discover

import (
	"context"
	"net"
	"net/netip"
	"strings"
	"time"
)

// MethodReverseDNS is the discovery.request method that selects the PTR lookup (plan §4).
const MethodReverseDNS = "reverse_dns"

const (
	// DefaultReverseDNSTimeout bounds one PTR lookup. It is deliberately not derived from
	// Options.HostTimeout: that budget sizes the active checks against the target itself, while
	// this query goes to the agent's own resolver, which may be a forwarder several hops away and
	// is answering for an address it very likely has no record for.
	DefaultReverseDNSTimeout = 2 * time.Second

	// MaxHostnameLen is the wire limit for DiscoveryFindingPayload.Hostname, and the longest a
	// DNS name can be anyway. A longer answer is discarded here rather than truncated: half a
	// name is not a name, and the server would reject the frame carrying it.
	MaxHostnameLen = 253
)

// ReverseDNS resolves the PTR name of a responsive address (plan §1).
//
// The resolver is injected so tests never reach one: a PTR answer is whatever the runner's
// network decided to say, and the answers this file most needs to test are ones no cooperating
// resolver would ever give.
type ReverseDNS struct {
	lookup  func(ctx context.Context, addr string) ([]string, error)
	timeout time.Duration
}

func NewReverseDNS() *ReverseDNS {
	return &ReverseDNS{lookup: net.DefaultResolver.LookupAddr, timeout: DefaultReverseDNSTimeout}
}

// Lookup returns the address's hostname, or "" when there is not a usable one.
//
// There is no error return by design. A host with no PTR record is the ordinary case on a LAN,
// an unreachable resolver is a property of the agent rather than of the address, and a hostile
// answer is not something a caller could do anything with. All three are "this host reported no
// name" — a finding that still carries the address, its MAC and its open ports, which is what the
// backend matches on. Failing the host instead would let one broken resolver empty a whole scan.
func (r *ReverseDNS) Lookup(ctx context.Context, addr netip.Addr, opts Options) string {
	if !opts.wants(MethodReverseDNS) {
		return ""
	}

	// The budget has to reach the resolver rather than merely wrap it: net.Resolver honours the
	// context it is handed, and the context a sweep passes down usually has no deadline of its
	// own. Without this a wedged resolver would hold the whole job open.
	ctx, cancel := context.WithTimeout(ctx, r.budget())
	defer cancel()

	// Unmap so an IPv4-mapped address is queried in in-addr.arpa rather than ip6.arpa, and drop
	// the zone, which names a local interface and is not part of the address LookupAddr parses.
	names, err := r.lookup(ctx, addr.Unmap().WithZone("").String())
	if err != nil {
		return ""
	}
	for _, name := range names {
		if hostname := usableHostname(name); hostname != "" {
			return hostname
		}
	}
	return ""
}

func (r *ReverseDNS) budget() time.Duration {
	if r.timeout <= 0 {
		return DefaultReverseDNSTimeout
	}
	return r.timeout
}

// usableHostname returns the name with its root dot removed, or "" if it is not plausibly a DNS
// name.
//
// The answer comes from a resolver on the network being scanned — frequently the same router the
// scan is looking at — and lands in ScanResult.hostname, which the review queue renders, the
// matcher compares, and an operator may go on to trust. A rejected answer costs nothing: the
// hostname is optional evidence, so this discards rather than sanitises, and never repairs.
//
// The byte-wise loop is what rejects invalid UTF-8, a NUL, a CR that would forge a second line in
// a log, and an ANSI escape sequence, all at once: every one of them contains a byte outside the
// set below. Underscores are allowed because real LANs are full of them, and non-ASCII names
// arrive from a resolver already punycoded, so anything else here is a resolver lying.
func usableHostname(name string) string {
	name = strings.TrimSuffix(name, ".")
	if name == "" || len(name) > MaxHostnameLen {
		return ""
	}
	for _, label := range strings.Split(name, ".") {
		if label == "" {
			return ""
		}
	}
	for i := 0; i < len(name); i++ {
		switch c := name[i]; {
		case c >= 'a' && c <= 'z', c >= 'A' && c <= 'Z', c >= '0' && c <= '9':
		case c == '-', c == '.', c == '_':
		default:
			return ""
		}
	}
	return name
}
