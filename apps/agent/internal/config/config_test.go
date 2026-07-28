package config

import (
	"os"
	"path/filepath"
	"testing"
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
