package noiseconn

import (
	"bytes"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"

	"github.com/flynn/noise"
)

// This is the cipher-state counterpart to internal/frame's conformance_test.go:
// where that one pins the JSON wire shape against the Python side, this one
// pins the *key schedule*. Both peers rekey their transport ciphers every 15
// minutes, so github.com/flynn/noise's CipherState.Rekey() and dissononce's
// Cipher.rekey() must agree byte-for-byte or the link silently stops
// decrypting mid-session. The same fixture is asserted from Python in
// apps/backend/tests/test_noise_rekey_conformance.py.

type rekeyVectors struct {
	InitialKeyHex    string   `json:"initial_key_hex"`
	RekeyedKeysHex   []string `json:"rekeyed_keys_hex"`
	TransportMessage struct {
		Nonce         uint64 `json:"nonce"`
		ADHex         string `json:"ad_hex"`
		PlaintextHex  string `json:"plaintext_hex"`
		CiphertextHex string `json:"ciphertext_hex"`
	} `json:"transport_message"`
}

func loadRekeyVectors(t *testing.T) rekeyVectors {
	t.Helper()
	// apps/agent/internal/noiseconn -> repo root is four levels up.
	path := filepath.Join("..", "..", "..", "..", "fixtures", "noise_rekey_vectors.json")
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read rekey vectors: %v", err)
	}
	var v rekeyVectors
	if err := json.Unmarshal(data, &v); err != nil {
		t.Fatalf("unmarshal rekey vectors: %v", err)
	}
	if len(v.RekeyedKeysHex) == 0 {
		t.Fatal("rekey vectors: no generations in fixture")
	}
	return v
}

func mustHexKey(t *testing.T, s string) [32]byte {
	t.Helper()
	raw, err := hex.DecodeString(s)
	if err != nil {
		t.Fatalf("decode key hex %q: %v", s, err)
	}
	if len(raw) != 32 {
		t.Fatalf("key hex %q decodes to %d bytes, want 32", s, len(raw))
	}
	var k [32]byte
	copy(k[:], raw)
	return k
}

// TestRekey_MatchesCrossLanguageVectors walks the fixture's rekey chain with
// flynn/noise's real Rekey() and asserts every generation's key material.
func TestRekey_MatchesCrossLanguageVectors(t *testing.T) {
	v := loadRekeyVectors(t)
	cs := noise.NewCipherSuite(noise.DH25519, noise.CipherChaChaPoly, noise.HashSHA256)
	state := noise.UnsafeNewCipherState(cs, mustHexKey(t, v.InitialKeyHex), 0)

	for i, wantHex := range v.RekeyedKeysHex {
		state.Rekey()
		got := state.UnsafeKey()
		if want := mustHexKey(t, wantHex); got != want {
			t.Fatalf("generation %d key = %x, want %x", i+1, got, want)
		}
	}
}

// TestRekey_PreservesNonce pins the spec §11.3 requirement that REKEY updates
// k but leaves n alone. dissononce's own CipherState.rekey() resets n to 0,
// which is why app/core/agent_crypto.py implements the operation itself
// instead of calling that wrapper — this test is the Go half of that contract.
func TestRekey_PreservesNonce(t *testing.T) {
	v := loadRekeyVectors(t)
	cs := noise.NewCipherSuite(noise.DH25519, noise.CipherChaChaPoly, noise.HashSHA256)
	for _, startNonce := range []uint64{0, 1, 42} {
		state := noise.UnsafeNewCipherState(cs, mustHexKey(t, v.InitialKeyHex), startNonce)
		state.Rekey()
		if got := state.Nonce(); got != startNonce {
			t.Errorf("nonce after Rekey() from %d = %d, want unchanged", startNonce, got)
		}
	}
}

// TestRekey_TransportMessageIsInteroperable is the actual interop proof: a
// cipher state rekeyed N times by flynn/noise produces exactly the ciphertext
// the fixture records (which the Python test independently reproduces with
// dissononce), and decrypts that same ciphertext back to the fixture
// plaintext.
func TestRekey_TransportMessageIsInteroperable(t *testing.T) {
	v := loadRekeyVectors(t)
	cs := noise.NewCipherSuite(noise.DH25519, noise.CipherChaChaPoly, noise.HashSHA256)

	ad, err := hex.DecodeString(v.TransportMessage.ADHex)
	if err != nil {
		t.Fatalf("decode ad: %v", err)
	}
	plaintext, err := hex.DecodeString(v.TransportMessage.PlaintextHex)
	if err != nil {
		t.Fatalf("decode plaintext: %v", err)
	}
	wantCT, err := hex.DecodeString(v.TransportMessage.CiphertextHex)
	if err != nil {
		t.Fatalf("decode ciphertext: %v", err)
	}

	newRekeyedState := func() *noise.CipherState {
		s := noise.UnsafeNewCipherState(cs, mustHexKey(t, v.InitialKeyHex), 0)
		for range v.RekeyedKeysHex {
			s.Rekey()
		}
		s.SetNonce(v.TransportMessage.Nonce)
		return s
	}

	gotCT, err := newRekeyedState().Encrypt(nil, ad, plaintext)
	if err != nil {
		t.Fatalf("Encrypt() error = %v", err)
	}
	if !bytes.Equal(gotCT, wantCT) {
		t.Errorf("ciphertext = %x, want %x", gotCT, wantCT)
	}

	gotPT, err := newRekeyedState().Decrypt(nil, ad, wantCT)
	if err != nil {
		t.Fatalf("Decrypt() error = %v", err)
	}
	if !bytes.Equal(gotPT, plaintext) {
		t.Errorf("plaintext = %x, want %x", gotPT, plaintext)
	}
}
