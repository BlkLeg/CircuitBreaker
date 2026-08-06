package update

import (
	"crypto/sha256"
	"encoding/hex"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"

	"circuitbreaker.dev/cb-agent/internal/config"
)

func TestDownloadAndVerify_RoundTrips(t *testing.T) {
	content := []byte("fake binary contents")
	sum := sha256.Sum256(content)
	wantHash := hex.EncodeToString(sum[:])

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Write(content)
	}))
	defer srv.Close()

	cfg := &config.Config{ServerURL: srv.URL}
	instr := Instruction{Version: "0.2.0", SHA256: wantHash, Arch: "amd64", OS: "linux"}

	tmpPath, err := Download(cfg, instr)
	if err != nil {
		t.Fatalf("Download() error = %v", err)
	}
	defer os.Remove(tmpPath)

	if err := VerifySHA256(tmpPath, wantHash); err != nil {
		t.Fatalf("VerifySHA256() error = %v, want nil", err)
	}
	if err := VerifySHA256(tmpPath, "0000"); err == nil {
		t.Fatal("VerifySHA256() with wrong hash = nil error, want an error")
	}
}

func TestSwapAndRollback(t *testing.T) {
	dir := t.TempDir()
	oldVersionDir := filepath.Join(dir, "versions", "0.1.0")
	if err := os.MkdirAll(oldVersionDir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(oldVersionDir, "cb-agent"), []byte("old binary"), 0o755); err != nil {
		t.Fatal(err)
	}
	currentLink := CurrentLinkPath(dir)
	if err := os.Symlink(filepath.Join(oldVersionDir, "cb-agent"), currentLink); err != nil {
		t.Fatal(err)
	}

	newBinary := filepath.Join(dir, "new-download")
	if err := os.WriteFile(newBinary, []byte("new binary"), 0o755); err != nil {
		t.Fatal(err)
	}

	prevVersionDir, err := Swap(newBinary, "0.2.0", dir)
	if err != nil {
		t.Fatalf("Swap() error = %v", err)
	}
	if prevVersionDir != oldVersionDir {
		t.Errorf("Swap() prevVersionDir = %q, want %q", prevVersionDir, oldVersionDir)
	}

	newVersionDir := filepath.Join(dir, "versions", "0.2.0")
	target, err := os.Readlink(currentLink)
	if err != nil || target != filepath.Join(newVersionDir, "cb-agent") {
		t.Errorf("current symlink = (%q, %v), want %q", target, err, filepath.Join(newVersionDir, "cb-agent"))
	}
	got, err := os.ReadFile(filepath.Join(newVersionDir, "cb-agent"))
	if err != nil || string(got) != "new binary" {
		t.Errorf("new version contents = (%q, %v), want %q", got, err, "new binary")
	}

	if err := Rollback(currentLink, prevVersionDir); err != nil {
		t.Fatalf("Rollback() error = %v", err)
	}
	target, err = os.Readlink(currentLink)
	if err != nil || target != filepath.Join(oldVersionDir, "cb-agent") {
		t.Errorf("current symlink after rollback = (%q, %v), want %q", target, err, filepath.Join(oldVersionDir, "cb-agent"))
	}
}

func TestMarker_WriteReadClear(t *testing.T) {
	dir := t.TempDir()

	if _, _, _, present, err := ReadMarker(dir); err != nil || present {
		t.Fatalf("ReadMarker() on fresh dir = (_, _, _, %v, %v), want (_, _, _, false, nil)", present, err)
	}

	if err := WriteMarker(dir, "0.2.0"); err != nil {
		t.Fatalf("WriteMarker() error = %v", err)
	}
	version, prevVersionDir, swapped, present, err := ReadMarker(dir)
	if err != nil || !present || version != "0.2.0" || swapped || prevVersionDir != "" {
		t.Fatalf("ReadMarker() = (%q, %q, %v, %v, %v), want (\"0.2.0\", \"\", false, true, nil) — WriteMarker alone must not report a completed swap or a previous version", version, prevVersionDir, swapped, present, err)
	}

	if err := ClearMarker(dir); err != nil {
		t.Fatalf("ClearMarker() error = %v", err)
	}
	if _, _, _, present, _ := ReadMarker(dir); present {
		t.Error("marker still present after ClearMarker()")
	}
}

func TestMarker_MarkSwappedTransitionsPhase(t *testing.T) {
	dir := t.TempDir()

	if err := WriteMarker(dir, "0.9.0"); err != nil {
		t.Fatalf("WriteMarker() error = %v", err)
	}
	if _, _, swapped, present, err := ReadMarker(dir); err != nil || !present || swapped {
		t.Fatalf("ReadMarker() after WriteMarker() = (_, _, %v, %v, %v), want (_, _, false, true, nil)", swapped, present, err)
	}

	prevVersionDir := filepath.Join(dir, "versions", "0.8.0")
	if err := MarkSwapped(dir, "0.9.0", prevVersionDir); err != nil {
		t.Fatalf("MarkSwapped() error = %v", err)
	}
	version, gotPrev, swapped, present, err := ReadMarker(dir)
	if err != nil || !present || !swapped || version != "0.9.0" || gotPrev != prevVersionDir {
		t.Fatalf("ReadMarker() after MarkSwapped() = (%q, %q, %v, %v, %v), want (\"0.9.0\", %q, true, true, nil)", version, gotPrev, swapped, present, err, prevVersionDir)
	}
}

// TestRollbackReport_WriteReadClear mirrors TestMarker_WriteReadClear for the
// rollback-report marker (Task 24): the version a rollback restored away
// from, persisted across the re-exec back into the prior binary so the fresh
// process can report update.status(rolled_back) once reconnected.
func TestRollbackReport_WriteReadClear(t *testing.T) {
	dir := t.TempDir()

	if _, present, err := ReadRollbackReport(dir); err != nil || present {
		t.Fatalf("ReadRollbackReport() on fresh dir = (_, %v, %v), want (_, false, nil)", present, err)
	}

	if err := WriteRollbackReport(dir, "0.3.0"); err != nil {
		t.Fatalf("WriteRollbackReport() error = %v", err)
	}
	version, present, err := ReadRollbackReport(dir)
	if err != nil || !present || version != "0.3.0" {
		t.Fatalf("ReadRollbackReport() = (%q, %v, %v), want (\"0.3.0\", true, nil)", version, present, err)
	}

	if err := ClearRollbackReport(dir); err != nil {
		t.Fatalf("ClearRollbackReport() error = %v", err)
	}
	if _, present, _ := ReadRollbackReport(dir); present {
		t.Error("rollback report still present after ClearRollbackReport()")
	}
}

// TestClearRollbackReport_AbsentIsNotAnError mirrors the marker's tolerance
// of an already-absent file — callers (e.g. link.go's ClearPendingUpdateOutcome
// hook) call this unconditionally after a successful report send.
func TestClearRollbackReport_AbsentIsNotAnError(t *testing.T) {
	dir := t.TempDir()
	if err := ClearRollbackReport(dir); err != nil {
		t.Errorf("ClearRollbackReport() on absent report error = %v, want nil", err)
	}
}
