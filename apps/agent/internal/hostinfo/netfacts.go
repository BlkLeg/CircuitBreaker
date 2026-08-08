package hostinfo

import (
	"net"
	"sort"

	"circuitbreaker.dev/cb-agent/internal/frame"
)

// netFactsCollector enumerates this host's directly connected networks. Interfaces and Addrs are
// its only two seams into the outside world, mirroring host.Collector's Now/Usage style: both
// fall back to the real net package when left nil, so a zero-valued struct is usable without
// wiring while every test drives fixture interfaces instead of the machine it runs on.
type netFactsCollector struct {
	Interfaces func() ([]net.Interface, error)
	Addrs      func(net.Interface) ([]net.Addr, error)
}

// Networks reports the real host's directly connected networks, for the `hello` frame at connect
// and for `capability.readiness` thereafter (Slice 4 D-8). It is exported so the readiness path
// has the same enumerator hello uses rather than a second one that could disagree with it about
// the same machine.
//
// Returns nil rather than erroring if the interface list can't be read (e.g. a sandboxed
// environment without /sys/class/net) — a hello with no networks is still a valid hello, and
// failing here would cost the link the whole connect. That nil is *distinct* from an empty
// slice; see collect.
func Networks() []frame.NetworkFacts {
	return netFactsCollector{}.collect()
}

func (c netFactsCollector) interfaces() ([]net.Interface, error) {
	if c.Interfaces == nil {
		return net.Interfaces()
	}
	return c.Interfaces()
}

func (c netFactsCollector) addrs(iface net.Interface) ([]net.Addr, error) {
	if c.Addrs == nil {
		return iface.Addrs()
	}
	return c.Addrs(iface)
}

// collect walks the interface list and keeps one entry per up, non-loopback interface that has
// at least one usable address. Output is sorted by interface name and then by address so the
// same host configuration always produces the same report: the backend bumps a scope generation
// whenever the normalized facts differ, and the kernel's enumeration order is not a contract.
// The two empty results are deliberately different values, and callers must keep them apart. nil
// means the question could not be asked; `[]frame.NetworkFacts{}` means it was asked and this host
// genuinely has nothing directly connected. Hello can conflate them — `networks` carries
// `omitempty` there — but capability.readiness cannot: its `networks` field has no omitempty
// precisely so an agent that lost every interface can send `[]` and replace the server's copy
// (D-8), and coercing an unreadable interface list into that same `[]` would wipe a working
// scope every time /sys/class/net blinked.
func (c netFactsCollector) collect() []frame.NetworkFacts {
	ifaces, err := c.interfaces()
	if err != nil {
		return nil
	}

	facts := []frame.NetworkFacts{}
	for _, iface := range ifaces {
		if iface.Flags&net.FlagLoopback != 0 || iface.Flags&net.FlagUp == 0 {
			continue
		}
		addrs, err := c.addrs(iface)
		if err != nil {
			continue // one unreadable interface must not lose the rest of the report
		}
		usable := usableAddrs(addrs)
		if len(usable) == 0 {
			// An interface with nothing directly connected says nothing: emitting it would only
			// give the generation comparison something to churn on.
			continue
		}
		facts = append(facts, frame.NetworkFacts{
			Name:  iface.Name,
			Flags: flagNames(iface.Flags),
			Addrs: usable,
		})
	}
	sort.Slice(facts, func(i, j int) bool { return facts[i].Name < facts[j].Name })
	return facts
}

// usableAddrs keeps the sorted CIDR form of every address that can name a directly connected
// network. Anything without a prefix is dropped (a point-to-point link can report a bare
// *net.IPAddr, which carries no network to be "connected to"), as is every address that can
// never be a probe destination on this link: loopback, link-local, multicast and the
// unspecified address. That set is *not* the scope policy — private/ULA filtering, exclusions
// and overrides are all evaluated server-side against these facts.
func usableAddrs(addrs []net.Addr) []string {
	var out []string
	for _, addr := range addrs {
		// Both halves have to be present: IPNet.String() renders a missing address *or* a
		// missing mask as the literal "<nil>", which would travel to the backend as an address
		// string the scope evaluator can only reject.
		ipnet, ok := addr.(*net.IPNet)
		if !ok || ipnet.IP == nil || ipnet.Mask == nil {
			continue
		}
		ip := ipnet.IP
		if ip.IsLoopback() || ip.IsLinkLocalUnicast() || ip.IsMulticast() || ip.IsUnspecified() {
			continue
		}
		out = append(out, ipnet.String())
	}
	sort.Strings(out)
	return out
}

// interfaceFlags is net's own flag vocabulary in net.Flags.String()'s order, restated here so
// NetworkFacts.Flags is a list of names rather than a "|"-joined string a consumer would have to
// split. Keep the names byte-identical to net's: the backend and Slice 4 match on them.
var interfaceFlags = []struct {
	flag net.Flags
	name string
}{
	{net.FlagUp, "up"},
	{net.FlagBroadcast, "broadcast"},
	{net.FlagLoopback, "loopback"},
	{net.FlagPointToPoint, "pointtopoint"},
	{net.FlagMulticast, "multicast"},
	{net.FlagRunning, "running"},
}

func flagNames(flags net.Flags) []string {
	var names []string
	for _, f := range interfaceFlags {
		if flags&f.flag != 0 {
			names = append(names, f.name)
		}
	}
	return names
}
