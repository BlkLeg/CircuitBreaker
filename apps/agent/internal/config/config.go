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

// TLSPinRotation is the successor TLS trust policy a server advertised to
// this agent over an authenticated `/link` connection (a `tls.pin.rotate`
// frame — see internal/frame.TLSPinRotatePayload and internal/link's
// handling of it), persisted so it survives reconnects and restarts.
//
// Held *alongside* agent.toml's own tls_pin, never in place of it: both
// policies stay acceptable until the agent actually completes a dial against
// the successor, at which point it promotes (see internal/link.PromoteTrust)
// and this file is cleared. agent.toml is never rewritten — it is root-owned
// and read-only to the agent, and a half-written config file would leave the
// agent unable to reach the server at all.
//
// Mode is "self_signed" (SuccessorPin holds the base64 SHA-256 SPKI digest
// of the successor leaf) or "public" (SuccessorPin is empty and the system
// CA store applies). Expiry is carried for observability; nothing on the
// agent acts on it, matching ServerKeyRotation's handling of the same field.
type TLSPinRotation struct {
	Mode         string    `json:"mode"`
	SuccessorPin string    `json:"successor_pin"`
	Expiry       time.Time `json:"expiry"`
}

func tlsPinRotationPath(stateDir string) string {
	return filepath.Join(stateDir, "tls_pin_rotation.json")
}

// LoadTLSPinRotation reads the persisted successor trust policy, if any.
// Returns (nil, nil) — not an error — when none has ever been advertised to
// this agent, which is the overwhelmingly common case.
func LoadTLSPinRotation(stateDir string) (*TLSPinRotation, error) {
	data, err := os.ReadFile(tlsPinRotationPath(stateDir))
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, fmt.Errorf("config: load tls pin rotation: %w", err)
	}
	var state TLSPinRotation
	if err := json.Unmarshal(data, &state); err != nil {
		return nil, fmt.Errorf("config: decode tls pin rotation: %w", err)
	}
	return &state, nil
}

// SaveTLSPinRotation durably persists state via a temp-file-then-rename
// write, so a crash between writing and the next read can never leave a
// corrupt, unparseable trust file behind.
func SaveTLSPinRotation(stateDir string, state TLSPinRotation) error {
	data, err := json.Marshal(state)
	if err != nil {
		return fmt.Errorf("config: encode tls pin rotation: %w", err)
	}
	return writeStateFileAtomically(stateDir, tlsPinRotationPath(stateDir), ".tmp-tls-pin-rotation-*", data)
}

// writeStateFileAtomically writes data to path via a temp-file-then-rename,
// so a crash between writing and the next read can never leave a corrupt,
// unparseable trust file behind. Shared by both TLS trust state files.
func writeStateFileAtomically(stateDir, path, pattern string, data []byte) error {
	tmp, err := os.CreateTemp(stateDir, pattern)
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

// ClearTLSPinRotation removes the persisted successor policy after a
// successful promotion. Absence is success: a clear that finds nothing has
// already achieved what it was asked to do.
func ClearTLSPinRotation(stateDir string) error {
	if err := os.Remove(tlsPinRotationPath(stateDir)); err != nil && !os.IsNotExist(err) {
		return fmt.Errorf("config: clear tls pin rotation: %w", err)
	}
	return nil
}

// TLSTrustPolicy is the trust policy this agent currently honors, once a
// rotation has actually completed — the successor it promoted after dialing
// against it successfully.
//
// This file exists because promotion cannot be expressed by deleting the
// rotation alone. agent.toml is root-owned and never rewritten (see
// TLSPinRotation), so its tls_pin still names the *replaced* certificate
// after a cutover. An agent that cleared the rotation and fell back to it
// would verify against the old leaf on its very next reconnect and strand —
// surviving exactly one connection past the cutover, which is the failure
// slice 4.1 exists to eliminate.
//
// Absent on every agent that has never completed a rotation, which is the
// overwhelmingly common case. Mode/Pin use the same vocabulary as
// TLSPinRotation: "self_signed" with a base64 SHA-256 SPKI digest, or
// "public" with an empty pin.
type TLSTrustPolicy struct {
	Mode string `json:"mode"`
	Pin  string `json:"pin"`
}

func effectiveTLSTrustPath(stateDir string) string {
	return filepath.Join(stateDir, "tls_trust.json")
}

// LoadEffectiveTLSTrust reads the promoted trust policy, if any. Returns
// (nil, nil) — not an error — when this agent has never completed a
// rotation, in which case agent.toml's tls_pin is still the effective
// policy.
func LoadEffectiveTLSTrust(stateDir string) (*TLSTrustPolicy, error) {
	data, err := os.ReadFile(effectiveTLSTrustPath(stateDir))
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, fmt.Errorf("config: load effective tls trust: %w", err)
	}
	var policy TLSTrustPolicy
	if err := json.Unmarshal(data, &policy); err != nil {
		return nil, fmt.Errorf("config: decode effective tls trust: %w", err)
	}
	return &policy, nil
}

// SaveEffectiveTLSTrust durably records the policy this agent promoted,
// through the same temp-file-then-rename write SaveTLSPinRotation uses.
func SaveEffectiveTLSTrust(stateDir string, policy TLSTrustPolicy) error {
	data, err := json.Marshal(policy)
	if err != nil {
		return fmt.Errorf("config: encode effective tls trust: %w", err)
	}
	return writeStateFileAtomically(
		stateDir, effectiveTLSTrustPath(stateDir), ".tmp-tls-trust-*", data,
	)
}
