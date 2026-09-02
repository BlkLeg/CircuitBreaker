package update

import (
	"crypto/ed25519"
	"encoding/base64"
	"errors"
	"fmt"
	"os"
	"strings"
)

// SigningPublicKey is the base64-encoded Ed25519 public key this binary
// verifies agent updates against. It is set at **build time** via
//
//	-ldflags "-X circuitbreaker.dev/cb-agent/internal/update.SigningPublicKey=<base64>"
//
// and is deliberately not configurable at runtime, not delivered by the
// server, and not read from disk. That is the entire point of route finding
// F3: integrity was previously a SHA-256 the *server* supplied, so a
// compromised server could serve any binary along with a matching digest and
// every agent would install it. A key the server can influence would
// reproduce exactly that.
//
// Empty is legitimate and common. `make build-from-source` cross-compiles
// agent binaries locally (scripts/build_native_release.py), and a
// self-hoster building their own has no access to the release private key.
// Such a build runs in warn mode; `make agent-signing-key` generates a
// keypair for operators who want enforcement on their own builds.
var SigningPublicKey = ""

// ErrNoSigningKey reports that this binary was built without an embedded
// public key, so no signature can be checked. Distinct from a verification
// *failure* on purpose: a caller must be able to warn about an unsigned
// build while still refusing a tampered one.
var ErrNoSigningKey = errors.New("update: this build has no embedded signing key")

// VerifySignature checks the detached Ed25519 signature at signaturePath
// over the exact bytes at binaryPath.
//
// Runs after VerifySHA256 and before the swap. The digest check proves the
// download matches what the server said; this proves the bytes were produced
// by whoever holds the signing key — which is what the server cannot forge.
func VerifySignature(binaryPath, signaturePath string) error {
	if SigningPublicKey == "" {
		return ErrNoSigningKey
	}
	pub, err := base64.StdEncoding.DecodeString(SigningPublicKey)
	if err != nil {
		return fmt.Errorf("update: decode embedded signing key: %w", err)
	}
	if len(pub) != ed25519.PublicKeySize {
		return fmt.Errorf(
			"update: embedded signing key is %d bytes, want %d",
			len(pub), ed25519.PublicKeySize,
		)
	}
	rawSig, err := os.ReadFile(signaturePath)
	if err != nil {
		return fmt.Errorf("update: read signature %s: %w", signaturePath, err)
	}
	sig, err := base64.StdEncoding.DecodeString(strings.TrimSpace(string(rawSig)))
	if err != nil {
		return fmt.Errorf("update: decode signature: %w", err)
	}
	// Read the whole binary rather than streaming: ed25519.Verify has no
	// streaming form, maxDownloadBytes already bounds the size, and the file
	// was just written by this process.
	contents, err := os.ReadFile(binaryPath)
	if err != nil {
		return fmt.Errorf("update: read %s: %w", binaryPath, err)
	}
	if !ed25519.Verify(ed25519.PublicKey(pub), contents, sig) {
		return errors.New("update: signature does not verify against the embedded signing key")
	}
	return nil
}

// SignatureEnforced reports whether a failed or absent signature must refuse
// the update rather than only warn.
//
// Defaults to false — warn — because agents running today have no embedded
// key and binaries built before this change carry no .sig at all. The
// default flips one release later, announced in the warn release's notes.
func SignatureEnforced() bool {
	switch strings.ToLower(strings.TrimSpace(os.Getenv("CB_AGENT_UPDATE_ENFORCE_SIGNATURE"))) {
	case "1", "true", "yes", "on":
		return true
	default:
		return false
	}
}

// Decision outcomes for one signature-verification result.
const (
	DecisionProceed = "proceed"
	DecisionWarn    = "warn"
	DecisionRefuse  = "refuse"
)

// UpdateDecision maps a verification outcome and the enforcement flag onto
// what the update path should do. Split out from the update path itself so
// the policy — which is the whole of slice 4.2's warn->enforce migration —
// is testable without a download, a swap and a re-exec.
//
// ErrNoSigningKey warns under *both* modes on purpose: a binary built with
// no embedded key has nothing to verify against, and `make
// build-from-source` produces exactly such a binary. Refusing it under
// enforce would strand every self-built agent the moment the flag defaults
// on, which would make enforcement unshippable.
func UpdateDecision(verifyErr error, enforced bool) string {
	switch {
	case verifyErr == nil:
		return DecisionProceed
	case errors.Is(verifyErr, ErrNoSigningKey):
		return DecisionWarn
	case enforced:
		return DecisionRefuse
	default:
		return DecisionWarn
	}
}
