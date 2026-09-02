package link

import (
	"testing"
	"time"

	"circuitbreaker.dev/cb-agent/internal/config"
	"circuitbreaker.dev/cb-agent/internal/tlsdial"
)

func TestResolveTrust_NoRotationIsTheConfiguredPin(t *testing.T) {
	got := ResolveTrust(&config.Config{TLSPin: "PIN-A"}, t.TempDir())
	if got.Mode != tlsdial.ModeSelfSigned {
		t.Errorf("Mode = %q, want %q", got.Mode, tlsdial.ModeSelfSigned)
	}
	if len(got.Pins) != 1 || got.Pins[0] != "PIN-A" {
		t.Errorf("Pins = %v, want [PIN-A]", got.Pins)
	}
}

// An empty tls_pin is how agent.toml expresses "public" trust — the
// installer writes no pin for a Let's Encrypt server.
func TestResolveTrust_EmptyPinIsPublicMode(t *testing.T) {
	got := ResolveTrust(&config.Config{}, t.TempDir())
	if got.Mode != tlsdial.ModePublic {
		t.Errorf("Mode = %q, want %q", got.Mode, tlsdial.ModePublic)
	}
}

func TestResolveTrust_AppendsThePersistedSuccessor(t *testing.T) {
	dir := t.TempDir()
	if err := config.SaveTLSPinRotation(dir, config.TLSPinRotation{
		Mode:         "self_signed",
		SuccessorPin: "PIN-B",
		Expiry:       time.Now().Add(time.Hour),
	}); err != nil {
		t.Fatalf("SaveTLSPinRotation: %v", err)
	}
	got := ResolveTrust(&config.Config{TLSPin: "PIN-A"}, dir)
	if len(got.Pins) != 2 || got.Pins[0] != "PIN-A" || got.Pins[1] != "PIN-B" {
		t.Errorf("Pins = %v, want [PIN-A PIN-B]", got.Pins)
	}
}

// A public-mode successor is the self-signed -> Let's Encrypt cutover. Both
// policies must stay acceptable across it, so the resolved mode stays
// self_signed (which is the one needing a callback) and the *server* proving
// a publicly-trusted leaf is handled by promotion, not by pre-emptively
// dropping the pin. Dropping it here would strand the agent the moment the
// successor was advertised but before the cert actually changed.
func TestResolveTrust_PublicSuccessorKeepsTheCurrentPinUsable(t *testing.T) {
	dir := t.TempDir()
	if err := config.SaveTLSPinRotation(dir, config.TLSPinRotation{
		Mode:   "public",
		Expiry: time.Now().Add(time.Hour),
	}); err != nil {
		t.Fatalf("SaveTLSPinRotation: %v", err)
	}
	got := ResolveTrust(&config.Config{TLSPin: "PIN-A"}, dir)
	if got.Mode != tlsdial.ModeSelfSigned {
		t.Errorf("Mode = %q, want the current policy to remain usable", got.Mode)
	}
	if len(got.Pins) != 1 || got.Pins[0] != "PIN-A" {
		t.Errorf("Pins = %v, want [PIN-A]", got.Pins)
	}
	if !got.PublicSuccessorPending {
		t.Error("PublicSuccessorPending = false, want true")
	}
}

func TestResolveTrust_EmptyStateDirSkipsTheLookup(t *testing.T) {
	got := ResolveTrust(&config.Config{TLSPin: "PIN-A"}, "")
	if len(got.Pins) != 1 {
		t.Errorf("Pins = %v, want just the configured pin", got.Pins)
	}
}
