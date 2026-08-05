package config

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"time"

	"github.com/BurntSushi/toml"
)

type Config struct {
	ServerURL      string `toml:"server_url"`
	ServerStaticPK string `toml:"server_static_pk"`
	TLSPin         string `toml:"tls_pin"`
	LogLevel       string `toml:"log_level"`
	SpoolCapBytes  int64  `toml:"spool_cap_bytes"`
}

func Load(path string) (*Config, error) {
	var cfg Config
	if _, err := toml.DecodeFile(path, &cfg); err != nil {
		return nil, fmt.Errorf("config: load %s: %w", path, err)
	}
	return &cfg, nil
}

func StateDir() string {
	if dir := os.Getenv("CB_AGENT_STATE_DIR"); dir != "" {
		return dir
	}
	return "/var/lib/cb-agent"
}

// ServerKeyRotation is the successor server identity public key a Task 28
// server-key rotation advertised to this agent over an authenticated `/link`
// connection (a `key.rotate` frame with kind="server" — see
// internal/frame.KeyRotatePayload and internal/link's handling of it).
// Persisted so the agent keeps trusting it — alongside the config file's own
// ServerStaticPK, never in place of it — across reconnects and restarts,
// mirroring the server's own "accept either key during the overlap window"
// behavior (apps/backend/src/app/core/agent_crypto.py's
// complete_ik_handshake). Expiry is carried through for observability only;
// nothing on the agent side currently acts on it — the agent simply keeps
// trusting both keys.
type ServerKeyRotation struct {
	SuccessorPK string    `json:"successor_pk"`
	Expiry      time.Time `json:"expiry"`
}

func serverKeyRotationPath(stateDir string) string {
	return filepath.Join(stateDir, "server_key_rotation.json")
}

// LoadServerKeyRotation reads the persisted successor server public key, if
// any. Returns (nil, nil) — not an error — when no rotation has ever been
// advertised to this agent, which is the overwhelmingly common case.
func LoadServerKeyRotation(stateDir string) (*ServerKeyRotation, error) {
	data, err := os.ReadFile(serverKeyRotationPath(stateDir))
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, fmt.Errorf("config: load server key rotation: %w", err)
	}
	var state ServerKeyRotation
	if err := json.Unmarshal(data, &state); err != nil {
		return nil, fmt.Errorf("config: decode server key rotation: %w", err)
	}
	return &state, nil
}

// SaveServerKeyRotation durably persists state — a temp-file-then-rename
// write (same "never observable half-written" property as
// internal/update.atomicWriteFile, reimplemented here rather than exported
// from that package since it's a small, self-contained primitive and
// internal/update owns a distinct durability property — its ordering
// relative to a binary swap — that has nothing to do with this file) so a
// crash between writing and the next read can never leave a corrupt,
// unparseable rotation file behind.
func SaveServerKeyRotation(stateDir string, state ServerKeyRotation) error {
	data, err := json.Marshal(state)
	if err != nil {
		return fmt.Errorf("config: encode server key rotation: %w", err)
	}
	path := serverKeyRotationPath(stateDir)
	tmp, err := os.CreateTemp(stateDir, ".tmp-server-key-rotation-*")
	if err != nil {
		return fmt.Errorf("config: create temp file: %w", err)
	}
	tmpPath := tmp.Name()
	renamed := false
	defer func() {
		if !renamed {
			os.Remove(tmpPath)
		}
	}()
	if _, err := tmp.Write(data); err != nil {
		tmp.Close()
		return fmt.Errorf("config: write temp file: %w", err)
	}
	if err := tmp.Chmod(0o600); err != nil {
		tmp.Close()
		return fmt.Errorf("config: chmod temp file: %w", err)
	}
	if err := tmp.Sync(); err != nil {
		tmp.Close()
		return fmt.Errorf("config: sync temp file: %w", err)
	}
	if err := tmp.Close(); err != nil {
		return fmt.Errorf("config: close temp file: %w", err)
	}
	if err := os.Rename(tmpPath, path); err != nil {
		return fmt.Errorf("config: rename into place: %w", err)
	}
	renamed = true
	return nil
}
