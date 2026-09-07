// apps/agent/internal/enroll/enrolled.go
package enroll

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
)

// enrolledFilename marks that the server has, at some point, confirmed this
// device active — written alongside device.key and (once the link has run)
// queue.head in the same state directory.
//
// Its presence is what lets runDaemon skip Run's network round trip on every
// subsequent process start: enrollment only needs to happen once per device,
// but until this marker existed Run was called — and its failure was
// fatal — on every single restart, including the overwhelming majority where
// the device was already active and the call could only ever answer
// "active" again.
const enrolledFilename = "enrolled"

// MarkEnrolled durably records that the server has confirmed this device
// active. Called from Run's "active" case, after that confirmation — never
// speculatively — so a crash before the server answers leaves no marker
// behind and the next start tries enrollment again, which is the safe
// direction to fail in.
//
// Uses the same temp-file-then-rename discipline as
// internal/spool.writeHeadMarker: write to a sibling temp file, then rename
// over the destination, so a reader (including a process that crashes
// mid-write) always sees either no marker or a complete one, never a torn
// file that happens to read back as "present".
func MarkEnrolled(stateDir string) error {
	path := filepath.Join(stateDir, enrolledFilename)
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, []byte("1\n"), 0o600); err != nil {
		return fmt.Errorf("enroll: write %s: %w", tmp, err)
	}
	if err := os.Rename(tmp, path); err != nil {
		return fmt.Errorf("enroll: rename %s to %s: %w", tmp, path, err)
	}
	return nil
}

// IsEnrolled reports whether MarkEnrolled has ever succeeded for stateDir.
// Any reason the marker can't be confirmed present (missing, unreadable, a
// directory where a file should be) reads as false rather than propagating
// an error: the safe default is to run Run and let the server confirm again,
// never to skip it on a guess.
func IsEnrolled(stateDir string) bool {
	_, err := os.Stat(filepath.Join(stateDir, enrolledFilename))
	return err == nil
}

// ClearEnrolled removes the marker, so the next daemon start calls Run again
// instead of skipping it.
//
// Nothing in this tree calls it yet — it exists for a later phase of this
// same effort: when a live link's hello.ack comes back
// accepted:false/reason:"unknown_device" (the server no longer has a row for
// this device — deleted, or a restored-from-backup database), the agent is
// expected to clear this marker so the next restart falls back to Run and
// the device reappears in the operator's approval queue, instead of a link
// loop that retries forever against a server that will never accept it
// again.
func ClearEnrolled(stateDir string) error {
	path := filepath.Join(stateDir, enrolledFilename)
	if err := os.Remove(path); err != nil && !errors.Is(err, os.ErrNotExist) {
		return fmt.Errorf("enroll: remove %s: %w", path, err)
	}
	return nil
}
