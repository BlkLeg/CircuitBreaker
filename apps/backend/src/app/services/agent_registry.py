"""Agent CRUD, presence, capability grants, and host linkage.

This module owns all mutation of `agents` / `agent_capability_grants` /
`agent_events`. No collector domain logic lives here — see
specs/2026-07-26-cb-agent-design.md §1.2 on agent_link.py's boundary, which
this module sits directly behind.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import uuid
from collections.abc import AsyncIterator, Awaitable, Mapping
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import Any, cast

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core import agent_crypto
from app.core.time import utcnow
from app.db.models import Agent, AgentCapabilityGrant, AgentEvent, AgentNetwork, Hardware
from app.schemas.agent_frame import TYPE_KEY_ROTATE, HelloPayload, NetworkFacts
from app.services.agent_capabilities import (
    CAPABILITY_DEFINITIONS,
    default_config_for,
    normalize_grant,
)

_logger = logging.getLogger(__name__)

# Derived, read-only views of the one capability registry
# (`app.services.agent_capabilities`, Task 14 / D-14) — kept only so existing
# importers keep working. They are snapshots taken at import time: anything
# that must honor a monkeypatched or future registry reads
# `CAPABILITY_DEFINITIONS` / `normalize_grant` / `default_config_for` directly,
# as `approve_agent`, `set_capability_grants` and `structured_grants_dict`
# below all do. Do not mutate them and do not add a fourth copy of either.
DEFAULT_CAPABILITY_GRANTS: Mapping[str, bool] = MappingProxyType(
    {name: definition.default_enabled for name, definition in CAPABILITY_DEFINITIONS.items()}
)
HOST_TELEMETRY_DEFAULT_CONFIG: Mapping[str, Any] = MappingProxyType(
    dict(CAPABILITY_DEFINITIONS["host_telemetry"].default_config)
)


# Task 21: cap on agents simultaneously awaiting approval. An anonymous
# /enroll flood using a fresh device keypair per connection creates a new
# `Agent` row every time (device_pk is unique, so there's no per-device
# reuse to fall back on), so without a ceiling nothing bounds how many
# pending rows — and their live-held /enroll poll connections — accumulate.
MAX_CONCURRENT_PENDING_AGENTS = 100

# Task 27: default device-key rotation transition window (Global Constraints:
# "Device-key transition window defaults to 15 minutes"). Tests monkeypatch
# this module attribute the same way tests monkeypatch
# agent_crypto.REKEY_INTERVAL_SECONDS.
DEVICE_KEY_ROTATION_WINDOW_SECONDS = 15 * 60

# Task 27 fix round 1: a device public key is a 32-byte X25519 key, i.e.
# exactly 64 lowercase hex characters. Mirrors
# app.schemas.agent_frame.KeyRotatePayload's own validator — duplicated
# rather than imported so this module's collision/format guard doesn't
# raise on bad hex even if a future or direct caller reaches
# `start_device_key_rotation` without going through that schema layer.
_HEX_PK_RE = re.compile(r"^[0-9a-f]{64}$")


def create_pending_agent(db: Session, **fields: Any) -> Agent:
    agent = Agent(status="pending", **fields)
    db.add(agent)
    db.flush()
    record_event(db, agent.id, "enrolled")
    return agent


def count_pending_agents(db: Session) -> int:
    """Number of agents currently in `pending` status, i.e. awaiting
    approval. Backs the concurrent-pending-enrollment cap in
    ws_agents.enroll_stream."""
    return db.execute(
        select(func.count()).select_from(Agent).where(Agent.status == "pending")
    ).scalar_one()


_PENDING_ENROLLMENT_LOCK_KEY = "agent_enroll_pending_cap_lock"
_PENDING_ENROLLMENT_LOCK_TTL_SECONDS = 5
_PENDING_ENROLLMENT_LOCK_RETRY_ATTEMPTS = 10
_PENDING_ENROLLMENT_LOCK_RETRY_DELAY_SECONDS = 0.05


async def acquire_pending_enrollment_lock() -> str | None:
    """Short-lived, cross-worker Redis lock serializing the
    count_pending_agents-then-create_pending_agent-then-commit sequence in
    ws_agents.enroll_stream's concurrent-pending-enrollment cap.

    Without this, two /enroll connections landing on different worker
    processes (each opening its own `SessionLocal()`) can race: both read
    `count_pending_agents` under Postgres's default READ COMMITTED
    isolation before either commits its INSERT, both see a count under
    `MAX_CONCURRENT_PENDING_AGENTS`, and both insert — overshooting the cap.
    That's a genuine cross-transaction TOCTOU, not something a single
    session's isolation level protects against on its own.

    Deliberately NOT a live Redis gauge (INCR on create, DECR on
    approve/reject/revoke/expire-stale): that would need release hooks
    threaded into every one of those code paths — scattered across
    agents.py's approval/rejection endpoints and the expiry worker — to
    avoid silently drifting from the DB's actual pending count over time.
    This lock only ever wraps the brief "count, then insert, then commit"
    sequence; the DB row count stays the sole source of truth, and Redis is
    purely a mutual-exclusion primitive around reading it consistently —
    same "reuse a proven primitive, don't invent a new counter mechanism"
    reasoning as `check_and_record_ws_attempt` reusing the pairing-miss
    lockout's counter pattern.

    Retries briefly with a short delay: contention here should be rare
    (needs near-simultaneous new-device enrollments) and short-lived (the
    critical section is a handful of DB statements, not the whole Noise
    handshake). Returns the lock's random token — needed so only the
    holder that actually acquired it can release it, via
    `release_pending_enrollment_lock` — or `None` if it couldn't be
    acquired within the retry budget, or if Redis is unreachable. Callers
    must treat `None` the same as "at capacity" and refuse the enrollment
    (fail closed, matching `check_and_record_ws_attempt`'s stance) rather
    than proceeding without the guard.
    """
    from app.core.redis import get_redis

    r = await get_redis()
    if r is None:
        return None

    token = uuid.uuid4().hex
    for _ in range(_PENDING_ENROLLMENT_LOCK_RETRY_ATTEMPTS):
        acquired = await r.set(
            _PENDING_ENROLLMENT_LOCK_KEY,
            token,
            nx=True,
            ex=_PENDING_ENROLLMENT_LOCK_TTL_SECONDS,
        )
        if acquired:
            return token
        await asyncio.sleep(_PENDING_ENROLLMENT_LOCK_RETRY_DELAY_SECONDS)
    return None


async def release_pending_enrollment_lock(token: str) -> None:
    """Release the lock from `acquire_pending_enrollment_lock`, but only if
    it's still this caller's — same atomic compare-and-delete Lua script as
    `deregister_agent_connection`'s `_COMPARE_AND_DELETE_LUA` below, guarding
    against releasing a different holder's lock in the (TTL-bounded, rare)
    case ours already expired and someone else acquired it in the meantime.
    """
    from app.core.redis import get_redis

    r = await get_redis()
    if r is None:
        return
    script = r.register_script(_COMPARE_AND_DELETE_LUA)
    await script(keys=[_PENDING_ENROLLMENT_LOCK_KEY], args=[token])


def get_agent(db: Session, agent_id: int) -> Agent | None:
    return db.get(Agent, agent_id)


def get_agent_by_device_pk(db: Session, device_pk: str) -> Agent | None:
    return db.execute(select(Agent).where(Agent.device_pk == device_pk)).scalar_one_or_none()


def resolve_agent_for_handshake(db: Session, device_pk_hex: str) -> Agent | None:
    """Look up the Agent whose identity a completed `/link` Noise handshake's
    initiator static key (`NoiseIKResponder.remote_static().hex()`) currently
    authenticates.

    This is `get_agent_by_device_pk`, extended (Task 27) to also match an
    in-progress device-key rotation's not-yet-expired `pending_device_pk` —
    see `agent_crypto.device_identity_matches` for why that check belongs to
    the crypto module rather than duplicating its time-window logic here.
    ws_agents.py's `link_stream` uses this instead of `get_agent_by_device_pk`
    directly; `enroll_stream` keeps using the exact-match function as-is,
    since enrollment has no rotation concept — a device mid-rotation
    reconnects over `/link`, it doesn't re-enroll.
    """
    agent = get_agent_by_device_pk(db, device_pk_hex)
    if agent is not None:
        return agent

    # `.first()`, not `.scalar_one_or_none()`: `pending_device_pk` is a
    # non-unique indexed column (unlike `device_pk`), so this must never be
    # able to raise `MultipleResultsFound` on a duplicate — even though
    # `start_device_key_rotation`'s collision check is what actually
    # prevents that duplicate from being written in the first place, this
    # read path is a defensive backstop against one somehow slipping through
    # (Task 27 fix round 1).
    candidate = (
        db.execute(select(Agent).where(Agent.pending_device_pk == device_pk_hex)).scalars().first()
    )
    if candidate is None:
        return None
    if agent_crypto.device_identity_matches(
        device_pk_hex,
        current_pk=candidate.device_pk,
        pending_pk=candidate.pending_device_pk,
        pending_expiry=candidate.pending_device_pk_expiry,
    ):
        return candidate
    return None


def update_hello_metadata(db: Session, agent: Agent, payload: HelloPayload) -> None:
    """Refresh the `Agent` row's device-reported fields from an accepted `hello`.

    Enrollment (`ws_agents.enroll_stream`) only ever sets os/os_version/arch/
    agent_version/primary_macs once, at enrollment time. This is the
    counterpart called on every accepted `/link` hello afterwards, so the row
    tracks reality as a device is upgraded or its network config changes (see
    specs/2026-07-26-cb-agent-design.md §4.6: "the agent reports its version
    in `hello`; the UI shows which agents are behind").

    Only overwrites a field when the hello payload actually *included* it —
    gated on presence (`payload.model_fields_set`), not truthiness. An
    old-shaped or partial hello payload (every `HelloPayload` field is
    optional) omits fields it doesn't know about, and those must never blank
    out data recorded at enrollment or on a prior hello. Conversely, a hello
    that explicitly sends a falsy value — e.g. `"primary_macs": []` because
    the device now has zero up network interfaces — must persist that value;
    checking truthiness instead of presence would make that update
    unrepresentable, since an omitted key and an explicit `[]` both parse to
    the same default. Caller is responsible for the commit/flush.

    Task 24: this is also the *only* place `version_changed` is ever
    recorded — deliberately not at update-request time (see
    `api/agents.py:post_update`, which records `update_queued` instead). A
    hello reporting `agent_version` that exactly matches
    `agent.pending_update_version` (the target version a queued update set,
    see that column's docstring) means the new binary has actually reconnected
    and identified itself; only then is the fleet-visible version change real,
    so `pending_update_version` is cleared right after recording it. A hello
    reporting some *other* version while an update is still pending (e.g. the
    agent hasn't updated yet, or updated to something unexpected) leaves
    `pending_update_version` untouched — it isn't this update's resolution.
    """
    fields_set = payload.model_fields_set
    if "os" in fields_set:
        agent.os = payload.os
    if "os_version" in fields_set:
        agent.os_version = payload.os_version
    if "arch" in fields_set:
        agent.arch = payload.arch
    if "agent_version" in fields_set:
        agent.agent_version = payload.agent_version
        if (
            agent.pending_update_version is not None
            and payload.agent_version == agent.pending_update_version
        ):
            record_event(db, agent.id, "version_changed", detail={"version": payload.agent_version})
            agent.pending_update_version = None
    if "primary_macs" in fields_set:
        agent.primary_macs = payload.primary_macs
    if "networks" in fields_set:
        record_network_facts(db, agent, payload.networks)
    if "spool_depth" in fields_set:
        # The at-connect backlog snapshot (D-12). `hello` has no
        # `spool_bytes` field, so the size is genuinely unknown here — None,
        # not 0 — and the heartbeat that follows within 20s fills it in.
        record_spool_stats(agent, payload.spool_depth, None)


def record_spool_stats(agent: Agent, depth: int, size_bytes: int | None = None) -> bool:
    """Record the agent's reported outbound-spool backlog, returning whether
    anything actually changed.

    `depth` is the number of frames still buffered; `size_bytes` is their
    on-disk size, or None when the reporting frame doesn't carry one (`hello`
    reports depth only — see `update_hello_metadata`), in which case the
    stored byte count is left untouched rather than blanked.

    The no-op return is load-bearing, not an optimization detail. Heartbeats
    arrive every 20 seconds per connected agent and the steady state is
    "depth 0, unchanged", so writing unconditionally would issue one row
    UPDATE per agent per 20s forever — a fleet-wide write storm carrying no
    new information. `spool_reported_at` is therefore "when the reported
    backlog last *changed*", not "when an agent last mentioned its spool";
    liveness already has `last_seen_at` and Redis presence.

    Callers gate this on `"spool_depth" in payload.model_fields_set`, never
    on the value: an agent that predates spool reporting sends an empty
    heartbeat payload and must leave all three columns NULL ("never
    reported"), while a current agent with a drained spool sends an explicit
    0 that must be persisted ("reported, empty") — that write is what clears
    the Agent Detail catch-up indicator. Caller owns the commit.
    """
    changed = agent.spool_depth != depth
    if size_bytes is not None and agent.spool_bytes != size_bytes:
        changed = True
    if not changed:
        return False
    agent.spool_depth = depth
    if size_bytes is not None:
        agent.spool_bytes = size_bytes
    agent.spool_reported_at = utcnow()
    return True


def _normalized_network_facts(networks: list[NetworkFacts]) -> list[dict[str, Any]]:
    """Canonical form of a reported `hello.networks` list.

    Every list is sorted — interfaces by name, and each interface's flags and
    addresses among themselves — so that "did the agent's networks change?" is
    a plain equality test against what is already stored. The agent sorts too
    (`internal/hostinfo/netfacts.go`), but that ordering is one agent build's
    behavior, not a wire contract; the generation counter is a scope version
    Slice 4 cancels in-flight work on, and it must not tick because an older
    or differently-ordered build enumerated the same interfaces in another
    sequence.
    """
    return sorted(
        ({"name": n.name, "flags": sorted(n.flags), "addrs": sorted(n.addrs)} for n in networks),
        key=lambda entry: cast(str, entry["name"]),
    )


def record_network_facts(db: Session, agent: Agent, networks: list[NetworkFacts]) -> bool:
    """Store the agent's directly connected networks, returning whether the
    report actually changed (D-1).

    `agent_networks` holds one current row per agent, and `generation`
    advances only on a real change: it is the scope version the scheduler, the
    UI and the audit trail all cite, so a counter that moved on every
    reconnect would say "this agent's scope changed" about nothing.
    `observed_at` follows the same rule and is therefore when *these* facts
    were first seen, not when the agent last mentioned them — liveness is
    already `agents.last_seen_at`, mirroring `record_spool_stats`.

    The caller gates this on presence in `payload.model_fields_set`, never on
    truthiness, which is the idiom `update_hello_metadata` applies to every
    other field: a build predating network reporting omits the key entirely
    and must leave the last known report standing, while an explicit `[]` is
    a real report of "nothing directly connected" and must replace it — an
    agent that has lost every usable interface must not keep a stale,
    wider-than-reality scope.

    The Go encodings differ by frame, deliberately (Slice 4 D-8). On
    `capability.readiness` — the mid-session refresh path, which is
    `agent_telemetry.ingest_readiness` — `Networks` is tagged `json:"networks"`
    with **no** `omitempty` (`internal/frame/frame.go:236`), so an agent that
    has lost every interface really can send `[]` and really does move the
    generation. `HelloPayload.Networks` still carries `omitempty`
    (`frame.go:205`), so the at-connect frame cannot express that `[]` and a
    hello from an agent with no interfaces is indistinguishable from one that
    predates the field. Either way the rule above belongs to the backend, not
    to one client's encoding. Caller owns the commit.
    """
    facts = _normalized_network_facts(networks)
    row = (
        db.execute(select(AgentNetwork).where(AgentNetwork.agent_id == agent.id)).scalars().first()
    )
    if row is None:
        # One agent can hold two live /link connections at once — cb-agent's
        # uninstall notifier deliberately opens a second one alongside the
        # daemon's (see `register_agent_connection`'s call site) — so two
        # first-ever hellos can race between the select above and the caller's
        # commit. ON CONFLICT makes the loser a no-op instead of an
        # IntegrityError that would tear down an otherwise healthy link; its
        # facts, if they somehow differ, land on its next hello. The suppressed
        # insert reports no change, because the racing winner is the call that
        # created generation 1 and already reported it.
        return (
            db.execute(
                pg_insert(AgentNetwork)
                .values(agent_id=agent.id, generation=1, observed_at=utcnow(), facts=facts)
                .on_conflict_do_nothing(index_elements=["agent_id"])
                .returning(AgentNetwork.id)
            ).scalar_one_or_none()
            is not None
        )
    if row.facts == facts:
        return False
    row.generation += 1
    row.observed_at = utcnow()
    row.facts = facts
    return True


def list_agents(db: Session, *, status: str | None = None) -> list[Agent]:
    stmt = select(Agent)
    if status is not None:
        stmt = stmt.where(Agent.status == status)
    return list(db.execute(stmt.order_by(Agent.created_at.desc())).scalars().all())


def approve_agent(
    db: Session,
    agent_id: int,
    *,
    approving_user_id: int,
    hardware_id: int | None = None,
    host_link_action: str | None = None,
    capability_overrides: dict[str, Any] | None = None,
) -> Agent:
    agent = db.get(Agent, agent_id)
    if agent is None:
        raise ValueError(f"agent {agent_id} not found")

    agent.status = "active"
    agent.approved_at = utcnow()
    agent.approved_by_user_id = approving_user_id
    if hardware_id is not None:
        agent.hardware_id = hardware_id

    # The ONE place `default_enabled` is ever consulted (Global Constraints:
    # "Upgrades never silently enable a new capability on an already-approved
    # agent"). Read live off CAPABILITY_DEFINITIONS, not the derived snapshot
    # above, so the registry stays the single source of truth.
    grants: dict[str, Any] = {
        name: definition.default_enabled for name, definition in CAPABILITY_DEFINITIONS.items()
    }
    grants.update(capability_overrides or {})
    for capability, value in grants.items():
        enabled, config = normalize_grant(capability, value)
        db.add(
            AgentCapabilityGrant(
                agent_id=agent.id,
                capability=capability,
                enabled=enabled,
                config=config,
                granted_by_user_id=approving_user_id,
            )
        )

    # host_link_action (Task 18's AgentApprovalModal: accept/select/create/
    # unlinked) is descriptive of *how* hardware_id was chosen, not required
    # for linkage itself — recorded on the event detail so the audit trail
    # distinguishes "approver accepted the proposed match" from "approver
    # picked a different record" even when both land on the same
    # hardware_id. Omitted entirely (both keys None) for older/untyped
    # callers so existing `approved` event assertions keep matching.
    detail = None
    if hardware_id is not None or host_link_action is not None:
        detail = {"hardware_id": hardware_id, "host_link_action": host_link_action}
    record_event(db, agent.id, "approved", actor_user_id=approving_user_id, detail=detail)
    db.flush()
    return agent


def set_hardware_link(
    db: Session, agent_id: int, hardware_id: int | None, *, actor_user_id: int | None
) -> Agent:
    """Change (or clear) which `Hardware` row an already-approved agent is
    linked to — the post-approval counterpart to `approve_agent`'s
    `hardware_id` param (Task 18 covers linkage *at* approval time; this is
    for correcting/relinking it afterwards, e.g. a mismatched proposal was
    accepted, or the underlying hardware was later retired/replaced).

    Unlike a plain `setattr(agent, "hardware_id", ...)`, this always records
    the change in `agent_events` — an approved agent's host link is part of
    its audit trail, so silently overwriting it would leave no record of
    what changed or when. A no-op call (new value equal to the current one,
    including None -> None) intentionally records nothing; only an actual
    linkage change is event-worthy, mirroring `update_hello_metadata`'s
    change-gated `version_changed` recording.

    Caller (api/agents.py `patch_agent`) is responsible for validating that
    `hardware_id` refers to an existing `Hardware` row before calling this —
    this function trusts its input the same way `approve_agent` already
    does, rather than duplicating that lookup here.
    """
    agent = db.get(Agent, agent_id)
    if agent is None:
        raise ValueError(f"agent {agent_id} not found")

    previous_hardware_id = agent.hardware_id
    if previous_hardware_id == hardware_id:
        return agent

    agent.hardware_id = hardware_id
    record_event(
        db,
        agent.id,
        "host_link_changed",
        actor_user_id=actor_user_id,
        detail={"previous_hardware_id": previous_hardware_id, "hardware_id": hardware_id},
    )
    db.flush()
    return agent


def reject_agent(db: Session, agent_id: int, *, actor_user_id: int) -> Agent:
    agent = db.get(Agent, agent_id)
    if agent is None:
        raise ValueError(f"agent {agent_id} not found")
    agent.status = "rejected"
    record_event(db, agent.id, "rejected", actor_user_id=actor_user_id)
    db.flush()
    return agent


def revoke_agent(
    db: Session, agent_id: int, *, actor_user_id: int | None, reason: str | None = None
) -> Agent:
    agent = db.get(Agent, agent_id)
    if agent is None:
        raise ValueError(f"agent {agent_id} not found")
    agent.status = "revoked"
    agent.revoked_at = utcnow()
    agent.revoked_by_user_id = actor_user_id
    agent.revoke_reason = reason
    record_event(db, agent.id, "revoked", actor_user_id=actor_user_id, detail={"reason": reason})
    db.flush()
    return agent


def start_device_key_rotation(
    db: Session,
    agent: Agent,
    successor_pk: str,
    *,
    window_seconds: int | None = None,
) -> bool:
    """Begin a device-key rotation for `agent`: persists `successor_pk` as its
    `pending_device_pk`, with an expiry `window_seconds` (default
    `DEVICE_KEY_ROTATION_WINDOW_SECONDS`, i.e. 15 minutes per Global
    Constraints) from now, and records `key_rotation_started`.

    Per Global Constraints ("The authenticated old Noise channel authorizes
    device-key rotation"), the only authorization this function requires is
    that its caller reached it from a `key.rotate` (kind="device") frame
    successfully decrypted and dispatched over an already-established `/link`
    session for this exact `agent` row — see `agent_link._handle_key_rotate`.
    This function itself performs no channel/identity check of its own, and
    the server-computed expiry always wins over whatever `expiry` the agent's
    own `KeyRotatePayload` proposed: the transition window is entirely
    server-controlled, not client-negotiable.

    Rejects (records `key_rotation_rejected`, leaves the row untouched, and
    returns `False`) rather than storing a pending key that could never be
    safely promoted:
      - `successor_pk` isn't exactly 64 lowercase hex characters (a 32-byte
        X25519 public key) — defense in depth alongside
        `KeyRotatePayload._successor_pk_must_be_hex_pubkey`'s frame-decode-time
        validator: this function must never raise on a malformed value even
        if some future/direct caller bypasses the schema layer, since
        `hashlib.sha256(bytes.fromhex(successor_pk))` below would otherwise
        raise an unhandled `ValueError` on bad hex.
      - `successor_pk` identical to the agent's current `device_pk` — a
        no-op rotation.
      - `successor_pk` already claimed by a *different* Agent row, either as
        its current `device_pk` or as another agent's in-progress
        `pending_device_pk` — storing it anyway would either collide with
        `device_pk`'s uniqueness constraint the moment
        `settle_device_key_rotation` tried to promote it, or leave two
        agents with the same `pending_device_pk`, which makes
        `resolve_agent_for_handshake`'s lookup on that column ambiguous.

    A second call while a prior pending rotation is still unexpired simply
    supersedes it (new successor key, restarted timer) — Task 27 places no
    "reject a second rotation while one is active" requirement on device-key
    rotation the way Task 28 does for the server's own key.
    """
    if not _HEX_PK_RE.fullmatch(successor_pk):
        record_event(
            db,
            agent.id,
            "key_rotation_rejected",
            detail={"reason": "successor_pk_malformed"},
        )
        return False

    if successor_pk == agent.device_pk:
        record_event(
            db,
            agent.id,
            "key_rotation_rejected",
            detail={"reason": "successor_matches_current"},
        )
        return False

    collision = (
        db.execute(
            select(Agent).where(
                or_(Agent.device_pk == successor_pk, Agent.pending_device_pk == successor_pk),
                Agent.id != agent.id,
            )
        )
        .scalars()
        .first()
    )
    if collision is not None:
        record_event(
            db,
            agent.id,
            "key_rotation_rejected",
            detail={"reason": "successor_key_in_use"},
        )
        return False

    window = window_seconds if window_seconds is not None else DEVICE_KEY_ROTATION_WINDOW_SECONDS
    expiry = utcnow() + timedelta(seconds=window)
    agent.pending_device_pk = successor_pk
    agent.pending_device_pk_expiry = expiry
    record_event(
        db,
        agent.id,
        "key_rotation_started",
        detail={
            "successor_fingerprint": hashlib.sha256(bytes.fromhex(successor_pk)).hexdigest()[:16],
            "expires_at": expiry.isoformat(),
        },
    )
    db.flush()
    return True


def settle_device_key_rotation(
    db: Session, agent: Agent, connected_device_pk: str, *, now: datetime | None = None
) -> None:
    """Settle whichever side of an in-progress device-key rotation one
    accepted `/link` handshake represents. Call once per accepted handshake,
    right after `resolve_agent_for_handshake` has already confirmed
    `connected_device_pk` is a currently-valid identity for `agent` (its
    current key, or its unexpired pending key) — this function trusts that
    check rather than repeating it.

    - Connected on the *pending* key: this is the rotation's first successful
      link under the new identity (Task 27: "promote the pending identity on
      its first successful link"). Promotes it to `device_pk`, clears the
      pending fields, and records `key_rotated`.
    - Connected on the *current* key while a pending rotation has passed its
      expiry: lazily clears the stale pending fields and records
      `key_rotation_expired` — there is no scheduled sweep for this (compare
      `expire_stale_pending_agents`, which does run on a schedule for a
      different column); the agent's own next reconnect on its unchanged
      current key is what notices and clears it.
    - Connected on the current key with no pending rotation, or with one
      that's still inside its window: no-op.

    A residual, deliberately-unhandled race: if some *other* Agent row
    enrolls with the exact bytes of this agent's `pending_device_pk` between
    `start_device_key_rotation`'s collision check and this promotion, the
    `device_pk` UNIQUE constraint raises here. No caller in this codebase
    catches that today (the equivalent enrollment-side race is exactly as
    unhandled), so this doesn't newly introduce a gap.
    """
    reference = now if now is not None else utcnow()
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)

    if agent.pending_device_pk is not None and connected_device_pk == agent.pending_device_pk:
        old_pk = agent.device_pk
        agent.device_pk = agent.pending_device_pk
        agent.pending_device_pk = None
        agent.pending_device_pk_expiry = None
        record_event(
            db,
            agent.id,
            "key_rotated",
            detail={
                "old_fingerprint": hashlib.sha256(bytes.fromhex(old_pk)).hexdigest()[:16],
                "new_fingerprint": hashlib.sha256(bytes.fromhex(connected_device_pk)).hexdigest()[
                    :16
                ],
            },
        )
        db.flush()
        return

    if agent.pending_device_pk is not None and agent.pending_device_pk_expiry is not None:
        expiry = agent.pending_device_pk_expiry
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=UTC)
        if reference > expiry:
            agent.pending_device_pk = None
            agent.pending_device_pk_expiry = None
            record_event(db, agent.id, "key_rotation_expired")
            db.flush()


def record_server_key_pin(
    db: Session, agent: Agent, key_kind: str, *, now: datetime | None = None
) -> None:
    """Record that `agent`'s most recent successful `/link` Noise handshake
    authenticated against the server's "current" or "successor" identity key
    (Task 28) — `key_kind` is whichever of those two strings
    `agent_crypto.complete_ik_handshake` returned for that handshake.

    Purely observational: nothing about handshake acceptance depends on
    these two timestamp columns (`agent_crypto.complete_ik_handshake` already
    decided acceptance before this is ever called). They exist so an
    admin's server-key rotation status view can answer "how much of the
    fleet has already pinned the successor key" — see `Agent.
    server_pk_current_pinned_at`/`server_pk_successor_pinned_at`'s docstring
    — rather than only knowing the rotation's global start/overlap timing.
    An unrecognized `key_kind` (should never happen — the crypto layer only
    ever produces "current"/"successor") is treated the same as "current",
    matching `settle_device_key_rotation`'s bias toward not raising on
    caller-internal invariants it trusts rather than re-validates.
    """
    reference = now if now is not None else utcnow()
    if key_kind == "successor":
        agent.server_pk_successor_pinned_at = reference
    else:
        agent.server_pk_current_pinned_at = reference
    db.flush()


async def broadcast_server_key_rotate(
    db: Session, state: agent_crypto.ServerKeyRotationState
) -> int:
    """Push a `key.rotate` (kind="server") control frame — the successor
    identity key a Task 28 rotation just started — to every currently
    connected `active` agent, over the same Task 8/9 cross-worker
    control-frame delivery path (`publish_agent_control_frame`)
    `agent_link._handle_key_rotate` already uses for its own kind="device"
    ack.

    Proactive, not lazy: called once, right after `api/agents.py`'s admin
    rotate endpoint commits the new rotation, so an agent already holding a
    live `/link` socket learns about the successor key well ahead of the
    (default 7-day) overlap's end — not only whenever it next happens to
    reconnect. A socket that never drops for the whole overlap window would
    otherwise never see this at all. `ws_agents.py`'s `link_stream`
    separately resends the same frame on every accepted hello.ack for as
    long as the rotation stays active (mirroring Task 11's full-capability-
    grant resend) as the durability fallback for whatever this broadcast
    misses — a worker down at push time, a connection that hadn't finished
    establishing yet, or a publish racing a disconnect.

    Caller's responsibility, not this function's: `state.rotation_active`
    must already be true (there is nothing meaningful to advertise
    otherwise) — asserted rather than silently no-op'd, since a caller
    reaching this with an inactive state is a caller bug, not a runtime
    condition to tolerate.

    Returns the number of agents found online (and so pushed to) at the
    moment of the call — informational only, not a delivery guarantee (see
    `publish_agent_control_frame`'s own docstring on that).
    """
    assert state.rotation_active
    assert state.successor_pub is not None
    assert state.overlap_expires_at is not None

    active_agents = list_agents(db, status="active")
    if not active_agents:
        return 0
    agent_ids = [agent.id for agent in active_agents]
    presence = await bulk_presence(agent_ids)

    payload = {
        "kind": "server",
        "successor_pk": state.successor_pub.hex(),
        "expiry": state.overlap_expires_at.isoformat(),
    }
    pushed = 0
    for agent_id in agent_ids:
        # A presence backend may legitimately omit an agent that disappeared
        # between the database query and the bulk lookup. Treat that race as
        # offline instead of aborting broadcasts for the remaining agents.
        if not presence.get(agent_id, {}).get("online", False):
            continue
        await publish_agent_control_frame(agent_id, {"type": TYPE_KEY_ROTATE, "payload": payload})
        pushed += 1
    return pushed


def set_capability_grants(
    db: Session, agent_id: int, grants: dict[str, Any], *, actor_user_id: int
) -> list[AgentCapabilityGrant]:
    existing = {
        g.capability: g
        for g in db.execute(
            select(AgentCapabilityGrant).where(AgentCapabilityGrant.agent_id == agent_id)
        ).scalars()
    }
    result = []
    event_detail: dict[str, Any] = {}
    for capability, value in grants.items():
        grant = existing.get(capability)
        # The existing row's config is the merge base, so a partial update
        # ({"host_telemetry": {"enabled": true, "config": {"interval_s": 60}}})
        # keeps every setting it didn't mention instead of resetting it to the
        # registry default.
        enabled, config = normalize_grant(
            capability, value, current_config=dict(grant.config or {}) if grant else None
        )
        if grant is None:
            grant = AgentCapabilityGrant(agent_id=agent_id, capability=capability)
            db.add(grant)
        grant.enabled = enabled
        grant.config = config
        grant.granted_by_user_id = actor_user_id
        grant.granted_at = utcnow()
        result.append(grant)
        event_detail[capability] = {"enabled": enabled, "config": config}
    record_event(
        db,
        agent_id,
        "capability_changed",
        actor_user_id=actor_user_id,
        detail=event_detail,
    )
    db.flush()
    return result


def grants_dict(db: Session, agent_id: int) -> dict[str, bool]:
    """Capability name -> enabled, for one agent.

    Consolidated here (rather than duplicated as a private helper in
    api/agents.py and services/agent_link.py, as the plan text originally
    had it) per a cross-task consistency ruling: this module is already the
    single place agent state mutates, so it's also the single place that
    reduces AgentCapabilityGrant rows to a lookup dict. Tasks 9 and 12 import
    this function instead of redefining it.
    """
    return {
        g.capability: g.enabled
        for g in db.execute(
            select(AgentCapabilityGrant).where(AgentCapabilityGrant.agent_id == agent_id)
        ).scalars()
    }


def _structured_grant(grant: AgentCapabilityGrant) -> dict[str, Any]:
    """One grant row -> the canonical `{enabled, config}` wire shape (Task 15,
    **D-11**).

    Shared by `structured_grants_dict` and `bulk_structured_grants_dict` so
    `GET /agents/{id}` and `GET /agents/presence` can never project the same
    row differently.

    The registry lookup goes through `default_config_for`, which is `.get`-based
    on purpose: `approve_agent` wrote an `AgentCapabilityGrant` row for any
    string key before Task 14's 422 validator landed, and nothing cleans those
    rows up, so a single legacy row naming an unregistered capability must
    render verbatim rather than turn both endpoints into 500s for the whole
    fleet.
    """
    return {
        "enabled": grant.enabled,
        "config": default_config_for(grant.capability) | dict(grant.config or {}),
    }


def structured_grants_dict(db: Session, agent_id: int) -> dict[str, dict[str, Any]]:
    """Normalized schema-2 grants, including centrally managed configuration."""
    return {
        g.capability: _structured_grant(g)
        for g in db.execute(
            select(AgentCapabilityGrant).where(AgentCapabilityGrant.agent_id == agent_id)
        ).scalars()
    }


def bulk_structured_grants_dict(
    db: Session, agent_ids: list[int]
) -> dict[int, dict[str, dict[str, Any]]]:
    """`structured_grants_dict`, but for many agents in one query.

    The bulk presence endpoint (Task 12) needs per-agent capability grants for
    a whole fleet without issuing one `AgentCapabilityGrant` SELECT per agent.
    Every id in `agent_ids` is present in the result (mapped to `{}` if it has
    no grant rows) so callers can index it unconditionally rather than
    special-casing a missing key.

    Emits the same canonical `{enabled, config}` shape as its single-agent
    twin — never a bare boolean (Task 15, **D-11**). The bool-valued
    `grants_dict` above stays, but only as the internal enforcement lookup in
    `services/agent_link.py`; it is not a wire shape.
    """
    result: dict[int, dict[str, dict[str, Any]]] = {agent_id: {} for agent_id in agent_ids}
    if not agent_ids:
        return result
    for g in db.execute(
        select(AgentCapabilityGrant).where(AgentCapabilityGrant.agent_id.in_(agent_ids))
    ).scalars():
        result.setdefault(g.agent_id, {})[g.capability] = _structured_grant(g)
    return result


def propose_hardware_match(db: Session, agent: Agent) -> Hardware | None:
    """Descending-confidence match: machine_id_hash -> MAC -> hostname (spec §3.3).

    `Hardware.machine_id_hash` (Task 16) is the strongest signal — a device's
    `/etc/machine-id` hash survives hostname renames and NIC swaps that would
    defeat the MAC/hostname branches below, so it's checked first. Falls
    through to an exact MAC-address match (any of the agent's reported
    `primary_macs`), then an exact hostname match, returning the first hit at
    whichever confidence tier produces one; `None` if nothing matches at any
    tier.
    """
    if agent.machine_id_hash:
        match = db.execute(
            select(Hardware).where(Hardware.machine_id_hash == agent.machine_id_hash)
        ).scalar_one_or_none()
        if match is not None:
            return match

    for mac in agent.primary_macs or []:
        match = db.execute(select(Hardware).where(Hardware.mac_address == mac)).scalar_one_or_none()
        if match is not None:
            return match

    if agent.hostname:
        return db.execute(
            select(Hardware).where(Hardware.name == agent.hostname)
        ).scalar_one_or_none()

    return None


def has_duplicate_machine_id(db: Session, agent: Agent) -> bool:
    """True if some *other* `Agent` row reports the same `machine_id_hash`.

    Surfaced identically from both the agent-detail endpoint and the
    pairing-lookup endpoint (api/agents.py `_to_read` / `post_pairing_lookup`)
    so an operator sees the same duplicate-machine warning regardless of
    which screen (fleet detail view vs. pairing-code approval flow) they use
    to review a device — see spec §3.3's "Duplicate machine_id_hash" row.
    An agent with no reported machine_id_hash (old-shaped hello, or a host
    that couldn't read /etc/machine-id) can never be flagged as a duplicate;
    there is nothing to compare.
    """
    if not agent.machine_id_hash:
        return False
    return (
        db.execute(
            select(Agent).where(
                Agent.machine_id_hash == agent.machine_id_hash,
                Agent.id != agent.id,
            )
        ).scalar_one_or_none()
        is not None
    )


def record_event(
    db: Session,
    agent_id: int,
    event_type: str,
    *,
    actor_user_id: int | None = None,
    detail: dict | None = None,
) -> AgentEvent:
    event = AgentEvent(
        agent_id=agent_id, event_type=event_type, actor_user_id=actor_user_id, detail=detail
    )
    db.add(event)
    db.flush()
    return event


_PRESENCE_TTL_SECONDS = 60
_LAST_SEEN_WRITE_THROTTLE_SECONDS = 60


def _presence_key(agent_id: int) -> str:
    return f"agent:presence:{agent_id}"


async def mark_presence_connected(agent_id: int, worker: str) -> None:
    from app.core.redis import get_redis

    r = await get_redis()
    if r is None:
        return
    payload = json.dumps({"connected_at": utcnow().isoformat(), "worker": worker})
    await r.setex(_presence_key(agent_id), _PRESENCE_TTL_SECONDS, payload)


async def mark_presence_disconnected(agent_id: int) -> None:
    from app.core.redis import get_redis

    r = await get_redis()
    if r is None:
        return
    await r.delete(_presence_key(agent_id))


async def is_agent_online(agent_id: int) -> bool:
    from app.core.redis import get_redis

    r = await get_redis()
    if r is None:
        return False
    return bool(await r.exists(_presence_key(agent_id)))


def _offline_presence() -> dict[str, Any]:
    return {"online": False, "connected_since": None}


async def bulk_presence(agent_ids: list[int]) -> dict[int, dict[str, Any]]:
    """`is_agent_online`, but for a whole fleet in one Redis round trip.

    The bulk presence REST endpoint (Task 12) must not do one `EXISTS`/`GET`
    per agent — this issues a single `MGET` across every agent's
    `agent:presence:{id}` key instead. Every id in `agent_ids` is present in
    the result, mapped to `{"online": bool, "connected_since": datetime |
    None}`: a missing or TTL-expired key (never connected, or the connection
    dropped without a fresh heartbeat) resolves to `online=False,
    connected_since=None`, exactly as a single `is_agent_online` call would
    for that agent — and a Redis-unavailable outcome degrades every agent to
    that same offline default, mirroring `is_agent_online`'s own
    degrade-gracefully contract rather than raising or partially answering.
    """
    if not agent_ids:
        return {}

    from app.core.redis import get_redis

    r = await get_redis()
    if r is None:
        return {agent_id: _offline_presence() for agent_id in agent_ids}

    keys = [_presence_key(agent_id) for agent_id in agent_ids]
    raw_values = await r.mget(keys)

    result: dict[int, dict[str, Any]] = {}
    for agent_id, raw in zip(agent_ids, raw_values, strict=True):
        if raw is None:
            result[agent_id] = _offline_presence()
            continue
        connected_since: datetime | None = None
        try:
            payload = json.loads(raw)
            connected_at = payload.get("connected_at")
            if connected_at:
                connected_since = datetime.fromisoformat(connected_at)
        except (TypeError, ValueError):
            _logger.warning("agent %s: malformed presence payload dropped", agent_id)
        result[agent_id] = {"online": True, "connected_since": connected_since}
    return result


async def refresh_presence_heartbeat(db: Session, agent_id: int, worker: str) -> None:
    """Refresh the Redis presence TTL every heartbeat; throttle the Postgres
    last_seen_at write to roughly once per minute so a large fleet doesn't
    generate one write per agent per 20s heartbeat."""
    from app.core.redis import get_redis

    r = await get_redis()
    if r is not None:
        payload = json.dumps({"connected_at": utcnow().isoformat(), "worker": worker})
        await r.setex(_presence_key(agent_id), _PRESENCE_TTL_SECONDS, payload)

    agent = db.get(Agent, agent_id)
    if agent is None:
        return
    now = utcnow()
    if (
        agent.last_seen_at is None
        or (now - agent.last_seen_at).total_seconds() >= _LAST_SEEN_WRITE_THROTTLE_SECONDS
    ):
        agent.last_seen_at = now
        db.flush()


_AGENTS_REDIS_CHANNEL = "cb:agents:events"


async def broadcast_presence(agent_id: int, event_type: str, detail: dict | None = None) -> None:
    """Push a presence event to every live WS /api/agents/stream viewer.

    Redis pub/sub is the cross-worker path (mirrors discovery_service.py's
    _emit_ws_event), but ws_manager.broadcast is always also attempted on
    this worker: /stream's Redis subscribe (Task 15) happens asynchronously
    right after connect, so a viewer whose subscribe hasn't landed yet would
    otherwise miss the event outright. Presence flips are infrequent enough
    that occasional duplicate delivery of an idempotent status message is a
    non-issue. Never raises — a bad payload or dead Redis/NATS must not
    abort the caller's own mutation (approve/reject/revoke, connect/
    disconnect).
    """
    from app.core import subjects
    from app.core.nats_client import nats_client
    from app.core.redis import get_redis
    from app.core.ws_manager import ws_manager

    message = {"agent_id": agent_id, "event_type": event_type, "detail": detail}

    try:
        r = await get_redis()
        if r is not None:
            await r.publish(_AGENTS_REDIS_CHANNEL, json.dumps(message, default=str))
    except Exception as exc:
        _logger.debug("agent presence broadcast (redis) failed: %s", exc)

    try:
        await ws_manager.broadcast(message)
    except Exception as exc:
        _logger.debug("agent presence broadcast (ws_manager) failed: %s", exc)

    try:
        await nats_client.publish(subjects.AGENT_EVENT, message)
    except Exception as exc:
        _logger.debug("agent presence broadcast (nats) failed: %s", exc)


WORKER_ID = uuid.uuid4().hex
"""Identifies *this* worker process for cross-worker /link connection
ownership and control-frame routing (Task 8).

No existing identifier in the codebase is fit for this purpose. The closest
candidate — the `worker` string `mark_presence_connected`/
`refresh_presence_heartbeat` already record (`socket.gethostname()`, set by
ws_agents.py's `link_stream`) — is a purely cosmetic display label for the UI
presence payload, not a routing key: multiple backend worker processes
commonly run on one host (e.g. multiple uvicorn/gunicorn workers), so
hostname alone cannot say *which one* currently holds a given agent's live
socket. There is likewise no existing per-process id from the NATS
integration (nats_client.py has no client-id concept surfaced to callers) or
from Redis channel naming (`cb:agents:events` is a single shared channel, not
per-worker). Absent such a concept, this is the "reasonable per-process UUID
generated at worker startup" the task brief allows for: generated once, at
this module's import time (i.e. once per worker process), and stable for
that process's lifetime.
"""

_CONNECTION_KEY_PREFIX = "agent:connection:"
# Same cadence as presence (_PRESENCE_TTL_SECONDS) — refreshed alongside it
# from the same heartbeat, so the two keys expire together rather than one
# outliving the other.
_CONNECTION_TTL_SECONDS = _PRESENCE_TTL_SECONDS


def _connection_key(agent_id: int) -> str:
    return f"{_CONNECTION_KEY_PREFIX}{agent_id}"


async def register_agent_connection(agent_id: int, *, worker_id: str = WORKER_ID) -> bool:
    """Record that `worker_id` currently holds `agent_id`'s live /link socket.

    Mirrors `mark_presence_connected`'s TTL-key pattern exactly (same 60s
    TTL). Unlike `mark_presence_connected`, a Redis-unavailable outcome is
    logged rather than silently swallowed: the /link WebSocket itself doesn't
    need Redis and can proceed either way, but with no registry entry this
    worker becomes unreachable for cross-worker control routing for as long
    as Redis stays down — a guarantee the global constraints call out as
    something that must "fail clearly, not silently weaken". Returns True on
    success, False when Redis is unavailable.
    """
    from app.core.redis import get_redis

    r = await get_redis()
    if r is None:
        _logger.warning(
            "agent %s: connection registry unavailable (Redis down) — "
            "cross-worker control routing disabled for this connection",
            agent_id,
        )
        return False
    await r.setex(_connection_key(agent_id), _CONNECTION_TTL_SECONDS, worker_id)
    return True


async def refresh_agent_connection(agent_id: int, *, worker_id: str = WORKER_ID) -> None:
    """Refresh the connection-registry TTL — call on the same cadence as
    `refresh_presence_heartbeat` (see agent_link.py's `_handle_heartbeat`),
    so a long-lived connection's registry entry never expires out from under
    it purely from the passage of time."""
    from app.core.redis import get_redis

    r = await get_redis()
    if r is None:
        return
    await r.setex(_connection_key(agent_id), _CONNECTION_TTL_SECONDS, worker_id)


# Atomic compare-and-delete (executed server-side via EVALSHA, the same
# register_script/EVALSHA idiom rate_limit_middleware.py uses for its
# sliding-window check). A GET-then-DELETE from Python would be two separate
# round trips with a window between them for another worker's
# register_agent_connection (SETEX) to land — this worker's DELETE would then
# blindly remove the new owner's freshly-written entry. Running the
# compare-and-delete as a single Lua script closes that window: Redis
# executes it as one atomic server-side step, so no other command can
# interleave between the GET and the DELETE.
_COMPARE_AND_DELETE_LUA = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""


async def deregister_agent_connection(agent_id: int, *, worker_id: str = WORKER_ID) -> None:
    """Remove the registry entry, but only if it's still this worker's.

    A fast disconnect/reconnect can land the agent on a *different* worker
    before this worker's own teardown runs (its `finally` block races the new
    connection's own `register_agent_connection`). Blindly deleting on
    disconnect — as `mark_presence_disconnected` does for the presence key —
    would then erase the new owner's freshly-written entry. The compare and
    the delete run as a single atomic Lua script (`_COMPARE_AND_DELETE_LUA`)
    rather than a GET followed by a DELETE, so only ever the row this worker
    itself owns is removed, even if another worker's register races in
    between what would otherwise be two separate round trips.
    """
    from app.core.redis import get_redis

    r = await get_redis()
    if r is None:
        return
    script = r.register_script(_COMPARE_AND_DELETE_LUA)
    await script(keys=[_connection_key(agent_id)], args=[worker_id])


async def get_agent_connection_owner(agent_id: int) -> str | None:
    """The `worker_id` of whichever worker currently holds `agent_id`'s live
    /link socket, or None if no worker is registered (agent offline, or the
    registry entry expired)."""
    from app.core.redis import get_redis

    r = await get_redis()
    if r is None:
        return None
    return cast(str | None, await cast(Awaitable[Any], r.get(_connection_key(agent_id))))


_CONTROL_CHANNEL_PREFIX = "cb:agents:control:"


def _control_channel(agent_id: int) -> str:
    return f"{_CONTROL_CHANNEL_PREFIX}{agent_id}"


async def publish_agent_control_frame(agent_id: int, frame: dict) -> bool:
    """Hand a control frame to whichever worker currently holds `agent_id`'s
    live /link socket.

    This is the generic delivery primitive only: it hands `frame` off over
    `agent_id`'s dedicated Redis pub/sub channel, published by any worker
    process regardless of whether it owns the connection. It does NOT itself
    know or care what `frame` means — Task 9 wires specific frame types
    (capabilities.set, update, disconnect, key-rotation, ping) through this.
    Actual delivery to the live socket depends on the owning worker running
    `claim_agent_control_frames` for this agent (also Task 9's concern).

    Never raises — a bad payload or dead Redis must not abort the caller's
    own control-plane action. Returns True once the frame has been published
    (note: publish success does not guarantee an owning worker was listening
    — Redis pub/sub has no persistence/replay for messages published to a
    channel with no current subscriber), False when Redis is unavailable or
    publish itself failed.
    """
    from app.core.redis import get_redis

    r = await get_redis()
    if r is None:
        _logger.warning("agent %s: control frame not published — Redis unavailable", agent_id)
        return False
    try:
        await r.publish(_control_channel(agent_id), json.dumps(frame, default=str))
        return True
    except Exception as exc:
        _logger.warning("agent %s: control frame publish failed: %s", agent_id, exc)
        return False


async def claim_agent_control_frames(
    agent_id: int, *, worker_id: str = WORKER_ID
) -> AsyncIterator[dict]:
    """Async generator: yields each control frame published for `agent_id`
    while — and only while — `worker_id` is currently registered as the
    owner of that agent's connection (`register_agent_connection`).

    This is the "claim" half of the delivery primitive: subscribing to
    `agent_id`'s channel alone is not sufficient authorization to act on a
    frame, because a message can arrive after this worker's own connection
    has already handed off to another worker (e.g. the agent reconnected
    elsewhere) but before whatever holds this generator has gotten around to
    stopping it. Re-checking ownership per message, rather than once at
    subscribe time, closes that window — a frame that arrives for an agent
    this worker no longer owns is silently dropped rather than delivered to
    a socket that's already gone.

    Callers own the generator's lifetime: run it inside its own `asyncio`
    task for the life of the /link connection and cancel that task to stop
    listening (e.g. when the socket closes) — cancellation reaches this
    generator as an ordinary `GeneratorExit`/`CancelledError` at its current
    `await`, and the `finally` block below unsubscribes cleanly, mirroring
    `_redis_agent_listener`'s teardown in ws_agents.py. Wiring this into
    `link_stream` itself is Task 9's job, not this primitive's.
    """
    from app.core.redis import get_redis

    r = await get_redis()
    if r is None:
        return
    pubsub = r.pubsub()
    try:
        await pubsub.subscribe(_control_channel(agent_id))
        while True:
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if msg is None or msg.get("type") != "message":
                continue
            owner = await get_agent_connection_owner(agent_id)
            if owner != worker_id:
                continue
            try:
                yield json.loads(msg["data"])
            except (TypeError, ValueError) as exc:
                _logger.warning("agent %s: malformed control frame dropped: %s", agent_id, exc)
    finally:
        try:
            await pubsub.unsubscribe()
            await pubsub.aclose()
        except Exception:
            pass


_PENDING_EXPIRY_DAYS = 7


def expire_stale_pending_agents(db: Session) -> int:
    from datetime import timedelta

    cutoff = utcnow() - timedelta(days=_PENDING_EXPIRY_DAYS)
    query = select(Agent).where(Agent.status == "pending", Agent.enrolled_at < cutoff)
    stale = list(db.execute(query).scalars())
    for agent in stale:
        agent.status = "rejected"
        record_event(db, agent.id, "rejected", detail={"reason": "pending_expired"})
    db.commit()
    return len(stale)
