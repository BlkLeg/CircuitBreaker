module circuitbreaker.dev/cb-agent

go 1.25.13

require (
	github.com/BurntSushi/toml v1.4.0
	github.com/flynn/noise v1.1.0
	github.com/gorilla/websocket v1.5.3
	// v1.1.63 remains sufficient for the agent's DNS record queries.
	// SOA and CAA are the reason for the dependency at all: net.Resolver cannot query them.
	github.com/miekg/dns v1.1.63
	golang.org/x/crypto v0.53.0
)

// The x/sys version follows the security-supported x/crypto and x/net graph.
// unix is the reason for the dependency: reading the kernel neighbor cache over RTM_GETNEIGH
// needs the netlink constants and raw socket calls, and the stdlib syscall package is frozen.
require golang.org/x/sys v0.46.0

// x/net is kept current because it handles attacker-controlled network input.
// icmp + ipv4/ipv6 are the reason for the dependency: the stdlib cannot build ICMP echo
// messages, and the agent probes over unprivileged datagram ICMP with no CAP_NET_RAW.
require golang.org/x/net v0.56.0

require (
	golang.org/x/mod v0.18.0 // indirect
	golang.org/x/sync v0.7.0 // indirect
	golang.org/x/tools v0.22.0 // indirect
)
