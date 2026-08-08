package netscope

import (
	"reflect"
	"testing"
)

// lanFacts is the shape hostinfo reports for a plain dual-stack LAN interface: the host
// address carrying its prefix, not the network address.
func lanFacts(addrs ...string) []InterfaceFacts {
	return []InterfaceFacts{{Name: "eth0", Flags: []string{"up", "broadcast", "multicast"}, Addrs: addrs}}
}

func TestDerive_OnlyPrivateAndULA(t *testing.T) {
	facts := []InterfaceFacts{
		{Name: "eth0", Flags: []string{"up", "broadcast"}, Addrs: []string{
			"10.0.0.5/24",    // private v4
			"203.0.113.7/24", // a public lease on the same NIC
			"fd00:a::5/64",   // ULA
			"2001:db8::5/64", // global unicast v6
			"192.168.8.2/8",  // a prefix too wide to be wholly private
		}},
		{Name: "lo", Flags: []string{"up", "loopback"}, Addrs: []string{"127.0.0.1/8"}},
		{Name: "wg0", Flags: []string{"up", "pointtopoint"}, Addrs: []string{"10.9.0.2/24"}},
	}

	scope := Derive(facts, Config{ScopeMode: ScopeModeDirectPrivate})

	want := []string{"10.0.0.0/24", "fd00:a::/64"}
	if !reflect.DeepEqual(scope.Networks, want) {
		t.Errorf("Networks = %v, want %v", scope.Networks, want)
	}
	if !reflect.DeepEqual(scope.DirectNetworks, want) {
		t.Errorf("DirectNetworks = %v, want %v", scope.DirectNetworks, want)
	}
}

func TestEvaluate_SpecialUseAlwaysDenied(t *testing.T) {
	// Every blocked range is also handed to the agent as an explicit override, so a pass
	// here proves the denial outranks the widening rule rather than merely preceding it.
	scope := Derive(lanFacts("10.0.0.5/24", "fd00:ec2::5/64"), Config{
		AdditionalCIDRs: []string{"127.0.0.0/8", "169.254.0.0/16", "fe80::/10", "224.0.0.0/4", "255.255.255.255/32"},
	})

	for _, destination := range []string{
		"127.0.0.1",       // loopback
		"169.254.169.254", // IPv4 cloud metadata
		"fd00:ec2::254",   // IPv6 cloud metadata, inside a directly connected ULA prefix
		"fe80::1",         // IPv6 link-local
		"224.0.0.251",     // multicast
		"ff02::fb",        // IPv6 multicast
		"0.0.0.0",         // unspecified
		"::",              // IPv6 unspecified
		"255.255.255.255", // limited broadcast
		"10.0.0.255",      // the directly connected prefix's own directed broadcast
	} {
		if decision := Evaluate(scope, destination, nil); decision.Allowed || decision.Reason != ReasonSpecialUse {
			t.Errorf("Evaluate(%q) = %+v, want denied %q", destination, decision, ReasonSpecialUse)
		}
	}
}

func TestEvaluate_EmptyScopeDeniesEverything(t *testing.T) {
	// The fail-open guard: network_acl.is_ip_in_cidrs answers True for an empty list, which
	// would read "this agent reported no usable network" as "this agent may probe anything".
	scope := Derive(nil, Config{})

	if len(scope.Networks) != 0 {
		t.Fatalf("Networks = %v, want empty", scope.Networks)
	}
	for _, destination := range []string{"10.0.0.9", "fd00:a::9", "203.0.113.7"} {
		if decision := Evaluate(scope, destination, nil); decision.Allowed || decision.Reason != ReasonEmptyScope {
			t.Errorf("Evaluate(%q) = %+v, want denied %q", destination, decision, ReasonEmptyScope)
		}
	}
	if decision := Evaluate(scope, "nas.lan", []string{"10.0.0.9"}); decision.Allowed {
		t.Errorf("Evaluate(hostname) = %+v, want denied", decision)
	}
}

func TestScope_HostnameWithAnyOutOfScopeAddressIsRejected(t *testing.T) {
	scope := Derive(lanFacts("10.0.0.5/24", "fd00:a::5/64"), Config{
		AdditionalHostnames: []string{"*.branch.example.com"},
	})

	tests := []struct {
		name     string
		host     string
		resolved []string
		allowed  bool
		reason   string
	}{
		{"every answer in scope", "nas.lan", []string{"10.0.0.9", "fd00:a::9"}, true, ReasonInScope},
		{"one public answer", "nas.lan", []string{"10.0.0.9", "203.0.113.7"}, false, ReasonOutOfScope},
		{"one loopback answer", "nas.lan", []string{"10.0.0.9", "127.0.0.1"}, false, ReasonSpecialUse},
		{"no answers at all", "nas.lan", nil, false, ReasonUnresolvedHostname},
		{"an unparseable answer", "nas.lan", []string{"10.0.0.9", "not-an-ip"}, false, ReasonInvalidDestination},
		// Approval names a routed use case, so it is consulted alongside the address check
		// and never instead of it: otherwise whoever holds that name's DNS holds the scope.
		{"an approved name resolving out of scope", "db.branch.example.com", []string{"203.0.113.7"}, false, ReasonOutOfScope},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			decision := Evaluate(scope, tc.host, tc.resolved)
			if decision.Allowed != tc.allowed || decision.Reason != tc.reason {
				t.Errorf("Evaluate(%q, %v) = %+v, want allowed=%v reason=%q", tc.host, tc.resolved, decision, tc.allowed, tc.reason)
			}
		})
	}
	if !HostnameIsApproved(scope, "DB.Branch.Example.com.") {
		t.Error("HostnameIsApproved() = false for a wildcard-covered name")
	}
	if HostnameIsApproved(scope, "db.example.com") {
		t.Error("HostnameIsApproved() = true for a name outside the pattern")
	}
}

func TestEvaluate_IPv4MappedIPv6IsEvaluatedAsIPv4(t *testing.T) {
	scope := Derive(lanFacts("10.0.0.5/24"), Config{})

	if decision := Evaluate(scope, "::ffff:10.0.0.9", nil); !decision.Allowed {
		t.Errorf("Evaluate(mapped in-scope) = %+v, want allowed", decision)
	}
	// The v6-only path must not become a way around the v4 rules.
	if decision := Evaluate(scope, "::ffff:169.254.169.254", nil); decision.Allowed || decision.Reason != ReasonSpecialUse {
		t.Errorf("Evaluate(mapped metadata) = %+v, want denied %q", decision, ReasonSpecialUse)
	}
	if decision := Evaluate(scope, "::ffff:203.0.113.7", nil); decision.Allowed || decision.Reason != ReasonOutOfScope {
		t.Errorf("Evaluate(mapped public) = %+v, want denied %q", decision, ReasonOutOfScope)
	}
}

func TestEvaluate_DirectlyConnectedRequirementRejectsRoutedTargetWithoutOverride(t *testing.T) {
	// §3's agent-side extra rule. The scope here is the server's answer, not one this host
	// derived: 10.40.0.0/16 is in the allow list but is neither directly connected nor named
	// by an administrator, which is what a hostile route advertisement would produce.
	routed := Scope{
		Networks:       []string{"10.0.0.0/24", "10.40.0.0/16"},
		DirectNetworks: []string{"10.0.0.0/24"},
	}
	decision := Evaluate(routed, "10.40.7.1", nil)
	if decision.Allowed || decision.Reason != ReasonNotDirectlyConnected {
		t.Errorf("Evaluate(routed) = %+v, want denied %q", decision, ReasonNotDirectlyConnected)
	}
	if decision := Evaluate(routed, "10.0.0.9", nil); !decision.Allowed {
		t.Errorf("Evaluate(directly connected) = %+v, want allowed", decision)
	}

	// The same destination under an explicit central override is allowed, which is what keeps
	// the rule a guard on unapproved widening rather than a ban on routed monitors.
	approved := Derive(lanFacts("10.0.0.5/24"), Config{AdditionalCIDRs: []string{"10.40.0.0/16"}})
	if decision := Evaluate(approved, "10.40.7.1", nil); !decision.Allowed || decision.Reason != ReasonInScope {
		t.Errorf("Evaluate(approved override) = %+v, want allowed %q", decision, ReasonInScope)
	}
}

func TestDerive_VersionMatchesTheBackendDigest(t *testing.T) {
	// Pinned against app.core.agent_scope.derive_scope's own output. The corpus carries no
	// version, so without this literal the two sides could agree on every decision while
	// disagreeing about when an agent's authorization changed — and consumers cancel
	// in-flight work on a moved version.
	cfg := Config{
		AdditionalCIDRs:     []string{"10.40.0.0/16"},
		ExcludedCIDRs:       []string{"10.0.0.128/25"},
		AdditionalHostnames: []string{"*.Branch.Example.com."},
	}
	scope := Derive(lanFacts("10.0.0.5/24", "fd00:a::5/64"), cfg)
	if scope.Version != "ade0d83c2a19a8e3" {
		t.Errorf("Version = %q, want %q", scope.Version, "ade0d83c2a19a8e3")
	}

	// Facts arriving in another order describe the same scope and must not move it.
	reordered := Derive([]InterfaceFacts{{Name: "eth0", Flags: []string{"broadcast", "up"}, Addrs: []string{"fd00:a::5/64", "10.0.0.5/24"}}}, cfg)
	if reordered.Version != scope.Version {
		t.Errorf("Version = %q after reordering facts, want %q", reordered.Version, scope.Version)
	}
	if empty := Derive(nil, Config{}); empty.Version != "b030b0aa1cde5b3e" {
		t.Errorf("empty Version = %q, want %q", empty.Version, "b030b0aa1cde5b3e")
	}
}

// --- Prefix-shaped questions (Slice 4, D-15) ---------------------------------
//
// NetworkInScope's decisions are pinned by the shared corpus. What the corpus
// cannot express is the two answers that have no backend counterpart, and the
// arithmetic behind the job ceiling.

func TestNetworkIsDirectlyConnected_SeparatesDerivedFromApproved(t *testing.T) {
	scope := Derive(
		[]InterfaceFacts{{Name: "eth0", Flags: []string{"up"}, Addrs: []string{"10.0.0.5/24"}}},
		Config{AdditionalCIDRs: []string{"172.16.5.0/24"}},
	)

	if !NetworkIsDirectlyConnected(scope, "10.0.0.0/25") {
		t.Error("a prefix inside the attached /24 must read as directly connected")
	}
	// In scope, but only because an administrator approved the route — §7 requires the agent to
	// be able to tell the two apart at execution time.
	if NetworkIsDirectlyConnected(scope, "172.16.5.0/24") {
		t.Error("a centrally approved routed network is not directly connected")
	}
	if NetworkIsDirectlyConnected(scope, "not-a-cidr") {
		t.Error("an unparseable prefix must not read as directly connected")
	}
}

func TestAddressCount_SumsPrefixesAndCountsOverlapOnce(t *testing.T) {
	for _, tc := range []struct {
		name  string
		cidrs []string
		want  uint64
	}{
		{"empty", nil, 0},
		{"one /24", []string{"10.0.0.0/24"}, 256},
		{"a /24 and a /25", []string{"10.0.0.0/24", "10.0.1.0/25"}, 384},
		{"a host route", []string{"10.0.0.7/32"}, 1},
		{"an IPv6 /120", []string{"fd00::/120"}, 256},
		// Naming the same segment twice, or a segment and a slice of it, must not exhaust the
		// ceiling twice over.
		{"an exact duplicate", []string{"10.0.0.0/24", "10.0.0.0/24"}, 256},
		{"a contained prefix", []string{"10.0.0.0/24", "10.0.0.0/25"}, 256},
		// Fail-soft, matching parseCIDRs everywhere else: by the time this is asked, every
		// prefix has already been refused-or-accepted by NetworkInScope.
		{"an unparseable entry", []string{"10.0.0.0/24", "garbage"}, 256},
	} {
		t.Run(tc.name, func(t *testing.T) {
			if got := AddressCount(tc.cidrs); got != tc.want {
				t.Errorf("AddressCount(%v) = %d, want %d", tc.cidrs, got, tc.want)
			}
		})
	}
}

func TestAddressCount_HandlesADualStackTargetSet(t *testing.T) {
	// The backend counts families separately because ipaddress.collapse_addresses
	// raises on a mixed list; the Go side guards containment on family for the
	// same reason. Both must reach the same total.
	if got := AddressCount([]string{"10.0.0.0/24", "fd00::/120"}); got != 512 {
		t.Errorf("AddressCount(dual stack) = %d, want 512", got)
	}
	if got := AddressCount([]string{"10.0.0.0/25", "10.0.0.128/25"}); got != 256 {
		t.Errorf("AddressCount(adjacent halves) = %d, want 256", got)
	}
}

// TestNetworkIsApproved_IsTheOtherHalfOfTheAttachmentQuestion pins the exemption Slice 4's
// request validator depends on: an administrator-added routed network is on no segment this host
// is attached to, so a target inside it can only be authorized by this half.
func TestNetworkIsApproved_IsTheOtherHalfOfTheAttachmentQuestion(t *testing.T) {
	scope := Derive(
		[]InterfaceFacts{{Name: "eth0", Flags: []string{"up"}, Addrs: []string{"10.0.0.5/24"}}},
		Config{AdditionalCIDRs: []string{"172.16.5.0/24"}},
	)

	if !NetworkIsApproved(scope, "172.16.5.0/24") {
		t.Error("the approved network itself must read as approved")
	}
	// Containment rather than equality: the backend dispatches a slice of an approved network as
	// readily as the whole of it, and an exact-match test would refuse the slice.
	if !NetworkIsApproved(scope, "172.16.5.128/25") {
		t.Error("a prefix inside the approved network must read as approved")
	}
	if NetworkIsApproved(scope, "10.0.0.0/25") {
		t.Error("a directly connected prefix is derived, not approved")
	}
	if NetworkIsApproved(scope, "172.16.0.0/16") {
		t.Error("a prefix merely overlapping the approved network is not contained by it")
	}
	if NetworkIsApproved(scope, "not-a-cidr") {
		t.Error("an unparseable prefix must not read as approved")
	}
}
