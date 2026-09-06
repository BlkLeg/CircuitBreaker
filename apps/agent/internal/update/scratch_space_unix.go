//go:build unix

// apps/agent/internal/update/scratch_space_unix.go
package update

import "golang.org/x/sys/unix"

// freeBytes reports the space available in the filesystem holding dir.
//
// Bavail, not Bfree: the difference between them is the reserve the kernel
// keeps for root, and cb-agent runs as an unprivileged user that cannot
// touch it. Counting it would let a candidate pass a check its own writes
// then fail.
func freeBytes(dir string) (uint64, error) {
	var st unix.Statfs_t
	if err := unix.Statfs(dir, &st); err != nil {
		return 0, err
	}
	return st.Bavail * uint64(st.Bsize), nil
}
