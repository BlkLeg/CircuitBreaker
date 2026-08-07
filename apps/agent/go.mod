module circuitbreaker.dev/cb-agent

go 1.22

require (
	github.com/BurntSushi/toml v1.4.0
	github.com/flynn/noise v1.1.0
	github.com/gorilla/websocket v1.5.3
	// v1.1.63 is the last release declaring go 1.19; CI pins setup-go to 1.22 (D-11),
	// so a newer miekg/dns (v1.1.66+ declares go 1.23.0) compiles locally and breaks CI.
	// SOA and CAA are the reason for the dependency at all: net.Resolver cannot query them.
	github.com/miekg/dns v1.1.63
	golang.org/x/crypto v0.31.0
)

// v0.33.0 is the last release declaring go 1.18; CI pins setup-go to 1.22 (D-11),
// so a newer x/net (v0.36.0+ declares go 1.23.0) compiles locally and breaks CI.
// icmp + ipv4/ipv6 are the reason for the dependency: the stdlib cannot build ICMP echo
// messages, and the agent probes over unprivileged datagram ICMP with no CAP_NET_RAW.
require golang.org/x/net v0.33.0

require (
	golang.org/x/mod v0.18.0 // indirect
	golang.org/x/sync v0.7.0 // indirect
	golang.org/x/sys v0.28.0 // indirect
	golang.org/x/tools v0.22.0 // indirect
)
