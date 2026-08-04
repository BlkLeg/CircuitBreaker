// apps/agent/internal/status/status_test.go
package status

import (
	"errors"
	"os"
	"path/filepath"
	"testing"

	"circuitbreaker.dev/cb-agent/internal/frame"
)

func TestRead_NotOkWhenFileAbsent(t *testing.T) {
	dir := t.TempDir()

	st, ok, err := Read(dir)
	if err != nil {
		t.Fatalf("Read() error = %v, want nil", err)
	}
	if ok {
		t.Error("Read() ok = true with no status.json written yet, want false")
	}
	if st.Version != "" || st.LinkState != "" || st.Grants != nil {
		t.Errorf("Read() status = %+v, want zero value", st)
	}
}

// TestWriter_Transitions drives each mutating method in isolation and checks
// the resulting on-disk snapshot — table-driven over the link-state
// transitions plus the auxiliary setters (grants/readiness/spool).
func TestWriter_Transitions(t *testing.T) {
	tests := []struct {
		name          string
		apply         func(w *Writer) error
		wantLinkState LinkState
		wantLastError string
		wantConnected bool // whether LastConnected should be non-zero
	}{
		{
			name:          "accepted clears any prior error and stamps LastConnected",
			apply:         func(w *Writer) error { return w.SetAccepted() },
			wantLinkState: LinkAccepted,
			wantLastError: "",
			wantConnected: true,
		},
		{
			name:          "rejected records the server's reason",
			apply:         func(w *Writer) error { return w.SetRejected("device_pk_mismatch") },
			wantLinkState: LinkRejected,
			wantLastError: "device_pk_mismatch",
			wantConnected: false,
		},
		{
			name:          "disconnected with a cause records its message",
			apply:         func(w *Writer) error { return w.SetDisconnected(errors.New("connection lost")) },
			wantLinkState: LinkDisconnected,
			wantLastError: "connection lost",
			wantConnected: false,
		},
		{
			name:          "disconnected with nil cause records no error",
			apply:         func(w *Writer) error { return w.SetDisconnected(nil) },
			wantLinkState: LinkDisconnected,
			wantLastError: "",
			wantConnected: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			dir := t.TempDir()
			w := NewWriter(dir, "1.2.3", "abcd-ef01")

			if err := tt.apply(w); err != nil {
				t.Fatalf("apply() error = %v", err)
			}

			st, ok, err := Read(dir)
			if err != nil {
				t.Fatalf("Read() error = %v", err)
			}
			if !ok {
				t.Fatal("Read() ok = false after a write, want true")
			}
			if st.LinkState != tt.wantLinkState {
				t.Errorf("LinkState = %q, want %q", st.LinkState, tt.wantLinkState)
			}
			if st.LastError != tt.wantLastError {
				t.Errorf("LastError = %q, want %q", st.LastError, tt.wantLastError)
			}
			if got := !st.LastConnected.IsZero(); got != tt.wantConnected {
				t.Errorf("LastConnected non-zero = %v, want %v", got, tt.wantConnected)
			}
			if st.Version != "1.2.3" || st.Fingerprint != "abcd-ef01" {
				t.Errorf("Version/Fingerprint = %q/%q, want 1.2.3/abcd-ef01", st.Version, st.Fingerprint)
			}
			if st.UpdatedAt.IsZero() {
				t.Error("UpdatedAt is zero, want it stamped on every write")
			}
		})
	}
}

func TestWriter_SetAccepted_ClearsAPriorError(t *testing.T) {
	dir := t.TempDir()
	w := NewWriter(dir, "1.0.0", "fp")

	if err := w.SetRejected("device_pk_mismatch"); err != nil {
		t.Fatalf("SetRejected() error = %v", err)
	}
	if err := w.SetAccepted(); err != nil {
		t.Fatalf("SetAccepted() error = %v", err)
	}

	st, ok, err := Read(dir)
	if err != nil || !ok {
		t.Fatalf("Read() = (%+v, %v, %v)", st, ok, err)
	}
	if st.LinkState != LinkAccepted {
		t.Errorf("LinkState = %q, want %q", st.LinkState, LinkAccepted)
	}
	if st.LastError != "" {
		t.Errorf("LastError = %q, want empty after a subsequent accept", st.LastError)
	}
	if !st.LastErrorAt.IsZero() {
		t.Errorf("LastErrorAt = %v, want zero after a subsequent accept", st.LastErrorAt)
	}
}

func TestWriter_SetGrants(t *testing.T) {
	dir := t.TempDir()
	w := NewWriter(dir, "1.0.0", "fp")

	grants := map[string]bool{"host_telemetry": true, "remote_probe": false}
	if err := w.SetGrants(grants); err != nil {
		t.Fatalf("SetGrants() error = %v", err)
	}

	st, ok, err := Read(dir)
	if err != nil || !ok {
		t.Fatalf("Read() = (%+v, %v, %v)", st, ok, err)
	}
	if !st.Grants["host_telemetry"] || st.Grants["remote_probe"] {
		t.Errorf("Grants = %+v, want %+v", st.Grants, grants)
	}
}

func TestWriter_SetReadiness(t *testing.T) {
	dir := t.TempDir()
	w := NewWriter(dir, "1.0.0", "fp")

	readiness := []frame.Readiness{{Collector: "agent.identity", State: "ready"}}
	if err := w.SetReadiness(readiness); err != nil {
		t.Fatalf("SetReadiness() error = %v", err)
	}

	st, ok, err := Read(dir)
	if err != nil || !ok {
		t.Fatalf("Read() = (%+v, %v, %v)", st, ok, err)
	}
	if len(st.Readiness) != 1 || st.Readiness[0].Collector != "agent.identity" {
		t.Errorf("Readiness = %+v, want %+v", st.Readiness, readiness)
	}
}

func TestWriter_SetSpoolStats(t *testing.T) {
	dir := t.TempDir()
	w := NewWriter(dir, "1.0.0", "fp")

	if err := w.SetSpoolStats(3, 4096); err != nil {
		t.Fatalf("SetSpoolStats() error = %v", err)
	}

	st, ok, err := Read(dir)
	if err != nil || !ok {
		t.Fatalf("Read() = (%+v, %v, %v)", st, ok, err)
	}
	if st.SpoolDepth != 3 || st.SpoolBytes != 4096 {
		t.Errorf("SpoolDepth/SpoolBytes = %d/%d, want 3/4096", st.SpoolDepth, st.SpoolBytes)
	}
}

func TestWriter_PersistLocked_Is0600AndLeavesNoTempFile(t *testing.T) {
	dir := t.TempDir()
	w := NewWriter(dir, "1.0.0", "fp")

	if err := w.SetAccepted(); err != nil {
		t.Fatalf("SetAccepted() error = %v", err)
	}

	path := filepath.Join(dir, filename)
	info, err := os.Stat(path)
	if err != nil {
		t.Fatalf("status.json not written: %v", err)
	}
	if info.Mode().Perm() != 0o600 {
		t.Errorf("status.json mode = %v, want 0600", info.Mode().Perm())
	}

	if _, err := os.Stat(path + ".tmp"); !os.IsNotExist(err) {
		t.Errorf("status.json.tmp still exists after a write, want it renamed away (err = %v)", err)
	}
}

// TestWriter_RepeatedWritesRemain0600AndConsistent exercises persistLocked
// several times in a row (simulating a run of link accept -> capability
// change -> disconnect -> accept again) and checks the file is readable and
// still 0600 after every step, not just the first.
func TestWriter_RepeatedWritesRemain0600AndConsistent(t *testing.T) {
	dir := t.TempDir()
	w := NewWriter(dir, "1.0.0", "fp")

	steps := []func() error{
		func() error { return w.SetAccepted() },
		func() error { return w.SetGrants(map[string]bool{"host_telemetry": true}) },
		func() error { return w.SetDisconnected(errors.New("connection lost")) },
		func() error { return w.SetAccepted() },
	}

	for i, step := range steps {
		if err := step(); err != nil {
			t.Fatalf("step %d error = %v", i, err)
		}
		info, err := os.Stat(filepath.Join(dir, filename))
		if err != nil {
			t.Fatalf("step %d: status.json missing: %v", i, err)
		}
		if info.Mode().Perm() != 0o600 {
			t.Errorf("step %d: status.json mode = %v, want 0600", i, info.Mode().Perm())
		}
	}

	st, ok, err := Read(dir)
	if err != nil || !ok {
		t.Fatalf("final Read() = (%+v, %v, %v)", st, ok, err)
	}
	if st.LinkState != LinkAccepted {
		t.Errorf("final LinkState = %q, want %q", st.LinkState, LinkAccepted)
	}
	if !st.Grants["host_telemetry"] {
		t.Error("final Grants lost the earlier SetGrants() call")
	}
}
