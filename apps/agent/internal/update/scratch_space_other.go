//go:build !unix

// apps/agent/internal/update/scratch_space_other.go
package update

import "errors"

// errFreeSpaceUnsupported keeps this package compiling for platforms the
// agent is not built for (the Makefile ships linux/amd64 and linux/arm64
// only), mirroring internal/collect/discover's neigh_stub.go. prepareScratch
// treats an unanswerable statfs as "do not refuse over it", so a stub build
// still stages downloads — it just cannot check room first.
var errFreeSpaceUnsupported = errors.New("free space is not queryable on this platform")

func freeBytes(_ string) (uint64, error) {
	return 0, errFreeSpaceUnsupported
}
