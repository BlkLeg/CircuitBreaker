package discover

import (
	"context"
	"net"
	"net/netip"
	"sort"
	"strconv"
	"sync"
	"time"

	"circuitbreaker.dev/cb-agent/internal/collect/probe"
)

// The method vocabulary discovery.request selects from and discovery.finding reports back as
// evidence (plan §4). Only the two active checks this file performs are named here; the neighbor
// cache and reverse DNS name themselves where they are implemented.
const (
	MethodICMP       = "icmp"
	MethodTCPConnect = "tcp_connect"
)

// The collector limits from plan §1, applied when a caller passes zero. They are the same numbers
// the grant defaults to, and they exist because a zero read out of a malformed or partially
// populated grant must mean "the documented bound", never "no bound at all" — an unbounded sweep
// would open one socket per address at once.
const (
	DefaultHostTimeout        = 1500 * time.Millisecond
	DefaultMaxConcurrentHosts = 64
)

// Options bounds one sweep. Every field comes from the server's discovery.request, which the
// backend has already clamped against the agent's local_discovery grant; nothing here re-derives
// or widens them.
type Options struct {
	// Methods restricts the sweep to the request's selected methods. Nil selects both checks: a
	// caller that wanted neither has no reason to call Sweep at all.
	Methods []string
	// TCPPorts is the explicit port set the grant allows. Empty means no port is touched — this
	// package never falls back to a port list of its own, because a port outside the grant is a
	// capability violation, not a default.
	TCPPorts []int
	// HostTimeout is the whole wall-clock budget for one address, shared by its echo and all of
	// its connects. It is not per check and not per port: the request's host_timeout_ms is what
	// the operator sized the job with, and a per-port budget would multiply it by the port count.
	HostTimeout time.Duration
	// MaxConcurrentHosts is how many addresses may be in flight at once.
	MaxConcurrentHosts int
}

func (o Options) wants(method string) bool {
	if o.Methods == nil {
		return true
	}
	for _, selected := range o.Methods {
		if selected == method {
			return true
		}
	}
	return false
}

// allowsPort answers whether the grant listed this port. There is no fallback and no default:
// a port outside the set is a capability violation, so "not listed" means the collector does not
// touch it at all.
func (o Options) allowsPort(port int) bool {
	for _, granted := range o.TCPPorts {
		if granted == port {
			return true
		}
	}
	return false
}

func (o Options) hostTimeout() time.Duration {
	if o.HostTimeout <= 0 {
		return DefaultHostTimeout
	}
	return o.HostTimeout
}

func (o Options) concurrency() int {
	if o.MaxConcurrentHosts <= 0 {
		return DefaultMaxConcurrentHosts
	}
	return o.MaxConcurrentHosts
}

// LiveHost is one address that answered at least one check. Only responsive addresses are ever
// reported: a discovery.finding describes a host that exists, and emitting silence would turn a
// /24 sweep into 254 findings the reviewer has to dismiss.
type LiveHost struct {
	Address netip.Addr
	// Evidence names the checks that answered, in the order they ran. It is the finding's
	// `evidence` array verbatim, which is why the values are the request's method names.
	Evidence []string
	// OpenPorts is ascending rather than in the granted order, because it is read by people.
	OpenPorts []int
}

// SweepSummary is what the terminal discovery.finding needs from a completed sweep.
type SweepSummary struct {
	// AddressesScanned counts the addresses actually started, so a cancelled sweep reports how
	// far it got rather than how far it was asked to go.
	AddressesScanned int
	HostsFound       int
	// ICMPUnavailable and ICMPReason carry the degradation described below: the sweep still ran,
	// on TCP connect alone, and the operator has to be told why the ICMP half is missing.
	ICMPUnavailable bool
	ICMPReason      string
}

// Liveness runs bounded host-liveness sweeps: one unprivileged ICMP echo and a connect to each
// granted TCP port, per address (plan §1).
//
// Both dependencies are injected so no test reaches the kernel — an ICMP socket needs
// ping_group_range to cover the test runner's GID, and a real connect would make the concurrency
// and deadline assertions depend on whatever is on the runner's LAN.
type Liveness struct {
	open func(network string) (probe.EchoSession, error)
	dial func(ctx context.Context, network, address string) (net.Conn, error)
}

func NewLiveness() *Liveness {
	dialer := &net.Dialer{}
	return &Liveness{open: probe.ListenUnprivilegedICMP, dial: dialer.DialContext}
}

// Sweep probes every address and calls emit once for each one that answers, then reports what it
// did. emit may be nil.
//
// A cancelled sweep returns ctx.Err() alongside the findings it already made: work stops, but an
// address that answered before the stop was still observed, and the caller's terminal summary
// reports both the cancellation and the hosts.
func (l *Liveness) Sweep(ctx context.Context, addrs []netip.Addr, opts Options, emit func(LiveHost)) (SweepSummary, error) {
	state := &sweepState{emit: emit}

	// A buffered channel is the whole concurrency bound. probe.Runtime counts slots by hand
	// (runtime.go:411-456) because assignments arrive one at a time and have to queue; a sweep
	// has its whole work list up front, so the send that blocks here *is* the queue.
	slots := make(chan struct{}, opts.concurrency())
	var workers sync.WaitGroup
	var err error

dispatch:
	for _, addr := range addrs {
		select {
		case <-ctx.Done():
			// Stop handing out new addresses immediately. The hosts already running collapse on
			// the same context, so this returns within one host budget and usually far sooner.
			err = ctx.Err()
			break dispatch
		case slots <- struct{}{}:
		}
		workers.Add(1)
		go func(addr netip.Addr) {
			defer workers.Done()
			defer func() { <-slots }()
			l.probeHost(ctx, addr, opts, state)
		}(addr)
	}

	// Joining before returning is what makes the goroutine-leak assertion hold: a sweep that
	// returned while its hosts kept probing would keep opening sockets under a job the caller
	// has already summarised and closed out.
	workers.Wait()
	return state.summary(), err
}

// probeHost runs one address's checks inside a single shared budget.
func (l *Liveness) probeHost(ctx context.Context, addr netip.Addr, opts Options, state *sweepState) {
	state.started()

	hostCtx, cancel := context.WithTimeout(ctx, opts.hostTimeout())
	defer cancel()

	host := LiveHost{Address: addr}
	if l.echo(hostCtx, addr, opts, state) {
		host.Evidence = append(host.Evidence, MethodICMP)
	}
	if ports := l.openPorts(hostCtx, addr, opts); len(ports) > 0 {
		host.Evidence = append(host.Evidence, MethodTCPConnect)
		host.OpenPorts = ports
	}
	if len(host.Evidence) == 0 {
		return
	}
	state.report(host)
}

// echo sends exactly one unprivileged ICMP echo and reports whether it was answered.
func (l *Liveness) echo(ctx context.Context, addr netip.Addr, opts Options, state *sweepState) bool {
	if !opts.wants(MethodICMP) || !state.icmpUsable() {
		return false
	}

	network := "udp4"
	if !addr.Unmap().Is4() {
		network = "udp6"
	}
	// One socket per host rather than one per sweep: probe.EchoSession matches replies by
	// sequence number on a single deadline, so two hosts sharing one would steal each other's
	// answers. The socket count is bounded by MaxConcurrentHosts, which is the point of the slot.
	session, err := l.open(network)
	if err != nil {
		state.disableICMP(err)
		return false
	}
	defer session.Close()

	// Sequence 0 for every host: the session is this host's alone and carries exactly one echo,
	// so there is nothing for a sequence number to disambiguate.
	_, replied, pingErr := session.Ping(ctx, addr, 0, opts.hostTimeout())
	if pingErr != nil {
		// The echo could not be sent to *this* address — an unreachable network for its family,
		// or the budget running out. It says nothing about the host and nothing about the socket,
		// so it is silence here rather than a degradation of the sweep.
		return false
	}
	return replied
}

// openPorts connects to each granted TCP port and returns those that accepted, ascending.
func (l *Liveness) openPorts(ctx context.Context, addr netip.Addr, opts Options) []int {
	if !opts.wants(MethodTCPConnect) || len(opts.TCPPorts) == 0 {
		return nil
	}

	var mu sync.Mutex
	open := make([]int, 0, len(opts.TCPPorts))
	// The ports of one host go out together because HostTimeout is a wall-clock budget for the
	// address. Connecting to them in turn would spend the whole budget on the first filtered
	// port and never reach the rest, making the size of the granted port set decide which ports
	// are looked at. In-flight sockets stay bounded by MaxConcurrentHosts x len(TCPPorts), both
	// of which the backend caps (256 and 32).
	var dials sync.WaitGroup
	for _, port := range opts.TCPPorts {
		dials.Add(1)
		go func(port int) {
			defer dials.Done()
			conn, err := l.dial(ctx, "tcp", net.JoinHostPort(addr.String(), strconv.Itoa(port)))
			if err != nil {
				return
			}
			// The handshake was the observation. Nothing is written and nothing is read: plan §7
			// bars discovery from speaking application protocols, and the bounded banner read is
			// its own deliberate, separately budgeted step.
			_ = conn.Close()
			mu.Lock()
			open = append(open, port)
			mu.Unlock()
		}(port)
	}
	dials.Wait()

	sort.Ints(open)
	return open
}

// sweepState is the bookkeeping every host of one sweep shares.
type sweepState struct {
	mu         sync.Mutex
	emit       func(LiveHost)
	scanned    int
	found      int
	icmpDown   bool
	icmpReason string
}

func (s *sweepState) started() {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.scanned++
}

// report hands one host to the caller. The callback runs under the lock deliberately: callers
// turn each host into a frame, and serialising here means none of them has to carry a lock of its
// own. A callback must therefore not call back into Sweep.
func (s *sweepState) report(host LiveHost) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.found++
	if s.emit != nil {
		s.emit(host)
	}
}

func (s *sweepState) icmpUsable() bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	return !s.icmpDown
}

// disableICMP records the first socket failure and stops the sweep attempting any more.
//
// Failing to open an unprivileged ICMP socket is a property of the host, not of the address being
// probed: net.ipv4.ping_group_range not covering the agent's GID, or a seccomp filter or namespace
// deciding otherwise. Retrying it once per address would cost a failed syscall per address and
// bury the one reason the operator has to act on. The latch is per sweep, so the next job picks
// the socket back up once the host is fixed — nothing has to restart the agent.
//
// This is a degradation, never a job failure: the sweep continues on TCP connect alone. Failing
// here instead would make an agent with no ICMP privileges unable to discover anything, which is
// exactly the deployment the unprivileged design is for.
func (s *sweepState) disableICMP(err error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.icmpDown {
		return
	}
	s.icmpDown = true
	s.icmpReason = err.Error()
}

func (s *sweepState) summary() SweepSummary {
	s.mu.Lock()
	defer s.mu.Unlock()
	return SweepSummary{
		AddressesScanned: s.scanned,
		HostsFound:       s.found,
		ICMPUnavailable:  s.icmpDown,
		ICMPReason:       s.icmpReason,
	}
}
