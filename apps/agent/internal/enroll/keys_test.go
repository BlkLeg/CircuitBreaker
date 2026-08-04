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

func TestLoadDeviceKey_NoFileYields_NotOkAndNoFileCreated(t *testing.T) {
	dir := t.TempDir()

	key, ok, err := LoadDeviceKey(dir)
	if err != nil {
		t.Fatalf("LoadDeviceKey() error = %v", err)
	}
	if ok {
		t.Error("LoadDeviceKey() ok = true with no device.key present, want false")
	}
	if key != nil {
		t.Errorf("LoadDeviceKey() key = %v, want nil", key)
	}
	if _, err := os.Stat(filepath.Join(dir, "device.key")); !os.IsNotExist(err) {
		t.Errorf("LoadDeviceKey() created device.key as a side effect (stat err = %v), want no file", err)
	}
}

func TestLoadDeviceKey_ReadsExistingKeyMatchingLoadOrCreate(t *testing.T) {
	dir := t.TempDir()

	created, err := LoadOrCreateDeviceKey(dir)
	if err != nil {
		t.Fatalf("LoadOrCreateDeviceKey() error = %v", err)
	}

	loaded, ok, err := LoadDeviceKey(dir)
	if err != nil {
		t.Fatalf("LoadDeviceKey() error = %v", err)
	}
	if !ok {
		t.Fatal("LoadDeviceKey() ok = false with an existing device.key, want true")
	}
	if loaded.Public != created.Public {
		t.Error("LoadDeviceKey() returned a different public key than LoadOrCreateDeviceKey wrote")
	}
}

func TestLoadDeviceKey_CorruptFileIsAnError(t *testing.T) {
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "device.key"), []byte("too-short"), 0o600); err != nil {
		t.Fatalf("write fixture: %v", err)
	}

	_, ok, err := LoadDeviceKey(dir)
	if err == nil {
		t.Fatal("LoadDeviceKey() error = nil, want an error for a wrong-length device.key")
	}
	if ok {
		t.Error("LoadDeviceKey() ok = true alongside an error, want false")
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
