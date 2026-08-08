// Package discover runs the agent's local network discovery
// (plans/2026-08-04-cbi-agent-slice4-local-discovery.md §1).
//
// Everything here is unprivileged: the agent ships with no CAP_NET_RAW and this package must
// never become a reason to grant it. That is what rules out raw ARP sweeps, SYN scans and OS
// fingerprinting, and it is why the neighbor cache is read out of the kernel rather than
// synthesised by probing.
//
// This package holds no CIDR opinion of its own. internal/netscope is the one scope evaluator,
// shared with the backend and pinned to one corpus; a collector here reports what it observed and
// leaves in-scope/out-of-scope entirely to that package.
package discover

import (
	"context"
	"errors"
	"net/netip"
)

// MethodNeighborCache is the discovery.request method that selects this collector (plan §4). It
// is the only one of the four that opens no socket, which is why a request may name it alone.
const MethodNeighborCache = "neighbor_cache"

// ErrNeighborsUnsupported reports that this build cannot read a kernel neighbor cache at all.
//
// Only the //go:build !linux stub returns it. Callers must treat it as "this evidence source is
// absent" and fall back to the active checks, never as a job failure: plan §1 lists the neighbor
// cache as one of four methods, and a discovery run that produced ICMP and TCP evidence is a
// successful run.
var ErrNeighborsUnsupported = errors.New("discover: the kernel neighbor cache is unavailable on this platform")

// Neighbor is one usable entry of the kernel's neighbor cache.
//
// MAC is empty whenever the kernel gave no link-layer address worth reporting. It is deliberately
// not defaulted to all-zeroes: the backend matches findings to existing Hardware rows by MAC
// (D-9), so a synthesised 00:00:00:00:00:00 would collapse every such host onto a single row.
type Neighbor struct {
	IP    netip.Addr
	MAC   string
	State string
}

// The NUD states that survive parsing, lowercased. States are reported rather than reduced to a
// boolean because they carry the freshness a caller needs: NeighborStale is a host the kernel
// spoke to at some point, NeighborReachable is one it confirmed within the last few seconds.
//
// NUD_FAILED, NUD_INCOMPLETE and NUD_NONE have no constant here on purpose — they are dropped
// during parsing and can never reach a caller. They are the kernel recording a resolution attempt,
// not a host: treating them as discovery evidence would report every address the agent itself
// probed as live.
const (
	NeighborReachable = "reachable"
	NeighborStale     = "stale"
	NeighborDelay     = "delay"
	NeighborProbe     = "probe"
	NeighborNoARP     = "noarp"
	NeighborPermanent = "permanent"
)

// Neighbors returns the kernel's current neighbor cache, or ErrNeighborsUnsupported where no such
// cache can be read. It performs no network activity: the entries are the kernel's existing
// knowledge, which is exactly why plan §1 lists it first among the collectors.
//
// The read is bounded: ctx cancellation is observed between kernel reads, and the call gives up
// on its own after neighborDumpTimeout even under a context that has none, so a wedged netlink
// socket cannot pin a discovery job for the whole job deadline.
//
// This wrapper exists so the contract is documented once and the two platform implementations of
// neighbors() cannot drift apart in signature; see neigh_linux.go and neigh_stub.go.
func Neighbors(ctx context.Context) ([]Neighbor, error) { return neighbors(ctx) }
