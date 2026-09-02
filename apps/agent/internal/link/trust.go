package link

import (
	"log"

	"circuitbreaker.dev/cb-agent/internal/config"
	"circuitbreaker.dev/cb-agent/internal/tlsdial"
)

// ResolveTrust returns the TLS trust policy every dial in this agent should
// honor: agent.toml's tls_pin as the effective policy, plus any successor a
// `tls.pin.rotate` frame advertised and internal/config durably persisted.
//
// This is the single resolver. All four dial sites — enrollment
// (internal/enroll), the /link websocket and its re-dial (internal/link), and
// the update download (internal/update) — go through it, so no path can be
// left behind on a trust change. That mattered enough to gate: the update
// download is how a broken agent would otherwise be repaired, so a stranded
// download path makes every other stranding unrecoverable.
// tests/build/test_phase4_supply_chain_ratchets.py enforces it.
//
// stateDir == "" skips the persisted-rotation lookup entirely and returns
// just the configured policy, unchanged from this function's absence —
// matching serverKeyCandidates' handling of the same case.
func ResolveTrust(cfg *config.Config, stateDir string) tlsdial.Trust {
	trust := tlsdial.Trust{Mode: tlsdial.ModeSelfSigned, Pins: []string{cfg.TLSPin}}
	if cfg.TLSPin == "" {
		trust = tlsdial.Trust{Mode: tlsdial.ModePublic}
	}
	if stateDir == "" {
		return trust
	}
	rotation, err := config.LoadTLSPinRotation(stateDir)
	if err != nil {
		log.Printf("link: reading persisted tls pin rotation: %v", err)
		return trust
	}
	if rotation == nil {
		return trust
	}
	if rotation.Mode == tlsdial.ModePublic {
		trust.PublicSuccessorPending = true
		return trust
	}
	if rotation.SuccessorPin != "" && rotation.SuccessorPin != cfg.TLSPin {
		trust.Pins = append(trust.Pins, rotation.SuccessorPin)
	}
	return trust
}

// PromoteTrust records the outcome of one completed TLS handshake against a
// trust policy ResolveTrust produced, and reports which policy matched.
//
// matchedIndex is the candidate index tlsdial.Trust.Matches returned. Index 0
// is the effective policy ("current"); anything above it is the advertised
// successor. A successor match means the server is now serving the new
// certificate, so the rotation has completed from this agent's point of view
// and the file is cleared — leaving cfg.TLSPin plus whatever the operator's
// next install writes as the resolved policy from then on.
//
// A current match deliberately keeps the rotation: the cutover has not
// happened yet, and dropping the successor here would mean the agent has to
// be re-advertised before it can survive the actual change.
//
// A successful cross-mode retry passes successorRetryIndex and lands in the
// same successor branch: there is no pin candidate to point at, but the
// server is demonstrably serving the advertised policy, which is exactly
// what promotion means.
//
// The returned kind travels to the server on the next hello as
// `tls_pin_kind`, which is what feeds the operator's convergence view and
// the activation gate (agent_registry.record_tls_pin).
func PromoteTrust(cfg *config.Config, stateDir string, matchedIndex int) (string, error) {
	if matchedIndex <= 0 {
		return "current", nil
	}
	if stateDir == "" {
		return "successor", nil
	}
	if err := config.ClearTLSPinRotation(stateDir); err != nil {
		return "successor", err
	}
	log.Printf("link: promoted the successor TLS trust policy — the server is now serving it")
	return "successor", nil
}

// successorRetryIndex is the candidate index PromoteTrust is given after a
// successful cross-mode retry. Any index above zero means "not the current
// policy", and a cross-mode successor has no pin candidate in the current
// policy's list to point at, so this is a named constant rather than a magic 1.
const successorRetryIndex = 1

// successorRetryTrust returns the trust policy one cross-mode retry should
// use, and whether such a retry is warranted at all.
//
// The mechanism is symmetric because the hazard is. Both cutover directions
// strand the whole fleet, and for mirror-image reasons:
//
//   - self_signed -> public: the agent holds a pin that can never match a
//     publicly-trusted leaf.
//   - public -> self_signed: the agent holds no pin and does standard
//     verification, which a self-signed leaf can never pass.
//
// In each case the *current* policy provably cannot verify the *successor*
// certificate, so no amount of retrying the current policy helps and the agent
// can never report convergence — which leaves the activation gate shut
// forever. One retry under the announced successor policy is what closes it.
//
// Warranted only when the server advertised the cross-mode successor over the
// already-authenticated Noise link and the agent persisted it. That
// precondition is what keeps this from being a trust-on-first-use fallback: an
// attacker who can merely make dials fail gets nothing, because they cannot
// make the agent believe a cutover was announced.
func successorRetryTrust(trust tlsdial.Trust, rotation *config.TLSPinRotation) (tlsdial.Trust, bool) {
	if rotation == nil {
		return tlsdial.Trust{}, false
	}
	switch {
	case trust.Mode == tlsdial.ModeSelfSigned && rotation.Mode == tlsdial.ModePublic:
		return tlsdial.Trust{Mode: tlsdial.ModePublic}, true
	case trust.Mode == tlsdial.ModePublic && rotation.Mode == tlsdial.ModeSelfSigned &&
		rotation.SuccessorPin != "":
		return tlsdial.Trust{
			Mode: tlsdial.ModeSelfSigned,
			Pins: []string{rotation.SuccessorPin},
		}, true
	}
	return tlsdial.Trust{}, false
}
