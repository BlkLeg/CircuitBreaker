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
`agent_install._tls_mode_and_pin` returns an empty pin for a letsencrypt
certificate and an SPKI digest otherwise, and the agent's tlsdial branches on
which kind of verification applies — so a server moving between the two modes
in either direction breaks every agent that only ever learned a digest. A
pin-only advertisement cannot say "stop pinning".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import update as sa_update
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.db.models import AppSettings, Certificate

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
    from app.services.agent_install import _tls_mode_and_pin

    reference = now if now is not None else utcnow()
    if load_tls_pin_rotation_state(db).rotation_active:
        return None

    mode, pin = _tls_mode_and_pin(cert)
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
