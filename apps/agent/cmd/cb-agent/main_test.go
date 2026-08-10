// apps/agent/cmd/cb-agent/main_test.go
package main

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"net/netip"
	"os"
	"path/filepath"
	"reflect"
	"sort"
	"strings"
	"sync/atomic"
	"syscall"
	"testing"
	"time"

	"github.com/flynn/noise"
	"github.com/gorilla/websocket"

	"circuitbreaker.dev/cb-agent/internal/capability"
	"circuitbreaker.dev/cb-agent/internal/collect"
	discovercollect "circuitbreaker.dev/cb-agent/internal/collect/discover"
	hostcollect "circuitbreaker.dev/cb-agent/internal/collect/host"
	probecollect "circuitbreaker.dev/cb-agent/internal/collect/probe"
	"circuitbreaker.dev/cb-agent/internal/config"
	"circuitbreaker.dev/cb-agent/internal/enroll"
	"circuitbreaker.dev/cb-agent/internal/frame"
	"circuitbreaker.dev/cb-agent/internal/link"
	"circuitbreaker.dev/cb-agent/internal/netscope"
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

// stageSwappedUpdate builds the on-disk state a swapped-but-unconfirmed
// update leaves behind, with the marker's rollback deadline set to deadline.
func stageSwappedUpdate(t *testing.T, deadline time.Time) (dir, currentLink, oldVersionDir string) {
	t.Helper()
	dir = t.TempDir()
	oldVersionDir = filepath.Join(dir, "versions", "1.0.0")
	newVersionDir := filepath.Join(dir, "versions", "2.0.0")
	for _, d := range []string{oldVersionDir, newVersionDir} {
		if err := os.MkdirAll(d, 0o755); err != nil {
			t.Fatal(err)
		}
	}
	if err := os.WriteFile(filepath.Join(newVersionDir, "cb-agent"), []byte("new binary"), 0o755); err != nil {
		t.Fatal(err)
	}
	currentLink = update.CurrentLinkPath(dir)
	if err := os.Symlink(filepath.Join(newVersionDir, "cb-agent"), currentLink); err != nil {
		t.Fatal(err)
	}
	if err := update.MarkSwapped(dir, "2.0.0", oldVersionDir, deadline); err != nil {
		t.Fatalf("MarkSwapped() error = %v", err)
	}
	return dir, currentLink, oldVersionDir
}

// TestRollbackExpiredUpdate_RollsBackAndReExecsWithoutEverReachingTheServer is
// the regression test for F-8. runDaemon calls this before enroll.Run, so the
// path exercised here is the one an agent takes when the update it just
// installed is the reason it can no longer reach the server: enrollment would
// fail, os.Exit(1) would follow, and watchForRollback — spawned only after a
// successful enrollment — would never run at all. Nothing in this test
// contacts a server, which is exactly the point.
func TestRollbackExpiredUpdate_RollsBackAndReExecsWithoutEverReachingTheServer(t *testing.T) {
	dir, currentLink, oldVersionDir := stageSwappedUpdate(t, time.Now().Add(-time.Second))

	reExecCalls := 0
	rollbackExpiredUpdate(dir, currentLink, time.Now(), func() error {
		reExecCalls++
		return nil
	})

	target, err := os.Readlink(currentLink)
	wantTarget := filepath.Join(oldVersionDir, "cb-agent")
	if err != nil || target != wantTarget {
		t.Errorf("current symlink = (%q, %v), want rolled back to %q", target, err, wantTarget)
	}
	if reExecCalls != 1 {
		t.Errorf("reExec called %d times, want exactly 1 — the rolled-back binary has to actually be executed", reExecCalls)
	}
	if _, _, _, present, _ := update.ReadMarker(dir); present {
		t.Error("marker still present after rollback, want cleared")
	}
	version, present, err := update.ReadRollbackReport(dir)
	if err != nil || !present || version != "2.0.0" {
		t.Errorf("ReadRollbackReport() = (%q, %v, %v), want (\"2.0.0\", true, nil)", version, present, err)
	}
}

// TestRollbackExpiredUpdate_InsideTheWindowIsAPlainNoOp pins the cost of the
// check on every ordinary start: a routine restart inside the window (the
// re-exec the update itself performs, a host reboot) must neither roll back
// nor re-exec, or a healthy update could never confirm.
func TestRollbackExpiredUpdate_InsideTheWindowIsAPlainNoOp(t *testing.T) {
	dir, currentLink, _ := stageSwappedUpdate(t, time.Now().Add(time.Hour))
	before, err := os.Readlink(currentLink)
	if err != nil {
		t.Fatal(err)
	}

	reExecCalls := 0
	rollbackExpiredUpdate(dir, currentLink, time.Now(), func() error {
		reExecCalls++
		return nil
	})

	if target, _ := os.Readlink(currentLink); target != before {
		t.Errorf("current symlink = %q, want %q unchanged", target, before)
	}
	if reExecCalls != 0 {
		t.Errorf("reExec called %d times, want 0", reExecCalls)
	}
	if _, _, _, present, _ := update.ReadMarker(dir); !present {
		t.Error("marker cleared inside the window, want it left for the confirmation to clear")
	}
}

// TestRollbackExpiredUpdate_NoMarkerNeitherRollsBackNorReExecs is the
// overwhelmingly common start: no update is pending at all.
func TestRollbackExpiredUpdate_NoMarkerNeitherRollsBackNorReExecs(t *testing.T) {
	dir := t.TempDir()

	reExecCalls := 0
	rollbackExpiredUpdate(dir, update.CurrentLinkPath(dir), time.Now(), func() error {
		reExecCalls++
		return nil
	})

	if reExecCalls != 0 {
		t.Errorf("reExec called %d times on a clean state dir, want 0", reExecCalls)
	}
}

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
	if err := update.MarkSwapped(dir, "0.6.0", oldVersionDir, time.Now().Add(rollbackWindow)); err != nil {
		t.Fatalf("MarkSwapped() error = %v", err)
	}

	reExecCalls := 0
	reExec := func() error {
		reExecCalls++
		return nil
	}

	watchForRollback(dir, currentLink, "0.6.0", rollbackWindow, reExec)

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
	if err := update.MarkSwapped(dir, "0.7.0", oldVersionDir, time.Now().Add(rollbackWindow)); err != nil {
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

	watchForRollback(dir, currentLink, "0.7.0", rollbackWindow, reExec)
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

	watchForRollback(dir, currentLink, "2.0.0", rollbackWindow, reExec)

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
	if err := update.MarkSwapped(dir, "0.8.0", "", time.Now().Add(rollbackWindow)); err != nil {
		t.Fatalf("MarkSwapped() error = %v", err)
	}

	reExecCalls := 0
	reExec := func() error {
		reExecCalls++
		return nil
	}

	watchForRollback(dir, currentLink, "0.8.0", rollbackWindow, reExec)

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

// networkFixture is the interface enumerator the startDaemonState tests install
// behind the hostNetworkFacts seam, and the only supported way to change what
// this host appears to enumerate *after* startDaemonState has returned.
//
// It has to be an atomic behind a stable func value rather than a plain
// reassignment of the package var, for two independent reasons. First,
// startDaemonState captures hostNetworkFacts once, at construction (see the
// comment on networkFacts there), so a test that reassigned the package var
// mid-run would be writing a var nothing reads any more and the change would
// silently do nothing — a test asserting on it would pass or fail for the wrong
// reason. Second, the captured enumerator is called from the host collector's
// own goroutine as well as the link's, so whatever the test mutates has to be
// synchronized: an atomic.Pointer is, a func-typed package var is not.
type networkFixture struct {
	v atomic.Pointer[[]frame.NetworkFacts]
}

// set replaces what the daemon's captured enumerator reports from now on. A nil
// n is a meaningful value, not "unset": it is hostinfo.Networks' encoding for
// "the interface list could not be read at all".
func (f *networkFixture) set(n []frame.NetworkFacts) { f.v.Store(&n) }

// report is the func value installed as hostNetworkFacts. It is never
// reassigned for the lifetime of the daemon under test.
func (f *networkFixture) report() []frame.NetworkFacts { return *f.v.Load() }

// daemonFixtureNetworks is the interface list every startDaemonState test's host
// appears to have: one directly connected private /24, whatever the machine
// running the test actually has plugged in.
//
// It is a named var rather than a literal inside the helper because the scope the
// daemon derives from it is *also* recomputed by the discovery tests, which have
// to state the netscope version a dispatch is authorized under (D-16). Two copies
// of these facts would make that version silently disagree and every discovery
// request refuse itself.
var daemonFixtureNetworks = []frame.NetworkFacts{{
	Name:  "eth0",
	Flags: []string{"up", "broadcast"},
	Addrs: []string{"10.20.0.5/24"},
}}

// startDaemonStateTestDir prepares an isolated state directory with a device
// key and, when grants is non-empty, a pre-seeded grants.json, points
// config.StateDir() at it, and swaps in fakeHostCollector plus the probe and
// discovery host seams for the duration of the test.
//
// Those collector seams are swapped for every startDaemonState test, not only the
// probe and discovery ones: applyProbeConfig and applyDiscoveryConfig both run as
// part of the startup sequence, and their production paths open an unprivileged
// ICMP socket, dump the kernel neighbor cache, read the machine's resolver
// configuration and enumerate its interfaces. None of that belongs in a unit
// test, and the derived scope has to be the same fixed /24 everywhere or an
// assertion would pass or fail on what the test host happens to have plugged in.
func startDaemonStateTestDir(t *testing.T, grants string, readiness []frame.Readiness) (string, *enroll.DeviceKey) {
	t.Helper()
	dir, key, _ := startDaemonStateTestDirNetworks(t, grants, readiness)
	return dir, key
}

// startDaemonStateTestDirNetworks is startDaemonStateTestDir for the tests that
// have to change this host's interface list while the daemon is running: it
// hands back the networkFixture that owns the enumeration so the test can call
// set() at any point, including after startDaemonState has captured the seam.
func startDaemonStateTestDirNetworks(t *testing.T, grants string, readiness []frame.Readiness) (string, *enroll.DeviceKey, *networkFixture) {
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

	prevReadiness, prevFacts := probeReadiness, hostNetworkFacts
	prevDiscoverReadiness := discoverReadiness
	probeReadiness = func() []frame.Readiness {
		items := make([]frame.Readiness, 0, len(probecollect.ProbeNames))
		for _, name := range probecollect.ProbeNames {
			items = append(items, frame.Readiness{Collector: name, State: "ready"})
		}
		return items
	}
	discoverReadiness = func(context.Context) []frame.Readiness {
		items := make([]frame.Readiness, 0, len(discovercollect.DiscoverNames))
		for _, name := range discovercollect.DiscoverNames {
			items = append(items, frame.Readiness{Collector: name, State: "ready"})
		}
		return items
	}
	// Seeded and installed here, before startDaemonState is ever called, so the
	// construction-time capture picks up fx.report and every later change the
	// test makes travels through the fixture rather than through the package var.
	fx := &networkFixture{}
	fx.set(daemonFixtureNetworks)
	hostNetworkFacts = fx.report
	t.Cleanup(func() {
		probeReadiness, hostNetworkFacts = prevReadiness, prevFacts
		discoverReadiness = prevDiscoverReadiness
	})
	return dir, key, fx
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

	if _, err := rt.capGate.ApplyGrants([]byte(`{"host_telemetry":{"enabled":false}}`)); err != nil {
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

	if _, err := rt.capGate.ApplyGrants([]byte(`{"host_telemetry":{"enabled":true,"config":{"interval_s":900}}}`)); err != nil {
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

// --- Task 12: capability grant faults report as readiness (D-6) -----------

// awaitCapabilityReadinessItem reads capability.readiness frames until one
// carries collector, and returns that entry. The host collector publishes on
// its own goroutine, so a test cannot assume the very next frame is the one it
// caused.
func awaitCapabilityReadinessItem(t *testing.T, ch <-chan frame.Frame, collector string) frame.Readiness {
	t.Helper()
	deadline := time.After(5 * time.Second)
	for {
		select {
		case f := <-ch:
			if f.Type != frame.TypeCapabilityReadiness {
				continue
			}
			var payload frame.CapabilityReadinessPayload
			if err := json.Unmarshal(f.Payload, &payload); err != nil {
				t.Fatalf("unmarshal readiness payload %s: %v", f.Payload, err)
			}
			for _, r := range payload.Readiness {
				if r.Collector == collector {
					return r
				}
			}
		case <-deadline:
			t.Fatalf("no capability.readiness frame carrying %q within 5s", collector)
		}
	}
}

// awaitCapabilityReadinessItems waits for a single capability.readiness frame
// that carries every named collector, and returns them together.
//
// Deliberately not two awaitCapabilityReadinessItem calls: each call consumes
// frames, so asserting on two collectors that way needs two frames. The daemon
// coalesces readiness into one payload, so the second frame only ever shows up
// if some other producer (the host collector's asynchronous first report) races
// in — which makes the test pass or hang depending on goroutine scheduling.
func awaitCapabilityReadinessItems(
	t *testing.T, ch <-chan frame.Frame, collectors ...string,
) map[string]frame.Readiness {
	t.Helper()
	deadline := time.After(5 * time.Second)
	for {
		select {
		case f := <-ch:
			if f.Type != frame.TypeCapabilityReadiness {
				continue
			}
			var payload frame.CapabilityReadinessPayload
			if err := json.Unmarshal(f.Payload, &payload); err != nil {
				t.Fatalf("unmarshal readiness payload %s: %v", f.Payload, err)
			}
			got := make(map[string]frame.Readiness, len(collectors))
			for _, r := range payload.Readiness {
				for _, want := range collectors {
					if r.Collector == want {
						got[want] = r
					}
				}
			}
			if len(got) == len(collectors) {
				return got
			}
		case <-deadline:
			t.Fatalf("no single capability.readiness frame carrying all of %v within 5s", collectors)
		}
	}
}

// awaitCapabilityReadinessState reads capability.readiness frames until one
// reports collector in state want.
//
// Deliberately not "read one frame and assert on it": one capabilities.set
// fans out into several publishes — the capability rows, applyProbeConfig's
// probe.* rows, and the host collector's first report on its own goroutine —
// so "the frame my call caused" is not something a test can name. Every frame
// is a full merged snapshot the server applies in order, so what the contract
// actually promises is that the corrected state *reaches* the server, which is
// what this waits for. A state that never clears fails on the deadline.
func awaitCapabilityReadinessState(t *testing.T, ch <-chan frame.Frame, collector, want string) frame.Readiness {
	t.Helper()
	deadline := time.After(5 * time.Second)
	var last string
	for {
		select {
		case f := <-ch:
			if f.Type != frame.TypeCapabilityReadiness {
				continue
			}
			var payload frame.CapabilityReadinessPayload
			if err := json.Unmarshal(f.Payload, &payload); err != nil {
				t.Fatalf("unmarshal readiness payload %s: %v", f.Payload, err)
			}
			for _, r := range payload.Readiness {
				if r.Collector != collector {
					continue
				}
				if r.State == want {
					return r
				}
				last = r.State
			}
		case <-deadline:
			t.Fatalf("%s state = %q after 5s, want %q", collector, last, want)
		}
	}
}

// TestOnCapabilitiesSet_ReportsCapabilityFaultAsDegradedReadiness pins D-6's
// reporting half: a capability whose config fails normalization is not a frame
// failure (onCapabilitiesSet returns nil, so internal/link stops logging it as
// one) — it is a capability.<name> = degraded readiness row, carried on the
// existing capability.readiness channel. A capability that applied cleanly in
// the same payload reports "ready", which is also what clears a corrected
// config's degraded row.
func TestOnCapabilitiesSet_ReportsCapabilityFaultAsDegradedReadiness(t *testing.T) {
	_, key := startDaemonStateTestDir(t, "", nil)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	rt, err := startDaemonState(&config.Config{}, key, "0.1.0-test", ctx)
	if err != nil {
		t.Fatalf("startDaemonState() error = %v", err)
	}
	t.Cleanup(func() { _ = rt.sp.Close() })
	rt.linked.Store(true)
	drainFrames(rt.controlFrames)

	bad := json.RawMessage(`{"host_telemetry":{"enabled":true,"config":{"interval_s":9}},"remote_probe":{"enabled":true}}`)
	if err := rt.onCapabilitiesSet(bad); err != nil {
		t.Fatalf("onCapabilitiesSet() error = %v, want nil — a per-capability fault is not a frame failure", err)
	}

	got := awaitCapabilityReadinessItem(t, rt.controlFrames, "capability.host_telemetry")
	if got.State != "degraded" {
		t.Errorf("capability.host_telemetry state = %q, want %q", got.State, "degraded")
	}
	if got.Reason == "" {
		t.Error("capability.host_telemetry reason is empty, want the normalization failure")
	}
	if got.Remediation == "" {
		t.Error("capability.host_telemetry remediation is empty")
	}
	if probe := awaitCapabilityReadinessItem(t, rt.controlFrames, "capability.remote_probe"); probe.State != "ready" {
		t.Errorf("capability.remote_probe state = %q, want %q — a clean capability in the same payload", probe.State, "ready")
	}
	if !rt.capGate.Allowed("remote_probe") {
		t.Error("Allowed(remote_probe) = false, want true — the good grant in the payload was discarded")
	}

	good := json.RawMessage(`{"host_telemetry":{"enabled":true,"config":{"interval_s":60}},"remote_probe":{"enabled":true}}`)
	if err := rt.onCapabilitiesSet(good); err != nil {
		t.Fatalf("onCapabilitiesSet() error = %v", err)
	}
	awaitCapabilityReadinessState(t, rt.controlFrames, "capability.host_telemetry", "ready")
}

// TestStartDaemonState_CachedGrantFaultIsReportedAtStartup covers the other
// entry point: LoadCached isolates faults the same way, and the daemon
// re-reports them on its first connection rather than swallowing them.
func TestStartDaemonState_CachedGrantFaultIsReportedAtStartup(t *testing.T) {
	_, key := startDaemonStateTestDir(t,
		`{"remote_probe":{"enabled":true},"host_telemetry":{"enabled":true,"config":{"interval_s":0}}}`, nil)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	rt, err := startDaemonState(&config.Config{}, key, "0.1.0-test", ctx)
	if err != nil {
		t.Fatalf("startDaemonState() error = %v", err)
	}
	t.Cleanup(func() { _ = rt.sp.Close() })
	if !rt.capGate.Allowed("remote_probe") {
		t.Error("Allowed(remote_probe) = false after a restart, want true — one bad cached grant dropped the rest")
	}

	// The startup report was published while unlinked; the link coming up is
	// what forces it out, exactly as OnConnected does.
	rt.linked.Store(true)
	rt.queueReadiness(true)

	got := awaitCapabilityReadinessItems(t, rt.controlFrames,
		"capability.host_telemetry", "capability.remote_probe")
	if got["capability.host_telemetry"].State != "degraded" {
		t.Errorf("capability.host_telemetry state = %q at startup, want %q",
			got["capability.host_telemetry"].State, "degraded")
	}
	if got["capability.remote_probe"].State != "ready" {
		t.Errorf("capability.remote_probe state = %q at startup, want %q",
			got["capability.remote_probe"].State, "ready")
	}
}

// ---------------------------------------------------------------------------
// Probe wiring (Task 20). The seams below exist so that not one assertion in
// this section can reach a socket, a resolver, or the interface list of the
// machine the test happens to run on.
// ---------------------------------------------------------------------------

// probeStubChecker stands in for the four real checkers. It reports every check
// it was asked to start and then holds until the test releases it or the run's
// context ends, which is what makes "still in flight" and "never started" both
// observable without any timing assumption inside the runtime.
type probeStubChecker struct {
	started chan string
	block   chan struct{}
}

func newProbeStubChecker() *probeStubChecker {
	return &probeStubChecker{started: make(chan string, 16), block: make(chan struct{})}
}

func (c *probeStubChecker) Check(ctx context.Context, host string, _ json.RawMessage) (probecollect.Outcome, error) {
	select {
	case c.started <- host:
	default:
	}
	select {
	case <-c.block:
	case <-ctx.Done():
		return probecollect.Outcome{}, ctx.Err()
	}
	return probecollect.Outcome{Up: true, Msg: "stub ok"}, nil
}

// awaitCheckStart waits for the next check the stub was asked to run.
func (c *probeStubChecker) awaitCheckStart(t *testing.T) string {
	t.Helper()
	select {
	case host := <-c.started:
		return host
	case <-time.After(5 * time.Second):
		t.Fatal("no check started within 5s")
	}
	return ""
}

// assertNoCheckStart fails if a check starts inside window.
func (c *probeStubChecker) assertNoCheckStart(t *testing.T, window time.Duration) {
	t.Helper()
	select {
	case host := <-c.started:
		t.Fatalf("a check for %q started, want the concurrency limit to hold it back", host)
	case <-time.After(window):
	}
}

// useProbeStubChecker swaps newProbeRuntime for one whose only checker is the
// returned stub, for the duration of the test. It must be called before
// startDaemonState, which is what constructs the runtime.
func useProbeStubChecker(t *testing.T) *probeStubChecker {
	t.Helper()
	stub := newProbeStubChecker()
	prev := newProbeRuntime
	newProbeRuntime = func(out chan<- frame.Frame) *probecollect.Runtime {
		return probecollect.New(out, probecollect.Options{
			Checkers: map[string]probecollect.Checker{
				probecollect.CheckTypeICMP: stub,
				probecollect.CheckTypeTCP:  stub,
				probecollect.CheckTypeHTTP: stub,
				probecollect.CheckTypeDNS:  stub,
			},
			Resolve: func(context.Context, string) ([]string, error) {
				return nil, errors.New("cb-agent test: no test may reach the real resolver")
			},
		})
	}
	t.Cleanup(func() { newProbeRuntime = prev })
	return stub
}

// The scope every probe test below runs under: one directly connected /24, so
// probeInScopeHost is reachable and probeOutOfScopeHost is not, whatever the
// host running the test actually has plugged in.
const (
	probeInScopeHost      = "10.20.0.9"
	probeOtherInScopeHost = "10.20.0.10"
	probeOutOfScopeHost   = "8.8.8.8"
)

// probeAssign builds one probe.assign payload for an immediate TCP check.
func probeAssign(t *testing.T, runID, host string) json.RawMessage {
	t.Helper()
	now := time.Now().UTC()
	data, err := json.Marshal(frame.ProbeAssignPayload{
		RunID:       runID,
		MonitorID:   7,
		CheckType:   probecollect.CheckTypeTCP,
		Host:        host,
		Config:      json.RawMessage(`{}`),
		ScheduledAt: now,
		DeadlineAt:  now.Add(30 * time.Second),
	})
	if err != nil {
		t.Fatalf("marshal probe.assign: %v", err)
	}
	return data
}

// awaitProbeResult reads the next probe.result off the daemon's outbound data
// channel.
func awaitProbeResult(t *testing.T, ch <-chan frame.Frame) frame.ProbeResultPayload {
	t.Helper()
	deadline := time.After(5 * time.Second)
	for {
		select {
		case f := <-ch:
			if f.Type != frame.TypeProbeResult {
				continue
			}
			var payload frame.ProbeResultPayload
			if err := json.Unmarshal(f.Payload, &payload); err != nil {
				t.Fatalf("decode probe.result payload %s: %v", f.Payload, err)
			}
			return payload
		case <-deadline:
			t.Fatal("no probe.result frame within 5s")
		}
	}
}

// TestApplyProbeConfig_DisablePublishesDisabledForEveryProbeName pins the
// probe half of D-4. ingest_readiness only ever upserts — it never deletes —
// so a revoked remote_probe grant that merely returned bare would leave Agent
// Detail showing this vantage as probe-ready for good. Every name in
// probecollect.ProbeNames must be actively overwritten with "disabled", and
// the agent's own identity row must survive that overwrite.
func TestApplyProbeConfig_DisablePublishesDisabledForEveryProbeName(t *testing.T) {
	_, key := startDaemonStateTestDir(t,
		`{"remote_probe":{"enabled":true},"host_telemetry":{"enabled":false}}`, nil)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	rt, err := startDaemonState(&config.Config{}, key, "0.1.0-test", ctx)
	if err != nil {
		t.Fatalf("startDaemonState() error = %v", err)
	}
	t.Cleanup(func() { _ = rt.sp.Close() })
	rt.linked.Store(true)
	rt.queueReadiness(true)

	states, _ := readinessFrameStates(t, awaitReadinessFrame(t, rt.controlFrames))
	for _, name := range probecollect.ProbeNames {
		if states[name] != "ready" {
			t.Fatalf("pre-condition: readiness[%q] = %q, want %q", name, states[name], "ready")
		}
	}
	drainFrames(rt.controlFrames)

	if _, err := rt.capGate.ApplyGrants([]byte(`{"remote_probe":{"enabled":false}}`)); err != nil {
		t.Fatalf("ApplyGrants() error = %v", err)
	}
	rt.applyProbeConfig()

	states, _ = readinessFrameStates(t, awaitReadinessFrame(t, rt.controlFrames))
	for _, name := range probecollect.ProbeNames {
		if states[name] != "disabled" {
			t.Errorf("readiness[%q] = %q after the grant was revoked, want %q", name, states[name], "disabled")
		}
	}
	if states["agent.identity"] == "" {
		t.Errorf("readiness = %v, want it to still carry agent.identity", states)
	}
}

// TestApplyProbeConfig_DisableCancelsInFlightRuns pins the other half of the
// revoke path: a revoked agent must stop probing immediately, not at the end of
// the current deadline, and the backend must be told so rather than left to
// expire the run. Cancellation outranks whatever the checker was doing, so the
// result is `cancelled` — never a target observation nobody made.
func TestApplyProbeConfig_DisableCancelsInFlightRuns(t *testing.T) {
	stub := useProbeStubChecker(t)
	_, key := startDaemonStateTestDir(t,
		`{"remote_probe":{"enabled":true},"host_telemetry":{"enabled":false}}`, nil)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	rt, err := startDaemonState(&config.Config{}, key, "0.1.0-test", ctx)
	if err != nil {
		t.Fatalf("startDaemonState() error = %v", err)
	}
	t.Cleanup(func() { _ = rt.sp.Close() })

	if err := rt.probeRuntime.Assign(probeAssign(t, "run-cancel", probeInScopeHost)); err != nil {
		t.Fatalf("Assign() error = %v", err)
	}
	if host := stub.awaitCheckStart(t); host != probeInScopeHost {
		t.Fatalf("check host = %q, want %q", host, probeInScopeHost)
	}

	if _, err := rt.capGate.ApplyGrants([]byte(`{"remote_probe":{"enabled":false}}`)); err != nil {
		t.Fatalf("ApplyGrants() error = %v", err)
	}
	rt.applyProbeConfig()

	result := awaitProbeResult(t, rt.dataFrames)
	if result.RunID != "run-cancel" {
		t.Errorf("probe.result run_id = %q, want %q", result.RunID, "run-cancel")
	}
	if result.Outcome != probecollect.OutcomeCancelled {
		t.Errorf("probe.result outcome = %q, want %q", result.Outcome, probecollect.OutcomeCancelled)
	}
	if len(result.Samples) != 0 {
		t.Errorf("probe.result samples = %+v, want none — a cancelled run observed nothing", result.Samples)
	}
	if rt.probeRuntime.OpenRuns() != 0 {
		t.Errorf("OpenRuns() = %d after the grant was revoked, want 0", rt.probeRuntime.OpenRuns())
	}
}

// TestApplyProbeConfig_ConcurrencyChangeTakesEffectWithoutRestart pins the
// grant-change path §2 asks for: raising max_concurrent must be picked up by
// the running dispatcher. Rebuilding the runtime instead would abandon every
// in-flight run and hand the backend a batch of timeouts for a change that is
// supposed to be transparent, so the test also asserts the runtime is the same
// object afterwards.
func TestApplyProbeConfig_ConcurrencyChangeTakesEffectWithoutRestart(t *testing.T) {
	stub := useProbeStubChecker(t)
	_, key := startDaemonStateTestDir(t,
		`{"remote_probe":{"enabled":true,"config":{"max_concurrent":1}},"host_telemetry":{"enabled":false}}`, nil)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	rt, err := startDaemonState(&config.Config{}, key, "0.1.0-test", ctx)
	if err != nil {
		t.Fatalf("startDaemonState() error = %v", err)
	}
	t.Cleanup(func() { _ = rt.sp.Close() })
	before := rt.probeRuntime

	for _, assignment := range []struct{ runID, host string }{
		{"run-first", probeInScopeHost},
		{"run-second", probeOtherInScopeHost},
	} {
		if err := rt.probeRuntime.Assign(probeAssign(t, assignment.runID, assignment.host)); err != nil {
			t.Fatalf("Assign(%s) error = %v", assignment.runID, err)
		}
	}
	if host := stub.awaitCheckStart(t); host != probeInScopeHost {
		t.Fatalf("first check host = %q, want %q", host, probeInScopeHost)
	}
	stub.assertNoCheckStart(t, 200*time.Millisecond)

	if _, err := rt.capGate.ApplyGrants([]byte(
		`{"remote_probe":{"enabled":true,"config":{"max_concurrent":2}}}`)); err != nil {
		t.Fatalf("ApplyGrants() error = %v", err)
	}
	rt.applyProbeConfig()

	if host := stub.awaitCheckStart(t); host != probeOtherInScopeHost {
		t.Errorf("second check host = %q, want %q", host, probeOtherInScopeHost)
	}
	if rt.probeRuntime != before {
		t.Error("applyProbeConfig replaced the probe runtime, want the running one reconfigured in place")
	}
}

// TestStartDaemonState_ProbeRuntimeIsWiredAfterTheGate pins the startup
// ordering the probe runtime depends on: the capability gate is restored from
// its on-disk cache *before* the runtime is configured, so a restart while
// disconnected comes back up already enforcing the last scope the server sent.
// A runtime configured before the gate loaded would carry an empty scope and
// refuse every assignment until the first capabilities.set arrived — an
// agent-shaped outage no monitor would explain. Run under -race
// (apps/agent/Makefile's `test` target): the configure path and the runtime's
// own dispatcher are different goroutines.
func TestStartDaemonState_ProbeRuntimeIsWiredAfterTheGate(t *testing.T) {
	stub := useProbeStubChecker(t)
	dir, key := startDaemonStateTestDir(t,
		`{"remote_probe":{"enabled":true,"config":{"max_concurrent":3}},"host_telemetry":{"enabled":false}}`, nil)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	rt, err := startDaemonState(&config.Config{}, key, "0.1.0-test", ctx)
	if err != nil {
		t.Fatalf("startDaemonState() error = %v", err)
	}
	t.Cleanup(func() { _ = rt.sp.Close() })
	if rt.probeRuntime == nil {
		t.Fatal("daemonRuntime.probeRuntime is nil, want a runtime link's probe callbacks can bind to")
	}

	// Readiness for all four check types is reported from startup, without
	// waiting for a connection or a grant push.
	awaitReadiness(t, dir, probecollect.ProbeNames...)

	// The cached grant's scope is already being enforced: a destination on the
	// agent's own directly connected network reaches the checker...
	if err := rt.probeRuntime.Assign(probeAssign(t, "run-in-scope", probeInScopeHost)); err != nil {
		t.Fatalf("Assign(in scope) error = %v", err)
	}
	if host := stub.awaitCheckStart(t); host != probeInScopeHost {
		t.Fatalf("check host = %q, want %q", host, probeInScopeHost)
	}

	// ...and one outside it is refused before anything is dialed.
	if err := rt.probeRuntime.Assign(probeAssign(t, "run-out-of-scope", probeOutOfScopeHost)); err != nil {
		t.Fatalf("Assign(out of scope) error = %v", err)
	}
	result := awaitProbeResult(t, rt.dataFrames)
	if result.RunID != "run-out-of-scope" {
		t.Fatalf("probe.result run_id = %q, want %q", result.RunID, "run-out-of-scope")
	}
	if result.Outcome != probecollect.OutcomeRejected {
		t.Errorf("probe.result outcome = %q, want %q", result.Outcome, probecollect.OutcomeRejected)
	}
	stub.assertNoCheckStart(t, 200*time.Millisecond)
}

// --- Task 13: current networks ride every capability.readiness frame (D-8) ---

// readinessFrameNetworks decodes a capability.readiness frame's `networks` and, separately, the
// raw key as it appeared on the wire. Both are needed: a nil slice and an absent key both decode
// to a nil Networks, and D-8's whole point is that the wire must tell them apart.
func readinessFrameNetworks(t *testing.T, f frame.Frame) ([]frame.NetworkFacts, json.RawMessage) {
	t.Helper()
	if f.Type != frame.TypeCapabilityReadiness {
		t.Fatalf("frame type = %q, want %q", f.Type, frame.TypeCapabilityReadiness)
	}
	var payload frame.CapabilityReadinessPayload
	if err := json.Unmarshal(f.Payload, &payload); err != nil {
		t.Fatalf("unmarshal readiness payload %s: %v", f.Payload, err)
	}
	var keys map[string]json.RawMessage
	if err := json.Unmarshal(f.Payload, &keys); err != nil {
		t.Fatalf("unmarshal readiness payload %s as a map: %v", f.Payload, err)
	}
	raw, ok := keys["networks"]
	if !ok {
		t.Fatalf("readiness payload %s carries no `networks` key — the field must have no omitempty", f.Payload)
	}
	return payload.Networks, raw
}

// TestPublishReadiness_CarriesTheCurrentNetworks pins D-8: `hello` reports this host's directly
// connected networks only at connect, so without them on the periodic frame a subnet that came up
// on this machine would not become discoverable until the next reconnect — which may be days.
func TestPublishReadiness_CarriesTheCurrentNetworks(t *testing.T) {
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

	networks, _ := readinessFrameNetworks(t, awaitReadinessFrame(t, rt.controlFrames))
	want := hostNetworkFacts()
	if !reflect.DeepEqual(networks, want) {
		t.Fatalf("readiness networks = %+v, want the host enumerator's own report %+v", networks, want)
	}
}

// TestPublishReadiness_AnEmptyNetworkListIsReportedAsSuch is the load-bearing half of D-8's
// no-omitempty tag. An agent that has lost every interface must be able to say `[]`: the server
// gates persistence on the key's presence, so a dropped field would leave it standing on a stale,
// wider-than-reality scope forever. It must also be a *change* — the frame has to go out now
// rather than at the next rate-limit window.
func TestPublishReadiness_AnEmptyNetworkListIsReportedAsSuch(t *testing.T) {
	_, key, fx := startDaemonStateTestDirNetworks(t, `{"host_telemetry":{"enabled":false}}`, nil)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	rt, err := startDaemonState(&config.Config{}, key, "0.1.0-test", ctx)
	if err != nil {
		t.Fatalf("startDaemonState() error = %v", err)
	}
	t.Cleanup(func() { _ = rt.sp.Close() })
	rt.linked.Store(true)
	rt.publishReadiness([]frame.Readiness{{Collector: "host.core", State: "ready"}})
	awaitReadinessFrame(t, rt.controlFrames)
	drainFrames(rt.controlFrames)

	// Every interface has gone away, but the enumeration itself succeeded.
	fx.set([]frame.NetworkFacts{})
	rt.publishReadiness([]frame.Readiness{{Collector: "host.core", State: "ready"}})

	networks, raw := readinessFrameNetworks(t, awaitReadinessFrame(t, rt.controlFrames))
	if len(networks) != 0 {
		t.Errorf("readiness networks = %+v, want none", networks)
	}
	if string(raw) != "[]" {
		t.Errorf("readiness networks encoded as %s, want [] — null is not a report the server can read", raw)
	}
}

// TestPublishReadiness_AnUnreadableInterfaceListRepeatsTheLastReport covers the case the wire has
// no encoding for. hostinfo.Networks returns nil when the interface list could not be read at all,
// and `networks` carries no omitempty, so the frame must say *something*: sending that nil as `[]`
// would claim every interface had disappeared and wipe a working scope — and bump the server's
// scope generation — every time /sys/class/net was momentarily unreadable.
func TestPublishReadiness_AnUnreadableInterfaceListRepeatsTheLastReport(t *testing.T) {
	_, key, fx := startDaemonStateTestDirNetworks(t, `{"host_telemetry":{"enabled":false}}`, nil)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	rt, err := startDaemonState(&config.Config{}, key, "0.1.0-test", ctx)
	if err != nil {
		t.Fatalf("startDaemonState() error = %v", err)
	}
	t.Cleanup(func() { _ = rt.sp.Close() })
	rt.linked.Store(true)
	rt.publishReadiness([]frame.Readiness{{Collector: "host.core", State: "ready"}})
	want, _ := readinessFrameNetworks(t, awaitReadinessFrame(t, rt.controlFrames))
	if len(want) == 0 {
		t.Fatal("the fixture enumerator reported no networks; this test asserts one is not lost")
	}
	drainFrames(rt.controlFrames)

	fx.set(nil)
	rt.publishReadiness([]frame.Readiness{{Collector: "host.core", State: "degraded"}})

	networks, raw := readinessFrameNetworks(t, awaitReadinessFrame(t, rt.controlFrames))
	if string(raw) == "null" {
		t.Fatalf("readiness networks encoded as null; the field is list-typed on the server")
	}
	if !reflect.DeepEqual(networks, want) {
		t.Errorf("readiness networks = %+v after an unreadable interface list, want the last real report %+v", networks, want)
	}
}

// TestQueueReadiness_ADroppedForcedFrameSurvivesTheRateLimitFloor pins the recovery half of D-8's
// "the frame has to go out now": a forced frame that could not be enqueued must still be sent at
// the next opportunity rather than swallowed.
//
// The send onto controlFrames is deliberately non-blocking — the channel is bounded and
// publishReadiness runs on the host collector's goroutine, which must not stall behind the link's
// websocket writer — so a force *can* be dropped when the writer is behind. By that point
// publishReadiness has already overwritten readinessPayload, which makes the dropped change the new
// dedup baseline: no later publish of the same state looks changed again, and the reconcile tick's
// unforced queueReadiness is refused by the readinessReportInterval floor. Without a pending-force
// memory the change is therefore never sent at all, and a networks-only change (which nothing else
// re-reports) waits a whole report interval — exactly the wiped-scope window D-8 exists to close.
func TestQueueReadiness_ADroppedForcedFrameSurvivesTheRateLimitFloor(t *testing.T) {
	_, key, fx := startDaemonStateTestDirNetworks(t, `{"host_telemetry":{"enabled":false}}`, nil)
	// A floor and a tick longer than the test can possibly run, so the delivery asserted below can
	// only be the surviving force — never the rate-limit window elapsing or the reconciler firing.
	shrinkReadinessTimers(t, time.Hour, time.Hour)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	rt, err := startDaemonState(&config.Config{}, key, "0.1.0-test", ctx)
	if err != nil {
		t.Fatalf("startDaemonState() error = %v", err)
	}
	t.Cleanup(func() { _ = rt.sp.Close() })
	rt.linked.Store(true)

	// One successful send first: the floor only bites once readinessSentAt has been stamped.
	rt.publishReadiness([]frame.Readiness{{Collector: "host.core", State: "ready"}})
	awaitReadinessFrame(t, rt.controlFrames)
	drainFrames(rt.controlFrames)

	// Now fill the channel so the next forced send has nowhere to go. Heartbeats are used as
	// filler because they are the one control frame this test never asserts on.
	for len(rt.controlFrames) < cap(rt.controlFrames) {
		rt.controlFrames <- frame.Frame{Type: frame.TypeHeartbeat, TS: time.Now().UTC()}
	}

	// A networks-only change: the readiness half of the payload is identical, so nothing but the
	// preserved force can get this onto the wire.
	fx.set([]frame.NetworkFacts{})
	rt.publishReadiness([]frame.Readiness{{Collector: "host.core", State: "ready"}})

	// The writer catches up. Every frame drained here must be filler — if a readiness frame is
	// among them the channel was not actually full and the test proves nothing.
	for n := 0; n < cap(rt.controlFrames); n++ {
		f := <-rt.controlFrames
		if f.Type == frame.TypeCapabilityReadiness {
			t.Fatalf("frame %d was %q; the forced send was not dropped, so this test is vacuous", n, f.Type)
		}
	}

	// An unforced caller, standing in for the reconcile tick. Inside the floor it may only send
	// because the dropped force is still owed.
	rt.queueReadiness(false)
	networks, raw := readinessFrameNetworks(t, awaitReadinessFrame(t, rt.controlFrames))
	if len(networks) != 0 || string(raw) != "[]" {
		t.Errorf("readiness networks = %+v (raw %s), want the dropped change's empty list", networks, raw)
	}
}

// --- Task 14: the discovery runtime's daemon wiring ---

// discoveryNeighborStub is the injected kernel-neighbor-cache read every
// discovery test below runs against, and the handle they use to hold a dispatch
// open.
//
// The neighbor cache is the only one of discovery's four collectors whose
// dependency is injectable from outside internal/collect/discover
// (discover.RuntimeOptions.Neighbors; Liveness' socket and dialer are
// unexported), and it is the only one these tests use: every request below names
// methods ["neighbor_cache"] with no tcp_ports, which is exactly the shape that
// makes discover.Liveness open nothing at all — its ICMP half and its TCP half
// are both gated on the request's method list. A cmd-level test that let the
// sweep run would be probing whatever is really on the runner's 10.20.0.0/24.
//
// hold is what makes "in flight" observable. The cache is read once per dispatch,
// inside the scan and before any sweep, so a read that blocks is a dispatch the
// runtime has genuinely started and not yet summarised — which is the state
// D-14's disable path and plan §4's cancellation both have to interrupt.
type discoveryNeighborStub struct {
	entries []discovercollect.Neighbor

	// reads receives one value per read, so a test can wait for the dispatch to
	// have actually reached the collector.
	reads chan struct{}
	// hold blocks every read until it is closed. A non-blocking stub is
	// constructed with it already closed.
	hold chan struct{}
	// calls counts reads, so a test can assert that a refused request never
	// looked at the host at all.
	calls atomic.Int64
}

func (s *discoveryNeighborStub) read(ctx context.Context) ([]discovercollect.Neighbor, error) {
	s.calls.Add(1)
	select {
	case s.reads <- struct{}{}:
	default:
	}
	select {
	case <-s.hold:
	case <-ctx.Done():
		return nil, ctx.Err()
	}
	return s.entries, nil
}

// awaitRead waits for the next neighbor-cache read.
func (s *discoveryNeighborStub) awaitRead(t *testing.T) {
	t.Helper()
	select {
	case <-s.reads:
	case <-time.After(5 * time.Second):
		t.Fatal("no discovery dispatch reached the neighbor cache within 5s")
	}
}

// useDiscoveryStub swaps newDiscoverRuntime for one whose only host-facing
// dependency is the returned stub, for the duration of the test. It must be
// called before startDaemonState, which is what constructs the runtime.
//
// blocking chooses whether a dispatch runs to completion or parks in the
// collector until the test releases it.
func useDiscoveryStub(t *testing.T, blocking bool) *discoveryNeighborStub {
	t.Helper()
	stub := &discoveryNeighborStub{
		entries: []discovercollect.Neighbor{{
			IP:    netip.MustParseAddr(discoveryKnownHost),
			MAC:   discoveryKnownMAC,
			State: discovercollect.NeighborReachable,
		}},
		reads: make(chan struct{}, 16),
		hold:  make(chan struct{}),
	}
	if !blocking {
		close(stub.hold)
	}
	// Released unconditionally at the end of the test: a dispatch still parked in
	// the collector would otherwise keep its goroutine alive past the assertions.
	t.Cleanup(func() {
		select {
		case <-stub.hold:
		default:
			close(stub.hold)
		}
	})

	prev := newDiscoverRuntime
	newDiscoverRuntime = func(out chan<- frame.Frame) *discovercollect.Runtime {
		return discovercollect.NewRuntime(out, discovercollect.RuntimeOptions{Neighbors: stub.read})
	}
	t.Cleanup(func() { newDiscoverRuntime = prev })
	return stub
}

// The one discovery topology every test below runs under. The target is a /30
// inside the fixture host's own directly connected /24, so it is neither the
// enclosing network's address nor its directed broadcast and netscope enumerates
// all four of its addresses; exactly one of them is in the stubbed neighbor
// cache, so a completed dispatch reports exactly one host.
const (
	discoveryInScopeTarget    = "10.20.0.8/30"
	discoveryOutOfScopeTarget = "8.8.8.0/30"
	discoveryTargetAddresses  = 4
	discoveryKnownHost        = "10.20.0.9"
	discoveryKnownMAC         = "aa:bb:cc:dd:ee:ff"
)

// Dispatch ids the backend would mint: exactly 32 lowercase hex characters.
// Distinct per request in a test, because the runtime refuses a duplicate id
// while the first one is still open.
const (
	discoveryDispatchOne   = "a1b2c3d4e5f60718293a4b5c6d7e8f90"
	discoveryDispatchTwo   = "b2c3d4e5f60718293a4b5c6d7e8f90a1"
	discoveryDispatchThree = "c3d4e5f60718293a4b5c6d7e8f90a1b2"
)

// discoveryHostTimeoutMS is the per-address budget every request below carries.
// Named because the assertions about how fast a cancellation takes effect are
// derived from it rather than written as a bare duration.
const discoveryHostTimeoutMS = 200

// discoveryScopeVersion recomputes the netscope version the daemon under test
// derives, from the same fixture interface list startDaemonStateTestDirNetworks
// installs plus the grant's own scope config.
//
// It is recomputed rather than read back off the runtime on purpose: D-16's
// contract is that the server and the agent derive the same version
// independently, and a test that asked the runtime what version it happened to
// hold would pin nothing at all.
func discoveryScopeVersion(cfg capability.LocalDiscoveryConfig) string {
	return netscope.Derive(probeInterfaceFacts(daemonFixtureNetworks), cfg.Config).Version
}

// discoveryRequest builds one discovery.request payload for a neighbor-cache-only
// scan of target, carrying the scope version the daemon is expected to hold.
func discoveryRequest(t *testing.T, dispatchID, target, scopeVersion string) json.RawMessage {
	t.Helper()
	data, err := json.Marshal(frame.DiscoveryRequestPayload{
		DispatchID:         dispatchID,
		ScanJobID:          41,
		Targets:            []string{target},
		Methods:            []string{discovercollect.MethodNeighborCache},
		HostTimeoutMS:      discoveryHostTimeoutMS,
		MaxConcurrentHosts: discoveryTargetAddresses,
		ScopeVersion:       scopeVersion,
		DeadlineAt:         time.Now().UTC().Add(30 * time.Second),
	})
	if err != nil {
		t.Fatalf("marshal discovery.request: %v", err)
	}
	return data
}

// discoveryCancel builds one discovery.cancel payload.
func discoveryCancel(t *testing.T, dispatchID, reason string) json.RawMessage {
	t.Helper()
	data, err := json.Marshal(frame.DiscoveryCancelPayload{DispatchID: dispatchID, Reason: reason})
	if err != nil {
		t.Fatalf("marshal discovery.cancel: %v", err)
	}
	return data
}

// awaitDiscoveryDispatch drains the daemon's outbound *data* channel until the
// dispatch's single terminal summary arrives, and returns the host findings that
// preceded it alongside that summary.
//
// Reading from dataFrames rather than controlFrames is itself an assertion: a
// discovery.finding is a data frame, so it spools through an outage instead of
// being dropped while disconnected, which is the whole reason finding ids are
// replay-stable.
func awaitDiscoveryDispatch(
	t *testing.T, ch <-chan frame.Frame, dispatchID string,
) ([]frame.DiscoveryFindingPayload, frame.DiscoveryFindingPayload) {
	t.Helper()
	var hosts []frame.DiscoveryFindingPayload
	deadline := time.After(5 * time.Second)
	for {
		select {
		case f := <-ch:
			if f.Type != frame.TypeDiscoveryFinding {
				continue
			}
			var payload frame.DiscoveryFindingPayload
			if err := json.Unmarshal(f.Payload, &payload); err != nil {
				t.Fatalf("decode discovery.finding payload %s: %v", f.Payload, err)
			}
			if payload.DispatchID != dispatchID {
				t.Fatalf("discovery.finding dispatch_id = %q, want %q", payload.DispatchID, dispatchID)
			}
			if !payload.Terminal {
				hosts = append(hosts, payload)
				continue
			}
			return hosts, payload
		case <-deadline:
			t.Fatalf("no terminal discovery.finding for %q within 5s (host findings so far: %d)",
				dispatchID, len(hosts))
		}
	}
}

// TestStartDaemonState_DiscoveryRuntimeIsWiredAfterTheGate pins the startup
// ordering the discovery runtime depends on, exactly as its probe counterpart
// does: the capability gate is restored from its on-disk cache *before* the
// runtime is configured, so a restart while disconnected comes back up already
// enforcing the last scope and the last bounds the server sent. A runtime
// configured before the gate loaded would hold an empty scope and refuse every
// dispatch until the first capabilities.set arrived.
//
// It also pins that the runtime's findings leave on the daemon's data channel and
// that discovery readiness is reported from startup, without waiting for a
// connection or a grant push. Run under -race (apps/agent/Makefile's `test`
// target): the configure path and the runtime's dispatcher are different
// goroutines.
func TestStartDaemonState_DiscoveryRuntimeIsWiredAfterTheGate(t *testing.T) {
	stub := useDiscoveryStub(t, false)
	dir, key := startDaemonStateTestDir(t,
		`{"local_discovery":{"enabled":true},"host_telemetry":{"enabled":false}}`, nil)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	rt, err := startDaemonState(&config.Config{}, key, "0.1.0-test", ctx)
	if err != nil {
		t.Fatalf("startDaemonState() error = %v", err)
	}
	t.Cleanup(func() { _ = rt.sp.Close() })
	if rt.discoverRuntime == nil {
		t.Fatal("daemonRuntime.discoverRuntime is nil, want a runtime link's discovery callbacks can bind to")
	}

	awaitReadiness(t, dir, discovercollect.DiscoverNames...)

	version := discoveryScopeVersion(capability.DefaultLocalDiscoveryConfig())
	if err := rt.discoverRuntime.Request(
		discoveryRequest(t, discoveryDispatchOne, discoveryInScopeTarget, version)); err != nil {
		t.Fatalf("Request(in scope) error = %v", err)
	}
	hosts, summary := awaitDiscoveryDispatch(t, rt.dataFrames, discoveryDispatchOne)
	if len(hosts) != 1 {
		t.Fatalf("host findings = %+v, want exactly the one address in the neighbor cache", hosts)
	}
	if hosts[0].IPAddress != discoveryKnownHost || hosts[0].MACAddress != discoveryKnownMAC {
		t.Errorf("host finding = %+v, want ip %q and mac %q",
			hosts[0], discoveryKnownHost, discoveryKnownMAC)
	}
	if summary.Outcome != frame.DiscoveryOutcomeCompleted {
		t.Errorf("summary outcome = %q (msg %q), want %q",
			summary.Outcome, summary.Msg, frame.DiscoveryOutcomeCompleted)
	}
	if summary.AddressesScanned == nil || *summary.AddressesScanned != discoveryTargetAddresses {
		t.Errorf("summary addresses_scanned = %v, want %d",
			summary.AddressesScanned, discoveryTargetAddresses)
	}

	// The cached grant's scope is already being enforced: a target on no network
	// this host is attached to is refused before the collector is ever read.
	before := stub.calls.Load()
	if err := rt.discoverRuntime.Request(
		discoveryRequest(t, discoveryDispatchTwo, discoveryOutOfScopeTarget, version)); err == nil {
		t.Fatal("Request(out of scope) error = nil, want the refusal the validator makes")
	}
	_, summary = awaitDiscoveryDispatch(t, rt.dataFrames, discoveryDispatchTwo)
	if summary.Outcome != frame.DiscoveryOutcomeRejected {
		t.Errorf("summary outcome = %q, want %q", summary.Outcome, frame.DiscoveryOutcomeRejected)
	}
	if summary.ErrorCode == "" {
		t.Error("summary error_code is empty, want the machine-readable scope reason")
	}
	if got := stub.calls.Load(); got != before {
		t.Errorf("neighbor cache reads = %d after a refused request, want %d — a refusal must touch nothing",
			got, before)
	}
}

// TestStartDaemonState_DiscoveryRuntimeScansNothingWhileUngranted is the "starts
// only when local_discovery is granted" half of Task 14.
//
// The runtime *object* is constructed and started unconditionally, for the same
// reason the probe runtime is: link's callbacks bind to it once, so a dispatch
// that arrives for an ungranted agent has to be refused with a terminal summary
// that closes the job rather than dropped on a nil handler — and once
// local_discovery is off, agent_link's grant gate would drop the agent's own
// summary, so a dispatch nobody refuses is a job nothing ever closes. What must
// not start is the *work*: no collector is read, no socket is opened, and every
// discovery readiness row says so.
func TestStartDaemonState_DiscoveryRuntimeScansNothingWhileUngranted(t *testing.T) {
	stub := useDiscoveryStub(t, false)
	_, key := startDaemonStateTestDir(t,
		`{"local_discovery":{"enabled":false},"host_telemetry":{"enabled":false}}`, nil)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	rt, err := startDaemonState(&config.Config{}, key, "0.1.0-test", ctx)
	if err != nil {
		t.Fatalf("startDaemonState() error = %v", err)
	}
	t.Cleanup(func() { _ = rt.sp.Close() })

	version := discoveryScopeVersion(capability.DefaultLocalDiscoveryConfig())
	err = rt.discoverRuntime.Request(
		discoveryRequest(t, discoveryDispatchOne, discoveryInScopeTarget, version))
	if !errors.Is(err, discovercollect.ErrNotEnabled) {
		t.Fatalf("Request() error = %v, want %v", err, discovercollect.ErrNotEnabled)
	}
	hosts, summary := awaitDiscoveryDispatch(t, rt.dataFrames, discoveryDispatchOne)
	if len(hosts) != 0 {
		t.Errorf("host findings = %+v, want none — an ungranted agent observed nothing", hosts)
	}
	if summary.Outcome != frame.DiscoveryOutcomeRejected {
		t.Errorf("summary outcome = %q, want %q", summary.Outcome, frame.DiscoveryOutcomeRejected)
	}
	if summary.ErrorCode != discovercollect.ErrorCodeCapabilityDisabled {
		t.Errorf("summary error_code = %q, want %q",
			summary.ErrorCode, discovercollect.ErrorCodeCapabilityDisabled)
	}
	if got := stub.calls.Load(); got != 0 {
		t.Errorf("neighbor cache reads = %d, want 0 — an ungranted capability may perform no work", got)
	}
}

// TestApplyDiscoveryConfig_DisablePublishesDisabledForEveryDiscoverName pins the
// discovery half of D-4. ingest_readiness only ever upserts — it never deletes —
// so a revoked local_discovery grant that merely returned bare would leave Agent
// Detail reading this vantage as a discovery-ready one for good. Every name in
// discover.DiscoverNames must be actively overwritten with "disabled" on the one
// readiness sink publishReadiness owns, and the agent's own identity row must
// survive that overwrite.
func TestApplyDiscoveryConfig_DisablePublishesDisabledForEveryDiscoverName(t *testing.T) {
	_, key := startDaemonStateTestDir(t,
		`{"local_discovery":{"enabled":true},"host_telemetry":{"enabled":false}}`, nil)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	rt, err := startDaemonState(&config.Config{}, key, "0.1.0-test", ctx)
	if err != nil {
		t.Fatalf("startDaemonState() error = %v", err)
	}
	t.Cleanup(func() { _ = rt.sp.Close() })
	rt.linked.Store(true)
	rt.queueReadiness(true)

	states, _ := readinessFrameStates(t, awaitReadinessFrame(t, rt.controlFrames))
	for _, name := range discovercollect.DiscoverNames {
		if states[name] != "ready" {
			t.Fatalf("pre-condition: readiness[%q] = %q, want %q", name, states[name], "ready")
		}
	}
	drainFrames(rt.controlFrames)

	if _, err := rt.capGate.ApplyGrants([]byte(`{"local_discovery":{"enabled":false}}`)); err != nil {
		t.Fatalf("ApplyGrants() error = %v", err)
	}
	rt.applyDiscoveryConfig()

	states, _ = readinessFrameStates(t, awaitReadinessFrame(t, rt.controlFrames))
	for _, name := range discovercollect.DiscoverNames {
		if states[name] != "disabled" {
			t.Errorf("readiness[%q] = %q after the grant was revoked, want %q", name, states[name], "disabled")
		}
	}
	if states["agent.identity"] == "" {
		t.Errorf("readiness = %v, want it to still carry agent.identity", states)
	}
}

// TestOnCapabilitiesSet_DisablingLocalDiscoveryCancelsInFlightWorkAndStopsFutureWork
// pins D-14 at the daemon's own seam: the whole path from a server
// capabilities.set that turns local_discovery off, through the gate, to a
// dispatch that stops now rather than at the end of its deadline.
//
// It has to go through onCapabilitiesSet rather than calling
// applyDiscoveryConfig directly, because the frame handler is what the server
// actually reaches — a wiring that installed the grant but forgot to re-apply the
// discovery half would pass an applyDiscoveryConfig-only test and leave a revoked
// agent scanning.
//
// Both halves are asserted. Cancelling in flight: the running dispatch is closed
// out with a `cancelled` summary, because once the grant is off agent_link's
// grant gate drops the agent's own terminal summary and a dispatch nobody closes
// is a job that hangs for its whole dispatch deadline. Stopping future work: the
// next dispatch is refused with `capability_disabled` and never reaches the
// collector.
func TestOnCapabilitiesSet_DisablingLocalDiscoveryCancelsInFlightWorkAndStopsFutureWork(t *testing.T) {
	stub := useDiscoveryStub(t, true)
	_, key := startDaemonStateTestDir(t,
		`{"local_discovery":{"enabled":true},"host_telemetry":{"enabled":false}}`, nil)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	rt, err := startDaemonState(&config.Config{}, key, "0.1.0-test", ctx)
	if err != nil {
		t.Fatalf("startDaemonState() error = %v", err)
	}
	t.Cleanup(func() { _ = rt.sp.Close() })

	version := discoveryScopeVersion(capability.DefaultLocalDiscoveryConfig())
	if err := rt.discoverRuntime.Request(
		discoveryRequest(t, discoveryDispatchOne, discoveryInScopeTarget, version)); err != nil {
		t.Fatalf("Request() error = %v", err)
	}
	stub.awaitRead(t)

	if err := rt.onCapabilitiesSet([]byte(`{"local_discovery":{"enabled":false}}`)); err != nil {
		t.Fatalf("onCapabilitiesSet() error = %v", err)
	}

	_, summary := awaitDiscoveryDispatch(t, rt.dataFrames, discoveryDispatchOne)
	if summary.Outcome != frame.DiscoveryOutcomeCancelled {
		t.Errorf("summary outcome = %q (msg %q), want %q",
			summary.Outcome, summary.Msg, frame.DiscoveryOutcomeCancelled)
	}
	if rt.discoverRuntime.OpenDispatches() != 0 {
		t.Errorf("OpenDispatches() = %d after the grant was revoked, want 0",
			rt.discoverRuntime.OpenDispatches())
	}

	before := stub.calls.Load()
	err = rt.discoverRuntime.Request(
		discoveryRequest(t, discoveryDispatchTwo, discoveryInScopeTarget, version))
	if !errors.Is(err, discovercollect.ErrNotEnabled) {
		t.Fatalf("Request() after revocation error = %v, want %v", err, discovercollect.ErrNotEnabled)
	}
	_, summary = awaitDiscoveryDispatch(t, rt.dataFrames, discoveryDispatchTwo)
	if summary.ErrorCode != discovercollect.ErrorCodeCapabilityDisabled {
		t.Errorf("summary error_code = %q, want %q",
			summary.ErrorCode, discovercollect.ErrorCodeCapabilityDisabled)
	}
	if got := stub.calls.Load(); got != before {
		t.Errorf("neighbor cache reads = %d after revocation, want %d — no future work may start",
			got, before)
	}
}

// TestOnCapabilitiesSet_DiscoveryBoundsAreReAppliedWithoutRestart pins the
// grant-change path plan §2 asks for: a rewritten local_discovery config must be
// what the *next* dispatch is judged against, with no restart. Rebuilding the
// runtime instead would abandon every dispatch in flight and hand the backend a
// batch of expired jobs for a change that is supposed to be transparent, so this
// also asserts the runtime is the same object afterwards.
//
// max_addresses_per_job is the bound under test because it is enforced by the
// validator the grant builds rather than by anything the request carries: a
// wiring that installed the new grant but never rebuilt the validator would keep
// refusing the same target forever.
func TestOnCapabilitiesSet_DiscoveryBoundsAreReAppliedWithoutRestart(t *testing.T) {
	stub := useDiscoveryStub(t, false)
	_, key := startDaemonStateTestDir(t,
		`{"local_discovery":{"enabled":true,"config":{"max_addresses_per_job":1}},"host_telemetry":{"enabled":false}}`,
		nil)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	rt, err := startDaemonState(&config.Config{}, key, "0.1.0-test", ctx)
	if err != nil {
		t.Fatalf("startDaemonState() error = %v", err)
	}
	t.Cleanup(func() { _ = rt.sp.Close() })
	before := rt.discoverRuntime

	// The scope is unchanged by either grant — max_addresses_per_job is not one of
	// the four fields netscope digests — so one version covers both halves.
	version := discoveryScopeVersion(capability.DefaultLocalDiscoveryConfig())

	if err := rt.discoverRuntime.Request(
		discoveryRequest(t, discoveryDispatchOne, discoveryInScopeTarget, version)); err == nil {
		t.Fatal("Request() error = nil, want the address ceiling to refuse a /30 under a grant of 1")
	}
	_, summary := awaitDiscoveryDispatch(t, rt.dataFrames, discoveryDispatchOne)
	if summary.ErrorCode != discovercollect.ErrorCodeAddressLimit {
		t.Fatalf("summary error_code = %q (msg %q), want %q",
			summary.ErrorCode, summary.Msg, discovercollect.ErrorCodeAddressLimit)
	}
	if got := stub.calls.Load(); got != 0 {
		t.Errorf("neighbor cache reads = %d, want 0 — a refused request touches nothing", got)
	}

	if err := rt.onCapabilitiesSet([]byte(
		`{"local_discovery":{"enabled":true,"config":{"max_addresses_per_job":4}}}`)); err != nil {
		t.Fatalf("onCapabilitiesSet() error = %v", err)
	}

	if err := rt.discoverRuntime.Request(
		discoveryRequest(t, discoveryDispatchTwo, discoveryInScopeTarget, version)); err != nil {
		t.Fatalf("Request() after the raised ceiling error = %v", err)
	}
	hosts, summary := awaitDiscoveryDispatch(t, rt.dataFrames, discoveryDispatchTwo)
	if summary.Outcome != frame.DiscoveryOutcomeCompleted {
		t.Errorf("summary outcome = %q (msg %q), want %q",
			summary.Outcome, summary.Msg, frame.DiscoveryOutcomeCompleted)
	}
	if len(hosts) != 1 {
		t.Errorf("host findings = %+v, want the one address in the neighbor cache", hosts)
	}
	if rt.discoverRuntime != before {
		t.Error("applyDiscoveryConfig replaced the discovery runtime, want the running one reconfigured in place")
	}
}

// generateDaemonTestKeypair and daemonTestResponder are a third copy of internal/link's and
// internal/enroll's Noise test responder, duplicated for the same reason those two are duplicates
// of each other: this repo has no shared Go test-utility package, and neither existing copy is
// exported. They exist here because the one thing cmd/cb-agent owns that no other package can
// check is whether the daemon's *own* link options deliver an inbound frame to the runtime that
// has to act on it.
func generateDaemonTestKeypair(t *testing.T) (priv, pub [32]byte) {
	t.Helper()
	dhKey, err := noise.DH25519.GenerateKeypair(rand.Reader)
	if err != nil {
		t.Fatalf("GenerateKeypair() error = %v", err)
	}
	copy(priv[:], dhKey.Private)
	copy(pub[:], dhKey.Public)
	return priv, pub
}

type daemonTestResponder struct {
	hs   *noise.HandshakeState
	send *noise.CipherState // responder -> agent
	recv *noise.CipherState // agent -> responder
}

func newDaemonTestResponder(t *testing.T, priv, pub [32]byte) *daemonTestResponder {
	t.Helper()
	cs := noise.NewCipherSuite(noise.DH25519, noise.CipherChaChaPoly, noise.HashSHA256)
	hs, err := noise.NewHandshakeState(noise.Config{
		CipherSuite:   cs,
		Pattern:       noise.HandshakeIK,
		Initiator:     false,
		StaticKeypair: noise.DHKey{Private: priv[:], Public: pub[:]},
	})
	if err != nil {
		t.Fatalf("NewHandshakeState() error = %v", err)
	}
	return &daemonTestResponder{hs: hs}
}

func (s *daemonTestResponder) readHandshakeMessage(msg1 []byte) ([]byte, error) {
	if _, _, _, err := s.hs.ReadMessage(nil, msg1); err != nil {
		return nil, fmt.Errorf("daemonTestResponder: read message 1: %w", err)
	}
	msg2, c1, c2, err := s.hs.WriteMessage(nil, nil)
	if err != nil {
		return nil, fmt.Errorf("daemonTestResponder: write message 2: %w", err)
	}
	s.recv, s.send = c1, c2
	return msg2, nil
}

func (s *daemonTestResponder) encrypt(plaintext []byte) []byte {
	ct, err := s.send.Encrypt(nil, nil, plaintext)
	if err != nil {
		panic(fmt.Sprintf("daemonTestResponder: encrypt: %v", err))
	}
	return ct
}

func (s *daemonTestResponder) decrypt(ciphertext []byte) ([]byte, error) {
	pt, err := s.recv.Decrypt(nil, nil, ciphertext)
	if err != nil {
		return nil, fmt.Errorf("daemonTestResponder: decrypt: %w", err)
	}
	return pt, nil
}

// discoveryLinkServer is a minimal stand-in for the backend's link endpoint
// (api/ws_agents.py's link_stream): it completes the Noise handshake, accepts the hello,
// dispatches one `discovery.request`, sends the matching `discovery.cancel` when the test says
// so, and surfaces every `discovery.finding` the agent sends back.
//
// It is a real socket rather than a direct call into daemonRuntime because the two things being
// pinned here are exactly the two that a direct call cannot see: that internal/link has an
// inbound arm for each of these frame types, and that runDaemon's own link options bind those
// arms to the discovery runtime.
type discoveryLinkServer struct {
	url         string
	serverPKHex string
	// findings carries every discovery.finding frame the agent sent, decrypted and decoded, in
	// the order it sent them.
	findings chan frame.Frame
	// cancelNow releases the discovery.cancel write. Cancellation is ordered *after* the
	// dispatch has demonstrably reached the collector rather than racing it, because a
	// cancellation that lands first is a different scenario (a queued dispatch closed out
	// without ever running) and would pin nothing about a running one.
	cancelNow chan struct{}
	// done releases the handler at teardown. httptest.Server.Close blocks until its handlers
	// return, and this one deliberately parks on the connection so the link stays up.
	done chan struct{}
}

func (s *discoveryLinkServer) sendCancel() { close(s.cancelNow) }

func newDiscoveryLinkServer(t *testing.T, request, cancellation json.RawMessage) *discoveryLinkServer {
	t.Helper()
	serverPriv, serverPub := generateDaemonTestKeypair(t)
	s := &discoveryLinkServer{
		serverPKHex: hex.EncodeToString(serverPub[:]),
		findings:    make(chan frame.Frame, 64),
		cancelNow:   make(chan struct{}),
		done:        make(chan struct{}),
	}

	upgrader := websocket.Upgrader{}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			t.Errorf("upgrade: %v", err)
			return
		}
		defer conn.Close()

		responder := newDaemonTestResponder(t, serverPriv, serverPub)
		_, msg1, err := conn.ReadMessage()
		if err != nil {
			return
		}
		msg2, err := responder.readHandshakeMessage(msg1)
		if err != nil {
			t.Errorf("responder handshake: %v", err)
			return
		}
		if err := conn.WriteMessage(websocket.BinaryMessage, msg2); err != nil {
			return
		}
		// The hello is *decrypted*, not merely read: the responder's receive cipher carries a
		// nonce counter, so skipping one message desynchronizes every later decrypt.
		_, helloCt, err := conn.ReadMessage()
		if err != nil {
			return
		}
		if _, err := responder.decrypt(helloCt); err != nil {
			t.Errorf("decrypt hello: %v", err)
			return
		}

		send := func(f frame.Frame) bool {
			data, encodeErr := frame.Encode(f)
			if encodeErr != nil {
				t.Errorf("encode %s: %v", f.Type, encodeErr)
				return false
			}
			return conn.WriteMessage(websocket.BinaryMessage, responder.encrypt(data)) == nil
		}
		acceptance, err := json.Marshal(frame.HelloAckPayload{Accepted: true, AgentID: 1})
		if err != nil {
			t.Errorf("marshal hello.ack: %v", err)
			return
		}
		if !send(frame.Frame{V: frame.FrameVersion, Type: frame.TypeHelloAck,
			Seq: 0, TS: time.Now().UTC(), Payload: acceptance}) {
			return
		}
		if !send(frame.Frame{V: frame.FrameVersion, Type: frame.TypeDiscoveryRequest,
			Seq: 1, TS: time.Now().UTC(), Payload: request}) {
			return
		}

		// One reader and one writer is all gorilla/websocket permits concurrently, so the
		// agent's frames are drained on their own goroutine while the write side below waits
		// its turn to send the cancellation.
		go func() {
			for {
				_, ct, readErr := conn.ReadMessage()
				if readErr != nil {
					return
				}
				pt, decryptErr := responder.decrypt(ct)
				if decryptErr != nil {
					t.Errorf("decrypt agent frame: %v", decryptErr)
					return
				}
				f, decodeErr := frame.Decode(pt)
				if decodeErr != nil {
					t.Errorf("decode agent frame: %v", decodeErr)
					return
				}
				if f.Type != frame.TypeDiscoveryFinding {
					continue
				}
				select {
				case s.findings <- f:
				default:
					t.Errorf("more than %d discovery.finding frames arrived", cap(s.findings))
					return
				}
			}
		}()

		select {
		case <-s.cancelNow:
		case <-s.done:
			return
		}
		if !send(frame.Frame{V: frame.FrameVersion, Type: frame.TypeDiscoveryCancel,
			Seq: 2, TS: time.Now().UTC(), Payload: cancellation}) {
			return
		}
		// Park rather than return: returning closes the connection, and the terminal summary
		// this test is waiting for still has to travel back over it.
		<-s.done
	}))
	t.Cleanup(srv.Close)
	// Registered *after* srv.Close so that it runs *before* it — t.Cleanup is LIFO. The handler
	// above parks on the connection, and httptest.Server.Close never returns while a hijacked
	// connection's handler is still running.
	t.Cleanup(func() { close(s.done) })
	s.url = "ws" + strings.TrimPrefix(srv.URL, "http")
	return s
}

// TestDiscoveryRuntime_RequestAndCancelFramesReachTheRuntime is Task 14's inbound half at the
// only level that can observe all of it: a `discovery.request` written by a stand-in backend has
// to cross a real Noise-encrypted link, be recognized by internal/link's inbound switch, be
// delivered to the binding runDaemon installed, start a scan, and have the matching
// `discovery.cancel` reach the same dispatch — with the terminal summary arriving back at the
// server as the frame that closes the scan job.
//
// Every earlier version of this test called rt.discoverRuntime.Request directly, which proved
// only that the method worked. It passed for the entire period during which nothing delivered an
// inbound frame to it at all: link.Options had no discovery callbacks and the inbound switch had
// no arm for either frame type, so a real dispatch was decoded, accepted and dropped, and the
// scan job hung to its dispatch deadline. Driving the socket is what makes that failure visible
// here instead of in production.
func TestDiscoveryRuntime_RequestAndCancelFramesReachTheRuntime(t *testing.T) {
	// Blocking, so the dispatch is demonstrably *running* when the cancellation arrives: a
	// dispatch that had already completed would produce the same terminal frame count with none
	// of the same meaning.
	stub := useDiscoveryStub(t, true)
	_, key := startDaemonStateTestDir(t,
		`{"local_discovery":{"enabled":true},"host_telemetry":{"enabled":false}}`, nil)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	rt, err := startDaemonState(&config.Config{}, key, "0.1.0-test", ctx)
	if err != nil {
		t.Fatalf("startDaemonState() error = %v", err)
	}
	t.Cleanup(func() { _ = rt.sp.Close() })

	const reason = "scope_changed"
	version := discoveryScopeVersion(capability.DefaultLocalDiscoveryConfig())
	srv := newDiscoveryLinkServer(t,
		discoveryRequest(t, discoveryDispatchThree, discoveryInScopeTarget, version),
		discoveryCancel(t, discoveryDispatchThree, reason))

	// The options are the daemon's own, not a hand-built set: rt.linkOptions is what runDaemon
	// runs with, so a binding dropped from it fails this test rather than silently disabling a
	// frame type. The hooks are left zero — link.Run nil-defaults them, and none of the
	// update-marker or status-file work they do is what is under test here.
	linkCfg := &config.Config{ServerURL: srv.url, ServerStaticPK: srv.serverPKHex}
	go func() { _ = link.Run(ctx, rt.linkOptions(linkCfg, key, "0.1.0-test", linkHooks{})) }()

	stub.awaitRead(t)
	srv.sendCancel()

	// Read the findings off the *server* side, not rt.dataFrames: once link.Run is up it owns
	// that channel, and asserting on what actually left the socket is the stronger claim anyway.
	hosts, summary := awaitDiscoveryDispatch(t, srv.findings, discoveryDispatchThree)
	if summary.Outcome != frame.DiscoveryOutcomeCancelled {
		t.Errorf("summary outcome = %q (msg %q), want %q",
			summary.Outcome, summary.Msg, frame.DiscoveryOutcomeCancelled)
	}
	if !strings.Contains(summary.Msg, reason) {
		t.Errorf("summary msg = %q, want it to carry the cancellation reason %q", summary.Msg, reason)
	}
	if summary.DispatchID != discoveryDispatchThree {
		t.Errorf("summary dispatch_id = %q, want %q", summary.DispatchID, discoveryDispatchThree)
	}
	if len(hosts) != 0 {
		t.Errorf("host findings = %+v, want none — the collector was still parked when the "+
			"cancellation arrived", hosts)
	}
	if rt.discoverRuntime.OpenDispatches() != 0 {
		t.Errorf("OpenDispatches() = %d after the cancellation, want 0",
			rt.discoverRuntime.OpenDispatches())
	}
}

// TestDaemonLinkOptions_EveryActionableInboundFrameTypeHasAHandler is the cheap standing guard
// behind the expensive test above. A link.Options field left unset is not a compile error, and an
// unset inbound handler is not an error at runtime either — internal/link nil-guards every one of
// them — so the failure mode of forgetting a binding is silence: the agent decodes the frame,
// accepts it, and does nothing. This asserts that each server -> agent type the daemon is
// required to act on has *something* installed, which is the property that was false for
// discovery.request and cost a whole scan job's dispatch deadline to notice.
func TestDaemonLinkOptions_EveryActionableInboundFrameTypeHasAHandler(t *testing.T) {
	useDiscoveryStub(t, false)
	_, key := startDaemonStateTestDir(t, `{"host_telemetry":{"enabled":false}}`, nil)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	rt, err := startDaemonState(&config.Config{}, key, "0.1.0-test", ctx)
	if err != nil {
		t.Fatalf("startDaemonState() error = %v", err)
	}
	t.Cleanup(func() { _ = rt.sp.Close() })

	opts := rt.linkOptions(&config.Config{}, key, "0.1.0-test", linkHooks{})
	for _, binding := range []struct {
		frameType string
		handler   func(json.RawMessage) error
	}{
		{frame.TypeCapabilitiesSet, opts.OnCapabilitiesSet},
		{frame.TypeProbeAssign, opts.OnProbeAssign},
		{frame.TypeProbeCancel, opts.OnProbeCancel},
		{frame.TypeDiscoveryRequest, opts.OnDiscoveryRequest},
		{frame.TypeDiscoveryCancel, opts.OnDiscoveryCancel},
	} {
		if binding.handler == nil {
			t.Errorf("link.Options has no handler for %q — the daemon would decode the frame "+
				"and drop it", binding.frameType)
		}
	}
	// The two data-frame paths every one of those handlers reports its outcome over. A nil
	// channel here would make a refusal unreportable, which is the same silent failure by
	// another route.
	if opts.DataFrames == nil || opts.ControlFrames == nil {
		t.Error("link.Options carries no outbound frame channels, so no handler could report anything")
	}
}
