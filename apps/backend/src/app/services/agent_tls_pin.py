"""Slice 4.1: the TLS trust rotation state machine (route finding F4).

An agent's `tls_pin` is loaded once from agent.toml and never rewritten, and
it gates all four of the agent's dial paths — enrollment, the /link socket,
its re-dial, and the update binary download. Changing the certificate an
install serves therefore strands every enrolled agent, and because the update
download is stranded with the rest, a stranded agent cannot be repaired by
pushing it a new binary.

This module advertises the *successor* trust policy over the already-
authenticated Noise link ahead of the certificate actually changing, so every
agent that is reachable during the overlap accepts either leaf across the
cutover. It deliberately mirrors `app.core.agent_crypto`'s server-key
rotation: one rotation in flight, a conditional UPDATE rather than a
check-then-write, and a status surface that never returns key material.

The rotated unit is a policy `(mode, pin)`, not a digest.
`agent_install.tls_policy_for_certificate` returns an empty pin for a
letsencrypt certificate and an SPKI digest otherwise, and the agent's tlsdial
branches on which kind of verification applies — so a server moving between the two modes
in either direction breaks every agent that only ever learned a digest. A
pin-only advertisement cannot say "stop pinning".
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import update as sa_update
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.db.models import AppSettings, Certificate

_logger = logging.getLogger(__name__)

# Matches SERVER_KEY_OVERLAP_SECONDS. An operator watching convergence needs
# the same amount of time to chase stragglers for either rotation, and two
# different windows would be one more thing to remember under pressure.
TLS_PIN_OVERLAP_SECONDS = 7 * 24 * 3600


@dataclass
class TLSPinRotationState:
    """The successor TLS trust policy and its overlap timing, as of one
    `load_tls_pin_rotation_state` call. Every field is None when no rotation
    is in progress."""

    successor_mode: str | None
    successor_pin: str | None
    started_at: datetime | None
    overlap_expires_at: datetime | None

    @property
    def rotation_active(self) -> bool:
        """True while a successor policy is advertised.

        Keyed on the *mode*, not the pin: a public-mode successor carries an
        empty pin by definition, and treating that as "no rotation" would
        make a Let's Encrypt cutover — one of the two cases this whole
        mechanism exists for — silently unadvertisable.
        """
        return self.successor_mode is not None


def load_tls_pin_rotation_state(db: Session) -> TLSPinRotationState:
    """Read the current rotation state fresh from `db`.

    Not cached, for the same reason `load_server_key_rotation_state` is not:
    a rotation can start or lapse underneath a running process.

    Takes no `now`, unlike its server-key counterpart, because it settles
    nothing: an elapsed overlap is *not* settled lazily here. Promotion of
    a TLS policy is a certificate activation an operator performs
    (api/certificates.py), not something a background read may do on their
    behalf — silently expiring the advertisement would drop the successor
    from agents that had not yet converged, which is exactly the stranding
    this slice exists to prevent. `overlap_expires_at` is surfaced to the
    operator instead.
    """
    from app.services.settings_service import get_or_create_settings

    row = get_or_create_settings(db)
    return TLSPinRotationState(
        successor_mode=row.agent_tls_pin_successor_mode,
        successor_pin=row.agent_tls_pin_successor,
        started_at=row.agent_tls_pin_rotation_started_at,
        overlap_expires_at=row.agent_tls_pin_rotation_overlap_expires_at,
    )


def start_tls_pin_rotation(
    db: Session,
    cert: Certificate,
    *,
    overlap_seconds: int | None = None,
    now: datetime | None = None,
) -> TLSPinRotationState | None:
    """Advertise `cert`'s trust policy as the successor, with an overlap
    window of `overlap_seconds` (default `TLS_PIN_OVERLAP_SECONDS`).

    Returns `None` — rejecting, doing nothing — when a rotation is already
    active; `api/agents.py` turns that into a 409. One rotation in flight,
    matching `start_server_key_rotation`.

    Serializes two concurrent callers the same way that function does: the
    write is a conditional `UPDATE ... WHERE agent_tls_pin_successor_mode IS
    NULL`, whose WHERE clause Postgres re-evaluates against the just-committed
    row for whichever caller waited on the other's row lock. A caller whose
    UPDATE affects zero rows lost the race and returns `None`, exactly as if
    it had seen an active rotation to begin with. A plain check-then-write
    would let both callers "win" and the second silently overwrite the first.
    """
    from app.services.agent_install import tls_policy_for_certificate

    reference = now if now is not None else utcnow()
    if load_tls_pin_rotation_state(db).rotation_active:
        return None

    mode, pin = tls_policy_for_certificate(cert)
    window = overlap_seconds if overlap_seconds is not None else TLS_PIN_OVERLAP_SECONDS
    expiry = reference + timedelta(seconds=window)

    result = db.execute(
        sa_update(AppSettings)
        .where(
            AppSettings.id == 1,
            AppSettings.agent_tls_pin_successor_mode.is_(None),
        )
        .values(
            agent_tls_pin_successor_mode=mode,
            agent_tls_pin_successor=pin,
            agent_tls_pin_rotation_started_at=reference,
            agent_tls_pin_rotation_overlap_expires_at=expiry,
        )
    )
    if result.rowcount == 0:  # type: ignore[attr-defined]
        # Lost the race. Roll back so this session does not carry a stale
        # view of the row into whatever its caller does next.
        db.rollback()
        return None
    db.commit()
    return load_tls_pin_rotation_state(db)


def complete_tls_pin_rotation(db: Session) -> None:
    """Clear the advertised successor once the certificate it describes is
    the one being served. Called by the activation route after a successful
    activation, so the fleet's next handshakes resolve to the new policy as
    their only policy.

    All four columns are cleared together — a half-cleared rotation would
    read as active with no successor to advertise.
    """
    db.execute(
        sa_update(AppSettings)
        .where(AppSettings.id == 1)
        .values(
            agent_tls_pin_successor_mode=None,
            agent_tls_pin_successor=None,
            agent_tls_pin_rotation_started_at=None,
            agent_tls_pin_rotation_overlap_expires_at=None,
        )
    )
    db.commit()


def convergence_counts(db: Session, state: TLSPinRotationState) -> tuple[int, int]:
    """(converged, unconverged) across `active` agents for the running rotation.

    An agent counts as converged only when it reported matching the successor
    policy *after* the rotation started — an older timestamp describes some
    previous rotation, not this one.

    Returns (0, 0) when no rotation is running. There is nothing to converge
    on then, and counting the whole fleet as unconverged would make the
    activation gate refuse every activation on an install that never rotates.
    """
    from app.services import agent_registry

    if not state.rotation_active or state.started_at is None:
        return 0, 0
    converged = 0
    unconverged = 0
    for agent in agent_registry.list_agents(db, status="active"):
        pinned = agent.tls_pin_successor_pinned_at
        if pinned is not None and pinned >= state.started_at:
            converged += 1
        else:
            unconverged += 1
    return converged, unconverged


def activation_block_reason(db: Session, cert: Certificate) -> str | None:
    """Why activating `cert` would strand agents, or None when it is safe.

    The convergence counts alone are not a sufficient gate. They are only
    meaningful *while a rotation is running*, so an operator who activates a
    new certificate without starting one at all — the likeliest way to hit
    F4, since it needs no knowledge of this mechanism to do — would sail
    through a gate keyed on them and brick the fleet. The rotation is also
    per-policy: rotating to certificate A and then activating certificate B
    passes a count-only check while stranding everyone.

    So the question asked here is the one that actually matters: *is this
    activation a trust change, and has the fleet been prepared for this
    specific one?*

    Safe, in order:

    - no active agents — there is nobody to strand;
    - the certificate's trust policy already matches what is being served —
      a Let's Encrypt renewal, or re-activating the current certificate,
      changes nothing an agent verifies;
    - the server serves nothing yet, so no agent can have pinned it;
    - a rotation advertising *this* policy has converged across the fleet.
    """
    from app.services import agent_install, agent_registry

    if not agent_registry.list_agents(db, status="active"):
        return None

    target = agent_install.tls_policy_for_certificate(cert)

    served = agent_install.served_trust_policy(db)
    if served is None:
        # Nothing on disk for nginx to present, so nothing an agent could
        # have pinned. Refusing here would block the first activation on an
        # install that has never served a certificate.
        return None
    if target == served:
        return None
    if target[0] == "public" and served[0] == "public":
        # Public trust pins nothing, so one publicly-trusted leaf replacing
        # another changes nothing an agent verifies. The pins differ on every
        # Let's Encrypt renewal — comparing them here refused the one case
        # this function's docstring names as always safe.
        return None

    state = load_tls_pin_rotation_state(db)
    advertised = (state.successor_mode, state.successor_pin or "")
    if not state.rotation_active or advertised != target:
        return (
            "Activating this certificate changes the TLS trust policy agents "
            "verify against, and no rotation has advertised this policy to the "
            "fleet. Every agent would be unable to reconnect — including over "
            "the update channel that would otherwise deliver a fix. Start a "
            "rotation first: POST /api/v1/agents/tls-pin/rotate with this "
            "certificate's id (see docs/tls-trust-rotation.md), or re-send "
            "with force=true to activate anyway."
        )

    _, unconverged = convergence_counts(db, state)
    if unconverged:
        return (
            f"{unconverged} active agent(s) have not confirmed the successor TLS "
            "policy and would be stranded by this activation. Check "
            "GET /api/v1/agents/tls-pin/pending, or re-send with force=true to "
            "activate anyway."
        )

    # Pending agents cannot converge and are deliberately outside the counts
    # above: `/link` closes a non-active agent before the rotation resend, so
    # they can never report readiness and folding them into the gate would
    # deadlock every rotation. They are not therefore *safe* — each one holds
    # the current pin from its install command and will be unable to reconnect
    # after the cutover, including to complete approval. Silence here is how
    # that becomes a support ticket, so it is logged rather than swallowed.
    pending = len(agent_registry.list_agents(db, status="pending"))
    if pending:
        _logger.warning(
            "[agent_tls_pin] activating a trust change with %d pending agent(s): "
            "they hold the current pin, cannot receive the successor, and will "
            "need re-enrolling with a fresh install command after the cutover",
            pending,
        )
    return None
