package hostinfo

import (
	"errors"
	"net"
	"reflect"
	"testing"

	"circuitbreaker.dev/cb-agent/internal/frame"
)

// cidrAddr builds the address shape the kernel actually hands back from Addrs(): the host
// address carrying its prefix length, not the network address.
func cidrAddr(t *testing.T, s string) net.Addr {
	t.Helper()
	ip, network, err := net.ParseCIDR(s)
	if err != nil {
		t.Fatalf("ParseCIDR(%q) error = %v", s, err)
	}
	return &net.IPNet{IP: ip, Mask: network.Mask}
}

// fixedEnumerator wires a netFactsCollector to a fixture interface list keyed by name, so no
// test in this file depends on the machine it runs on.
func fixedEnumerator(t *testing.T, ifaces []net.Interface, addrs map[string][]net.Addr) netFactsCollector {
	t.Helper()
	return netFactsCollector{
		Interfaces: func() ([]net.Interface, error) { return ifaces, nil },
		Addrs: func(iface net.Interface) ([]net.Addr, error) {
			return addrs[iface.Name], nil
		},
	}
}

func TestNetFacts_SkipsLoopbackAndDownInterfaces(t *testing.T) {
	c := fixedEnumerator(t,
		[]net.Interface{
			{Name: "lo", Flags: net.FlagUp | net.FlagLoopback},
			{Name: "eth0", Flags: net.FlagUp | net.FlagBroadcast | net.FlagMulticast},
			{Name: "eth1", Flags: net.FlagBroadcast | net.FlagMulticast}, // admin-down
		},
		map[string][]net.Addr{
			"lo":   {cidrAddr(t, "127.0.0.1/8")},
			"eth0": {cidrAddr(t, "10.0.0.5/24")},
			"eth1": {cidrAddr(t, "10.1.0.5/24")},
		},
	)

	want := []frame.NetworkFacts{
		{Name: "eth0", Flags: []string{"up", "broadcast", "multicast"}, Addrs: []string{"10.0.0.5/24"}},
	}
	if got := c.collect(); !reflect.DeepEqual(got, want) {
		t.Errorf("collect() = %+v, want %+v", got, want)
	}
}

func TestNetFacts_EmitsIPv4AndIPv6PrefixesFromInjectedEnumerator(t *testing.T) {
	c := fixedEnumerator(t,
		[]net.Interface{{Name: "eth0", Flags: net.FlagUp | net.FlagBroadcast | net.FlagMulticast}},
		map[string][]net.Addr{
			"eth0": {cidrAddr(t, "10.0.0.5/24"), cidrAddr(t, "fd00::1/64"), cidrAddr(t, "203.0.113.7/32")},
		},
	)

	// A public address is kept: this collector reports facts, not policy. Restricting the
	// reachable set to private/ULA is the scope evaluator's job, and it needs to see the
	// address it is excluding.
	want := []frame.NetworkFacts{{
		Name:  "eth0",
		Flags: []string{"up", "broadcast", "multicast"},
		Addrs: []string{"10.0.0.5/24", "203.0.113.7/32", "fd00::1/64"},
	}}
	if got := c.collect(); !reflect.DeepEqual(got, want) {
		t.Errorf("collect() = %+v, want %+v", got, want)
	}
}

func TestNetFacts_OmitsLinkLocalAndUnroutableAddresses(t *testing.T) {
	c := fixedEnumerator(t,
		[]net.Interface{
			{Name: "eth0", Flags: net.FlagUp | net.FlagMulticast},
			{Name: "eth1", Flags: net.FlagUp | net.FlagMulticast},
		},
		map[string][]net.Addr{
			"eth0": {
				cidrAddr(t, "169.254.10.4/16"),           // IPv4 link-local (APIPA)
				cidrAddr(t, "fe80::1/64"),                // IPv6 link-local
				cidrAddr(t, "224.0.0.251/32"),            // multicast
				cidrAddr(t, "0.0.0.0/0"),                 // unspecified
				cidrAddr(t, "127.0.0.2/8"),               // loopback address on a non-loopback interface
				&net.IPAddr{IP: net.ParseIP("10.9.9.9")}, // prefix-less: some point-to-point links report this
				// Prefix-less the other way: an *net.IPNet whose Mask never got filled in.
				// IPNet.String() renders that as the literal "<nil>", which would reach the
				// backend as an address string the scope evaluator has to reject.
				&net.IPNet{IP: net.ParseIP("10.8.8.8")},
				cidrAddr(t, "10.0.0.5/24"),
			},
			// Nothing usable at all: the interface itself is dropped rather than reported with
			// an empty address list, so the backend's generation comparison never sees an entry
			// that says nothing.
			"eth1": {cidrAddr(t, "fe80::2/64")},
		},
	)

	want := []frame.NetworkFacts{
		{Name: "eth0", Flags: []string{"up", "multicast"}, Addrs: []string{"10.0.0.5/24"}},
	}
	if got := c.collect(); !reflect.DeepEqual(got, want) {
		t.Errorf("collect() = %+v, want %+v", got, want)
	}
}

func TestNetFacts_IsDeterministicallyOrdered(t *testing.T) {
	// The kernel's enumeration order is not a stable contract, and Task 2 bumps a generation
	// counter whenever the normalized facts differ — an unsorted report would churn that
	// counter on every reconnect without a single byte of the host's networking having changed.
	c := fixedEnumerator(t,
		[]net.Interface{
			{Name: "eth2", Flags: net.FlagUp},
			{Name: "eth0", Flags: net.FlagUp},
			{Name: "eth1", Flags: net.FlagUp},
		},
		map[string][]net.Addr{
			"eth2": {cidrAddr(t, "10.2.0.5/24")},
			"eth0": {cidrAddr(t, "fd00::1/64"), cidrAddr(t, "10.0.0.9/24"), cidrAddr(t, "10.0.0.5/24")},
			"eth1": {cidrAddr(t, "10.1.0.5/24")},
		},
	)

	want := []frame.NetworkFacts{
		{Name: "eth0", Flags: []string{"up"}, Addrs: []string{"10.0.0.5/24", "10.0.0.9/24", "fd00::1/64"}},
		{Name: "eth1", Flags: []string{"up"}, Addrs: []string{"10.1.0.5/24"}},
		{Name: "eth2", Flags: []string{"up"}, Addrs: []string{"10.2.0.5/24"}},
	}
	got := c.collect()
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("collect() = %+v, want %+v", got, want)
	}
	if again := c.collect(); !reflect.DeepEqual(again, got) {
		t.Errorf("collect() is not repeatable: second call = %+v, first = %+v", again, got)
	}
}

func TestNetFacts_EnumeratorErrorYieldsEmptySliceNotPanic(t *testing.T) {
	// A hello with no networks is still a valid hello (the field is optional on both sides), so
	// an unreadable interface list degrades to "nothing to report" rather than failing the
	// connect that carries it.
	failing := netFactsCollector{
		Interfaces: func() ([]net.Interface, error) { return nil, errors.New("no /sys/class/net") },
		Addrs:      func(net.Interface) ([]net.Addr, error) { return nil, errors.New("unreachable") },
	}
	if got := failing.collect(); len(got) != 0 {
		t.Errorf("collect() = %+v, want no entries when the interface list cannot be read", got)
	}

	// One interface failing must not lose the rest of the report.
	partial := netFactsCollector{
		Interfaces: func() ([]net.Interface, error) {
			return []net.Interface{{Name: "eth0", Flags: net.FlagUp}, {Name: "eth1", Flags: net.FlagUp}}, nil
		},
		Addrs: func(iface net.Interface) ([]net.Addr, error) {
			if iface.Name == "eth0" {
				return nil, errors.New("address enumeration failed")
			}
			return []net.Addr{cidrAddr(t, "10.1.0.5/24")}, nil
		},
	}
	want := []frame.NetworkFacts{{Name: "eth1", Flags: []string{"up"}, Addrs: []string{"10.1.0.5/24"}}}
	if got := partial.collect(); !reflect.DeepEqual(got, want) {
		t.Errorf("collect() = %+v, want %+v", got, want)
	}
}

// TestNetFacts_UnreadableAndEmptyAreDistinguishableResults pins the one thing about collect's two
// empty results that a `len(got) == 0` assertion cannot see.
//
// capability.readiness' `networks` field carries no `omitempty` so that an agent which lost every
// interface can send `[]` and replace the server's scope (D-8). That makes nil and `[]` two
// different statements on the wire, and the daemon decides which to send by testing this exact
// nilness: an unreadable /sys/class/net coerced into `[]` would wipe a working scope and churn
// the scope generation every time the read blinked.
func TestNetFacts_UnreadableAndEmptyAreDistinguishableResults(t *testing.T) {
	unreadable := netFactsCollector{
		Interfaces: func() ([]net.Interface, error) { return nil, errors.New("no /sys/class/net") },
	}
	if got := unreadable.collect(); got != nil {
		t.Errorf("collect() = %#v with an unreadable interface list, want nil — the question could not be asked", got)
	}

	// Loopback only: the host was enumerated successfully and has nothing directly connected.
	empty := netFactsCollector{
		Interfaces: func() ([]net.Interface, error) {
			return []net.Interface{{Name: "lo", Flags: net.FlagUp | net.FlagLoopback}}, nil
		},
		Addrs: func(net.Interface) ([]net.Addr, error) { return []net.Addr{cidrAddr(t, "127.0.0.1/8")}, nil },
	}
	got := empty.collect()
	if got == nil {
		t.Fatal("collect() = nil on a host with no directly connected network, want a non-nil empty slice — the answer is \"nothing\", not \"unknown\"")
	}
	if len(got) != 0 {
		t.Errorf("collect() = %+v, want no entries", got)
	}
}
