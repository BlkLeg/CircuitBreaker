// apps/agent/internal/update/scratch.go
package update

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"circuitbreaker.dev/cb-agent/internal/config"
)

// scratchDirName is the staging directory the agent keeps inside its own
// state directory, and the same name the installer stages into — one
// directory, one chown, one sweep.
const scratchDirName = ".staging"

// staleScratchAge is how long a staged download may sit before the next one
// deletes it. Staging in a persistent directory means nothing else ever
// cleans it: /tmp was swept by the OS, /var/lib/cb-agent is not, so the
// debris a crash between download and swap leaves behind is the agent's to
// remove. Comfortably longer than any download can take (downloadTimeout is
// two minutes), so this can never race a transfer in flight.
const staleScratchAge = 24 * time.Hour

// scratchFloorBytes is how much room a candidate must have when the server
// sends no Content-Length and the requirement is therefore unknown. Sized
// well above a real agent binary (tens of MB) without demanding the whole
// maxDownloadBytes ceiling, which would refuse perfectly adequate hosts.
const scratchFloorBytes int64 = 64 << 20

// scratchArtifactPrefix is what this package names the files it stages, and
// so the only thing the sweep is entitled to delete. Both Download and
// DownloadSignature pass a prefix beginning with it.
const scratchArtifactPrefix = "cb-agent-update-"

// scratchProbePrefix names the zero-length file prepareScratch writes to
// prove a directory accepts a write. Swept on the same terms as a download:
// a probe only survives if the process died between creating and removing it.
const scratchProbePrefix = ".cb-write-probe-"

// scratchCandidates lists the directories a download may be staged in, best
// first, with duplicates and unset values dropped.
//
// The agent's own state directory leads because it is the same filesystem as
// the install target (`{StateDir}/versions/...`), which makes Swap a rename
// rather than the cross-mount copy moveFile falls back to, and because it is
// real disk: systemd's PrivateTmp= gives this unit a RAM-backed /tmp of its
// own, and on a homelab host /tmp is routinely a small tmpfs that is already
// full. That is not hypothetical — a full /tmp is what made an agent
// deployment fail with whatever error curl happened to surface.
//
// CB_AGENT_DOWNLOAD_DIR overrides everything for the operator whose /var/lib
// is the constrained filesystem. The two general-purpose fallbacks follow, so
// a machine that cannot write its state directory at all still updates.
func scratchCandidates() []string {
	candidates := make([]string, 0, 4)
	add := func(dir string) {
		if dir == "" {
			return
		}
		for _, seen := range candidates {
			if seen == dir {
				return
			}
		}
		candidates = append(candidates, dir)
	}
	add(os.Getenv("CB_AGENT_DOWNLOAD_DIR"))
	add(filepath.Join(config.StateDir(), scratchDirName))
	add(os.TempDir())
	add("/var/tmp")
	return candidates
}

// scratchDir returns the first candidate directory that exists (creating it
// if it can), accepts a write, and has room for need bytes — sweeping its
// stale leftovers on the way out.
//
// When none qualifies the error names every candidate and why each was
// refused. That message is the whole point of checking in advance: "no space
// left on device" from somewhere inside a download says nothing about which
// filesystem to free.
func scratchDir(need int64) (string, error) {
	if need < 0 {
		need = 0
	}
	refusals := make([]string, 0, 4)
	for _, dir := range scratchCandidates() {
		if err := prepareScratch(dir, need); err != nil {
			refusals = append(refusals, fmt.Sprintf("%s (%v)", dir, err))
			continue
		}
		sweepScratch(dir)
		return dir, nil
	}
	return "", fmt.Errorf(
		"update: no directory can stage a %d byte download: %s; "+
			"free space on one of them, or set CB_AGENT_DOWNLOAD_DIR to a directory with room",
		need, strings.Join(refusals, "; "),
	)
}

// prepareScratch reports whether dir can hold a need-byte download, creating
// it if necessary.
//
// A write probe *and* a free-space check, because neither alone is enough: a
// directory with one byte free still accepts an empty file, and a filesystem
// with gigabytes free is useless if this process may not write to it.
func prepareScratch(dir string, need int64) error {
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return fmt.Errorf("cannot be created: %w", err)
	}
	probe, err := os.CreateTemp(dir, scratchProbePrefix+"*")
	if err != nil {
		return fmt.Errorf("not writable: %w", err)
	}
	probe.Close()
	os.Remove(probe.Name())

	free, err := freeBytes(dir)
	if err != nil {
		// The filesystem would not answer. A directory that has just proven
		// it accepts a write is still a better answer than refusing to
		// update at all, so an unanswerable statfs is not disqualifying.
		return nil
	}
	if free < uint64(need) {
		return fmt.Errorf("%d bytes free, needs %d", free, need)
	}
	return nil
}

// sweepScratch deletes this package's own abandoned files from dir.
//
// Best-effort by design: a sweep that cannot read the directory, or cannot
// delete one entry in it, must not stop the update that is about to happen —
// the worst case is the disk usage this function exists to reclaim. It only
// ever removes names this package writes, so a directory an operator points
// CB_AGENT_DOWNLOAD_DIR at is not a place the agent deletes their files.
func sweepScratch(dir string) {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return
	}
	cutoff := time.Now().Add(-staleScratchAge)
	for _, entry := range entries {
		name := entry.Name()
		if entry.IsDir() {
			continue
		}
		if !strings.HasPrefix(name, scratchArtifactPrefix) &&
			!strings.HasPrefix(name, scratchProbePrefix) {
			continue
		}
		info, infoErr := entry.Info()
		if infoErr != nil || info.ModTime().After(cutoff) {
			continue
		}
		os.Remove(filepath.Join(dir, name))
	}
}
