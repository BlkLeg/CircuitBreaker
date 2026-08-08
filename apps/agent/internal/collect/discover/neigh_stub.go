//go:build !linux

package discover

import "context"

// The neighbor cache is a Linux netlink concept. The agent only ships linux/amd64 and
// linux/arm64 (Makefile build-all), but every contributor's `go build ./...` and `go vet ./...`
// has to work on macOS too, and without this file the package would not compile there at all.
//
// It reports the sentinel rather than an empty slice: an empty neighbor cache is a real and
// unremarkable state on Linux, so silently returning one here would make a platform that cannot
// answer the question indistinguishable from a host that answered "nothing".
func neighbors(context.Context) ([]Neighbor, error) { return nil, ErrNeighborsUnsupported }
