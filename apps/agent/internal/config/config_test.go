package config

import (
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestLoad_ParsesValidTOML(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "agent.toml")
	contents := `
server_url = "https://cb.example.com"
server_static_pk = "deadbeef"
tls_pin = "abcd1234"
log_level = "info"
spool_cap_bytes = 67108864
`
	if err := os.WriteFile(path, []byte(contents), 0o600); err != nil {
		t.Fatal(err)
	}

	cfg, err := Load(path)
	if err != nil {
		t.Fatalf("Load() error = %v", err)
	}
	if cfg.ServerURL != "https://cb.example.com" {
		t.Errorf("ServerURL = %q, want %q", cfg.ServerURL, "https://cb.example.com")
	}
	if cfg.SpoolCapBytes != 67108864 {
		t.Errorf("SpoolCapBytes = %d, want 67108864", cfg.SpoolCapBytes)
	}
}

func TestLoad_MissingFileReturnsError(t *testing.T) {
	if _, err := Load("/nonexistent/agent.toml"); err == nil {
		t.Fatal("expected error for missing config file, got nil")
	}
}

func TestStateDir_DefaultsWhenEnvUnset(t *testing.T) {
	t.Setenv("CB_AGENT_STATE_DIR", "")
	if got := StateDir(); got != "/var/lib/cb-agent" {
		t.Errorf("StateDir() = %q, want /var/lib/cb-agent", got)
	}
}

func TestStateDir_HonorsEnvOverride(t *testing.T) {
	t.Setenv("CB_AGENT_STATE_DIR", "/tmp/cb-agent-test")
	if got := StateDir(); got != "/tmp/cb-agent-test" {
		t.Errorf("StateDir() = %q, want /tmp/cb-agent-test", got)
	}
}

// ── ServerKeyRotation persistence (Task 28) ────────────────────────────────

func TestLoadServerKeyRotation_ReturnsNilWhenNeverPersisted(t *testing.T) {
	dir := t.TempDir()

	state, err := LoadServerKeyRotation(dir)

	if err != nil {
		t.Fatalf("LoadServerKeyRotation() error = %v", err)
	}
	if state != nil {
		t.Errorf("LoadServerKeyRotation() = %+v, want nil", state)
	}
}

func TestSaveThenLoadServerKeyRotation_RoundTrips(t *testing.T) {
	dir := t.TempDir()
	expiry := time.Date(2026, 8, 12, 0, 0, 0, 0, time.UTC)
	want := ServerKeyRotation{SuccessorPK: "ab" + hexFill(62), Expiry: expiry}

	if err := SaveServerKeyRotation(dir, want); err != nil {
		t.Fatalf("SaveServerKeyRotation() error = %v", err)
	}

	got, err := LoadServerKeyRotation(dir)
	if err != nil {
		t.Fatalf("LoadServerKeyRotation() error = %v", err)
	}
	if got == nil {
		t.Fatal("LoadServerKeyRotation() = nil, want a persisted state")
	}
	if got.SuccessorPK != want.SuccessorPK {
		t.Errorf("SuccessorPK = %q, want %q", got.SuccessorPK, want.SuccessorPK)
	}
	if !got.Expiry.Equal(want.Expiry) {
		t.Errorf("Expiry = %v, want %v", got.Expiry, want.Expiry)
	}
}

func TestSaveServerKeyRotation_OverwritesPriorState(t *testing.T) {
	dir := t.TempDir()
	first := ServerKeyRotation{SuccessorPK: "aa" + hexFill(62), Expiry: time.Now().UTC()}
	second := ServerKeyRotation{SuccessorPK: "bb" + hexFill(62), Expiry: time.Now().UTC()}

	if err := SaveServerKeyRotation(dir, first); err != nil {
		t.Fatalf("SaveServerKeyRotation(first) error = %v", err)
	}
	if err := SaveServerKeyRotation(dir, second); err != nil {
		t.Fatalf("SaveServerKeyRotation(second) error = %v", err)
	}

	got, err := LoadServerKeyRotation(dir)
	if err != nil {
		t.Fatalf("LoadServerKeyRotation() error = %v", err)
	}
	if got.SuccessorPK != second.SuccessorPK {
		t.Errorf("SuccessorPK = %q, want the second write's %q", got.SuccessorPK, second.SuccessorPK)
	}
}

func TestSaveServerKeyRotation_LeavesNoTempFileBehind(t *testing.T) {
	dir := t.TempDir()
	if err := SaveServerKeyRotation(dir, ServerKeyRotation{SuccessorPK: "cc" + hexFill(62)}); err != nil {
		t.Fatalf("SaveServerKeyRotation() error = %v", err)
	}

	entries, err := os.ReadDir(dir)
	if err != nil {
		t.Fatal(err)
	}
	for _, e := range entries {
		if e.Name() != "server_key_rotation.json" {
			t.Errorf("unexpected leftover file in state dir: %s", e.Name())
		}
	}
}

// hexFill returns n lowercase hex characters ("dd" repeated), a small helper
// so the 64-char successor-pk-shaped strings above stay readable at the call
// site rather than spelled out in full each time.
func hexFill(n int) string {
	out := make([]byte, n)
	for i := range out {
		out[i] = 'd'
	}
	return string(out)
}
