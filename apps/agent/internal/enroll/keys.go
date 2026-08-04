// apps/agent/internal/enroll/keys.go
package enroll

import (
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"golang.org/x/crypto/curve25519"
)

type DeviceKey struct {
	Private [32]byte
	Public  [32]byte
}

const deviceKeyFilename = "device.key"

// LoadDeviceKey reads <stateDir>/device.key if present, without ever
// creating one. ok is false with a nil error when no key exists yet — the
// correct response for read-only/inspection callers like `cb-agent status`
// and `cb-agent version`, which must not generate agent identity as a side
// effect of an inspection command.
func LoadDeviceKey(stateDir string) (key *DeviceKey, ok bool, err error) {
	path := filepath.Join(stateDir, deviceKeyFilename)

	data, err := os.ReadFile(path)
	if os.IsNotExist(err) {
		return nil, false, nil
	}
	if err != nil {
		return nil, false, fmt.Errorf("enroll: read %s: %w", path, err)
	}
	if len(data) != 32 {
		return nil, false, fmt.Errorf("enroll: device.key at %s has length %d, want 32", path, len(data))
	}
	var priv [32]byte
	copy(priv[:], data)
	key, err = deviceKeyFromPrivate(priv)
	if err != nil {
		return nil, false, err
	}
	return key, true, nil
}

// LoadOrCreateDeviceKey reads <stateDir>/device.key if present, else generates
// an X25519 keypair and persists the private key (mode 0600).
func LoadOrCreateDeviceKey(stateDir string) (*DeviceKey, error) {
	if key, ok, err := LoadDeviceKey(stateDir); err != nil {
		return nil, err
	} else if ok {
		return key, nil
	}

	path := filepath.Join(stateDir, deviceKeyFilename)
	var priv [32]byte
	if _, err := rand.Read(priv[:]); err != nil {
		return nil, fmt.Errorf("enroll: generate private key: %w", err)
	}

	if err := os.MkdirAll(stateDir, 0o700); err != nil {
		return nil, fmt.Errorf("enroll: create state dir %s: %w", stateDir, err)
	}
	if err := os.WriteFile(path, priv[:], 0o600); err != nil {
		return nil, fmt.Errorf("enroll: write %s: %w", path, err)
	}

	return deviceKeyFromPrivate(priv)
}

func deviceKeyFromPrivate(priv [32]byte) (*DeviceKey, error) {
	pub, err := curve25519.X25519(priv[:], curve25519.Basepoint)
	if err != nil {
		return nil, fmt.Errorf("enroll: derive public key: %w", err)
	}
	var pubArr [32]byte
	copy(pubArr[:], pub)
	return &DeviceKey{Private: priv, Public: pubArr}, nil
}

// Fingerprint returns 32 lowercase hex chars — the first 16 bytes of SHA-256
// over the public key. Matches app.core.agent_crypto.server_fingerprint()'s
// derivation on the Python side.
func (k *DeviceKey) Fingerprint() string {
	sum := sha256.Sum256(k.Public[:])
	return hex.EncodeToString(sum[:16])
}

// FingerprintGrouped renders Fingerprint() as eight 4-char groups joined by
// "-", the display form shown on stdout and compared against the approval
// screen (spec §2.1).
func (k *DeviceKey) FingerprintGrouped() string {
	fp := k.Fingerprint()
	groups := make([]string, 0, 8)
	for i := 0; i < len(fp); i += 4 {
		groups = append(groups, fp[i:i+4])
	}
	return strings.Join(groups, "-")
}
