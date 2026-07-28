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
	target := filepath.Join(dir, "cb-agent")
	if err := os.WriteFile(target, []byte("old binary"), 0o755); err != nil {
		t.Fatal(err)
	}
	newBinary := filepath.Join(dir, "new-download")
	if err := os.WriteFile(newBinary, []byte("new binary"), 0o755); err != nil {
		t.Fatal(err)
	}

	backupPath, err := Swap(newBinary, target)
	if err != nil {
		t.Fatalf("Swap() error = %v", err)
	}
	got, _ := os.ReadFile(target)
	if string(got) != "new binary" {
		t.Errorf("target contents = %q, want %q", got, "new binary")
	}

	if err := Rollback(target); err != nil {
		t.Fatalf("Rollback() error = %v", err)
	}
	got, _ = os.ReadFile(target)
	if string(got) != "old binary" {
		t.Errorf("target contents after rollback = %q, want %q", got, "old binary")
	}
	if _, err := os.Stat(backupPath); !os.IsNotExist(err) {
		t.Errorf("backup file %s still exists after rollback, want removed", backupPath)
	}
}

func TestMarker_WriteReadClear(t *testing.T) {
	dir := t.TempDir()

	if _, present, err := ReadMarker(dir); err != nil || present {
		t.Fatalf("ReadMarker() on fresh dir = (_, %v, %v), want (_, false, nil)", present, err)
	}

	if err := WriteMarker(dir, "0.2.0"); err != nil {
		t.Fatalf("WriteMarker() error = %v", err)
	}
	version, present, err := ReadMarker(dir)
	if err != nil || !present || version != "0.2.0" {
		t.Fatalf("ReadMarker() = (%q, %v, %v), want (\"0.2.0\", true, nil)", version, present, err)
	}

	if err := ClearMarker(dir); err != nil {
		t.Fatalf("ClearMarker() error = %v", err)
	}
	if _, present, _ := ReadMarker(dir); present {
		t.Error("marker still present after ClearMarker()")
	}
}
