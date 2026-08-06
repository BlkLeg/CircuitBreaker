// apps/agent/cmd/cb-agent/main_test.go
package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"reflect"
	"sort"
	"strings"
	"syscall"
	"testing"
	"time"

	"circuitbreaker.dev/cb-agent/internal/capability"
	"circuitbreaker.dev/cb-agent/internal/collect"
	hostcollect "circuitbreaker.dev/cb-agent/internal/collect/host"
	"circuitbreaker.dev/cb-agent/internal/config"
	"circuitbreaker.dev/cb-agent/internal/enroll"
	"circuitbreaker.dev/cb-agent/internal/frame"
	"circuitbreaker.dev/cb-agent/internal/spool"
	"circuitbreaker.dev/cb-agent/internal/status"
	"circuitbreaker.dev/cb-agent/internal/update"
)

// TestPrintVersion covers the Task 20 bug fix directly: `cb-agent version`
// must never generate a device key as a side effect, and must only print a
// fingerprint line when one already exists.
func TestPrintVersion(t *testing.T) {
	tests := []struct {
		name            string
		seedDeviceKey   bool
		wantFingerprint bool
	}{
		{name: "no identity yet — no fingerprint line, no key created", seedDeviceKey: false, wantFingerprint: false},
		{name: "identity exists — fingerprint line printed", seedDeviceKey: true, wantFingerprint: true},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			dir := t.TempDir()
			var wantKey *enroll.DeviceKey
			if tt.seedDeviceKey {
				k, err := enroll.LoadOrCreateDeviceKey(dir)
				if err != nil {
					t.Fatalf("seed LoadOrCreateDeviceKey() error = %v", err)
				}
				wantKey = k
			}

			var buf bytes.Buffer
			if err := printVersion(&buf, dir, "1.2.3-test"); err != nil {
				t.Fatalf("printVersion() error = %v", err)
			}
			out := buf.String()

			if !strings.Contains(out, "cb-agent 1.2.3-test") {
				t.Errorf("output = %q, want it to contain the version line", out)
			}

			hasFingerprint := strings.Contains(out, "fingerprint:")
			if hasFingerprint != tt.wantFingerprint {
				t.Errorf("output contains a fingerprint line = %v, want %v (output: %q)", hasFingerprint, tt.wantFingerprint, out)
			}
			if tt.wantFingerprint && !strings.Contains(out, wantKey.FingerprintGrouped()) {
				t.Errorf("output = %q, want it to contain %q", out, wantKey.FingerprintGrouped())
			}

			// The critical regression check: printVersion must never create
			// device.key when it didn't already exist.
			_, err := os.Stat(filepath.Join(dir, "device.key"))
			keyNowExists := err == nil
			if keyNowExists != tt.seedDeviceKey {
				t.Errorf("device.key exists after printVersion = %v, want %v (printVersion must not create identity as a side effect)",
					keyNowExists, tt.seedDeviceKey)
			}
		})
	}
}

// TestPrintStatus_NoFileYet covers the other Task 20 bug-fix requirement:
// `cb-agent status` must not generate a device key (or anything else) when
// no runtime status file exists yet.
func TestPrintStatus_NoFileYet(t *testing.T) {
	dir := t.TempDir()

	var buf bytes.Buffer
	if err := printStatus(&buf, dir); err != nil {
		t.Fatalf("printStatus() error = %v", err)
	}

	out := buf.String()
	if !strings.Contains(out, "no status recorded yet") {
		t.Errorf("output = %q, want a truthful \"no status recorded yet\" message", out)
	}

	if _, err := os.Stat(filepath.Join(dir, "device.key")); !os.IsNotExist(err) {
		t.Errorf("printStatus created device.key as a side effect (stat err = %v), want no file", err)
	}
}

// TestPrintStatus_ReflectsWriterState drives the same status.Writer the
// daemon uses through a table of realistic states and asserts printStatus's
// output reflects each field truthfully — this is the "status reflects a
// running daemon's real state read from the file" requirement.
func TestPrintStatus_ReflectsWriterState(t *testing.T) {
	tests := []struct {
		name    string
		mutate  func(w *status.Writer) error
		wantAll []string // substrings that must all appear in the output
		wantNot []string // substrings that must NOT appear
	}{
		{
			name: "accepted link with grants and readiness",
			mutate: func(w *status.Writer) error {
				if err := w.SetGrants(map[string]bool{"host_telemetry": true, "remote_probe": false}); err != nil {
					return err
				}
				if err := w.MergeReadiness([]frame.Readiness{{Collector: "agent.identity", State: "ready"}}); err != nil {
					return err
				}
				return w.SetAccepted()
			},
			wantAll: []string{
				"link: accepted",
				"host_telemetry: true",
				"remote_probe: false",
				"readiness: agent.identity = ready",
				"spool: depth=0 bytes=0",
				"last connected:",
			},
			wantNot: []string{"last error:"},
		},
		{
			name:   "rejected link records the reason as the last error",
			mutate: func(w *status.Writer) error { return w.SetRejected("device_pk_mismatch") },
			wantAll: []string{
				"link: rejected",
				"last error: device_pk_mismatch",
				"grants: none",
				"readiness: none reported",
			},
			wantNot: []string{"last connected:"},
		},
		{
			name:   "disconnected with a cause records the last error",
			mutate: func(w *status.Writer) error { return w.SetDisconnected(errors.New("connection lost")) },
			wantAll: []string{
				"link: disconnected",
				"last error: connection lost",
			},
		},
		{
			name:   "spool statistics",
			mutate: func(w *status.Writer) error { return w.SetSpoolStats(7, 12345) },
			wantAll: []string{
				"spool: depth=7 bytes=12345",
			},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			dir := t.TempDir()
			w := status.NewWriter(dir, "9.9.9", "abcd-ef01-2345-6789-abcd-ef01-2345-6789")
			if err := tt.mutate(w); err != nil {
				t.Fatalf("mutate() error = %v", err)
			}

			var buf bytes.Buffer
			if err := printStatus(&buf, dir); err != nil {
				t.Fatalf("printStatus() error = %v", err)
			}
			out := buf.String()

			if !strings.Contains(out, "version: 9.9.9") {
				t.Errorf("output = %q, want the version line", out)
			}
			if !strings.Contains(out, "fingerprint: abcd-ef01-2345-6789-abcd-ef01-2345-6789") {
				t.Errorf("output = %q, want the fingerprint line", out)
			}
			for _, want := range tt.wantAll {
				if !strings.Contains(out, want) {
					t.Errorf("output = %q, want it to contain %q", out, want)
				}
			}
			for _, notWant := range tt.wantNot {
				if strings.Contains(out, notWant) {
					t.Errorf("output = %q, want it to NOT contain %q", out, notWant)
				}
			}
		})
	}
}

// TestPrintStatus_ReadError surfaces a corrupt status file as an error
// rather than silently reporting an empty/default status.
func TestPrintStatus_ReadError(t *testing.T) {
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "status.json"), []byte("not json"), 0o600); err != nil {
		t.Fatalf("write fixture: %v", err)
	}

	var buf bytes.Buffer
	if err := printStatus(&buf, dir); err == nil {
		t.Error("printStatus() error = nil, want an error for a corrupt status.json")
	}
}

// TestOpenSpool_RecoversAfterUncleanShutdownAndReportsStats is this task's
// daemon-startup verification that the spool's existing recovery logic
// (spool.Open's load()) is actually invoked at daemon startup, and that the
// recovered backlog gets surfaced into the runtime status file `cb-agent
// status` reads (spec: "Recover valid segments after an unclean shutdown").
// It uses a fake, test-only frame type — no real Slice 1 data frame type
// exists to populate a backlog with (Global Constraints).
func TestOpenSpool_RecoversAfterUncleanShutdownAndReportsStats(t *testing.T) {
	dir := t.TempDir()

	// Simulate a prior daemon run that spooled two data frames and then
	// crashed (no clean shutdown) — spool.Enqueue persists on every call, so
	// the on-disk queue already reflects this without an explicit close.
	prior, err := spool.Open(dir, spool.DefaultCapBytes)
	if err != nil {
		t.Fatalf("spool.Open() error = %v", err)
	}
	fakeFrame := func(seq uint64) frame.Frame {
		return frame.Frame{V: 1, Type: "test.fakedata", Seq: seq, Payload: []byte(`{}`)}
	}
	if err := prior.Enqueue(fakeFrame(1)); err != nil {
		t.Fatalf("Enqueue() error = %v", err)
	}
	if err := prior.Enqueue(fakeFrame(2)); err != nil {
		t.Fatalf("Enqueue() error = %v", err)
	}

	statusWriter := status.NewWriter(dir, "0.1.0-test", "AB:CD")
	sp, err := openSpool(&config.Config{}, dir, statusWriter)
	if err != nil {
		t.Fatalf("openSpool() error = %v", err)
	}
	if got := sp.Len(); got != 2 {
		t.Errorf("openSpool() recovered Len() = %d, want 2", got)
	}

	st, ok, err := status.Read(dir)
	if err != nil || !ok {
		t.Fatalf("status.Read() = (%+v, %v, %v), want a persisted status file", st, ok, err)
	}
	if st.SpoolDepth != 2 {
		t.Errorf("status SpoolDepth = %d, want 2", st.SpoolDepth)
	}
	if st.SpoolBytes <= 0 {
		t.Errorf("status SpoolBytes = %d, want > 0", st.SpoolBytes)
	}
}

// TestOpenSpool_DefaultsCapWhenConfigZero verifies a Config left at its
// zero-valued SpoolCapBytes (no spool_cap_bytes in agent.toml) resolves to
// spool.DefaultCapBytes rather than leaving the spool capped at zero bytes.
// A real zero cap would evict every enqueued frame but the single most
// recent one on every call — this test would catch that regression by
// enqueueing more than one frame and expecting all of them to survive.
func TestOpenSpool_DefaultsCapWhenConfigZero(t *testing.T) {
	dir := t.TempDir()
	statusWriter := status.NewWriter(dir, "0.1.0-test", "AB:CD")

	sp, err := openSpool(&config.Config{SpoolCapBytes: 0}, dir, statusWriter)
	if err != nil {
		t.Fatalf("openSpool() error = %v", err)
	}
	for i := uint64(0); i < 3; i++ {
		f := frame.Frame{V: 1, Type: "test.fakedata", Seq: i, Payload: []byte(`{}`)}
		if err := sp.Enqueue(f); err != nil {
			t.Fatalf("Enqueue(%d) error = %v", i, err)
		}
	}
	if got := sp.Len(); got != 3 {
		t.Errorf("Len() = %d, want 3 — a zero cap (not defaulted) would have evicted down to 1", got)
	}
}

// --- Task 30: startup ownership/mode audit -------------------------------

// sensitiveAuditFiles mirrors the file classes auditStateDir enforces —
// identity (device.key), cached capability grant (grants.json), and runtime
// status (status.json) — so tests can drive all three from one table
// instead of triplicating each case.
var sensitiveAuditFiles = []string{"device.key", "grants.json", "status.json"}

// TestAuditStateDir_MissingStateDir covers the "never ran yet" case — no
// state directory exists at all. This is not an error: nothing has been
// created, so there is nothing to audit, and callers that need the
// directory to exist (enroll.LoadOrCreateDeviceKey et al.) create it
// themselves before auditStateDir ever runs in the real startup sequence.
func TestAuditStateDir_MissingStateDir(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "does-not-exist")
	if err := auditStateDir(dir, os.Geteuid(), os.Getegid()); err != nil {
		t.Errorf("auditStateDir() error = %v, want nil for a state dir that was never created", err)
	}
}

// TestAuditStateDir_MissingSensitiveFileIsNotError covers a fresh install
// that has an identity but has never received a capabilities.set frame
// (spec §4.2) — grants.json legitimately does not exist yet. Auditing must
// not treat an individual missing sensitive file as an error.
func TestAuditStateDir_MissingSensitiveFileIsNotError(t *testing.T) {
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "device.key"), []byte("x"), 0o600); err != nil {
		t.Fatalf("seed device.key: %v", err)
	}
	// grants.json and status.json deliberately absent.

	if err := auditStateDir(dir, os.Geteuid(), os.Getegid()); err != nil {
		t.Errorf("auditStateDir() error = %v, want nil when grants.json/status.json don't exist yet", err)
	}
}

// TestAuditStateDir_CorrectOwnershipAndModesPassSilently is the "well-formed
// install" baseline: every sensitive file already at 0600, owned by the
// user this process actually runs as. auditStateDir must return nil and
// must not touch any file (no unnecessary chmod).
func TestAuditStateDir_CorrectOwnershipAndModesPassSilently(t *testing.T) {
	dir := t.TempDir()
	for _, name := range sensitiveAuditFiles {
		if err := os.WriteFile(filepath.Join(dir, name), []byte("x"), 0o600); err != nil {
			t.Fatalf("seed %s: %v", name, err)
		}
	}

	if err := auditStateDir(dir, os.Geteuid(), os.Getegid()); err != nil {
		t.Errorf("auditStateDir() error = %v, want nil for correct ownership and mode", err)
	}

	for _, name := range sensitiveAuditFiles {
		path := filepath.Join(dir, name)
		info, err := os.Stat(path)
		if err != nil {
			t.Fatalf("stat %s: %v", path, err)
		}
		if got := info.Mode().Perm(); got != 0o600 {
			t.Errorf("%s mode = %04o after audit, want unchanged 0600", name, got)
		}
	}
}

// TestAuditStateDir_CorrectsWrongMode covers the actual gap this task
// closes: status.json's mode was only ever set at creation (Task 20) — this
// asserts every one of the three sensitive file classes gets its mode
// corrected back to 0600 at startup, not merely at creation, if it is ever
// found wider.
func TestAuditStateDir_CorrectsWrongMode(t *testing.T) {
	for _, name := range sensitiveAuditFiles {
		t.Run(name, func(t *testing.T) {
			dir := t.TempDir()
			path := filepath.Join(dir, name)
			if err := os.WriteFile(path, []byte("x"), 0o644); err != nil {
				t.Fatalf("seed %s: %v", name, err)
			}

			if err := auditStateDir(dir, os.Geteuid(), os.Getegid()); err != nil {
				t.Fatalf("auditStateDir() error = %v, want nil (mode drift is corrected, not fatal)", err)
			}

			info, err := os.Stat(path)
			if err != nil {
				t.Fatalf("stat %s: %v", path, err)
			}
			if got := info.Mode().Perm(); got != 0o600 {
				t.Errorf("%s mode after audit = %04o, want corrected to 0600", name, got)
			}
		})
	}
}

// TestAuditStateDir_OwnershipMismatchFailsLoudly covers the fail-loud path:
// when the state directory (and everything under it) isn't owned by the
// user the daemon is actually running as, auditStateDir must return an
// error rather than silently continuing — the caller in runDaemon turns
// this into a startup abort. It also asserts nothing gets chmod'd once
// ownership has already failed: a daemon that's about to refuse to start
// has no business mutating files it may not trust.
func TestAuditStateDir_OwnershipMismatchFailsLoudly(t *testing.T) {
	dir := t.TempDir()
	for _, name := range sensitiveAuditFiles {
		if err := os.WriteFile(filepath.Join(dir, name), []byte("x"), 0o644); err != nil {
			t.Fatalf("seed %s: %v", name, err)
		}
	}

	// A uid that cannot equal os.Geteuid() — this process's own euid,
	// offset by one — stands in for "owned by someone other than the
	// dedicated agent user" without requiring root to actually chown a
	// file to a different real user in a test environment.
	wrongUID := os.Geteuid() + 1

	err := auditStateDir(dir, wrongUID, os.Getegid())
	if err == nil {
		t.Fatal("auditStateDir() error = nil, want a loud failure on ownership mismatch")
	}

	for _, name := range sensitiveAuditFiles {
		path := filepath.Join(dir, name)
		info, err := os.Stat(path)
		if err != nil {
			t.Fatalf("stat %s: %v", path, err)
		}
		if got := info.Mode().Perm(); got != 0o644 {
			t.Errorf("%s mode = %04o after a failed ownership audit, want untouched 0644 (no mode-correction after a fail-loud abort)", name, got)
		}
	}
}

// fakeFileInfo wraps a real os.FileInfo but reports a caller-supplied
// syscall.Stat_t from Sys(), so checkOwnership's uid/gid comparison can be
// exercised against an arbitrary owner without needing to actually chown a
// file to a different real user (which requires root).
type fakeFileInfo struct {
	os.FileInfo
	stat syscall.Stat_t
}

func (f fakeFileInfo) Sys() any { return &f.stat }

// TestCheckOwnership_PerFileClass exercises checkOwnership directly against
// each sensitive file class with a synthetic owner, so a file-level (not
// just directory-level) ownership mismatch on device.key, grants.json, and
// status.json specifically is proven to fail loudly.
func TestCheckOwnership_PerFileClass(t *testing.T) {
	dir := t.TempDir()
	for _, name := range sensitiveAuditFiles {
		t.Run(name, func(t *testing.T) {
			path := filepath.Join(dir, name)
			if err := os.WriteFile(path, []byte("x"), 0o600); err != nil {
				t.Fatalf("seed %s: %v", name, err)
			}
			realInfo, err := os.Stat(path)
			if err != nil {
				t.Fatalf("stat %s: %v", path, err)
			}

			// Matching owner passes silently.
			match := fakeFileInfo{FileInfo: realInfo, stat: syscall.Stat_t{Uid: 42, Gid: 42}}
			if err := checkOwnership(path, match, 42, 42); err != nil {
				t.Errorf("checkOwnership() error = %v, want nil for a matching owner", err)
			}

			// Mismatched owner fails loudly.
			mismatch := fakeFileInfo{FileInfo: realInfo, stat: syscall.Stat_t{Uid: 42, Gid: 42}}
			if err := checkOwnership(path, mismatch, 43, 42); err == nil {
				t.Error("checkOwnership() error = nil, want a loud failure for a uid mismatch")
			}
			if err := checkOwnership(path, mismatch, 42, 43); err == nil {
				t.Error("checkOwnership() error = nil, want a loud failure for a gid mismatch")
			}
		})
	}
}

// --- Task 25: durable update swap and rollback --------------------------

// TestWatchForRollback_NoConfirmationTriggersRollback covers "a restart
// without hello.ack within 2 minutes triggers rollback to the previous
// binary". rollbackWindow is shrunk to a few tens of milliseconds (mirrors
// internal/link's stabilityWindow/rekeyInterval shrink-for-tests pattern)
// rather than sleeping for real minutes; nothing ever clears the marker, so
// watchForRollback must conclude the update never confirmed.
func TestWatchForRollback_NoConfirmationTriggersRollback(t *testing.T) {
	orig := rollbackWindow
	rollbackWindow = 30 * time.Millisecond
	defer func() { rollbackWindow = orig }()

	dir := t.TempDir()
	oldVersionDir := filepath.Join(dir, "versions", "0.5.0")
	newVersionDir := filepath.Join(dir, "versions", "0.6.0")
	for _, d := range []string{oldVersionDir, newVersionDir} {
		if err := os.MkdirAll(d, 0o755); err != nil {
			t.Fatal(err)
		}
	}
	if err := os.WriteFile(filepath.Join(newVersionDir, "cb-agent"), []byte("new binary"), 0o755); err != nil {
		t.Fatal(err)
	}
	currentLink := update.CurrentLinkPath(dir)
	if err := os.Symlink(filepath.Join(newVersionDir, "cb-agent"), currentLink); err != nil {
		t.Fatal(err)
	}
	// MarkSwapped (not the plain WriteMarker) — this test simulates a
	// restart *after* update.Swap actually completed, i.e. the marker is in
	// its phasePendingConfirm phase and prevVersionDir genuinely names
	// this update's own backup. See
	// TestWatchForRollback_CrashBeforeSwapDoesNotRollBackToStaleBackup for
	// the phasePendingSwap (Swap never ran) case this must be told apart
	// from.
	if err := update.MarkSwapped(dir, "0.6.0", oldVersionDir); err != nil {
		t.Fatalf("MarkSwapped() error = %v", err)
	}

	reExecCalls := 0
	reExec := func() error {
		reExecCalls++
		return nil
	}

	watchForRollback(dir, currentLink, "0.6.0", reExec)

	target, err := os.Readlink(currentLink)
	wantTarget := filepath.Join(oldVersionDir, "cb-agent")
	if err != nil || target != wantTarget {
		t.Errorf("current symlink = (%q, %v), want rolled back to %q", target, err, wantTarget)
	}
	if _, _, _, present, _ := update.ReadMarker(dir); present {
		t.Error("marker still present after rollback, want cleared")
	}
	version, present, err := update.ReadRollbackReport(dir)
	if err != nil || !present || version != "0.6.0" {
		t.Errorf("ReadRollbackReport() = (%q, %v, %v), want (\"0.6.0\", true, nil) — the fresh process re-exec'd below needs this to report update.status(rolled_back)", version, present, err)
	}
	if reExecCalls != 1 {
		t.Errorf("reExec called %d times, want exactly 1", reExecCalls)
	}
}

// TestWatchForRollback_ConfirmedWithinWindowRetainsNewBinary covers "a
// restart that gets hello.ack within 2 minutes retains the new binary and
// clears the marker". A goroutine simulates onConnected's hello.ack-gated
// confirmation (Task 4) by clearing the marker partway through the window;
// watchForRollback must observe that and leave the new binary and backup
// alone, never re-exec.
func TestWatchForRollback_ConfirmedWithinWindowRetainsNewBinary(t *testing.T) {
	orig := rollbackWindow
	rollbackWindow = 150 * time.Millisecond
	defer func() { rollbackWindow = orig }()

	dir := t.TempDir()
	oldVersionDir := filepath.Join(dir, "versions", "0.6.0")
	newVersionDir := filepath.Join(dir, "versions", "0.7.0")
	for _, d := range []string{oldVersionDir, newVersionDir} {
		if err := os.MkdirAll(d, 0o755); err != nil {
			t.Fatal(err)
		}
	}
	if err := os.WriteFile(filepath.Join(newVersionDir, "cb-agent"), []byte("new binary"), 0o755); err != nil {
		t.Fatal(err)
	}
	currentLink := update.CurrentLinkPath(dir)
	if err := os.Symlink(filepath.Join(newVersionDir, "cb-agent"), currentLink); err != nil {
		t.Fatal(err)
	}
	if err := update.MarkSwapped(dir, "0.7.0", oldVersionDir); err != nil {
		t.Fatalf("MarkSwapped() error = %v", err)
	}

	confirmed := make(chan struct{})
	go func() {
		// Well inside the 150ms window — simulates onConnected firing from
		// an accepted hello.ack shortly after the daemon reconnects.
		time.Sleep(20 * time.Millisecond)
		if err := update.ClearMarker(dir); err != nil {
			t.Errorf("ClearMarker() error = %v", err)
		}
		close(confirmed)
	}()

	reExecCalls := 0
	reExec := func() error {
		reExecCalls++
		return nil
	}

	watchForRollback(dir, currentLink, "0.7.0", reExec)
	<-confirmed

	target, err := os.Readlink(currentLink)
	wantTarget := filepath.Join(newVersionDir, "cb-agent")
	if err != nil || target != wantTarget {
		t.Errorf("current symlink = (%q, %v), want unchanged %q — a confirmed update must not be rolled back", target, err, wantTarget)
	}
	if _, _, _, present, _ := update.ReadMarker(dir); present {
		t.Error("marker still present, want cleared by the simulated onConnected confirmation")
	}
	if _, present, _ := update.ReadRollbackReport(dir); present {
		t.Error("rollback report present, want none — the update confirmed, no rollback happened")
	}
	if reExecCalls != 0 {
		t.Errorf("reExec called %d times, want 0 (a confirmed update must not re-exec)", reExecCalls)
	}
}

// TestWatchForRollback_CrashBeforeSwapDoesNotRollBackToStaleBackup
// reproduces, live, the fix-round-1 Critical finding: marker-first ordering
// (Task 25's own fix) broke the invariant that a marker's presence implies
// ".previous" is *that* update's actual backup, because nothing stopped a
// crash between WriteMarker and Swap from leaving a marker naming a new
// version while ".previous" still held a stale, two-versions-back backup
// from an earlier, already-confirmed update.
//
// Scenario: a v0->v1 update already completed and confirmed — target holds
// the healthy, running v1 binary, and its ".previous" (v0) was retained per
// the existing "keep .previous until confirmed" design. A v2 update
// instruction then arrives: WriteMarker("2.0.0") succeeds durably, and the
// process is killed (power loss, OOM, systemctl restart) before
// update.Swap ever runs — target is untouched, still the healthy v1 binary.
// On restart, the marker is present naming "2.0.0"; without this fix,
// watchForRollback would arm its window and, finding the marker still
// present after it elapses (no hello.ack — exactly the condition this
// scenario's server-unreachable window represents), roll back by renaming
// the STALE v0 ".previous" over the healthy running v1 — a silent
// multi-version downgrade reported as update.status(rolled_back) for a
// version ("2.0.0") that was never actually installed.
//
// With the fix, WriteMarker alone leaves the marker in phasePendingSwap
// (swapped == false), which watchForRollback must recognize as "Swap never
// ran, nothing to roll back" rather than blindly trusting whatever
// ".previous" happens to be sitting on disk.
func TestWatchForRollback_CrashBeforeSwapDoesNotRollBackToStaleBackup(t *testing.T) {
	orig := rollbackWindow
	rollbackWindow = 30 * time.Millisecond
	defer func() { rollbackWindow = orig }()

	dir := t.TempDir()
	// v1Dir is the healthy, currently-running version from an earlier
	// v0->v1 update that already completed and confirmed (and so, per
	// PruneVersions, has no stale v0 directory left lying around).
	v1Dir := filepath.Join(dir, "versions", "1.0.0")
	if err := os.MkdirAll(v1Dir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(v1Dir, "cb-agent"), []byte("v1 binary (healthy, running)"), 0o755); err != nil {
		t.Fatal(err)
	}
	currentLink := update.CurrentLinkPath(dir)
	if err := os.Symlink(filepath.Join(v1Dir, "cb-agent"), currentLink); err != nil {
		t.Fatal(err)
	}

	// Reproduces the crash: a v2 update instruction's WriteMarker succeeded,
	// but the process died before update.Swap ever ran (main.go's onUpdate
	// calls these in that order). The marker therefore names "2.0.0" but
	// carries phasePendingSwap, not phasePendingConfirm, and no
	// prevVersionDir.
	if err := update.WriteMarker(dir, "2.0.0"); err != nil {
		t.Fatalf("WriteMarker() error = %v", err)
	}

	reExecCalls := 0
	reExec := func() error {
		reExecCalls++
		return nil
	}

	watchForRollback(dir, currentLink, "2.0.0", reExec)

	target, err := os.Readlink(currentLink)
	wantTarget := filepath.Join(v1Dir, "cb-agent")
	if err != nil || target != wantTarget {
		t.Errorf("current symlink = (%q, %v), want unchanged %q — the healthy running v1 must never be silently replaced", target, err, wantTarget)
	}
	if _, _, _, present, _ := update.ReadMarker(dir); present {
		t.Error("marker still present after an abandoned (pre-swap) update attempt, want cleared")
	}
	if _, present, _ := update.ReadRollbackReport(dir); present {
		t.Error("rollback report present, want none — nothing was rolled back, so there is nothing to report")
	}
	if reExecCalls != 0 {
		t.Errorf("reExec called %d times, want 0 — an abandoned pre-swap attempt must never re-exec", reExecCalls)
	}
}

// TestWatchForRollback_FailedRollbackStillClearsMarker covers the
// fix-round-1 Important finding: if update.Rollback itself fails (no
// ".previous" present, unreadable, a cross-device error, ...),
// watchForRollback must still clear the marker rather than leaving it in
// place — an uncleared marker would re-arm this exact same doomed rollback
// attempt on every subsequent restart, forever, since nothing else would
// ever clear it (the update that wrote it never confirmed, and never will,
// since it never actually installed).
//
// This scenario is a newly-live path after Task 25's marker-first
// reordering: a first-ever update crashing between WriteMarker and Swap
// leaves a phasePendingConfirm-less marker with no ".previous" at all to
// roll back to (there's never been a prior install to back up). This test
// forces the same failure directly against a phasePendingConfirm marker
// (Rollback failing for any reason, not just this specific cause) to
// isolate the marker-clearing behavior from the phase-detection behavior
// TestWatchForRollback_CrashBeforeSwapDoesNotRollBackToStaleBackup already
// covers.
func TestWatchForRollback_FailedRollbackStillClearsMarker(t *testing.T) {
	orig := rollbackWindow
	rollbackWindow = 30 * time.Millisecond
	defer func() { rollbackWindow = orig }()

	dir := t.TempDir()
	currentDir := filepath.Join(dir, "versions", "0.8.0")
	if err := os.MkdirAll(currentDir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(currentDir, "cb-agent"), []byte("current binary"), 0o755); err != nil {
		t.Fatal(err)
	}
	currentLink := update.CurrentLinkPath(dir)
	if err := os.Symlink(filepath.Join(currentDir, "cb-agent"), currentLink); err != nil {
		t.Fatal(err)
	}
	// Deliberately no prevVersionDir recorded — Rollback must fail.
	if err := update.MarkSwapped(dir, "0.8.0", ""); err != nil {
		t.Fatalf("MarkSwapped() error = %v", err)
	}

	reExecCalls := 0
	reExec := func() error {
		reExecCalls++
		return nil
	}

	watchForRollback(dir, currentLink, "0.8.0", reExec)

	if _, _, _, present, _ := update.ReadMarker(dir); present {
		t.Error("marker still present after a failed Rollback, want cleared to avoid a permanently stuck retry loop")
	}
	target, err := os.Readlink(currentLink)
	wantTarget := filepath.Join(currentDir, "cb-agent")
	if err != nil || target != wantTarget {
		t.Errorf("current symlink = (%q, %v), want unchanged %q — a failed rollback must not partially mutate current", target, err, wantTarget)
	}
	if reExecCalls != 0 {
		t.Errorf("reExec called %d times, want 0 — a failed rollback must not re-exec into whatever partial state resulted", reExecCalls)
	}
}

// --- Bug 1 fix round 4: test-only pre-re-exec delay override -------------

// TestResolveReExecDelay_UnsetIsInert pins the production-safety guarantee
// for reExecDelayEnvOverride: with CB_AGENT_TEST_PRE_REEXEC_DELAY_MS unset
// (the state of every real deployment), resolveReExecDelay must return
// exactly 0 — onUpdate's re-exec must never be delayed in production.
func TestResolveReExecDelay_UnsetIsInert(t *testing.T) {
	t.Setenv(reExecDelayEnvOverride, "")
	if got := resolveReExecDelay(); got != 0 {
		t.Fatalf("resolveReExecDelay() with env unset = %v, want 0 (production must never delay re-exec)", got)
	}
}

// TestResolveReExecDelay_HonorsOverride confirms the override actually takes
// effect when explicitly set.
func TestResolveReExecDelay_HonorsOverride(t *testing.T) {
	t.Setenv(reExecDelayEnvOverride, "500")
	if got := resolveReExecDelay(); got != 500*time.Millisecond {
		t.Fatalf("resolveReExecDelay() with env=500 = %v, want 500ms", got)
	}
}

// TestResolveReExecDelay_IgnoresGarbageAndNonPositive confirms malformed or
// non-positive overrides are silently ignored rather than e.g. panicking or
// producing a negative sleep duration — the fallback is always 0 (no delay).
func TestResolveReExecDelay_IgnoresGarbageAndNonPositive(t *testing.T) {
	for _, v := range []string{"not-a-number", "0", "-5"} {
		t.Setenv(reExecDelayEnvOverride, v)
		if got := resolveReExecDelay(); got != 0 {
			t.Fatalf("resolveReExecDelay() with env=%q = %v, want 0", v, got)
		}
	}
}

// --- Task 29: self-performing `cb-agent uninstall` -----------------------

// TestRequireRoot covers the "non-root invocation refuses with a clear
// error" requirement directly, without needing the test process to actually
// run as either uid — euid is passed in rather than read from the real
// process, exactly the same "inject the identity, don't rely on the real
// one" approach TestAuditStateDir_OwnershipMismatchFailsLoudly next door
// uses.
func TestRequireRoot(t *testing.T) {
	tests := []struct {
		name    string
		euid    int
		wantErr bool
	}{
		{name: "root (euid 0) is permitted", euid: 0, wantErr: false},
		{name: "non-root euid refuses", euid: 1000, wantErr: true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			err := requireRoot(tt.euid)
			if (err != nil) != tt.wantErr {
				t.Errorf("requireRoot(%d) error = %v, want error presence = %v", tt.euid, err, tt.wantErr)
			}
			if tt.wantErr && !strings.Contains(err.Error(), "root") {
				t.Errorf("requireRoot(%d) error = %q, want it to mention root", tt.euid, err)
			}
		})
	}
}

// fakeSystemctl builds a systemctlRunner test double that records every
// invocation (in order) into calls, and fails invocations for which
// shouldFail (nil means "never fail") returns true — the fake-systemctl
// harness the brief asks for, standing in for a real systemd (which unit
// tests must never touch).
func fakeSystemctl(calls *[][]string, shouldFail func(args []string) bool) systemctlRunner {
	return func(args ...string) error {
		*calls = append(*calls, append([]string(nil), args...))
		if shouldFail != nil && shouldFail(args) {
			return errors.New("fake systemctl failure")
		}
		return nil
	}
}

// seedUninstallFootprint builds a temp-directory stand-in for
// defaultUninstallPaths — a unit file, binary, and its ".previous" update-
// swap backup (plain files), plus a config dir containing only this
// agent's own agent.toml (so it comes out empty and is itself removable —
// TestPerformUninstall_ConfigDirCoLocatedWithServerFilesLeftIntact below
// covers the opposite, populated case) and a state dir (populated the way
// Task 30's auditStateDir expects: device.key/grants.json/status.json
// directly under it, plus a spool/ subdirectory) — so performUninstall's
// "remove the whole state dir" behavior is exercised against a realistic
// footprint, not just an empty directory.
func seedUninstallFootprint(t *testing.T) uninstallPaths {
	t.Helper()
	root := t.TempDir()

	unitFile := filepath.Join(root, "cb-agent.service")
	if err := os.WriteFile(unitFile, []byte("[Unit]\n"), 0o644); err != nil {
		t.Fatalf("seed unit file: %v", err)
	}
	binary := filepath.Join(root, "cb-agent")
	if err := os.WriteFile(binary, []byte("binary"), 0o755); err != nil {
		t.Fatalf("seed binary: %v", err)
	}
	configDir := filepath.Join(root, "circuit-breaker")
	if err := os.MkdirAll(configDir, 0o755); err != nil {
		t.Fatalf("seed config dir: %v", err)
	}
	configFile := filepath.Join(configDir, "agent.toml")
	if err := os.WriteFile(configFile, []byte("server_url = \"\"\n"), 0o644); err != nil {
		t.Fatalf("seed agent.toml: %v", err)
	}
	stateDir := filepath.Join(root, "state")
	if err := os.MkdirAll(filepath.Join(stateDir, "spool"), 0o755); err != nil {
		t.Fatalf("seed state dir: %v", err)
	}
	for _, name := range sensitiveAuditFiles {
		if err := os.WriteFile(filepath.Join(stateDir, name), []byte("x"), 0o600); err != nil {
			t.Fatalf("seed %s: %v", name, err)
		}
	}

	return uninstallPaths{
		unitFile:   unitFile,
		binary:     binary,
		configFile: configFile,
		configDir:  configDir,
		stateDir:   stateDir,
	}
}

// TestPerformUninstall_RemovesExpectedPathsAndReloadsSystemd is this task's
// core requirement: "root invocation removes the expected unit/binary/
// config/state paths and reloads systemd". Root itself is never exercised
// here (requireRoot is the gate for that, tested separately) — this proves
// the actual removal logic, temp-directory paths standing in for the real
// root-owned /etc and /usr/local/bin locations. Because seedUninstallFootprint's
// configDir contains only agent.toml, removing it empties the directory, so
// this also covers configDir itself being removed once nothing but this
// agent's own file was in it (the non-co-located case).
func TestPerformUninstall_RemovesExpectedPathsAndReloadsSystemd(t *testing.T) {
	paths := seedUninstallFootprint(t)

	var calls [][]string
	result := performUninstall(paths, fakeSystemctl(&calls, nil))

	if !result.DisabledUnit {
		t.Errorf("DisabledUnit = false (err=%v), want true", result.DisableErr)
	}
	if !result.ReloadedDaemon {
		t.Errorf("ReloadedDaemon = false (err=%v), want true", result.ReloadErr)
	}
	if len(result.RemoveErrs) != 0 {
		t.Errorf("RemoveErrs = %v, want none", result.RemoveErrs)
	}

	wantRemoved := []string{paths.unitFile, paths.binary, paths.configFile, paths.stateDir, paths.configDir}
	if !reflect.DeepEqual(result.Removed, wantRemoved) {
		t.Errorf("Removed = %v, want %v", result.Removed, wantRemoved)
	}

	for _, path := range wantRemoved {
		if _, err := os.Stat(path); !os.IsNotExist(err) {
			t.Errorf("stat %s after performUninstall = %v, want IsNotExist", path, err)
		}
	}

	wantCalls := [][]string{
		{"disable", "--now", uninstallUnitName},
		{"daemon-reload"},
	}
	if !reflect.DeepEqual(calls, wantCalls) {
		t.Errorf("systemctl calls = %v, want %v (disable-before-remove, reload last)", calls, wantCalls)
	}
}

// TestPerformUninstall_ConfigDirCoLocatedWithServerFilesLeftIntact is the
// regression test for this round's Critical finding: on a host where
// cb-agent monitors the CircuitBreaker server itself, /etc/circuit-breaker
// also holds the server's own config.toml and circuit-breaker.env (the
// latter holding CB_VAULT_KEY, CB_DB_URL, NATS_AUTH_TOKEN — see
// packaging/postinstall.sh and apps/backend/src/app/core/config_toml.py).
// Uninstalling cb-agent must remove only its own agent.toml, must leave
// configDir and every other file in it untouched, and must not report this
// as an error.
func TestPerformUninstall_ConfigDirCoLocatedWithServerFilesLeftIntact(t *testing.T) {
	paths := seedUninstallFootprint(t)

	serverConfig := filepath.Join(paths.configDir, "config.toml")
	if err := os.WriteFile(serverConfig, []byte("[server]\n"), 0o644); err != nil {
		t.Fatalf("seed server config.toml: %v", err)
	}
	serverEnv := filepath.Join(paths.configDir, "circuit-breaker.env")
	if err := os.WriteFile(serverEnv, []byte("CB_VAULT_KEY=super-secret\n"), 0o600); err != nil {
		t.Fatalf("seed server circuit-breaker.env: %v", err)
	}

	var calls [][]string
	result := performUninstall(paths, fakeSystemctl(&calls, nil))

	if len(result.RemoveErrs) != 0 {
		t.Errorf("RemoveErrs = %v, want none — a non-empty configDir must be a silent no-op, not an error", result.RemoveErrs)
	}

	if _, err := os.Stat(paths.configFile); !os.IsNotExist(err) {
		t.Errorf("stat agent.toml after performUninstall = %v, want IsNotExist — this agent's own config must still be removed", err)
	}
	for _, p := range []string{paths.configDir, serverConfig, serverEnv} {
		if _, err := os.Stat(p); err != nil {
			t.Errorf("stat %s after performUninstall = %v, want it to still exist — must not touch the co-located server's files", p, err)
		}
	}

	for _, path := range result.Removed {
		if path == paths.configDir {
			t.Errorf("Removed = %v, want configDir absent — it still has the server's own files in it", result.Removed)
		}
	}

	data, err := os.ReadFile(serverEnv)
	if err != nil {
		t.Fatalf("re-read circuit-breaker.env: %v", err)
	}
	if string(data) != "CB_VAULT_KEY=super-secret\n" {
		t.Errorf("circuit-breaker.env content = %q, want untouched", data)
	}
}

// TestPerformUninstall_MissingPathsSkippedWithoutError covers a second
// uninstall attempt (or a partial/manual removal beforehand) where some or
// all paths are already gone — that must not be reported as an error, and
// systemd must still be disabled/reloaded.
func TestPerformUninstall_MissingPathsSkippedWithoutError(t *testing.T) {
	root := t.TempDir()
	paths := uninstallPaths{
		unitFile:   filepath.Join(root, "does-not-exist", "cb-agent.service"),
		binary:     filepath.Join(root, "does-not-exist", "cb-agent"),
		configFile: filepath.Join(root, "does-not-exist", "circuit-breaker", "agent.toml"),
		configDir:  filepath.Join(root, "does-not-exist", "circuit-breaker"),
		stateDir:   filepath.Join(root, "does-not-exist", "state"),
	}

	var calls [][]string
	result := performUninstall(paths, fakeSystemctl(&calls, nil))

	if len(result.Removed) != 0 {
		t.Errorf("Removed = %v, want none — nothing existed on disk", result.Removed)
	}
	if len(result.RemoveErrs) != 0 {
		t.Errorf("RemoveErrs = %v, want none — a missing path is not an error", result.RemoveErrs)
	}
	if !result.DisabledUnit || !result.ReloadedDaemon {
		t.Errorf("DisabledUnit=%v ReloadedDaemon=%v, want both true even with nothing to remove", result.DisabledUnit, result.ReloadedDaemon)
	}
}

// TestPerformUninstall_SystemctlDisableFailureDoesNotBlockFileRemoval
// verifies the three phases are independent: a failed `systemctl disable`
// (unit never installed, or systemd unavailable) must not prevent file
// removal or the final daemon-reload attempt.
func TestPerformUninstall_SystemctlDisableFailureDoesNotBlockFileRemoval(t *testing.T) {
	paths := seedUninstallFootprint(t)

	var calls [][]string
	failDisable := func(args []string) bool { return len(args) > 0 && args[0] == "disable" }
	result := performUninstall(paths, fakeSystemctl(&calls, failDisable))

	if result.DisabledUnit {
		t.Error("DisabledUnit = true, want false for a fake systemctl that fails disable")
	}
	if result.DisableErr == nil {
		t.Error("DisableErr = nil, want the fake failure recorded")
	}
	if !result.ReloadedDaemon {
		t.Errorf("ReloadedDaemon = false (err=%v), want true — a failed disable must not block daemon-reload", result.ReloadErr)
	}
	wantRemoved := []string{paths.unitFile, paths.binary, paths.configFile, paths.stateDir, paths.configDir}
	if !reflect.DeepEqual(result.Removed, wantRemoved) {
		t.Errorf("Removed = %v, want %v — a failed disable must not block file removal", result.Removed, wantRemoved)
	}
}

// TestPerformUninstall_SystemctlReloadFailureStillReportsRemoval mirrors the
// previous test for the opposite ordering: a failed final daemon-reload must
// not retroactively hide the fact that every file was actually removed.
func TestPerformUninstall_SystemctlReloadFailureStillReportsRemoval(t *testing.T) {
	paths := seedUninstallFootprint(t)

	var calls [][]string
	failReload := func(args []string) bool { return len(args) > 0 && args[0] == "daemon-reload" }
	result := performUninstall(paths, fakeSystemctl(&calls, failReload))

	if !result.DisabledUnit {
		t.Errorf("DisabledUnit = false (err=%v), want true", result.DisableErr)
	}
	if result.ReloadedDaemon {
		t.Error("ReloadedDaemon = true, want false for a fake systemctl that fails daemon-reload")
	}
	if result.ReloadErr == nil {
		t.Error("ReloadErr = nil, want the fake failure recorded")
	}
	wantRemoved := []string{paths.unitFile, paths.binary, paths.configFile, paths.stateDir, paths.configDir}
	if !reflect.DeepEqual(result.Removed, wantRemoved) {
		t.Errorf("Removed = %v, want %v — a failed daemon-reload must not hide successful file removal", result.Removed, wantRemoved)
	}
}

// TestResolveUninstallPaths_PinsToInstalledBinaryPath is the regression
// test for the self-update-fix design gap: resolveUninstallPaths must
// always target the fixed /usr/local/bin/cb-agent entry point, not
// os.Executable()'s resolved (symlink-followed) result. Under the
// versioned-symlink layout (specs/2026-08-05-cb-agent-self-update-fix-
// design.md), os.Executable() resolves straight through to whatever
// {stateDir}/versions/<v>/cb-agent happens to be running, which would
// leave the actual root-owned /usr/local/bin/cb-agent symlink behind after
// an otherwise-complete uninstall.
func TestResolveUninstallPaths_PinsToInstalledBinaryPath(t *testing.T) {
	paths := resolveUninstallPaths()

	if paths.binary != installedBinaryPath {
		t.Errorf("resolveUninstallPaths().binary = %q, want the fixed %q", paths.binary, installedBinaryPath)
	}
	if paths.unitFile != defaultUninstallPaths.unitFile {
		t.Errorf("resolveUninstallPaths().unitFile = %q, want %q", paths.unitFile, defaultUninstallPaths.unitFile)
	}
	if paths.configFile != defaultUninstallPaths.configFile {
		t.Errorf("resolveUninstallPaths().configFile = %q, want %q", paths.configFile, defaultUninstallPaths.configFile)
	}
	if paths.configDir != defaultUninstallPaths.configDir {
		t.Errorf("resolveUninstallPaths().configDir = %q, want %q", paths.configDir, defaultUninstallPaths.configDir)
	}
	if paths.stateDir != defaultUninstallPaths.stateDir {
		t.Errorf("resolveUninstallPaths().stateDir = %q, want %q", paths.stateDir, defaultUninstallPaths.stateDir)
	}
}

// --- Task 10: daemon startup ordering ------------------------------------

// fakeHostCollector stands in for internal/collect/host during the
// startDaemonState tests. The real collector reads /proc and /sys, which no
// test may touch (Global Constraints — test hygiene); this one returns a
// fixed, deterministic readiness report and an empty payload instead, so the
// tests assert on startup *ordering* rather than on host state.
type fakeHostCollector struct {
	readiness []frame.Readiness
}

func (f fakeHostCollector) Collect(context.Context) (collect.Result, error) {
	return collect.Result{Readiness: f.readiness}, nil
}

// startDaemonStateTestDir prepares an isolated state directory with a device
// key and, when grants is non-empty, a pre-seeded grants.json, points
// config.StateDir() at it, and swaps in fakeHostCollector for the duration of
// the test.
func startDaemonStateTestDir(t *testing.T, grants string, readiness []frame.Readiness) (string, *enroll.DeviceKey) {
	t.Helper()
	dir := t.TempDir()
	t.Setenv("CB_AGENT_STATE_DIR", dir)
	key, err := enroll.LoadOrCreateDeviceKey(dir)
	if err != nil {
		t.Fatalf("LoadOrCreateDeviceKey() error = %v", err)
	}
	if grants != "" {
		if err := os.WriteFile(filepath.Join(dir, "grants.json"), []byte(grants), 0o600); err != nil {
			t.Fatalf("seed grants.json: %v", err)
		}
	}
	prev := newHostCollector
	newHostCollector = func(capability.HostConfig) collect.Collector {
		return fakeHostCollector{readiness: readiness}
	}
	t.Cleanup(func() { newHostCollector = prev })
	return dir, key
}

// awaitReadiness polls the persisted status file until every wanted collector
// name appears in its readiness listing, or fails the test.
func awaitReadiness(t *testing.T, dir string, want ...string) status.Status {
	t.Helper()
	deadline := time.Now().Add(5 * time.Second)
	var last status.Status
	for time.Now().Before(deadline) {
		st, ok, err := status.Read(dir)
		if err != nil {
			t.Fatalf("status.Read() error = %v", err)
		}
		if ok {
			last = st
			have := make(map[string]struct{}, len(st.Readiness))
			for _, r := range st.Readiness {
				have[r.Collector] = struct{}{}
			}
			missing := false
			for _, name := range want {
				if _, ok := have[name]; !ok {
					missing = true
				}
			}
			if !missing {
				return st
			}
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatalf("status.json readiness = %+v after 5s, want entries for %v", last.Readiness, want)
	return last
}

// TestStartDaemonState_NoRaceBetweenCollectorReadinessAndStatusWriter pins
// the ordering defect this task exists to close: the collector goroutine's
// OnReadiness callback must never observe a statusWriter the main startup
// goroutine is still assigning. Run under -race (apps/agent/Makefile's `test`
// target), this failed as a DATA RACE while applyHostConfig() ran before the
// status.NewWriter assignment it captured.
func TestStartDaemonState_NoRaceBetweenCollectorReadinessAndStatusWriter(t *testing.T) {
	dir, key := startDaemonStateTestDir(t,
		`{"host_telemetry":{"enabled":true,"config":{"interval_s":10}}}`,
		[]frame.Readiness{{Collector: "host.core", State: "ready"}})

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	rt, err := startDaemonState(&config.Config{}, key, "0.1.0-test", ctx)
	if err != nil {
		t.Fatalf("startDaemonState() error = %v", err)
	}
	t.Cleanup(func() { _ = rt.sp.Close() })

	awaitReadiness(t, dir, "host.core")
}

// TestStartDaemonState_CollectorReadinessIsNotErasedByIdentityReadiness
// covers the second half of the same defect: even with the ordering fixed, a
// whole-slice SetReadiness meant whichever of the two producers wrote last
// erased the other. Both the startup identity report and the first host
// collection must survive.
func TestStartDaemonState_CollectorReadinessIsNotErasedByIdentityReadiness(t *testing.T) {
	dir, key := startDaemonStateTestDir(t,
		`{"host_telemetry":{"enabled":true,"config":{"interval_s":10}}}`,
		[]frame.Readiness{{Collector: "host.core", State: "ready"}})

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	rt, err := startDaemonState(&config.Config{}, key, "0.1.0-test", ctx)
	if err != nil {
		t.Fatalf("startDaemonState() error = %v", err)
	}
	t.Cleanup(func() { _ = rt.sp.Close() })

	st := awaitReadiness(t, dir, "agent.identity", "host.core")
	for i := 1; i < len(st.Readiness); i++ {
		if st.Readiness[i-1].Collector > st.Readiness[i].Collector {
			t.Errorf("readiness = %+v, want it sorted by collector", st.Readiness)
			break
		}
	}
}

// TestStartDaemonState_AuditRunsBeforeAnyStateWrite pins the narrowed
// invariant stated in auditStateDir's doc comment: the audit precedes every
// daemon-loop state write. A state directory owned by someone else must abort
// startup with neither status.json nor the spool queue created. Requires root
// to chown the directory to a foreign uid, so it skips otherwise — the
// ownership check itself is covered without root by
// TestAuditStateDir_OwnershipMismatchFailsLoudly.
func TestStartDaemonState_AuditRunsBeforeAnyStateWrite(t *testing.T) {
	if os.Geteuid() != 0 {
		t.Skip("requires root to chown the state directory to a foreign uid")
	}
	dir, key := startDaemonStateTestDir(t,
		`{"host_telemetry":{"enabled":true,"config":{"interval_s":10}}}`,
		[]frame.Readiness{{Collector: "host.core", State: "ready"}})
	if err := os.Chown(dir, 12345, 12345); err != nil {
		t.Fatalf("chown %s: %v", dir, err)
	}

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	rt, err := startDaemonState(&config.Config{}, key, "0.1.0-test", ctx)
	if err == nil {
		if rt != nil && rt.sp != nil {
			_ = rt.sp.Close()
		}
		t.Fatal("startDaemonState() error = nil for a foreign-owned state dir, want a startup abort")
	}
	for _, name := range []string{"status.json", filepath.Join("spool", "queue.jsonl")} {
		if _, statErr := os.Stat(filepath.Join(dir, name)); !os.IsNotExist(statErr) {
			t.Errorf("%s exists after a failed ownership audit, want the audit to precede every state write", name)
		}
	}
}

// readinessFrameStates decodes a capability.readiness frame's payload into a
// collector -> state map, and returns the payload's collector order so a test
// can also assert the sort the daemon promises.
func readinessFrameStates(t *testing.T, f frame.Frame) (map[string]string, []string) {
	t.Helper()
	if f.Type != frame.TypeCapabilityReadiness {
		t.Fatalf("frame type = %q, want %q", f.Type, frame.TypeCapabilityReadiness)
	}
	var payload frame.CapabilityReadinessPayload
	if err := json.Unmarshal(f.Payload, &payload); err != nil {
		t.Fatalf("unmarshal readiness payload %s: %v", f.Payload, err)
	}
	states := make(map[string]string, len(payload.Readiness))
	order := make([]string, 0, len(payload.Readiness))
	for _, r := range payload.Readiness {
		states[r.Collector] = r.State
		order = append(order, r.Collector)
	}
	return states, order
}

// awaitReadinessFrame waits for the next capability.readiness frame on the
// daemon's control channel.
func awaitReadinessFrame(t *testing.T, ch <-chan frame.Frame) frame.Frame {
	t.Helper()
	select {
	case f := <-ch:
		return f
	case <-time.After(5 * time.Second):
		t.Fatal("no capability.readiness frame within 5s")
	}
	return frame.Frame{}
}

// drainFrames empties ch without blocking and reports how many frames it took.
func drainFrames(ch <-chan frame.Frame) int {
	n := 0
	for {
		select {
		case <-ch:
			n++
		default:
			return n
		}
	}
}

// shrinkReadinessTimers makes the reconciliation ticker and the per-frame
// rate-limit floor test-scale for the duration of one test.
func shrinkReadinessTimers(t *testing.T, tick, floor time.Duration) {
	t.Helper()
	prevTick, prevFloor := reconcileTickInterval, readinessReportInterval
	reconcileTickInterval, readinessReportInterval = tick, floor
	t.Cleanup(func() { reconcileTickInterval, readinessReportInterval = prevTick, prevFloor })
}

// TestApplyHostConfig_DisableEmitsDisabledForEveryHostCollector pins D-4: a
// revoked host_telemetry grant must actively overwrite every host.* readiness
// row with "disabled" rather than returning bare and leaving the server's rows
// frozen at their last good value (the stale-"Live" defect). The agent's own
// identity row must survive that overwrite.
func TestApplyHostConfig_DisableEmitsDisabledForEveryHostCollector(t *testing.T) {
	dir, key := startDaemonStateTestDir(t,
		`{"host_telemetry":{"enabled":true,"config":{"interval_s":900}}}`,
		[]frame.Readiness{{Collector: "host.core", State: "ready"}})

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	rt, err := startDaemonState(&config.Config{}, key, "0.1.0-test", ctx)
	if err != nil {
		t.Fatalf("startDaemonState() error = %v", err)
	}
	t.Cleanup(func() { _ = rt.sp.Close() })
	rt.linked.Store(true)

	awaitReadiness(t, dir, "agent.identity", "host.core")
	drainFrames(rt.controlFrames)

	if err := rt.capGate.ApplyGrants([]byte(`{"host_telemetry":{"enabled":false}}`)); err != nil {
		t.Fatalf("ApplyGrants() error = %v", err)
	}
	rt.applyHostConfig()

	states, _ := readinessFrameStates(t, awaitReadinessFrame(t, rt.controlFrames))
	for _, name := range hostcollect.CollectorNames {
		if states[name] != "disabled" {
			t.Errorf("readiness[%q] = %q, want %q", name, states[name], "disabled")
		}
	}
	if states["agent.identity"] == "" {
		t.Errorf("readiness = %v, want it to still carry agent.identity", states)
	}
}

// TestApplyHostConfig_ReEnableFlipsDisabledBackToReady proves the other half of
// D-4: nothing synthesizes an "enabling" report — the runner's first collection
// fires immediately and Task 9's all-six-every-run guarantee is what overwrites
// the disabled rows.
func TestApplyHostConfig_ReEnableFlipsDisabledBackToReady(t *testing.T) {
	allReady := make([]frame.Readiness, 0, len(hostcollect.CollectorNames))
	for _, name := range hostcollect.CollectorNames {
		allReady = append(allReady, frame.Readiness{Collector: name, State: "ready"})
	}
	_, key := startDaemonStateTestDir(t, `{"host_telemetry":{"enabled":false}}`, allReady)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	rt, err := startDaemonState(&config.Config{}, key, "0.1.0-test", ctx)
	if err != nil {
		t.Fatalf("startDaemonState() error = %v", err)
	}
	t.Cleanup(func() { _ = rt.sp.Close() })
	// Mirror what OnConnected does: the disable report was published while
	// unlinked, so the link coming up is what forces it out.
	rt.linked.Store(true)
	rt.queueReadiness(true)

	states, _ := readinessFrameStates(t, awaitReadinessFrame(t, rt.controlFrames))
	for _, name := range hostcollect.CollectorNames {
		if states[name] != "disabled" {
			t.Fatalf("pre-condition: readiness[%q] = %q, want %q", name, states[name], "disabled")
		}
	}

	if err := rt.capGate.ApplyGrants([]byte(`{"host_telemetry":{"enabled":true,"config":{"interval_s":900}}}`)); err != nil {
		t.Fatalf("ApplyGrants() error = %v", err)
	}
	rt.applyHostConfig()

	states, _ = readinessFrameStates(t, awaitReadinessFrame(t, rt.controlFrames))
	for _, name := range hostcollect.CollectorNames {
		if states[name] != "ready" {
			t.Errorf("readiness[%q] = %q after re-enable, want %q", name, states[name], "ready")
		}
	}
}

// TestReadinessReconciliation_FiresWithoutAnyCollection pins the reconciliation
// ticker: the slice-2 contract's "every 15 minutes" must hold when
// host_telemetry is disabled and no collection ever happens, which is exactly
// the state in which the server most needs to hear from the agent.
func TestReadinessReconciliation_FiresWithoutAnyCollection(t *testing.T) {
	shrinkReadinessTimers(t, 5*time.Millisecond, time.Millisecond)
	_, key := startDaemonStateTestDir(t, `{"host_telemetry":{"enabled":false}}`, nil)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	rt, err := startDaemonState(&config.Config{}, key, "0.1.0-test", ctx)
	if err != nil {
		t.Fatalf("startDaemonState() error = %v", err)
	}
	t.Cleanup(func() { _ = rt.sp.Close() })
	rt.linked.Store(true)

	// Nothing here ever collects and nothing forces a send — the disable
	// report was published while still unlinked — so every frame that arrives
	// can only have come from the reconciliation ticker.
	awaitReadinessFrame(t, rt.controlFrames)
	states, _ := readinessFrameStates(t, awaitReadinessFrame(t, rt.controlFrames))
	if states["agent.identity"] == "" {
		t.Errorf("reconciliation readiness = %v, want it to carry agent.identity", states)
	}
}

// TestQueueReadiness_DoesNotConsumeBudgetWhileDisconnected pins the link-aware
// rate limit: runOnce discards control frames until the link is up, so a state
// change made mid-outage must not stamp the 15-minute budget — otherwise the
// agent goes readiness-dark for up to 15 minutes after reconnecting.
func TestQueueReadiness_DoesNotConsumeBudgetWhileDisconnected(t *testing.T) {
	_, key := startDaemonStateTestDir(t, `{"host_telemetry":{"enabled":false}}`, nil)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	rt, err := startDaemonState(&config.Config{}, key, "0.1.0-test", ctx)
	if err != nil {
		t.Fatalf("startDaemonState() error = %v", err)
	}
	t.Cleanup(func() { _ = rt.sp.Close() })

	// startDaemonState's applyHostConfig already published the disable report
	// while unlinked; nothing may have been queued.
	if n := drainFrames(rt.controlFrames); n != 0 {
		t.Fatalf("queued %d frames while disconnected, want 0", n)
	}

	rt.linked.Store(true)
	// Unforced: this only sends if the disconnected attempt left
	// readinessSentAt untouched.
	rt.queueReadiness(false)
	states, _ := readinessFrameStates(t, awaitReadinessFrame(t, rt.controlFrames))
	if states["agent.identity"] == "" {
		t.Errorf("readiness = %v, want the newest payload including agent.identity", states)
	}

	// ...and the successful send *does* consume the budget, so the ticker
	// cannot double-send behind a fresh connection's forced frame.
	rt.queueReadiness(false)
	if n := drainFrames(rt.controlFrames); n != 0 {
		t.Errorf("queued %d further frames inside the rate-limit floor, want 0", n)
	}
}

// TestPublishReadiness_MergesIdentityWithHostCollectors pins the single sink:
// every capability.readiness frame carries the union of the startup identity
// report and the host collectors, sorted by collector name.
func TestPublishReadiness_MergesIdentityWithHostCollectors(t *testing.T) {
	_, key := startDaemonStateTestDir(t, `{"host_telemetry":{"enabled":false}}`, nil)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	rt, err := startDaemonState(&config.Config{}, key, "0.1.0-test", ctx)
	if err != nil {
		t.Fatalf("startDaemonState() error = %v", err)
	}
	t.Cleanup(func() { _ = rt.sp.Close() })
	rt.linked.Store(true)
	drainFrames(rt.controlFrames)

	rt.publishReadiness([]frame.Readiness{{Collector: "host.core", State: "ready"}})

	states, order := readinessFrameStates(t, awaitReadinessFrame(t, rt.controlFrames))
	if states["agent.identity"] == "" {
		t.Errorf("readiness = %v, want an agent.identity entry", states)
	}
	for _, name := range hostcollect.CollectorNames {
		if states[name] == "" {
			t.Errorf("readiness = %v, want an entry for %q", states, name)
		}
	}
	if states["host.core"] != "ready" {
		t.Errorf("readiness[host.core] = %q, want %q", states["host.core"], "ready")
	}
	if !sort.StringsAreSorted(order) {
		t.Errorf("readiness order = %v, want it sorted by collector", order)
	}
}
