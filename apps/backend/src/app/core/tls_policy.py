"""The TLS trust policy an agent verifies, and how it is identified.

Lives in `core` rather than beside the rotation state machine in
`services/agent_tls_pin.py` for two reasons. It is pure — no database, no
settings — so a Tier 0 gate can import it and check the real implementation
rather than a copy of the algorithm, which is what a static test of a digest
is otherwise reduced to. And `core` is the inner layer, so the service may
depend on this while nothing here depends on the service.
"""

from __future__ import annotations

import hashlib

#: Length of a policy fingerprint, in hex characters. Long enough that two
#: distinct policies will not collide in any fleet; short enough to travel on
#: every heartbeat without being noticed.
POLICY_FINGERPRINT_CHARS = 32


def policy_fingerprint(mode: str | None, pin: str | None) -> str:
    """A stable digest of a `(mode, pin)` TLS trust policy.

    Over the *policy*, not the pin, because the rotated unit is a policy: a
    public-mode successor carries an empty pin, so a pin-only digest cannot
    tell "stop pinning" apart from "no successor at all" — the same reasoning
    that made `TLSPinRotationState.rotation_active` key on the mode.

    The NUL separator is load-bearing. Without it `("self", "_signedX")` and
    `("self_signed", "X")` produce identical bytes, and a digest that conflates
    two distinct fields lets one policy pass as another.

    The agent computes this identically in
    `apps/agent/internal/link/trust.go:PolicyFingerprint`. Two languages
    agreeing on a digest is exactly the kind of contract that drifts in
    silence — each suite would check its own arithmetic against itself and
    agree with whatever it had become — so both are pinned against the shared
    vectors in `apps/agent/internal/link/testdata/fingerprint_vectors.json`.
    """
    material = f"{mode or ''}\x00{pin or ''}".encode()
    return hashlib.sha256(material).hexdigest()[:POLICY_FINGERPRINT_CHARS]
