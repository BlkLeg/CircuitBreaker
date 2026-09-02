package update

import (
	"crypto/ed25519"
	"crypto/rand"
	"encoding/base64"
	"errors"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"circuitbreaker.dev/cb-agent/internal/config"
	"circuitbreaker.dev/cb-agent/internal/tlsdial"
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

func TestDownloadSignature_FetchesTheSigBesideTheBinary(t *testing.T) {
	var requested string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requested = r.URL.Path
		w.Write([]byte("c2lnbmF0dXJlLWJ5dGVz"))
	}))
	defer srv.Close()

	path, err := DownloadSignature(
		&config.Config{ServerURL: srv.URL},
		tlsdial.Trust{Mode: tlsdial.ModePublic},
		Instruction{Version: "1.2.3", Arch: "amd64", OS: "linux"},
	)
	if err != nil {
		t.Fatalf("DownloadSignature = %v", err)
	}
	defer os.Remove(path)

	if !strings.HasSuffix(requested, ".sig") {
		t.Errorf("requested %q, want a path ending in .sig", requested)
	}
	got, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read downloaded signature: %v", err)
	}
	if string(got) != "c2lnbmF0dXJlLWJ5dGVz" {
		t.Errorf("downloaded %q, want the served signature", got)
	}
}

// A signature is 88 base64 characters. Reusing maxDownloadBytes would let a
// hostile server stream gigabytes into a client expecting a fixed-size blob.
func TestDownloadSignature_RefusesAnOversizedResponse(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Write(make([]byte, maxSignatureBytes+1))
	}))
	defer srv.Close()

	if _, err := DownloadSignature(
		&config.Config{ServerURL: srv.URL},
		tlsdial.Trust{Mode: tlsdial.ModePublic},
		Instruction{Version: "1.2.3", Arch: "amd64", OS: "linux"},
	); err == nil {
		t.Error("DownloadSignature on an oversized response = nil, want an error")
	}
}

func TestDownloadSignature_MissingSignatureIsAnError(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, "not found", http.StatusNotFound)
	}))
	defer srv.Close()

	if _, err := DownloadSignature(
		&config.Config{ServerURL: srv.URL},
		tlsdial.Trust{Mode: tlsdial.ModePublic},
		Instruction{Version: "1.2.3", Arch: "amd64", OS: "linux"},
	); err == nil {
		t.Error("DownloadSignature on a 404 = nil, want an error")
	}
}

// UpdateDecision is the branch the update path takes for one verification
// outcome. Testing it here keeps the warn->enforce policy verifiable without
// standing up a download, a swap and a re-exec.
func TestUpdateDecision(t *testing.T) {
	cases := []struct {
		name      string
		verifyErr error
		enforced  bool
		want      string
	}{
		{"verified", nil, true, DecisionProceed},
		{"verified, warn mode", nil, false, DecisionProceed},
		{"no embedded key, warn mode", ErrNoSigningKey, false, DecisionWarn},
		// A build with no embedded key has nothing to verify against.
		// Refusing here would strand every self-built agent the moment
		// enforcement defaults on.
		{"no embedded key, enforce mode", ErrNoSigningKey, true, DecisionWarn},
		{"bad signature, warn mode", errors.New("bad sig"), false, DecisionWarn},
		{"bad signature, enforce mode", errors.New("bad sig"), true, DecisionRefuse},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := UpdateDecision(tc.verifyErr, tc.enforced); got != tc.want {
				t.Errorf("UpdateDecision(%v, %v) = %q, want %q",
					tc.verifyErr, tc.enforced, got, tc.want)
			}
		})
	}
}
