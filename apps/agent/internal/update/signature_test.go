package update

import (
	"crypto/ed25519"
	"crypto/rand"
	"encoding/base64"
	"errors"
	"os"
	"path/filepath"
	"testing"
)

// signedFixture writes a binary and a valid detached signature over it, and
// returns their paths plus the base64 public key. The keypair is generated
// per-test: no signing key may be checked into this repository, including in
// test fixtures.
func signedFixture(t *testing.T, contents []byte) (binPath, sigPath, pubB64 string) {
	t.Helper()
	pub, priv, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatalf("generate key: %v", err)
	}
	dir := t.TempDir()
	binPath = filepath.Join(dir, "cb-agent")
	sigPath = binPath + ".sig"
	if err := os.WriteFile(binPath, contents, 0o755); err != nil {
		t.Fatalf("write binary: %v", err)
	}
	sig := ed25519.Sign(priv, contents)
	if err := os.WriteFile(sigPath, []byte(base64.StdEncoding.EncodeToString(sig)), 0o644); err != nil {
		t.Fatalf("write signature: %v", err)
	}
	return binPath, sigPath, base64.StdEncoding.EncodeToString(pub)
}

func TestVerifySignature_AcceptsAValidSignature(t *testing.T) {
	binPath, sigPath, pub := signedFixture(t, []byte("agent binary contents"))
	t.Cleanup(withSigningKey(pub))

	if err := VerifySignature(binPath, sigPath); err != nil {
		t.Errorf("VerifySignature = %v, want nil", err)
	}
}

// The whole point of F3: a server that serves a different binary, with a
// matching SHA-256 it also controls, must still be refused.
func TestVerifySignature_RefusesATamperedBinary(t *testing.T) {
	binPath, sigPath, pub := signedFixture(t, []byte("agent binary contents"))
	t.Cleanup(withSigningKey(pub))

	if err := os.WriteFile(binPath, []byte("malicious contents"), 0o755); err != nil {
		t.Fatalf("tamper: %v", err)
	}
	if err := VerifySignature(binPath, sigPath); err == nil {
		t.Error("VerifySignature on a tampered binary = nil, want an error")
	}
}

func TestVerifySignature_RefusesASignatureFromAnotherKey(t *testing.T) {
	binPath, sigPath, _ := signedFixture(t, []byte("agent binary contents"))
	otherPub, _, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatalf("generate key: %v", err)
	}
	t.Cleanup(withSigningKey(base64.StdEncoding.EncodeToString(otherPub)))

	if err := VerifySignature(binPath, sigPath); err == nil {
		t.Error("VerifySignature against an unrelated key = nil, want an error")
	}
}

func TestVerifySignature_RefusesAMissingSignature(t *testing.T) {
	binPath, sigPath, pub := signedFixture(t, []byte("agent binary contents"))
	t.Cleanup(withSigningKey(pub))
	os.Remove(sigPath)

	if err := VerifySignature(binPath, sigPath); err == nil {
		t.Error("VerifySignature with no signature file = nil, want an error")
	}
}

// A binary built without an embedded key (the `make build-from-source` case)
// reports a distinguishable sentinel, so the caller can warn rather than
// refuse. Conflating "unsigned build" with "bad signature" would brick every
// self-hoster's own build the moment enforcement defaulted on.
func TestVerifySignature_NoEmbeddedKeyIsADistinctError(t *testing.T) {
	binPath, sigPath, _ := signedFixture(t, []byte("agent binary contents"))
	t.Cleanup(withSigningKey(""))

	err := VerifySignature(binPath, sigPath)
	if !errors.Is(err, ErrNoSigningKey) {
		t.Errorf("VerifySignature with no embedded key = %v, want ErrNoSigningKey", err)
	}
}

func TestSignatureEnforced_DefaultsToWarn(t *testing.T) {
	t.Setenv("CB_AGENT_UPDATE_ENFORCE_SIGNATURE", "")
	if SignatureEnforced() {
		t.Error("SignatureEnforced() = true with the flag unset, want false (warn mode)")
	}
}

func TestSignatureEnforced_HonorsTheFlag(t *testing.T) {
	for _, v := range []string{"1", "true", "TRUE", "yes"} {
		t.Setenv("CB_AGENT_UPDATE_ENFORCE_SIGNATURE", v)
		if !SignatureEnforced() {
			t.Errorf("SignatureEnforced() = false for %q, want true", v)
		}
	}
}

// withSigningKey swaps the build-time key for the duration of one test and
// returns the restore function.
func withSigningKey(pub string) func() {
	previous := SigningPublicKey
	SigningPublicKey = pub
	return func() { SigningPublicKey = previous }
}
