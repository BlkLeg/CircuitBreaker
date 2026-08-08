// Package netscope is the Go mirror of the backend's app.core.agent_scope.
//
// It turns this host's directly connected networks plus the server-issued `remote_probe` grant
// config into a versioned effective scope, and answers "may this agent reach that destination?".
// §3 requires the backend and the agent to enforce scope independently — which is a safety
// property only while both enforce the *same* scope, so every decision here is pinned against
// fixtures/agent_scope_corpus.json, the corpus the backend evaluator is driven through too.
//
// The package deliberately depends on nothing but the standard library: internal/capability
// embeds Config in its `remote_probe` grant config and Slice 4's local discovery imports it too,
// so a dependency on internal/frame, internal/link or internal/collect would either be an import
// cycle or a reason for somebody to grow a second rule set instead.
//
// Two ordering rules carry the security weight, and both mirror the backend exactly:
//
//   - Special-use denial runs *before* any allow rule, so no override can hand an agent
//     loopback, link-local or cloud-metadata reachability.
//   - A hostname is only as safe as its worst answer: every resolved address must pass on its
//     own, which is what makes a rebinding resolver useless.
package netscope

import (
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"net/netip"
	"sort"
	"strings"
)

// ScopeModeDirectPrivate is the only policy v1 defines: scope is derived from the private and
// ULA prefixes the agent is directly attached to.
const ScopeModeDirectPrivate = "direct_private"

// Machine-readable decision reasons, byte-identical to agent_scope.py's. They travel into
// capability-violation events and probe-run audit rows and are matched by the shared corpus, so
// they are constants rather than prose.
const (
	ReasonInScope            = "in_scope"
	ReasonSpecialUse         = "special_use"
	ReasonExcluded           = "excluded_cidr"
	ReasonEmptyScope         = "empty_scope"
	ReasonOutOfScope         = "out_of_scope"
	ReasonInvalidDestination = "invalid_destination"
	ReasonUnresolvedHostname = "unresolved_hostname"

	// ReasonNotDirectlyConnected has no backend counterpart on purpose: it is §3's agent-side
	// extra rule, which the backend cannot express because only the agent knows which of the
	// networks it was authorized for it is actually attached to right now.
	ReasonNotDirectlyConnected = "not_directly_connected"
)

// ulaV6 is IPv6 unique local address space. The private-space test is defined here for both
// families rather than half-borrowed, matching agent_scope.py: v6 has no RFC 1918.
var ulaV6 = netip.MustParsePrefix("fc00::/7")

// rfc1918 mirrors network_acl._RFC1918_NETWORKS.
var rfc1918 = []netip.Prefix{
	netip.MustParsePrefix("10.0.0.0/8"),
	netip.MustParsePrefix("172.16.0.0/12"),
	netip.MustParsePrefix("192.168.0.0/16"),
}

// blockedNetworks is never reachable, whatever the grant says. Wider than the strictly named
// cases so that "unspecified", "limited broadcast" and the reserved space around them cannot be
// probed either: 0.0.0.0/8 covers this-network, 240.0.0.0/4 covers reserved plus
// 255.255.255.255, and 169.254.0.0/16 covers the IPv4 cloud-metadata address. Its IPv6
// counterpart sits inside ULA and would otherwise be derived as in-scope on any EC2 host, so it
// is listed explicitly.
var blockedNetworks = []netip.Prefix{
	netip.MustParsePrefix("0.0.0.0/8"),
	netip.MustParsePrefix("127.0.0.0/8"),
	netip.MustParsePrefix("169.254.0.0/16"),
	netip.MustParsePrefix("224.0.0.0/4"),
	netip.MustParsePrefix("240.0.0.0/4"),
	netip.MustParsePrefix("::/128"),
	netip.MustParsePrefix("::1/128"),
	netip.MustParsePrefix("fe80::/10"),
	netip.MustParsePrefix("ff00::/8"),
	netip.MustParsePrefix("fd00:ec2::254/128"),
}

// excludedInterfaceFlags names the interfaces whose networks are not "directly connected" in
// §3's sense: a loopback has no peers and a point-to-point tunnel carries a route, not a shared
// segment. Down interfaces are *not* filtered — hostinfo reports only up ones, and an absent
// flags list is an older report rather than a down link.
var excludedInterfaceFlags = map[string]bool{"loopback": true, "pointtopoint": true}

// InterfaceFacts is one directly connected network as the agent reported it on `hello`. Field
// tags match frame.NetworkFacts and agent_networks.facts so the same JSON decodes into either.
type InterfaceFacts struct {
	Name  string   `json:"name"`
	Flags []string `json:"flags,omitempty"`
	Addrs []string `json:"addrs,omitempty"`
}

// Config is the scope half of the server's normalized `remote_probe` grant config.
//
// An empty ScopeMode means the field was absent, and takes the default; the server's normalizer
// only ever emits a member of the known mode set, so a config without one predates the field
// rather than asking for "no networks at all".
type Config struct {
	ScopeMode           string   `json:"scope_mode,omitempty"`
	AdditionalCIDRs     []string `json:"additional_cidrs,omitempty"`
	ExcludedCIDRs       []string `json:"excluded_cidrs,omitempty"`
	AdditionalHostnames []string `json:"additional_hostnames,omitempty"`
}

// Scope is what one agent may reach, and the version of that answer.
//
// Networks is the allow list (directly connected plus centrally approved); DirectNetworks and
// ApprovedNetworks are the two halves that produced it, kept apart because §3's agent-side rule
// needs to tell them apart — a destination that is in Networks but in neither half was
// authorized by something this host cannot corroborate.
//
// Networks is an allow list, not the reachable set: Evaluate subtracts ExcludedNetworks and the
// static special-use blocklist from it.
//
// Version changes when, and only when, the four fields the backend digests change, so a consumer
// can treat a moved version as "this agent's authorization changed" without diffing CIDR lists.
type Scope struct {
	Networks         []string
	DirectNetworks   []string
	ApprovedNetworks []string
	ExcludedNetworks []string
	Hostnames        []string
	Version          string
}

// Decision is the evaluator's answer. Address names the resolved address that decided a
// hostname's fate, so a refusal can say *which* answer was unacceptable.
type Decision struct {
	Allowed bool
	Reason  string
	Address string
}

// Derive builds an agent's effective scope from its reported networks and its grant config.
//
// Nothing in here fails. It runs against whatever the kernel and the server handed over, so a
// malformed entry is dropped rather than allowed to fail a check that would then read as the
// target being down; administrator input was validated server-side at write time.
func Derive(facts []InterfaceFacts, cfg Config) Scope {
	mode := cfg.ScopeMode
	if mode == "" {
		mode = ScopeModeDirectPrivate
	}
	// An unrecognized mode derives nothing rather than everything: a config written by a newer
	// backend must not be read here as "no restriction".
	var direct []netip.Prefix
	if mode == ScopeModeDirectPrivate {
		direct = directNetworks(facts)
	}
	// A /0 cannot reach an allow list even if one slipped past the server's normalizer — the
	// same fail-closed reason it is rejected at write time.
	var approved []netip.Prefix
	for _, prefix := range parseCIDRs(cfg.AdditionalCIDRs) {
		if prefix.Bits() > 0 {
			approved = append(approved, prefix)
		}
	}

	networks := sortedNetworks(append(append([]netip.Prefix{}, direct...), approved...))
	directNets := sortedNetworks(direct)
	approvedNets := sortedNetworks(approved)
	excluded := sortedNetworks(parseCIDRs(cfg.ExcludedCIDRs))
	hostnames := sortedHostnames(cfg.AdditionalHostnames)
	return Scope{
		Networks:         networks,
		DirectNetworks:   directNets,
		ApprovedNetworks: approvedNets,
		ExcludedNetworks: excluded,
		Hostnames:        hostnames,
		// ApprovedNetworks is not digested: it is a subset of Networks, so it can never move
		// without moving that. Keeping the inputs identical to the backend's is what lets the
		// two versions be compared at all.
		Version: version(networks, directNets, excluded, hostnames),
	}
}

// Evaluate decides whether destination is permitted under scope.
//
// An IP literal is judged directly. A hostname is judged by resolved, which the caller supplies —
// this package never resolves anything, so the same answer set can be checked at dispatch and
// re-checked immediately before connecting. A name with no answers is refused rather than assumed
// reachable.
func Evaluate(scope Scope, destination string, resolved []string) Decision {
	host := strings.TrimSpace(destination)
	if host == "" {
		return Decision{Reason: ReasonInvalidDestination}
	}
	if literal, ok := parseAddress(host); ok {
		return evaluateAddress(scope, literal)
	}
	if len(resolved) == 0 {
		return Decision{Reason: ReasonUnresolvedHostname}
	}
	for _, candidate := range resolved {
		address, ok := parseAddress(candidate)
		if !ok {
			return Decision{Reason: ReasonInvalidDestination, Address: candidate}
		}
		if decision := evaluateAddress(scope, address); !decision.Allowed {
			return decision
		}
	}
	return Decision{Allowed: true, Reason: ReasonInScope}
}

// HostnameIsApproved reports whether host matches an additional_hostnames entry.
//
// Approval names a routed use case an administrator signed off on; it is consulted alongside the
// directly-connected requirement, never instead of Evaluate — an approved name whose addresses
// fall outside scope is still refused, or whoever controls that name's DNS would control the
// agent's scope.
func HostnameIsApproved(scope Scope, host string) bool {
	name := canonicalHostname(host)
	for _, pattern := range scope.Hostnames {
		if strings.HasPrefix(pattern, "*.") {
			if strings.HasSuffix(name, pattern[1:]) {
				return true
			}
			continue
		}
		if name == pattern {
			return true
		}
	}
	return false
}

func evaluateAddress(scope Scope, address netip.Addr) Decision {
	text := address.String()
	if containsAny(blockedNetworks, address) {
		return Decision{Reason: ReasonSpecialUse, Address: text}
	}
	networks := parseCIDRs(scope.Networks)
	// A subnet-directed broadcast is only recognizable against the prefix that defines it, so it
	// is checked here rather than in the static blocklist. Against *any* scope network, not just
	// the matching one: a /16 that also covers the address must not make its /24's broadcast
	// probeable.
	for _, network := range networks {
		if isDirectedBroadcast(network, address) {
			return Decision{Reason: ReasonSpecialUse, Address: text}
		}
	}
	if containsAny(parseCIDRs(scope.ExcludedNetworks), address) {
		return Decision{Reason: ReasonExcluded, Address: text}
	}
	if len(networks) == 0 {
		return Decision{Reason: ReasonEmptyScope, Address: text}
	}
	// §3's agent-side rule: the allow list is not enough on its own. A destination is reachable
	// only where this host is actually attached to it, or where an administrator named it
	// explicitly — so a network that entered the server's allow list some other way (a route
	// advertisement seen when the facts were last reported, say) cannot widen the default grant.
	if containsAny(parseCIDRs(scope.DirectNetworks), address) ||
		containsAny(parseCIDRs(scope.ApprovedNetworks), address) {
		return Decision{Allowed: true, Reason: ReasonInScope, Address: text}
	}
	if containsAny(networks, address) {
		return Decision{Reason: ReasonNotDirectlyConnected, Address: text}
	}
	return Decision{Reason: ReasonOutOfScope, Address: text}
}

func containsAny(networks []netip.Prefix, address netip.Addr) bool {
	for _, network := range networks {
		if network.Contains(address) {
			return true
		}
	}
	return false
}

func isDirectedBroadcast(network netip.Prefix, address netip.Addr) bool {
	// /31 and /32 have no broadcast address (RFC 3021), and IPv6 has none at all.
	if !network.Addr().Is4() || network.Bits() > 30 || !address.Is4() {
		return false
	}
	octets := network.Masked().Addr().As4()
	value := binary.BigEndian.Uint32(octets[:]) | uint32(0xffffffff)>>uint(network.Bits())
	binary.BigEndian.PutUint32(octets[:], value)
	return address == netip.AddrFrom4(octets)
}

// parseAddress parses a destination address, collapsing IPv4-mapped IPv6 to its IPv4 form so
// ::ffff:169.254.169.254 cannot take a v6-only path around the v4 rules.
func parseAddress(value string) (netip.Addr, bool) {
	address, err := netip.ParseAddr(strings.TrimSpace(value))
	if err != nil {
		return netip.Addr{}, false
	}
	return address.Unmap(), true
}

// parseCIDRs keeps the prefixes it can read and drops the rest, matching agent_scope.py's
// tolerance for agent-supplied facts. A bare address is a host prefix, as ipaddress.ip_network
// treats it; a prefix's host bits are masked off, as strict=False does.
func parseCIDRs(values []string) []netip.Prefix {
	var prefixes []netip.Prefix
	for _, value := range values {
		text := strings.TrimSpace(value)
		if prefix, err := netip.ParsePrefix(text); err == nil {
			prefixes = append(prefixes, prefix.Masked())
			continue
		}
		if address, err := netip.ParseAddr(text); err == nil {
			prefixes = append(prefixes, netip.PrefixFrom(address, address.BitLen()))
		}
	}
	return prefixes
}

func directNetworks(facts []InterfaceFacts) []netip.Prefix {
	var networks []netip.Prefix
	for _, entry := range facts {
		if hasExcludedFlag(entry.Flags) {
			continue
		}
		for _, network := range parseCIDRs(entry.Addrs) {
			if isPrivateNetwork(network) {
				networks = append(networks, network)
			}
		}
	}
	return networks
}

func hasExcludedFlag(flags []string) bool {
	for _, flag := range flags {
		if excludedInterfaceFlags[strings.ToLower(flag)] {
			return true
		}
	}
	return false
}

// isPrivateNetwork reports whether the *whole* prefix is private, not merely its host address: a
// 192.168.8.2/8 report describes 192.0.0.0/8, most of which is public, and putting that in scope
// would be a routing mistake widening a grant.
func isPrivateNetwork(network netip.Prefix) bool {
	if network.Addr().Is4() {
		for _, private := range rfc1918 {
			if isSubnetOf(network, private) {
				return true
			}
		}
		return false
	}
	return isSubnetOf(network, ulaV6)
}

func isSubnetOf(network, outer netip.Prefix) bool {
	return outer.Bits() <= network.Bits() && outer.Contains(network.Addr())
}

// sortedNetworks renders canonical, de-duplicated CIDR strings ordered by family, then network
// address, then prefix length — ipaddress's own ordering. Ordering is part of the scope version,
// so it must not depend on the order interfaces or config entries were written in.
func sortedNetworks(networks []netip.Prefix) []string {
	sort.Slice(networks, func(i, j int) bool {
		if cmp := networks[i].Addr().Compare(networks[j].Addr()); cmp != 0 {
			return cmp < 0
		}
		return networks[i].Bits() < networks[j].Bits()
	})
	var out []string
	for _, network := range networks {
		text := network.String()
		if len(out) > 0 && out[len(out)-1] == text {
			continue
		}
		out = append(out, text)
	}
	return out
}

func sortedHostnames(hostnames []string) []string {
	var out []string
	seen := map[string]bool{}
	for _, host := range hostnames {
		name := canonicalHostname(host)
		if !seen[name] {
			seen[name] = true
			out = append(out, name)
		}
	}
	sort.Strings(out)
	return out
}

func canonicalHostname(host string) string {
	return strings.TrimRight(strings.ToLower(strings.TrimSpace(host)), ".")
}

// version digests the scope's four dimensions, not what produced them: facts arriving in a
// different order, or an unrelated grant key changing, must leave it alone.
func version(networks, direct, excluded, hostnames []string) string {
	payload := strings.Join([]string{
		"agent-scope/v1",
		strings.Join(networks, ","),
		strings.Join(direct, ","),
		strings.Join(excluded, ","),
		strings.Join(hostnames, ","),
	}, "|")
	sum := sha256.Sum256([]byte(payload))
	return hex.EncodeToString(sum[:])[:16]
}
