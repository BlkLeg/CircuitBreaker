// apps/agent/internal/update/update.go
package update

import (
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
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
// the marker's recorded backup was *this* update's actual prior version —
// true only because, pre-Task-25, the marker was written after Swap
// succeeded. Task 25 correctly moved WriteMarker to run before Swap (so a
// crash between the two leaves a recoverable "nothing happened yet" state
// instead of an unguarded replaced binary), but that reordering broke the
// old proof: a marker written just before a crash, with Swap never having
// run, would otherwise be indistinguishable from one written after a real
// Swap — and watchForRollback would "roll back" current to whatever stale
// version directory happens to be lying around from some earlier,
// already-confirmed update. Two versions back. Silently.
//
//   - phasePendingSwap: WriteMarker has run but Swap has not (yet) durably
//     completed for this marker's version. current is untouched and no
//     prevVersionDir has been recorded yet — there is nothing to roll back
//     to.
//   - phasePendingConfirm: Swap completed and MarkSwapped recorded
//     prevVersionDir — that directory is now guaranteed to be *this*
//     update's actual prior version, so a rollback (if the update never
//     confirms) is safe and meaningful.
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

// CurrentLinkPath returns the path of the "current" symlink under stateDir
// that Swap/Rollback re-point — the middle link in the two-level indirection
// /usr/local/bin/cb-agent -> {stateDir}/current ->
// {stateDir}/versions/<version>/cb-agent (see
// specs/2026-08-05-cb-agent-self-update-fix-design.md). Exported so
// cmd/cb-agent/main.go builds the same path without duplicating the
// "current" literal.
func CurrentLinkPath(stateDir string) string {
	return filepath.Join(stateDir, "current")
}

// versionDir returns the path of a specific version's install directory
// under stateDir: {stateDir}/versions/<version>/.
func versionDir(stateDir, version string) string {
	return filepath.Join(stateDir, "versions", version)
}

// atomicSymlink re-points linkPath to target: create a new symlink at a
// temp name alongside linkPath, then os.Rename it over linkPath — an atomic
// same-filesystem rename (mirrors atomicWriteFile's temp-then-rename
// idiom), so a reader (including a process that crashes and restarts) only
// ever observes linkPath as either its old target or its new one, never
// briefly absent.
func atomicSymlink(linkPath, target string) error {
	dir := filepath.Dir(linkPath)
	tmp := filepath.Join(dir, fmt.Sprintf(".tmp-%s-%d", filepath.Base(linkPath), time.Now().UnixNano()))
	if err := os.Symlink(target, tmp); err != nil {
		return fmt.Errorf("atomic symlink %s: create temp symlink: %w", linkPath, err)
	}
	if err := os.Rename(tmp, linkPath); err != nil {
		os.Remove(tmp)
		return fmt.Errorf("atomic symlink %s: rename into place: %w", linkPath, err)
	}
	fsyncDir(linkPath)
	return nil
}

// resolveSymlinkAbs reads linkPath's target and, if it's relative, resolves
// it against linkPath's own directory (matching how the kernel resolves a
// relative symlink target) so callers always get an absolute path back.
// Returns ("", nil) if linkPath does not exist.
func resolveSymlinkAbs(linkPath string) (string, error) {
	target, err := os.Readlink(linkPath)
	if err != nil {
		if os.IsNotExist(err) {
			return "", nil
		}
		return "", err
	}
	if filepath.IsAbs(target) {
		return target, nil
	}
	return filepath.Join(filepath.Dir(linkPath), target), nil
}

// Swap fsyncs newBinaryPath (see fsyncFile), moves it into
// {stateDir}/versions/<version>/cb-agent (immutable once written), then
// atomically re-points {stateDir}/current to that new version directory —
// so self-update never touches anything outside stateDir, which is already
// writable by the unprivileged cb-agent user running this process (see
// specs/2026-08-05-cb-agent-self-update-fix-design.md — this replaces the
// old in-place rename at a root-owned /usr/local/bin/cb-agent, which that
// user could never actually perform). Returns the version directory
// current pointed to *before* the swap, so a later Rollback knows where to
// point back to; empty if current did not exist yet (never happens against
// a real install, whose install script always creates it — see
// agent_install.py — but tolerated so tests can exercise a first-ever swap
// without seeding one).
func Swap(newBinaryPath, version, stateDir string) (prevVersionDir string, err error) {
	// version ultimately comes from a server-controlled update instruction
	// (internal/update.Instruction) and is used directly as a path
	// component below (versionDir). Reject anything that isn't a single
	// path segment before it ever reaches a filesystem call — a version
	// like "../../etc" must never let a compromised or malicious update
	// source write outside stateDir/versions.
	if version == "" || version == "." || version == ".." || version != filepath.Base(version) {
		return "", fmt.Errorf("update: invalid version %q", version)
	}

	if err := fsyncFile(newBinaryPath); err != nil {
		return "", fmt.Errorf("update: sync new binary: %w", err)
	}

	newVersionDir := versionDir(stateDir, version)
	if err := os.MkdirAll(newVersionDir, 0o755); err != nil {
		return "", fmt.Errorf("update: create version dir %s: %w", newVersionDir, err)
	}
	newBinaryTarget := filepath.Join(newVersionDir, "cb-agent")
	if err := moveFile(newBinaryPath, newBinaryTarget); err != nil {
		return "", fmt.Errorf("update: install new binary: %w", err)
	}
	if err := os.Chmod(newBinaryTarget, 0o755); err != nil {
		return "", fmt.Errorf("update: chmod new binary: %w", err)
	}
	fsyncDir(newBinaryTarget)

	currentLink := CurrentLinkPath(stateDir)
	prevTarget, err := resolveSymlinkAbs(currentLink)
	if err != nil {
		return "", fmt.Errorf("update: read current symlink: %w", err)
	}
	// prevTarget is a file path (or empty if current didn't exist); extract its directory
	if prevTarget != "" {
		prevVersionDir = filepath.Dir(prevTarget)
	}

	if err := atomicSymlink(currentLink, newBinaryTarget); err != nil {
		return "", fmt.Errorf("update: re-point current: %w", err)
	}
	return prevVersionDir, nil
}

// PruneVersions removes every {stateDir}/versions/<v> directory except
// currentLink's live target and keepVersionDir (the version an update was
// just confirmed away from) — called once an update confirms (a
// post-update hello.ack arrives; see cmd/cb-agent/main.go's onConnected),
// mirroring the single-".previous"-backup retention the old scheme kept.
// keepVersionDir may be "" (nothing to additionally retain beyond
// current). Best-effort: a failure removing one stale version directory is
// collected and returned, but does not stop pruning from attempting the
// rest.
func PruneVersions(stateDir, currentLink, keepVersionDir string) error {
	liveFile, err := resolveSymlinkAbs(currentLink)
	if err != nil {
		return fmt.Errorf("update: prune versions: read current symlink: %w", err)
	}
	// liveFile is a file path (or empty if current didn't exist); extract its directory
	var liveDir string
	if liveFile != "" {
		liveDir = filepath.Dir(liveFile)
	}
	if liveDir == "" {
		// current is missing or unreadable — refuse to prune rather than
		// treating "nothing is live" as "nothing is protected": with
		// liveDir == "", every entry below would fail the dir == liveDir
		// check and (absent keepVersionDir matching it) get removed,
		// including the version this process may currently be running
		// through. This should never happen in practice (a connected
		// daemon just re-exec'd through current), but the failure mode if
		// it ever did — deleting the whole versions/ tree — is severe
		// enough to guard against explicitly.
		return nil
	}

	versionsRoot := filepath.Join(stateDir, "versions")
	entries, err := os.ReadDir(versionsRoot)
	if err != nil {
		if os.IsNotExist(err) {
			return nil
		}
		return fmt.Errorf("update: prune versions: read %s: %w", versionsRoot, err)
	}

	var errs []error
	for _, entry := range entries {
		dir := filepath.Join(versionsRoot, entry.Name())
		if dir == liveDir || dir == keepVersionDir {
			continue
		}
		if err := os.RemoveAll(dir); err != nil {
			errs = append(errs, fmt.Errorf("remove %s: %w", dir, err))
		}
	}
	if len(errs) > 0 {
		return fmt.Errorf("update: prune versions: %d failure(s): %w", len(errs), errors.Join(errs...))
	}
	return nil
}

// Rollback re-points currentLink back to prevVersionDir — the inverse of
// Swap, used when a post-update hello.ack never arrives within
// rollbackWindow (see cmd/cb-agent/main.go's watchForRollback).
// prevVersionDir must be non-empty (the caller's ReadMarker/Swap call
// recorded it) — an empty value means there is nothing to roll back to,
// which is a caller bug, not a recoverable runtime condition.
func Rollback(currentLink, prevVersionDir string) error {
	if prevVersionDir == "" {
		return fmt.Errorf("update: rollback: no previous version recorded")
	}
	prevBinaryPath := filepath.Join(prevVersionDir, "cb-agent")
	if err := atomicSymlink(currentLink, prevBinaryPath); err != nil {
		return fmt.Errorf("update: rollback: %w", err)
	}
	return nil
}

// WriteMarker durably records that targetVersion is pending confirmation via
// atomicWriteFile — a torn write here would be worse than useless, since the
// whole point of the marker is that it's trustworthy after an unplanned
// restart. Callers (cmd/cb-agent/main.go's onUpdate) must call this *before*
// executing the binary swap it guards, not after: if a crash lands between
// WriteMarker and Swap, the marker still correctly names the version that
// was *about to be* installed, and ReadMarker on restart finds a
// consistent, recoverable state (Swap never ran, so current is untouched —
// there's nothing to roll back).
//
// The marker written here starts in phasePendingSwap with no previous
// version recorded yet (Swap hasn't run, so there's nothing to record) —
// see MarkSwapped, which callers must invoke once Swap actually succeeds.
func WriteMarker(stateDir, targetVersion string) error {
	return writeMarkerPhase(stateDir, phasePendingSwap, targetVersion, "", time.Time{})
}

// MarkSwapped durably transitions an already-written marker from
// phasePendingSwap to phasePendingConfirm, recording prevVersionDir (Swap's
// return value) so a later Rollback or PruneVersions knows which version
// directory to act on. Callers (cmd/cb-agent/main.go's onUpdate) must call
// this immediately after Swap returns successfully, before re-exec.
//
// If this write itself fails, the swap has already durably happened and
// cannot be undone from here; the marker is simply left in
// phasePendingSwap, which forfeits this update's rollback safety net (a
// restart before confirmation will treat it as abandoned) but is not a
// correctness violation — callers should log the failure and proceed
// rather than failing the update outright.
func MarkSwapped(stateDir, targetVersion, prevVersionDir string, deadline time.Time) error {
	return writeMarkerPhase(stateDir, phasePendingConfirm, targetVersion, prevVersionDir, deadline)
}

// writeMarkerPhase encodes phase, targetVersion, prevVersionDir and deadline
// into the marker file as
// "<phase>\n<targetVersion>\n<prevVersionDir>\n<deadline>" and writes it via
// atomicWriteFile. prevVersionDir is "" for phasePendingSwap, and deadline is
// the zero time for every phase except phasePendingConfirm — there is nothing
// to roll back until Swap has run, so an unswapped marker has no window to
// expire. A zero deadline encodes as an empty fourth field, which is also
// exactly what a marker written by an older agent build looks like; see
// RollbackIfExpired for why that is deliberately inert rather than expired.
func writeMarkerPhase(stateDir string, phase markerPhase, targetVersion, prevVersionDir string, deadline time.Time) error {
	encodedDeadline := ""
	if !deadline.IsZero() {
		encodedDeadline = deadline.UTC().Format(time.RFC3339Nano)
	}
	data := []byte(string(phase) + "\n" + targetVersion + "\n" + prevVersionDir + "\n" + encodedDeadline)
	if err := atomicWriteFile(filepath.Join(stateDir, markerFilename), data, 0o600); err != nil {
		return fmt.Errorf("update: write marker: %w", err)
	}
	return nil
}

// ReadMarker reads back a marker written by WriteMarker/MarkSwapped.
// version is the target version the marker names; prevVersionDir is the
// version directory current pointed to before this update's Swap ran,
// meaningful only when swapped == true — it's Rollback's second argument.
// swapped reports whether Swap has durably completed for that version
// (i.e. the marker is in phasePendingConfirm, written by MarkSwapped) —
// callers must treat swapped == false as "nothing to roll back". present is
// false with a nil error when no marker exists at all.
func ReadMarker(stateDir string) (version, prevVersionDir string, swapped, present bool, err error) {
	m, present, err := readMarker(stateDir)
	if err != nil || !present {
		return "", "", false, false, err
	}
	return m.version, m.prevVersionDir, m.phase == phasePendingConfirm, true, nil
}

// marker is the parsed form of the on-disk marker file. ReadMarker remains the
// public accessor for the four fields every pre-existing caller needs; this
// exists so RollbackIfExpired can also see the deadline without a second read
// of the same file (and without growing ReadMarker a sixth return value).
type marker struct {
	phase          markerPhase
	version        string
	prevVersionDir string
	// deadline is the instant after which an unconfirmed update is to be
	// rolled back. Zero means "not recorded" — either the marker has not
	// reached phasePendingConfirm, or it was written by an agent build that
	// predates deadline stamping.
	deadline time.Time
}

func readMarker(stateDir string) (m marker, present bool, err error) {
	data, err := os.ReadFile(filepath.Join(stateDir, markerFilename))
	if os.IsNotExist(err) {
		return marker{}, false, nil
	}
	if err != nil {
		return marker{}, false, fmt.Errorf("update: read marker: %w", err)
	}
	phase, rest, ok := strings.Cut(string(data), "\n")
	if !ok {
		return marker{}, false, fmt.Errorf("update: malformed marker: missing phase separator")
	}
	m.phase = markerPhase(phase)
	m.version, rest, _ = strings.Cut(rest, "\n")
	// A marker written before the deadline field existed has no third
	// separator at all, so prevVersionDir is simply the remainder.
	m.prevVersionDir, rest, _ = strings.Cut(rest, "\n")
	if rest != "" {
		// A deadline that cannot be parsed is treated exactly like an absent
		// one: inert. The alternative — failing the whole read — would take
		// the daemon's startup down over a field that only ever makes the
		// rollback safety net *more* available.
		if deadline, parseErr := time.Parse(time.RFC3339Nano, rest); parseErr == nil {
			m.deadline = deadline
		}
	}
	return m, true, nil
}

// RollbackIfExpired restores the previous binary when the marker on disk names
// an update that was durably swapped in but never confirmed before its
// deadline, and reports the version it rolled back away from ("" when it did
// nothing).
//
// This exists because the in-process rollback window (cmd/cb-agent's
// watchForRollback) cannot cover the failure it matters most for. That
// goroutine is spawned only after runDaemon's unconditional enroll.Run
// succeeds, and an enrollment failure is fatal — so an update that leaves the
// agent unable to reach the server at all kills the process long before the
// window elapses, and does so again on every restart. Evaluating a durable
// deadline from disk, before any network call, is what makes a crash-looping
// agent converge on a rollback instead of looping forever on a broken build.
//
// The two watchForRollback rules that still apply here apply for the same
// reasons: an unswapped marker has nothing to roll back (current was never
// re-pointed, and its recorded prevVersionDir, if any, belongs to some earlier
// already-confirmed update), and a failed Rollback still clears the marker so
// the same doomed attempt is not re-armed on every subsequent start.
//
// A marker with no deadline is deliberately inert rather than expired: it was
// written by an older agent build, its update may well be healthy and
// in-flight, and watchForRollback remains its judge.
func RollbackIfExpired(stateDir, currentLink string, now time.Time) (rolledBackFrom string, err error) {
	m, present, err := readMarker(stateDir)
	if err != nil || !present {
		return "", err
	}
	if m.phase != phasePendingConfirm || m.deadline.IsZero() || now.Before(m.deadline) {
		return "", nil
	}
	if err := Rollback(currentLink, m.prevVersionDir); err != nil {
		if clearErr := ClearMarker(stateDir); clearErr != nil {
			return "", errors.Join(err, clearErr)
		}
		return "", err
	}
	// This process has no live /link connection to report over — that is
	// exactly why it is rolling back — so the rollback is persisted for the
	// re-exec'd process to send once it reconnects.
	if err := WriteRollbackReport(stateDir, m.version); err != nil {
		return "", err
	}
	if err := ClearMarker(stateDir); err != nil {
		return "", err
	}
	return m.version, nil
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
