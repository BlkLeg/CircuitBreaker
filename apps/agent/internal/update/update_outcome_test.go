// Tests for the durable pending-outcome record (§3.3 of
// docs/design/2026-09-16-agent-deployment-connection-plan.md) and for the
// context-aware download cancellation (§3.1/§8.5).
package update

import (
	"context"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"circuitbreaker.dev/cb-agent/internal/config"
	"circuitbreaker.dev/cb-agent/internal/tlsdial"
)

// The whole lifecycle §3.3 requires: write the outcome before the live send,
// read it back in the next process, clear it only after that send succeeded.
func TestPendingOutcomeRoundTrip(t *testing.T) {
	dir := t.TempDir()

	if version, phase, ok, err := ReadPendingOutcome(dir); ok || err != nil || version != "" || phase != "" {
		t.Fatalf("ReadPendingOutcome on an empty state dir = (%q, %q, %v, %v), want (\"\", \"\", false, nil)", version, phase, ok, err)
	}

	if err := WritePendingOutcome(dir, "0.9.0", "succeeded"); err != nil {
		t.Fatalf("WritePendingOutcome() error = %v", err)
	}
	version, phase, ok, err := ReadPendingOutcome(dir)
	if err != nil || !ok {
		t.Fatalf("ReadPendingOutcome() = (%q, %q, %v, %v), want ok=true, err=nil", version, phase, ok, err)
	}
	if version != "0.9.0" || phase != "succeeded" {
		t.Fatalf("ReadPendingOutcome() = (%q, %q), want (0.9.0, succeeded)", version, phase)
	}

	if err := ClearPendingOutcome(dir); err != nil {
		t.Fatalf("ClearPendingOutcome() error = %v", err)
	}
	if _, _, ok, err := ReadPendingOutcome(dir); ok || err != nil {
		t.Fatalf("ReadPendingOutcome() after clear = ok=%v err=%v, want ok=false err=nil", ok, err)
	}
	// Clearing an already-absent outcome is not an error, so the report-send
	// path can call it unconditionally — same rule as ClearRollbackReport.
	if err := ClearPendingOutcome(dir); err != nil {
		t.Fatalf("ClearPendingOutcome() on an absent file = %v, want nil", err)
	}
}

// A record that exists but does not parse is an error, never a silent miss —
// the caller must not mistake an unreportable record for "nothing to report".
func TestPendingOutcomeMalformedRecordIsAnError(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, pendingOutcomeFilename)
	if err := os.WriteFile(path, []byte("no-phase-separator-at-all"), 0o600); err != nil {
		t.Fatalf("seed malformed outcome: %v", err)
	}
	if _, _, ok, err := ReadPendingOutcome(dir); ok || err == nil {
		t.Fatalf("ReadPendingOutcome() on a malformed record = ok=%v err=%v, want ok=false err!=nil", ok, err)
	}
}

// The pending outcome and the rollback report are deliberately separate
// files: reading one must never surface the other's contents as a phantom
// outcome (or a phantom rollback).
func TestPendingOutcomeAndRollbackReportAreSeparateRecords(t *testing.T) {
	dir := t.TempDir()

	if err := WriteRollbackReport(dir, "0.8.0"); err != nil {
		t.Fatalf("WriteRollbackReport() error = %v", err)
	}
	if _, _, ok, err := ReadPendingOutcome(dir); ok || err != nil {
		t.Fatalf("ReadPendingOutcome() with only a rollback report present = ok=%v err=%v, want ok=false err=nil", ok, err)
	}

	if err := ClearPendingOutcome(dir); err != nil {
		t.Fatalf("ClearPendingOutcome() error = %v", err)
	}
	if version, ok, _ := ReadRollbackReport(dir); !ok || version != "0.8.0" {
		t.Fatalf("ClearPendingOutcome() removed the rollback report too: ReadRollbackReport() = (%q, %v)", version, ok)
	}
}

// §5's "Download cancellation interrupts a stalled HTTP response": a context
// cancelled mid-body must abort the copy immediately, not after
// downloadTimeout. This is the property that keeps daemon shutdown bounded —
// the whole point of threading ctx into Download.
func TestDownloadContextCancellationInterruptsStalledResponse(t *testing.T) {
	// Keep downloadTimeout at its production 2 minutes for this test: the
	// assertion is precisely that ctx does NOT wait for it.
	release := make(chan struct{})
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Length", "1048576") // 1 MiB: under the cap
		w.WriteHeader(http.StatusOK)
		// Stream a little, then hang until the test releases.
		_, _ = w.Write([]byte("first bytes"))
		if f, ok := w.(http.Flusher); ok {
			f.Flush()
		}
		<-release
	}))
	defer srv.Close()
	defer close(release)

	cfg := &config.Config{ServerURL: srv.URL}
	instr := Instruction{Version: "0.2.0", SHA256: "00", Arch: "amd64", OS: "linux"}

	ctx, cancel := context.WithCancel(context.Background())
	errCh := make(chan error, 1)
	started := make(chan struct{})
	go func() {
		close(started)
		_, err := Download(ctx, cfg, tlsdial.Trust{Mode: tlsdial.ModePublic}, instr)
		errCh <- err
	}()

	<-started
	// Give the request time to connect and start reading the body before
	// cancelling — cancelling a request that never left is a weaker test.
	time.Sleep(200 * time.Millisecond)
	cancel()

	select {
	case err := <-errCh:
		if err == nil {
			t.Fatal("Download() after cancellation = nil error, want the context error")
		}
		if !strings.Contains(err.Error(), "context canceled") {
			t.Errorf("Download() error = %v, want it to wrap context canceled", err)
		}
	case <-time.After(5 * time.Second):
		// downloadTimeout is 2 minutes; 5s proves the cancellation path
		// fired rather than the timeout ever being what stopped it.
		t.Fatal("Download() did not return within 5s of context cancellation — shutdown would hang on a stalled download")
	}
}

// TestDownloadSignatureContextCancellationInterruptsStalledResponse is the
// §8.5 twin for the .sig fetch: DownloadSignature shares downloadTo with
// Download, and a SIGTERM mid-signature must not wait out downloadTimeout.
func TestDownloadSignatureContextCancellationInterruptsStalledResponse(t *testing.T) {
	release := make(chan struct{})
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Length", "64")
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("sig-prefix"))
		if f, ok := w.(http.Flusher); ok {
			f.Flush()
		}
		<-release
	}))
	defer srv.Close()
	defer close(release)

	cfg := &config.Config{ServerURL: srv.URL}
	instr := Instruction{Version: "0.2.0", SHA256: "00", Arch: "amd64", OS: "linux"}

	ctx, cancel := context.WithCancel(context.Background())
	errCh := make(chan error, 1)
	started := make(chan struct{})
	go func() {
		close(started)
		_, err := DownloadSignature(ctx, cfg, tlsdial.Trust{Mode: tlsdial.ModePublic}, instr)
		errCh <- err
	}()

	<-started
	time.Sleep(200 * time.Millisecond)
	cancel()

	select {
	case err := <-errCh:
		if err == nil {
			t.Fatal("DownloadSignature() after cancellation = nil error, want the context error")
		}
		if !strings.Contains(err.Error(), "context canceled") {
			t.Errorf("DownloadSignature() error = %v, want it to wrap context canceled", err)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("DownloadSignature() did not return within 5s of context cancellation — shutdown would hang on a stalled signature fetch")
	}
}
