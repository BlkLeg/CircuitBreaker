package link

import (
	"log"
	"slices"

	"circuitbreaker.dev/cb-agent/internal/config"
	"circuitbreaker.dev/cb-agent/internal/tlsdial"
)

// ResolveTrust returns the TLS trust policy every dial in this agent should
// honor: the effective policy — a previously promoted successor
// (config.TLSTrustPolicy) if one exists, otherwise agent.toml's tls_pin —
// plus any successor a `tls.pin.rotate` frame advertised and internal/config
// durably persisted.
//
// This is the single resolver. All four dial sites — enrollment
// (internal/enroll), the /link websocket and its re-dial (internal/link), and
// the update download (internal/update) — go through it, so no path can be
// left behind on a trust change. That mattered enough to gate: the update
// download is how a broken agent would otherwise be repaired, so a stranded
// download path makes every other stranding unrecoverable.
// tests/build/test_phase4_supply_chain_ratchets.py enforces it.
//
// stateDir == "" skips both persisted lookups entirely and returns just the
// configured policy, unchanged from this function's absence — matching
// serverKeyCandidates' handling of the same case.
func ResolveTrust(cfg *config.Config, stateDir string) tlsdial.Trust {
	trust := tlsdial.Trust{Mode: tlsdial.ModeSelfSigned, Pins: []string{cfg.TLSPin}}
	if cfg.TLSPin == "" {
		trust = tlsdial.Trust{Mode: tlsdial.ModePublic}
	}
	if stateDir == "" {
		return trust
	}
	// A previously promoted policy replaces agent.toml's, which names the
	// certificate that rotation retired. See config.TLSTrustPolicy.
	if promoted, err := config.LoadEffectiveTLSTrust(stateDir); err != nil {
		log.Printf("link: reading promoted tls trust policy: %v", err)
	} else if promoted != nil {
		if promoted.Mode == tlsdial.ModePublic {
			trust = tlsdial.Trust{Mode: tlsdial.ModePublic}
		} else if promoted.Pin != "" {
			trust = tlsdial.Trust{Mode: tlsdial.ModeSelfSigned, Pins: []string{promoted.Pin}}
		}
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
	// Compared against the *effective* pin rather than cfg.TLSPin: after one
	// promotion those differ, and comparing against the retired pin would
	// re-append a successor the agent is already serving under.
	if rotation.SuccessorPin != "" && !slices.Contains(trust.Pins, rotation.SuccessorPin) {
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
// certificate, so the rotation has completed from this agent's point of view:
// the successor is recorded as the effective policy and the rotation file is
// cleared.
//
// Recording it is not optional. agent.toml is root-owned and never rewritten,
// so its tls_pin still names the certificate the rotation retired; an agent
// that only cleared the rotation would fall back to that retired pin and
// strand on its very next reconnect, one connection past the cutover.
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
	rotation, err := config.LoadTLSPinRotation(stateDir)
	if err != nil {
		return "successor", err
	}
	if rotation == nil {
		// Nothing was advertised, so there is no policy to promote. The
		// caller still matched above index 0, which cannot happen without a
		// successor candidate — treat it as already promoted rather than
		// writing a policy this agent was never told about.
		return "successor", nil
	}
	// Recorded BEFORE the clear, and this order is the whole fix: the
	// rotation file is the only record of what was promoted, so clearing it
	// first and failing here would leave the agent resolving agent.toml's
	// retired pin against the certificate now being served.
	if err := config.SaveEffectiveTLSTrust(stateDir, config.TLSTrustPolicy{
		Mode: rotation.Mode,
		Pin:  rotation.SuccessorPin,
	}); err != nil {
		return "successor", err
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
