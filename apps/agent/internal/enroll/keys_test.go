// apps/agent/internal/enroll/keys_test.go
package enroll

import (
	"os"
	"path/filepath"
	"testing"
)

func TestLoadOrCreateDeviceKey_GeneratesOnFirstRun(t *testing.T) {
	dir := t.TempDir()

	key, err := LoadOrCreateDeviceKey(dir)
	if err != nil {
		t.Fatalf("LoadOrCreateDeviceKey() error = %v", err)
	}
	if key.Public == ([32]byte{}) {
		t.Fatal("public key is all-zero, generation likely failed")
	}

	info, err := os.Stat(filepath.Join(dir, "device.key"))
	if err != nil {
		t.Fatalf("device.key not written: %v", err)
	}
	if info.Mode().Perm() != 0o600 {
		t.Errorf("device.key mode = %v, want 0600", info.Mode().Perm())
	}
}

func TestLoadOrCreateDeviceKey_IsStableAcrossCalls(t *testing.T) {
	dir := t.TempDir()

	first, err := LoadOrCreateDeviceKey(dir)
	if err != nil {
		t.Fatalf("first call error = %v", err)
	}
	second, err := LoadOrCreateDeviceKey(dir)
	if err != nil {
		t.Fatalf("second call error = %v", err)
	}
	if first.Public != second.Public {
		t.Error("public key changed across calls — device.key not being reused")
	}
}

func TestFingerprint_Is32LowercaseHexCharsGroupedInFours(t *testing.T) {
	dir := t.TempDir()
	key, err := LoadOrCreateDeviceKey(dir)
	if err != nil {
		t.Fatalf("LoadOrCreateDeviceKey() error = %v", err)
	}

	fp := key.Fingerprint()
	if len(fp) != 32 {
		t.Errorf("Fingerprint() len = %d, want 32", len(fp))
	}

	grouped := key.FingerprintGrouped()
	wantLen := 32 + 7 // 8 groups of 4 chars + 7 separators
	if len(grouped) != wantLen {
		t.Errorf("FingerprintGrouped() len = %d, want %d (got %q)", len(grouped), wantLen, grouped)
	}
}
