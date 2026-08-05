// apps/agent/cmd/cb-agent/main_test.go
package main

import (
	"bytes"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"testing"
	"time"

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
				if err := w.SetReadiness([]frame.Readiness{{Collector: "agent.identity", State: "ready"}}); err != nil {
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
	target := filepath.Join(dir, "cb-agent")
	if err := os.WriteFile(target, []byte("new binary"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(target+".previous", []byte("old binary"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := update.WriteMarker(dir, "0.6.0"); err != nil {
		t.Fatalf("WriteMarker() error = %v", err)
	}

	reExecCalls := 0
	reExec := func() error {
		reExecCalls++
		return nil
	}

	watchForRollback(dir, target, "0.6.0", reExec)

	got, err := os.ReadFile(target)
	if err != nil || string(got) != "old binary" {
		t.Errorf("target contents = (%q, %v), want rolled back to %q", got, err, "old binary")
	}
	if _, present, _ := update.ReadMarker(dir); present {
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
	target := filepath.Join(dir, "cb-agent")
	if err := os.WriteFile(target, []byte("new binary"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(target+".previous", []byte("old binary"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := update.WriteMarker(dir, "0.7.0"); err != nil {
		t.Fatalf("WriteMarker() error = %v", err)
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

	watchForRollback(dir, target, "0.7.0", reExec)
	<-confirmed // watchForRollback already outlasted this by construction; just for cleanliness.

	got, err := os.ReadFile(target)
	if err != nil || string(got) != "new binary" {
		t.Errorf("target contents = (%q, %v), want unchanged %q — a confirmed update must not be rolled back", got, err, "new binary")
	}
	if _, present, _ := update.ReadMarker(dir); present {
		t.Error("marker still present, want cleared by the simulated onConnected confirmation")
	}
	if _, present, _ := update.ReadRollbackReport(dir); present {
		t.Error("rollback report present, want none — the update confirmed, no rollback happened")
	}
	if reExecCalls != 0 {
		t.Errorf("reExec called %d times, want 0 (a confirmed update must not re-exec)", reExecCalls)
	}
}
