package hostinfo

import "runtime"

// goArch is a named wrapper (not an inline runtime.GOARCH reference) so Task 21's cross-compile
// step has one obvious place to verify arch reporting for both amd64 and arm64 builds.
func goArch() string { return runtime.GOARCH }
