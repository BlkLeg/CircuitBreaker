package link

import (
	"encoding/json"
	"os"
	"testing"
)

// The vectors are shared with the server's suite
// (tests/build/test_tls_pin_fingerprint_contract.py). Both read this one file,
// so an implementation that drifts fails its own language's tests rather than
// only being caught in a composed E2E — or, more likely, not at all: each
// suite checking its own arithmetic against itself would agree with whatever
// it had become.
type fingerprintVectors struct {
	Algorithm string `json:"algorithm"`
	Cases     []struct {
		Name        string `json:"name"`
		Mode        string `json:"mode"`
		Pin         string `json:"pin"`
		Fingerprint string `json:"fingerprint"`
	} `json:"cases"`
}

func loadFingerprintVectors(t *testing.T) fingerprintVectors {
	t.Helper()
	raw, err := os.ReadFile("testdata/fingerprint_vectors.json")
	if err != nil {
		t.Fatalf("read shared fingerprint vectors: %v", err)
	}
	var vectors fingerprintVectors
	if err := json.Unmarshal(raw, &vectors); err != nil {
		t.Fatalf("parse shared fingerprint vectors: %v", err)
	}
	if len(vectors.Cases) == 0 {
		t.Fatal("shared fingerprint vectors are empty; the contract would pass vacuously")
	}
	return vectors
}

func TestPolicyFingerprintMatchesSharedVectors(t *testing.T) {
	for _, c := range loadFingerprintVectors(t).Cases {
		got := PolicyFingerprint(c.Mode, c.Pin)
		if got != c.Fingerprint {
			t.Errorf(
				"%s: PolicyFingerprint(%q, %q) = %q, shared vector says %q. "+
					"The server credits convergence on this digest matching; a drift "+
					"here makes every agent read as unconverged and forces every rotation",
				c.Name, c.Mode, c.Pin, got, c.Fingerprint,
			)
		}
	}
}

func TestPolicyFingerprintSeparatesModeFromPin(t *testing.T) {
	// ("self", "_signedX") and ("self_signed", "X") concatenate to the same
	// bytes. Mode and pin are distinct fields and a digest that conflated them
	// would let one policy pass as another.
	if PolicyFingerprint("self", "_signedX") == PolicyFingerprint("self_signed", "X") {
		t.Fatal("mode and pin are concatenated without a separator")
	}
}

func TestSuccessorFingerprintIsEmptyWithoutARotation(t *testing.T) {
	// "" is the honest answer, and the server counts it as unconverged. An
	// agent that reports a fingerprint it does not hold is exactly the stale
	// successor this field exists to expose.
	if got := SuccessorFingerprint(t.TempDir()); got != "" {
		t.Fatalf("SuccessorFingerprint with no persisted rotation = %q, want empty", got)
	}
	if got := SuccessorFingerprint(""); got != "" {
		t.Fatalf("SuccessorFingerprint with no state dir = %q, want empty", got)
	}
}
