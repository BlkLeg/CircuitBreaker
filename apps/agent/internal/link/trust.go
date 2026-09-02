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
