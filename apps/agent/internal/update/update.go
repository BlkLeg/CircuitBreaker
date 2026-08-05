// apps/agent/internal/update/update.go
package update

import (
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"time"

	"circuitbreaker.dev/cb-agent/internal/config"
	"circuitbreaker.dev/cb-agent/internal/tlsdial"
)

type Instruction struct {
	Version string `json:"version"`
	SHA256  string `json:"sha256"`
	Arch    string `json:"arch"`
	OS      string `json:"os"`
}

const markerFilename = "update_pending"

// markerPhase distinguishes the two states a still-present rollback marker
// can be in when read back after an unplanned restart. Before this
// distinction existed, a marker's mere presence was treated as proof that
// targetPath+".previous" was *this* update's actual backup — true only
// because, pre-Task-25, the marker was written after Swap succeeded. Task 25
// correctly moved WriteMarker to run before Swap (so a crash between the two
// leaves a recoverable "nothing happened yet" state instead of an unguarded
// replaced binary), but that reordering broke the old proof: a marker
// written just before a crash, with Swap never having run, would otherwise
// be indistinguishable from one written after a real Swap — and
// watchForRollback would "roll back" to whatever stale .previous happens to
// be lying around from some earlier, already-confirmed update. Two versions
// back. Silently.
//
//   - phasePendingSwap: WriteMarker has run but Swap has not (yet) durably
//     completed for this marker's version. The target binary on disk is
//     untouched — there is nothing to roll back to, and .previous (if one
//     exists at all) belongs to an earlier, already-confirmed update, not
//     this one.
//   - phasePendingConfirm: Swap completed and MarkSwapped recorded that
//     fact — .previous is now guaranteed to be *this* update's actual
//     backup, so a rollback (if the update never confirms) is safe and
//     meaningful.
type markerPhase string

const (
	phasePendingSwap    markerPhase = "pending-swap"
	phasePendingConfirm markerPhase = "pending-confirm"
)

// rollbackReportFilename persists the version a rollback restored *away*
// from, across the re-exec that follows a rollback decision. The process
// that decides to roll back (main.go's 2-minute confirm-window goroutine)
// has no live /link connection to report over at that moment — that's
// exactly why it's rolling back — so it writes this marker instead, then
// re-execs into the restored (prior) binary. That fresh process starts
// through the normal daemon startup path, and once it reconnects, reports an
// `update.status` frame with phase "rolled_back" for the version named here,
// then clears it (see internal/link's ReportPendingUpdateOutcome/
// ClearPendingUpdateOutcome options and cmd/cb-agent/main.go's wiring).
const rollbackReportFilename = "rollback_report"

// downloadTimeout bounds the entire update-binary download (connect + TLS
// handshake + headers + body) via http.Client.Timeout — an update source
// that hangs mid-response must not wedge the agent's update goroutine
// indefinitely. A var, not a const, so tests can shrink it rather than
// waiting out the production value; mirrors internal/link's
// stabilityWindow/rekeyInterval pattern.
var downloadTimeout = 2 * time.Minute

// maxDownloadBytes caps the response body Download will accept, both via an
// upfront Content-Length check and (since a server can omit or lie about
// that header) by capping actual bytes copied regardless. A cb-agent binary
// is a few tens of MB; 256 MiB leaves generous headroom while still bounding
// memory/disk against a misconfigured or malicious source. A var, not a
// const, so tests can shrink it instead of writing hundreds of MB of dummy
// data.
var maxDownloadBytes int64 = 256 * 1024 * 1024

// Download fetches the update binary named by instr from cfg.ServerURL and
// writes it to a new temp file, returning its path. The request routes
// through tlsdial.NewTransport(cfg.TLSPin) — the same pinned-TLS/proxy
// policy used for the agent's enroll and link websocket connections —
// rather than a bare http.Get, so a self-signed/TOFU install's tls_pin is
// actually enforced for the download and not just the control connection.
func Download(cfg *config.Config, instr Instruction) (string, error) {
	url := fmt.Sprintf(
		"%s/api/v1/agents/binary/%s/%s/%s",
		strings.TrimRight(cfg.ServerURL, "/"), instr.Version, instr.OS, instr.Arch,
	)

	client := &http.Client{
		Transport: tlsdial.NewTransport(cfg.TLSPin),
		Timeout:   downloadTimeout,
	}
	resp, err := client.Get(url)
	if err != nil {
		return "", fmt.Errorf("update: download %s: %w", url, err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("update: download %s: status %d", url, resp.StatusCode)
	}
	if resp.ContentLength > maxDownloadBytes {
		return "", fmt.Errorf(
			"update: download %s: content-length %d exceeds limit %d bytes",
			url, resp.ContentLength, maxDownloadBytes,
		)
	}

	tmp, err := os.CreateTemp("", "cb-agent-update-*")
	if err != nil {
		return "", fmt.Errorf("update: create temp file: %w", err)
	}
	defer tmp.Close()

	// Read one byte past the limit so an over-limit response can be told
	// apart from one landing exactly at it, without trusting Content-Length
	// (checked above only as an early rejection when present and honest).
	n, err := io.Copy(tmp, io.LimitReader(resp.Body, maxDownloadBytes+1))
	if err != nil {
		os.Remove(tmp.Name())
		return "", fmt.Errorf("update: write temp file: %w", err)
	}
	if n > maxDownloadBytes {
		os.Remove(tmp.Name())
		return "", fmt.Errorf("update: download %s: response exceeded size limit %d bytes", url, maxDownloadBytes)
	}
	if err := tmp.Chmod(0o755); err != nil {
		os.Remove(tmp.Name())
		return "", fmt.Errorf("update: chmod temp file: %w", err)
	}
	return tmp.Name(), nil
}

func VerifySHA256(path, want string) error {
	f, err := os.Open(path)
	if err != nil {
		return fmt.Errorf("update: open %s: %w", path, err)
	}
	defer f.Close()

	h := sha256.New()
	if _, err := io.Copy(h, f); err != nil {
		return fmt.Errorf("update: hash %s: %w", path, err)
	}
	got := hex.EncodeToString(h.Sum(nil))
	if !constantTimeEqualHexFold(got, want) {
		return fmt.Errorf("update: sha256 mismatch: got %s, want %s", got, want)
	}
	return nil
}

// constantTimeEqualHexFold reports whether hex strings a and b represent the
// same bytes, comparing case-insensitively (want ultimately comes from a
// server-controlled update instruction, which may use either hex case) using
// crypto/subtle.ConstantTimeCompare rather than strings.EqualFold/== — so
// neither the result nor its timing depends on where the two values first
// diverge.
func constantTimeEqualHexFold(a, b string) bool {
	if len(a) != len(b) {
		return false
	}
	return subtle.ConstantTimeCompare([]byte(strings.ToLower(a)), []byte(strings.ToLower(b))) == 1
}

// moveFile renames src to dst, falling back to a copy+remove when the rename
// fails across a filesystem boundary (EXDEV) — expected in practice, since
// Download() writes into os.TempDir() while the install target usually
// lives on a different mount (e.g. /usr/local/bin).
func moveFile(src, dst string) error {
	if err := os.Rename(src, dst); err == nil {
		return nil
	}

	info, err := os.Stat(src)
	if err != nil {
		return fmt.Errorf("moveFile: stat %s: %w", src, err)
	}
	in, err := os.Open(src)
	if err != nil {
		return fmt.Errorf("moveFile: open %s: %w", src, err)
	}
	defer in.Close()

	out, err := os.OpenFile(dst, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, info.Mode())
	if err != nil {
		return fmt.Errorf("moveFile: create %s: %w", dst, err)
	}
	if _, err := io.Copy(out, in); err != nil {
		out.Close()
		os.Remove(dst)
		return fmt.Errorf("moveFile: copy %s -> %s: %w", src, dst, err)
	}
	// This is the production install path in practice — Download() writes
	// into os.TempDir() while the install target usually lives on a
	// different mount, so os.Rename above almost always fails with EXDEV and
	// lands here. Without an explicit Sync, dst's data may still be sitting
	// in the page cache when Close returns: Close flushes Go-side buffers,
	// not the kernel's, so a power loss right after a cross-mount swap could
	// leave dst truncated or partially written — and unlike the same-
	// filesystem rename path, there would be no way to detect or roll back
	// that damage, since the file at dst never becomes healthy at all.
	if err := out.Sync(); err != nil {
		out.Close()
		os.Remove(dst)
		return fmt.Errorf("moveFile: sync %s: %w", dst, err)
	}
	if err := out.Close(); err != nil {
		return fmt.Errorf("moveFile: close %s: %w", dst, err)
	}
	return os.Remove(src)
}

// fsyncFile opens path and fsyncs it, forcing its already-written contents
// out of the page cache and onto durable storage. Swap calls this on newPath
// (Download's temp file) before touching targetPath at all: the download
// itself finished and closed its file handle well before Swap ever runs (see
// onUpdate in cmd/cb-agent/main.go — Download, then VerifySHA256, then
// Swap), so without an explicit fsync here a crash immediately after the
// rename below could in principle expose a target file whose data was never
// actually durable, even though the rename that made it visible was itself
// atomic.
func fsyncFile(path string) error {
	f, err := os.Open(path)
	if err != nil {
		return fmt.Errorf("fsync %s: %w", path, err)
	}
	defer f.Close()
	if err := f.Sync(); err != nil {
		return fmt.Errorf("fsync %s: %w", path, err)
	}
	return nil
}

// fsyncDir best-effort fsyncs the directory containing path, so a preceding
// create/rename within it is durable across a crash rather than only
// eventually flushed by some unrelated later fsync. Errors are swallowed:
// some platforms/filesystems don't support fsync on a directory descriptor,
// and the property that matters most for crash-recovery correctness — a
// rename being atomic, so a reader never observes a half-written file — does
// not depend on this succeeding.
func fsyncDir(path string) {
	dir, err := os.Open(filepath.Dir(path))
	if err != nil {
		return
	}
	defer dir.Close()
	_ = dir.Sync()
}

// atomicWriteFile writes data to a temp file alongside path, fsyncs it, then
// renames it into place — so any reader (including a process that crashes
// and restarts) only ever observes path either fully absent or fully
// containing data, never a partial write. Used for the rollback marker
// (WriteMarker): its ordering relative to the binary swap it guards is the
// core correctness property this exists for (see WriteMarker's doc
// comment), and that ordering is only meaningful if the write itself can't
// land half-finished.
func atomicWriteFile(path string, data []byte, mode os.FileMode) error {
	dir := filepath.Dir(path)
	tmp, err := os.CreateTemp(dir, ".tmp-"+filepath.Base(path)+"-*")
	if err != nil {
		return fmt.Errorf("atomic write %s: create temp file: %w", path, err)
	}
	tmpPath := tmp.Name()
	renamed := false
	defer func() {
		if !renamed {
			os.Remove(tmpPath)
		}
	}()

	if _, err := tmp.Write(data); err != nil {
		tmp.Close()
		return fmt.Errorf("atomic write %s: write temp file: %w", path, err)
	}
	if err := tmp.Chmod(mode); err != nil {
		tmp.Close()
		return fmt.Errorf("atomic write %s: chmod temp file: %w", path, err)
	}
	if err := tmp.Sync(); err != nil {
		tmp.Close()
		return fmt.Errorf("atomic write %s: sync temp file: %w", path, err)
	}
	if err := tmp.Close(); err != nil {
		return fmt.Errorf("atomic write %s: close temp file: %w", path, err)
	}
	if err := os.Rename(tmpPath, path); err != nil {
		return fmt.Errorf("atomic write %s: rename into place: %w", path, err)
	}
	renamed = true
	fsyncDir(path)
	return nil
}

// Swap fsyncs newPath (see fsyncFile), backs up targetPath to
// targetPath+".previous", moves newPath into targetPath, then restores
// targetPath's original file mode and ownership — so an in-place
// self-update doesn't silently widen or reassign permissions a deployment
// set deliberately, since Download's temp file always lands at a fixed
// 0o755 owned by whichever user this process runs as. Returns the backup
// path for Rollback. The backup is left in place for the caller to retain
// until the update is confirmed (a successful post-update hello.ack, per
// Task 4's OnConnected — see cmd/cb-agent/main.go's onConnected/
// watchForRollback) — Swap itself never removes it.
//
// Mode/ownership restoration happens after the file is already installed at
// targetPath and is deliberately best-effort (see preserveModeAndOwnership):
// by that point the swap itself has already durably succeeded (moveFile
// returned nil), and failing Swap's own return here would tell the caller
// the swap didn't happen when it did — leaving them to, e.g., clear a
// rollback marker for a binary that in fact now needs one.
func Swap(newPath, targetPath string) (string, error) {
	if err := fsyncFile(newPath); err != nil {
		return "", fmt.Errorf("update: sync new binary: %w", err)
	}

	origInfo, err := os.Stat(targetPath)
	if err != nil {
		return "", fmt.Errorf("update: stat current binary: %w", err)
	}

	backupPath := targetPath + ".previous"
	if err := os.Rename(targetPath, backupPath); err != nil {
		return "", fmt.Errorf("update: back up current binary: %w", err)
	}
	if err := moveFile(newPath, targetPath); err != nil {
		os.Rename(backupPath, targetPath) // best-effort restore
		return "", fmt.Errorf("update: install new binary: %w", err)
	}
	preserveModeAndOwnership(targetPath, origInfo)
	fsyncDir(targetPath)
	return backupPath, nil
}

// preserveModeAndOwnership best-effort restores path's mode and owning
// uid/gid to match origInfo (the pre-swap target binary's own stat, captured
// by Swap before it renamed anything). Both are applied on a fresh-off-
// moveFile file already installed at path, in the ordinary case as the same
// user that owned it before — chmod to that same user's own file, and chown
// to the uid/gid it's already running as, both routinely succeed. A failure
// here (e.g. a chown genuinely requiring root when running unprivileged
// against a binary owned by a different user) does not fail Swap, whose
// caller cannot un-happen an install that has, in fact, already happened.
func preserveModeAndOwnership(path string, origInfo os.FileInfo) {
	_ = os.Chmod(path, origInfo.Mode().Perm())

	stat, ok := origInfo.Sys().(*syscall.Stat_t)
	if !ok {
		// Not a platform where ownership is statable this way — this daemon
		// targets linux amd64/arm64 only, so in practice this never
		// triggers outside a non-Unix test build.
		return
	}
	_ = os.Chown(path, int(stat.Uid), int(stat.Gid))
}

func Rollback(targetPath string) error {
	backupPath := targetPath + ".previous"
	if err := os.Rename(backupPath, targetPath); err != nil {
		return fmt.Errorf("update: rollback: %w", err)
	}
	return nil
}

// WriteMarker durably records that targetVersion is pending confirmation via
// atomicWriteFile — a torn write here would be worse than useless, since the
// whole point of the marker is that it's trustworthy after an unplanned
// restart. Callers (cmd/cb-agent/main.go's onUpdate) must call this *before*
// executing the binary swap it guards, not after: if a crash lands between
// WriteMarker and the swap, the marker still correctly names the version
// that was *about to be* installed, and ReadMarker on restart finds a
// consistent, recoverable state (no swap happened, so there's nothing to
// roll back — the target binary is simply still the old one). The reverse
// ordering (swap first, marker after) would instead let a crash in that
// window leave a replaced binary running with no marker at all — no
// rollback safety net for an update that never got a chance to confirm.
//
// The marker written here starts in phasePendingSwap — see MarkSwapped,
// which callers must invoke once Swap actually succeeds, and markerPhase's
// doc comment for why that second write matters.
func WriteMarker(stateDir, targetVersion string) error {
	return writeMarkerPhase(stateDir, phasePendingSwap, targetVersion)
}

// MarkSwapped durably transitions an already-written marker from
// phasePendingSwap to phasePendingConfirm. Callers (cmd/cb-agent/main.go's
// onUpdate) must call this immediately after Swap returns successfully,
// before re-exec — it is what lets a subsequent restart's ReadMarker tell a
// genuinely fresh backup (this update's own .previous, safe to roll back to)
// apart from a stale one left over from some earlier, already-confirmed
// update (unsafe — see markerPhase's doc comment for the downgrade this
// prevents).
//
// If this write itself fails, the swap has already durably happened
// (Swap returned nil) and cannot be undone from here; the marker is simply
// left in phasePendingSwap, which means a restart before confirmation will
// treat this update as abandoned rather than arming a rollback for it. That
// forfeits this particular update's rollback safety net but is not a
// correctness violation — the currently-running binary is, in fact, the new
// one — so callers should log the failure and proceed rather than trying to
// fail the update outright.
func MarkSwapped(stateDir, targetVersion string) error {
	return writeMarkerPhase(stateDir, phasePendingConfirm, targetVersion)
}

// writeMarkerPhase encodes phase and targetVersion into the marker file as
// "<phase>\n<targetVersion>" and writes it via atomicWriteFile.
func writeMarkerPhase(stateDir string, phase markerPhase, targetVersion string) error {
	data := []byte(string(phase) + "\n" + targetVersion)
	if err := atomicWriteFile(filepath.Join(stateDir, markerFilename), data, 0o600); err != nil {
		return fmt.Errorf("update: write marker: %w", err)
	}
	return nil
}

// ReadMarker reads back a marker written by WriteMarker/MarkSwapped.
// version is the target version the marker names. swapped reports whether
// Swap has durably completed for that version (i.e. the marker is in
// phasePendingConfirm, written by MarkSwapped) — callers must treat
// swapped == false as "nothing to roll back", even though a stale .previous
// from an earlier, already-confirmed update may still be sitting on disk
// (see markerPhase's doc comment). present is false with a nil error when no
// marker exists at all.
func ReadMarker(stateDir string) (version string, swapped bool, present bool, err error) {
	data, err := os.ReadFile(filepath.Join(stateDir, markerFilename))
	if os.IsNotExist(err) {
		return "", false, false, nil
	}
	if err != nil {
		return "", false, false, fmt.Errorf("update: read marker: %w", err)
	}
	phase, rest, ok := strings.Cut(string(data), "\n")
	if !ok {
		// Not a format this package's own writers ever produce. Treat
		// defensively as an unconfirmed swap rather than risking a rollback
		// against a .previous this marker can't actually vouch for.
		return string(data), false, true, nil
	}
	return rest, markerPhase(phase) == phasePendingConfirm, true, nil
}

func ClearMarker(stateDir string) error {
	err := os.Remove(filepath.Join(stateDir, markerFilename))
	if err != nil && !os.IsNotExist(err) {
		return fmt.Errorf("update: clear marker: %w", err)
	}
	return nil
}

// WriteRollbackReport persists failedVersion — the target version a rollback
// just restored away from — so the next process (already re-exec'd back to
// the prior binary) can report it once reconnected. See
// rollbackReportFilename's doc comment for the full lifecycle.
func WriteRollbackReport(stateDir, failedVersion string) error {
	return os.WriteFile(filepath.Join(stateDir, rollbackReportFilename), []byte(failedVersion), 0o600)
}

// ReadRollbackReport mirrors ReadMarker: ok is false with a nil error when no
// report is pending (the common case — most connections never rolled back).
func ReadRollbackReport(stateDir string) (string, bool, error) {
	data, err := os.ReadFile(filepath.Join(stateDir, rollbackReportFilename))
	if os.IsNotExist(err) {
		return "", false, nil
	}
	if err != nil {
		return "", false, fmt.Errorf("update: read rollback report: %w", err)
	}
	return string(data), true, nil
}

// ClearRollbackReport mirrors ClearMarker: removing an already-absent report
// is not an error, so a caller can call this unconditionally after a
// successful report-send.
func ClearRollbackReport(stateDir string) error {
	err := os.Remove(filepath.Join(stateDir, rollbackReportFilename))
	if err != nil && !os.IsNotExist(err) {
		return fmt.Errorf("update: clear rollback report: %w", err)
	}
	return nil
}
