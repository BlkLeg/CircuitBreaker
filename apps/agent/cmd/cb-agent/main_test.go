// apps/agent/cmd/cb-agent/main_test.go
package main

import (
	"bytes"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"circuitbreaker.dev/cb-agent/internal/enroll"
	"circuitbreaker.dev/cb-agent/internal/frame"
	"circuitbreaker.dev/cb-agent/internal/status"
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
