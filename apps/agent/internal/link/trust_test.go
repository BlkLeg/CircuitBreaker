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

func TestHandleTLSPinRotate_PersistsTheSuccessor(t *testing.T) {
	dir := t.TempDir()
	payload := []byte(`{"mode":"self_signed","successor_pin":"PIN-B","expiry":"2026-09-08T10:00:00Z"}`)

	handleTLSPinRotate(Options{StateDir: dir}, payload)

	got, err := config.LoadTLSPinRotation(dir)
	if err != nil {
		t.Fatalf("LoadTLSPinRotation: %v", err)
	}
	if got == nil {
		t.Fatal("LoadTLSPinRotation = nil, want the advertised rotation")
	}
	if got.Mode != "self_signed" || got.SuccessorPin != "PIN-B" {
		t.Errorf("persisted = %+v, want mode=self_signed pin=PIN-B", *got)
	}
}

func TestHandleTLSPinRotate_PersistsAPublicCutover(t *testing.T) {
	dir := t.TempDir()
	payload := []byte(`{"mode":"public","successor_pin":"","expiry":"2026-09-08T10:00:00Z"}`)

	handleTLSPinRotate(Options{StateDir: dir}, payload)

	got, err := config.LoadTLSPinRotation(dir)
	if err != nil {
		t.Fatalf("LoadTLSPinRotation: %v", err)
	}
	if got == nil || got.Mode != "public" {
		t.Errorf("persisted = %+v, want a present public-mode rotation", got)
	}
}

// A malformed or unknown-mode frame must be dropped, not persisted. Writing
// garbage into the trust file would be worse than ignoring the frame: the
// agent still reaches the server on its current pin, and an operator can
// retry the rotation.
func TestHandleTLSPinRotate_DropsMalformedAndUnknownModes(t *testing.T) {
	for name, payload := range map[string]string{
		"malformed json": `{not json`,
		"unknown mode":   `{"mode":"whatever","successor_pin":"X","expiry":"2026-09-08T10:00:00Z"}`,
		"self_signed with no pin": `{"mode":"self_signed","successor_pin":"","expiry":"2026-09-08T10:00:00Z"}`,
	} {
		t.Run(name, func(t *testing.T) {
			dir := t.TempDir()
			handleTLSPinRotate(Options{StateDir: dir}, []byte(payload))
			got, err := config.LoadTLSPinRotation(dir)
			if err != nil {
				t.Fatalf("LoadTLSPinRotation: %v", err)
			}
			if got != nil {
				t.Errorf("persisted = %+v, want nothing written", *got)
			}
		})
	}
}

// StateDir unset means there is nowhere durable to record the successor.
// Logging and dropping is correct; panicking or writing to the process CWD
// would both be worse.
func TestHandleTLSPinRotate_NoStateDirIsANoOp(t *testing.T) {
	handleTLSPinRotate(Options{}, []byte(`{"mode":"public","expiry":"2026-09-08T10:00:00Z"}`))
}

func TestPromoteTrust_MatchingTheCurrentPinReportsCurrentAndKeepsTheRotation(t *testing.T) {
	dir := t.TempDir()
	if err := config.SaveTLSPinRotation(dir, config.TLSPinRotation{
		Mode: "self_signed", SuccessorPin: "PIN-B", Expiry: time.Now().Add(time.Hour),
	}); err != nil {
		t.Fatalf("SaveTLSPinRotation: %v", err)
	}

	kind, err := PromoteTrust(&config.Config{TLSPin: "PIN-A"}, dir, 0)
	if err != nil {
		t.Fatalf("PromoteTrust: %v", err)
	}
	if kind != "current" {
		t.Errorf("kind = %q, want current", kind)
	}
	got, err := config.LoadTLSPinRotation(dir)
	if err != nil {
		t.Fatalf("LoadTLSPinRotation: %v", err)
	}
	if got == nil {
		t.Error("rotation was cleared on a current-pin match, want it kept — the cutover has not happened yet")
	}
}

func TestPromoteTrust_MatchingTheSuccessorClearsTheRotation(t *testing.T) {
	dir := t.TempDir()
	if err := config.SaveTLSPinRotation(dir, config.TLSPinRotation{
		Mode: "self_signed", SuccessorPin: "PIN-B", Expiry: time.Now().Add(time.Hour),
	}); err != nil {
		t.Fatalf("SaveTLSPinRotation: %v", err)
	}

	kind, err := PromoteTrust(&config.Config{TLSPin: "PIN-A"}, dir, 1)
	if err != nil {
		t.Fatalf("PromoteTrust: %v", err)
	}
	if kind != "successor" {
		t.Errorf("kind = %q, want successor", kind)
	}
	got, err := config.LoadTLSPinRotation(dir)
	if err != nil {
		t.Fatalf("LoadTLSPinRotation: %v", err)
	}
	if got != nil {
		t.Errorf("rotation = %+v after promotion, want it cleared", *got)
	}
}

func TestPromoteTrust_NoRotationReportsCurrent(t *testing.T) {
	kind, err := PromoteTrust(&config.Config{TLSPin: "PIN-A"}, t.TempDir(), 0)
	if err != nil {
		t.Fatalf("PromoteTrust: %v", err)
	}
	if kind != "current" {
		t.Errorf("kind = %q, want current", kind)
	}
}

// The self-signed -> Let's Encrypt cutover. The pinned dial fails because the
// new leaf is publicly trusted rather than pinned; because a public successor
// was advertised, one standard-verification retry is warranted.
func TestSuccessorRetry_SelfSignedToPublic(t *testing.T) {
	pinned := tlsdial.Trust{Mode: tlsdial.ModeSelfSigned, Pins: []string{"PIN-A"}}

	if _, ok := successorRetryTrust(pinned, nil); ok {
		t.Error("successorRetryTrust with no advertised successor = true, want false")
	}

	retry, ok := successorRetryTrust(pinned, &config.TLSPinRotation{Mode: "public"})
	if !ok {
		t.Fatal("successorRetryTrust with an advertised public successor = false, want true")
	}
	if retry.Mode != tlsdial.ModePublic {
		t.Errorf("retry mode = %q, want public", retry.Mode)
	}
}

// The reverse cutover, Let's Encrypt -> self-signed. The agent holds no pin and
// does standard verification, which a self-signed leaf can never pass — the
// mirror image of the case above, and equally fleet-fatal without a retry.
func TestSuccessorRetry_PublicToSelfSigned(t *testing.T) {
	unpinned := tlsdial.Trust{Mode: tlsdial.ModePublic}

	retry, ok := successorRetryTrust(unpinned, &config.TLSPinRotation{
		Mode: "self_signed", SuccessorPin: "PIN-B",
	})
	if !ok {
		t.Fatal("successorRetryTrust with an advertised self-signed successor = false, want true")
	}
	if retry.Mode != tlsdial.ModeSelfSigned {
		t.Errorf("retry mode = %q, want self_signed", retry.Mode)
	}
	if len(retry.Pins) != 1 || retry.Pins[0] != "PIN-B" {
		t.Errorf("retry pins = %v, want [PIN-B]", retry.Pins)
	}
}

// A same-mode successor is not a cross-mode cutover: ResolveTrust already
// carries it as an extra pin candidate, so the first dial covers it and a
// retry would be redundant.
func TestSuccessorRetry_NotOfferedForASameModeSuccessor(t *testing.T) {
	pinned := tlsdial.Trust{Mode: tlsdial.ModeSelfSigned, Pins: []string{"PIN-A", "PIN-B"}}

	if _, ok := successorRetryTrust(pinned, &config.TLSPinRotation{
		Mode: "self_signed", SuccessorPin: "PIN-B",
	}); ok {
		t.Error("successorRetryTrust for a same-mode successor = true, want false")
	}
}

// A self-signed successor with no pin is malformed; there is nothing to retry
// against and it must not produce an empty pin set, which tlsdial fails closed
// on anyway.
func TestSuccessorRetry_RefusesASelfSignedSuccessorWithNoPin(t *testing.T) {
	if _, ok := successorRetryTrust(tlsdial.Trust{Mode: tlsdial.ModePublic},
		&config.TLSPinRotation{Mode: "self_signed"}); ok {
		t.Error("successorRetryTrust with a pinless self-signed successor = true, want false")
	}
}

// After a successful public retry the agent promotes: the advertised policy is
// now the served one, so the rotation file is cleared and the connection
// reports "successor" — which is what lets convergence reach zero and the
// operator's activation gate open.
func TestPromoteTrust_PublicRetryReportsSuccessorAndClears(t *testing.T) {
	dir := t.TempDir()
	if err := config.SaveTLSPinRotation(dir, config.TLSPinRotation{
		Mode: "public", Expiry: time.Now().Add(time.Hour),
	}); err != nil {
		t.Fatalf("SaveTLSPinRotation: %v", err)
	}

	kind, err := PromoteTrust(&config.Config{TLSPin: "PIN-A"}, dir, successorRetryIndex)
	if err != nil {
		t.Fatalf("PromoteTrust: %v", err)
	}
	if kind != "successor" {
		t.Errorf("kind = %q, want successor", kind)
	}
	got, err := config.LoadTLSPinRotation(dir)
	if err != nil {
		t.Fatalf("LoadTLSPinRotation: %v", err)
	}
	if got != nil {
		t.Errorf("rotation = %+v after a public promotion, want it cleared", *got)
	}
}
