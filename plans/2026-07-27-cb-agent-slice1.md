# cb-agent Slice 1 (Foundation) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the cb-agent foundation — a downloadable Go daemon that enrolls against a Circuit
Breaker instance over an end-to-end-encrypted channel, appears in-app for approval, and shows
online, reporting nothing but heartbeats. No collectors (host telemetry, remote probe, local
discovery) ship in this slice — those are slices 2–4 per
`specs/2026-07-26-cb-agent-design.md` §8.

**Architecture:** Three new subsystems wired together by one protocol. `apps/agent/` is a new Go
module (first Go code in this repo) implementing keygen, Noise `IK` handshakes, a bounded spool,
and a capability gate behind a `Collector`-ready seam. The backend gains an agent control plane
(`agents.py`, `ws_agents.py`, `agent_enrollment.py`, `agent_registry.py`, `agent_link.py`,
`agent_crypto.py`) that terminates the Noise channel, persists agent state, and never contains
collector domain logic. The frontend gets a new top-level Agents surface following the
`MonitorsPage`/`useMonitorStream` pattern already in the codebase.

**Tech Stack:** Go 1.22+ (`github.com/flynn/noise` for Noise `IK`, `github.com/gorilla/websocket`
for the WSS client), Python/FastAPI (`dissononce` for the Noise `IK` responder, `cryptography`
for X25519 keygen — already a dependency), Postgres/Alembic, Redis (pairing codes, presence),
NATS (event fan-out via existing `core/subjects.py` + `core/nats_client.py`), React (existing
`lucide-react`, `useMonitorStream`-style hooks).

## Global Constraints

Copied verbatim from `specs/2026-07-26-cb-agent-design.md` — every task's requirements implicitly
include these:

- **No network relay/tunnel capability in v1.** Every agent-initiated frame is outbound-only.
- **Frame envelope:** `{v, type, seq, ts, payload}` — defined once per language, nowhere else.
- **Fingerprint:** first 128 bits of SHA-256 over the device static public key, rendered as eight
  groups of four hex characters (`XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX`... i.e. 32 hex chars
  grouped in 4s).
- **Pairing code:** 60 bits of entropy, Crockford base32, formatted `XXXX-XXXX-XXXX`, stored
  **hashed** in Redis under `agent_pairing:{code_hash}`, 15-minute TTL, single-use.
- **Noise channel:** `IK` pattern, agent is initiator, X25519 DH, ChaCha20-Poly1305 cipher,
  SHA-256 hash. Rekey every 15 minutes. Handshakes with a timestamp outside ±60s are rejected
  with an explicit clock-skew error, not a generic auth failure.
- **Heartbeat:** every 20s; server declares an agent dead after three misses (60s).
- **Reconnect:** exponential backoff with jitter, 1s → 5-minute cap.
- **Spool:** `/var/lib/cb-agent/spool/`, 64 MB default cap, oldest segment dropped when full.
  Only data frames spool — control frames never do. Drain interleaves spooled with live traffic
  at a compile-time-constant ratio of one spooled frame per four live frames.
- **Default capability grant on approval:** `host_telemetry` enabled, `remote_probe` and
  `local_discovery` disabled. In slice 1 the grants exist in the data model with no collector
  behind any of them.
- **Server enforces grants independently of the agent's own gate.** A frame whose type isn't
  covered by an active grant is dropped server-side and recorded as `capability_violation`, even
  if the agent-side gate should have already refused to send it.
- **Self-update rollback:** if the new binary fails to re-establish a link within two minutes,
  the agent automatically rolls back to the previous binary.
- **Migration convention:** new tables must be added to `_EXCLUDED_TABLES` in
  `apps/backend/migrations/versions/0001_init.py`, verified with a fresh-volume mono boot
  (project convention — see `_EXCLUDED_TABLES` already containing `monitor_events` as precedent).
- **RBAC:** `/api/agents/*` uses the existing `viewer / editor / admin` hierarchy via
  `app.core.rbac.require_role(...)`.
- **Test isolation:** backend tests use the SAVEPOINT-based `db_session` / `async_db_session`
  fixtures in `apps/backend/tests/conftest.py`. `log_worker_audit` bypasses SAVEPOINT rollback —
  never use real production keys as `entity_name` in direct tests of it.
- **No `Co-Authored-By: Claude` trailers** on any commit made while executing this plan.

## File Structure

**Go module — `apps/agent/`** (new):

| File | Responsibility |
|---|---|
| `go.mod`, `go.sum` | module `circuitbreaker.dev/cb-agent`, Go 1.22+ |
| `cmd/cb-agent/main.go` | process entrypoint, signal handling, CLI subcommand dispatch |
| `internal/config/config.go` | `/etc/circuit-breaker/agent.toml` load/validate, state dir paths |
| `internal/frame/frame.go` | the `Frame` envelope type — `{v, type, seq, ts, payload}` — shared by enroll and link |
| `internal/noiseconn/noiseconn.go` | Noise `IK` initiator wrapper over a `*websocket.Conn`, shared by enroll and link |
| `internal/enroll/keys.go` | X25519 keygen, `device.key` persistence (mode 0600) |
| `internal/enroll/enroll.go` | dial `WS /api/agents/enroll`, run the Noise handshake, print pairing code/fingerprint |
| `internal/link/link.go` | dial `WS /api/agents/link`, heartbeat loop, reconnect/backoff |
| `internal/spool/spool.go` | bounded on-disk queue, oldest-dropped, drain-interleave |
| `internal/capability/capability.go` | in-agent capability gate — refuse and log ungranted instructions |
| `internal/update/update.go` | self-update: download, verify SHA-256, swap binary, re-exec, rollback |

**Backend — `apps/backend/src/app/`** (new files):

| File | Responsibility |
|---|---|
| `core/agent_crypto.py` | server X25519 static keypair (vault-backed), Noise `IK` responder, replay/clock-skew window |
| `services/agent_enrollment.py` | pairing-code lifecycle in Redis |
| `services/agent_registry.py` | agent CRUD, presence (Redis + Postgres throttle), capability grants, host-link proposal |
| `services/agent_link.py` | frame decode → capability check → dispatch. No domain logic. |
| `api/agents.py` | fleet REST — list, detail, approve, reject, revoke, rename, grants, install-command |
| `api/ws_agents.py` | `WS /enroll`, `WS /link` (unauthenticated, Noise-authenticated), `WS /stream` (session-authenticated presence) |
| `schemas/agents.py` | Pydantic request/response models |
| `migrations/versions/0089_agents.py` | `agents`, `agent_capability_grants`, `agent_events` tables |

**Frontend — `apps/frontend/src/`** (new files):

| File | Responsibility |
|---|---|
| `api/agents.js` | REST client for `/api/agents/*` |
| `hooks/useAgentLive.js` | subscribes to `WS /api/agents/stream`, mirrors `useMonitorStream.js` |
| `pages/AgentsPage.jsx` | list, pending-approval banner, add-agent modal, approval flow |
| `pages/AgentDetailPage.jsx` | live header, capabilities, events, revoke |
| `components/agents/AgentApprovalModal.jsx` | shared approval screen (pasted code, magic link, and live-panel click all converge here) |

Each Go package and each Python module is introduced by the task that first needs it — see the
task list below for exact ordering.

---

### Task 1: Data model — `agents`, `agent_capability_grants`, `agent_events`

**Files:**
- Create: `apps/backend/migrations/versions/0089_agents.py`
- Modify: `apps/backend/migrations/versions/0001_init.py` (add three table names to `_EXCLUDED_TABLES`)
- Modify: `apps/backend/src/app/db/models.py` (add `Agent`, `AgentCapabilityGrant`, `AgentEvent` ORM classes)
- Modify: `apps/backend/tests/factories.py` (add `agent`, `agent_capability_grant`, `agent_event` factory methods)
- Test: `apps/backend/tests/test_models.py`

**Interfaces:**
- Produces: `Agent` (`id`, `name`, `device_pk`, `fingerprint`, `status`, `hostname`,
  `machine_id_hash`, `os`, `os_version`, `arch`, `agent_version`, `primary_macs`, `reported_ip`,
  `hardware_id`, `tenant_id`, `enrolled_at`, `approved_at`, `approved_by_user_id`, `revoked_at`,
  `revoked_by_user_id`, `revoke_reason`, `last_seen_at`, `connected_since`, `notes`, `created_at`,
  `updated_at`), `AgentCapabilityGrant` (`id`, `agent_id`, `capability`, `enabled`, `config`,
  `granted_by_user_id`, `granted_at`), `AgentEvent` (`id`, `agent_id`, `event_type`,
  `actor_user_id`, `detail`, `created_at`) — every later backend task imports these three from
  `app.db.models`.
- Consumes: `app.db.session.Base`, `app.core.time.utcnow` (as `_now`, matching `MonitorItem`'s
  pattern at `apps/backend/src/app/db/models.py:226-259`).

- [ ] **Step 1: Write the migration**

```python
# apps/backend/migrations/versions/0089_agents.py
"""Add agents, agent_capability_grants, agent_events.

Revision ID: 0089_agents
Revises: 0088_compute_unit_telemetry_last_polled
Create Date: 2026-07-27
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0089_agents"
down_revision = "0088_compute_unit_telemetry_last_polled"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agents",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("device_pk", sa.String(), nullable=False, unique=True),
        sa.Column("fingerprint", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("hostname", sa.String(), nullable=True),
        sa.Column("machine_id_hash", sa.String(), nullable=True),
        sa.Column("os", sa.String(), nullable=True),
        sa.Column("os_version", sa.String(), nullable=True),
        sa.Column("arch", sa.String(), nullable=True),
        sa.Column("agent_version", sa.String(), nullable=True),
        sa.Column("primary_macs", JSONB(), nullable=True),
        sa.Column("reported_ip", sa.String(), nullable=True),
        sa.Column(
            "hardware_id", sa.Integer(),
            sa.ForeignKey("hardware.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column(
            "tenant_id", sa.Integer(),
            sa.ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("enrolled_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("revoke_reason", sa.Text(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("connected_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        if_not_exists=True,
    )
    op.create_index("ix_agents_fingerprint", "agents", ["fingerprint"], if_not_exists=True)

    op.create_table(
        "agent_capability_grants",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "agent_id", sa.Integer(),
            sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("capability", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("config", JSONB(), nullable=False, server_default="{}"),
        sa.Column("granted_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("agent_id", "capability", name="uq_agent_capability_grants_agent_capability"),
        if_not_exists=True,
    )

    op.create_table(
        "agent_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "agent_id", sa.Integer(),
            sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("detail", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        if_not_exists=True,
    )
    op.create_index(
        "ix_agent_events_agent_time", "agent_events", ["agent_id", "created_at"], if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_agent_events_agent_time", table_name="agent_events", if_exists=True)
    op.drop_table("agent_events", if_exists=True)
    op.drop_table("agent_capability_grants", if_exists=True)
    op.drop_index("ix_agents_fingerprint", table_name="agents", if_exists=True)
    op.drop_table("agents", if_exists=True)
```

- [ ] **Step 2: Add the three tables to `0001_init.py`'s exclusion list**

In `apps/backend/migrations/versions/0001_init.py`, add `"agents"`, `"agent_capability_grants"`,
`"agent_events"` to the `_EXCLUDED_TABLES` set (alphabetical position, next to the existing
`monitor_events` / `notification_routes` entries).

- [ ] **Step 3: Add the ORM models**

In `apps/backend/src/app/db/models.py`, immediately after the `MonitorEvent` class (line 280),
add:

```python
class Agent(Base):
    """A cb-agent instance enrolled against this Circuit Breaker server."""

    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    device_pk: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    # pending|active|revoked|rejected
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    hostname: Mapped[str | None] = mapped_column(String, nullable=True)
    machine_id_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    os: Mapped[str | None] = mapped_column(String, nullable=True)
    os_version: Mapped[str | None] = mapped_column(String, nullable=True)
    arch: Mapped[str | None] = mapped_column(String, nullable=True)
    agent_version: Mapped[str | None] = mapped_column(String, nullable=True)
    primary_macs: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    reported_ip: Mapped[str | None] = mapped_column(String, nullable=True)
    hardware_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey(_FK_HARDWARE_ID, ondelete="SET NULL"), nullable=True
    )
    tenant_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True
    )
    enrolled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    revoke_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    connected_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    __table_args__ = (Index("ix_agents_fingerprint", "fingerprint"),)


class AgentCapabilityGrant(Base):
    """Per-agent, per-capability enable/disable — default-deny beyond host_telemetry."""

    __tablename__ = "agent_capability_grants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    # host_telemetry|remote_probe|local_discovery
    capability: Mapped[str] = mapped_column(String, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    granted_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (
        UniqueConstraint("agent_id", "capability", name="uq_agent_capability_grants_agent_capability"),
    )


class AgentEvent(Base):
    """Timeline entry for an agent — enrolled, approved, revoked, capability_violation, etc."""

    __tablename__ = "agent_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    actor_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (Index("ix_agent_events_agent_time", "agent_id", "created_at"),)
```

- [ ] **Step 4: Add factory methods**

In `apps/backend/tests/factories.py`, add to the `Factories` class:

```python
def agent(self, status: str = "pending", **kwargs):
    import hashlib
    import secrets

    from app.db.models import Agent

    device_pk = kwargs.pop("device_pk", secrets.token_hex(32))
    defaults = {
        "device_pk": device_pk,
        "fingerprint": hashlib.sha256(bytes.fromhex(device_pk)).hexdigest()[:32],
        "status": status,
        "hostname": fake.hostname(),
        "os": "linux",
        "arch": "amd64",
        "agent_version": "0.1.0",
    }
    defaults.update(kwargs)
    agent = Agent(**defaults)
    self.session.add(agent)
    self.session.flush()
    return agent

def agent_capability_grant(self, agent, capability: str = "host_telemetry", enabled: bool = True, **kwargs):
    from app.db.models import AgentCapabilityGrant

    defaults = {"agent_id": agent.id, "capability": capability, "enabled": enabled}
    defaults.update(kwargs)
    grant = AgentCapabilityGrant(**defaults)
    self.session.add(grant)
    self.session.flush()
    return grant

def agent_event(self, agent, event_type: str = "enrolled", **kwargs):
    from app.db.models import AgentEvent

    defaults = {"agent_id": agent.id, "event_type": event_type}
    defaults.update(kwargs)
    event = AgentEvent(**defaults)
    self.session.add(event)
    self.session.flush()
    return event
```

- [ ] **Step 5: Write the model test**

```python
# apps/backend/tests/test_models.py — append
def test_agent_model_roundtrip(db_session, factories):
    agent = factories.agent(status="pending", hostname="box1")
    grant = factories.agent_capability_grant(agent, capability="host_telemetry", enabled=True)
    event = factories.agent_event(agent, event_type="enrolled")

    db_session.flush()

    assert agent.id is not None
    assert agent.status == "pending"
    assert grant.agent_id == agent.id
    assert event.agent_id == agent.id


def test_agent_capability_grant_unique_per_agent(db_session, factories):
    from sqlalchemy.exc import IntegrityError

    agent = factories.agent()
    factories.agent_capability_grant(agent, capability="host_telemetry")
    db_session.flush()

    factories.agent_capability_grant(agent, capability="host_telemetry")
    with pytest.raises(IntegrityError):
        db_session.flush()
```

- [ ] **Step 4: Run the test to verify it fails, then passes**

Run: `cd apps/backend && pytest tests/test_models.py -k agent -v`
Expected before Step 3/4 exist: `ImportError: cannot import name 'Agent'`. After: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/migrations/versions/0089_agents.py \
        apps/backend/migrations/versions/0001_init.py \
        apps/backend/src/app/db/models.py \
        apps/backend/tests/factories.py \
        apps/backend/tests/test_models.py
git commit -m "feat(agents): add agents, agent_capability_grants, agent_events data model"
```

---

### Task 2: Server-side crypto — `agent_crypto.py`

**Files:**
- Create: `apps/backend/src/app/core/agent_crypto.py`
- Modify: `apps/backend/pyproject.toml` (add `dissononce` dependency)
- Test: `apps/backend/tests/test_agent_crypto.py`

**Interfaces:**
- Consumes: `app.services.credential_vault.get_vault()` (`encrypt(str) -> str`,
  `decrypt(str) -> str`, per `apps/backend/src/app/services/credential_vault.py`),
  `cryptography.hazmat.primitives.asymmetric.x25519` (already available — `cryptography>=48.0.1`
  is an existing dependency).
- Produces: `get_server_static_keypair() -> tuple[bytes, bytes]` (raw 32-byte private, public),
  `server_fingerprint() -> str` (32 lowercase hex chars, no separators — formatting into
  `XXXX-XXXX-...` groups is a presentation concern left to callers/frontend),
  `class NoiseIKResponder` with `__init__(self, server_private: bytes)`,
  `read_message(self, data: bytes) -> bytes` (processes the initiator's handshake message,
  returns the response bytes to send back), `remote_static() -> bytes` (available after the
  handshake completes — the agent's device public key), `encrypt(self, plaintext: bytes) -> bytes`
  / `decrypt(self, ciphertext: bytes) -> bytes` (post-handshake transport), and
  `check_clock_skew(ts: datetime, *, now: datetime | None = None) -> None` (raises
  `ClockSkewError` if `abs((now - ts).total_seconds()) > 60`). Every later backend task
  (`agent_enrollment.py`, `ws_agents.py`, `agent_link.py`) imports from this module. Slice-2+
  tasks (not in this plan) will add rekeying; slice 1 only needs single-handshake responders,
  since a link session is re-established (fresh handshake) on every reconnect.

- [ ] **Step 1: Add the `dissononce` dependency**

In `apps/backend/pyproject.toml`, add `"dissononce>=0.34.3",` to the `dependencies` list, next
to `"cryptography>=48.0.1",`. Run `cd apps/backend && python3 scripts/gen_requirements.py` per
the file's own header comment to refresh the pinned `requirements.txt`.

- [ ] **Step 2: Write the failing test for keypair generation and vault round-trip**

```python
# apps/backend/tests/test_agent_crypto.py
import pytest

from app.core.agent_crypto import get_server_static_keypair, server_fingerprint


def test_server_static_keypair_is_stable_across_calls(db_session):
    priv1, pub1 = get_server_static_keypair()
    priv2, pub2 = get_server_static_keypair()

    assert priv1 == priv2
    assert pub1 == pub2
    assert len(priv1) == 32
    assert len(pub1) == 32


def test_server_fingerprint_is_derived_from_the_public_key():
    import hashlib

    _, pub = get_server_static_keypair()
    expected = hashlib.sha256(pub).hexdigest()[:32]

    assert server_fingerprint() == expected
    assert len(server_fingerprint()) == 32
```

- [ ] **Step 3: Run it to see the import fail**

Run: `cd apps/backend && pytest tests/test_agent_crypto.py -v`
Expected: `ModuleNotFoundError: No module named 'app.core.agent_crypto'`.

- [ ] **Step 4: Implement keypair storage on top of the existing vault**

The vault (`credential_vault.py`) is string-in/string-out Fernet only — no raw-bytes or
named-secret API. Store the private key hex-encoded inside an `AppSettings` row keyed
`"agent_server_private_key"`, encrypted through `vault.encrypt()`. Check
`apps/backend/src/app/db/models.py` for `AppSettings`'s exact key/value column names before
writing this — it is a generic `key: str, value: str` settings table used elsewhere in the
codebase (e.g. `settings_service.py`); reuse it rather than adding a new table.

```python
# apps/backend/src/app/core/agent_crypto.py
"""Server-side X25519 identity and Noise IK responder for the agent link.

The server holds one static X25519 keypair for its whole lifetime, generated on
first use and persisted (encrypted) via the existing credential vault. Every
enrolling/linking agent verifies against this same public key.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta
from functools import lru_cache

from cryptography.hazmat.primitives.asymmetric import x25519
from dissononce.cipher.chachapoly import ChaChaPolyCipher
from dissononce.dh.x25519.x25519 import X25519DH
from dissononce.dh.keypair import KeyPair
from dissononce.hash.sha256 import SHA256Hash
from dissononce.processing.handshakepatterns.interactive.IK import IKHandshakePattern
from dissononce.processing.impl.handshakestate import HandshakeState
from dissononce.processing.impl.symmetricstate import SymmetricState
from dissononce.processing.impl.cipherstate import CipherState

_logger = logging.getLogger(__name__)

_SETTINGS_KEY = "agent_server_private_key"
_CLOCK_SKEW_SECONDS = 60


class ClockSkewError(Exception):
    pass


def _generate_keypair() -> tuple[bytes, bytes]:
    priv = x25519.X25519PrivateKey.generate()
    priv_bytes = priv.private_bytes_raw()
    pub_bytes = priv.public_key().public_bytes_raw()
    return priv_bytes, pub_bytes


@lru_cache(maxsize=1)
def _load_or_create_keypair() -> tuple[bytes, bytes]:
    from sqlalchemy import select

    from app.db.models import AppSettings
    from app.db.session import SessionLocal
    from app.services.credential_vault import get_vault

    vault = get_vault()
    with SessionLocal() as db:
        row = db.execute(select(AppSettings).where(AppSettings.key == _SETTINGS_KEY)).scalar_one_or_none()
        if row is not None:
            priv_hex = vault.decrypt(row.value)
            priv_bytes = bytes.fromhex(priv_hex)
            pub_bytes = x25519.X25519PrivateKey.from_private_bytes(priv_bytes).public_key().public_bytes_raw()
            return priv_bytes, pub_bytes

        priv_bytes, pub_bytes = _generate_keypair()
        db.add(AppSettings(key=_SETTINGS_KEY, value=vault.encrypt(priv_bytes.hex())))
        db.commit()
        return priv_bytes, pub_bytes


def get_server_static_keypair() -> tuple[bytes, bytes]:
    """Return (private_bytes, public_bytes), 32 bytes each, generating once on first call."""
    return _load_or_create_keypair()


def server_fingerprint() -> str:
    """32 lowercase hex chars over the server static public key. Grouping into
    XXXX-XXXX-... is a display concern handled by callers."""
    _, pub = get_server_static_keypair()
    return hashlib.sha256(pub).hexdigest()[:32]


def check_clock_skew(ts: datetime, *, now: datetime | None = None) -> None:
    now = now or datetime.utcnow()
    delta = abs((now - ts).total_seconds())
    if delta > _CLOCK_SKEW_SECONDS:
        raise ClockSkewError(f"handshake timestamp skew {delta:.1f}s exceeds {_CLOCK_SKEW_SECONDS}s")


def _keypair_from_private(priv_bytes: bytes) -> KeyPair:
    dh = X25519DH()
    pub_bytes = x25519.X25519PrivateKey.from_private_bytes(priv_bytes).public_key().public_bytes_raw()
    return KeyPair.from_bytes(priv_bytes, pub_bytes)


class NoiseIKResponder:
    """Server-side (responder) half of a Noise_IK_25519_ChaChaPoly_SHA256 handshake."""

    def __init__(self, server_private: bytes) -> None:
        self._state = HandshakeState(
            SymmetricState(CipherState(ChaChaPolyCipher()), SHA256Hash()),
            X25519DH(),
        )
        self._state.initialize(
            IKHandshakePattern(), False, b"", s=_keypair_from_private(server_private),
        )
        self._cipher_pair: tuple[CipherState, CipherState] | None = None

    def read_message(self, data: bytes) -> bytes:
        """Process the initiator's single IK message, return our response message."""
        payload_buf = bytearray()
        self._state.read_message(data, payload_buf)
        response = bytearray()
        self._cipher_pair = self._state.write_message(b"", response)
        return bytes(response)

    def remote_static(self) -> bytes:
        """The agent's device public key, known once the IK handshake's single
        inbound message has been processed by read_message()."""
        return self._state.rs.public_bytes if self._state.rs else b""

    def encrypt(self, plaintext: bytes) -> bytes:
        send_cipher, _ = self._cipher_pair
        return send_cipher.encrypt_with_ad(b"", plaintext)

    def decrypt(self, ciphertext: bytes) -> bytes:
        _, recv_cipher = self._cipher_pair
        return recv_cipher.decrypt_with_ad(b"", ciphertext)
```

> **Verification note for the implementer:** `dissononce`'s exact class/method names
> (`HandshakeState.rs`, `KeyPair.from_bytes`, the `write_message`/`read_message` buffer-argument
> convention) must be confirmed against the installed version before trusting the snippet above
> verbatim — run `python3 -c "import dissononce; help(dissononce)"` and
> `python3 -c "from dissononce.processing.impl.handshakestate import HandshakeState; help(HandshakeState)"`
> after Step 1's install, and adjust names to match. This is the one third-party API surface in
> this plan that couldn't be confirmed by reading this repo, since no Noise library is used here
> yet.

- [ ] **Step 5: Run the keypair/fingerprint tests to verify they pass**

Run: `cd apps/backend && pytest tests/test_agent_crypto.py -v`
Expected: 2 passed.

- [ ] **Step 6: Write and pass a same-process handshake round-trip test**

This test doesn't yet import the Go side — it proves the Python responder is self-consistent by
running it against a same-process Python **initiator** built with the identical library, which
is the cheapest way to catch API-usage mistakes before Task 8 builds the real Go initiator.

```python
def test_noise_ik_responder_completes_handshake_against_python_initiator():
    from dissononce.processing.impl.handshakestate import HandshakeState as HS
    from dissononce.processing.impl.symmetricstate import SymmetricState as SS
    from dissononce.processing.impl.cipherstate import CipherState as CS
    from dissononce.cipher.chachapoly import ChaChaPolyCipher
    from dissononce.dh.x25519.x25519 import X25519DH
    from dissononce.hash.sha256 import SHA256Hash
    from dissononce.processing.handshakepatterns.interactive.IK import IKHandshakePattern

    from app.core.agent_crypto import NoiseIKResponder, _keypair_from_private, _generate_keypair

    server_priv, server_pub = _generate_keypair()
    agent_priv, agent_pub = _generate_keypair()

    responder = NoiseIKResponder(server_priv)

    initiator = HS(SS(CS(ChaChaPolyCipher()), SHA256Hash()), X25519DH())
    initiator.initialize(
        IKHandshakePattern(), True, b"",
        s=_keypair_from_private(agent_priv),
        rs=_keypair_from_private(server_priv).public,
    )
    msg1 = bytearray()
    initiator.write_message(b"", msg1)

    msg2 = responder.read_message(bytes(msg1))

    payload = bytearray()
    initiator_ciphers = initiator.read_message(msg2, payload)

    send_cipher, recv_cipher = initiator_ciphers
    ct = send_cipher.encrypt_with_ad(b"", b"hello from agent")
    pt = responder.decrypt(ct)
    assert pt == b"hello from agent"
```

Run: `cd apps/backend && pytest tests/test_agent_crypto.py -v` — expected: 3 passed (adjust
exact `dissononce` call signatures per the Step 4 verification note if this fails on names, not
on protocol logic).

**If this test fails specifically with a MAC/authentication error on `responder.decrypt(ct)`**
(not an `AttributeError`/`ImportError`), the cause is almost certainly `NoiseIKResponder`'s
`self._cipher_pair` tuple being unpacked in the wrong order in `encrypt`/`decrypt` above. Noise
returns the pair as `(c1, c2)` where `c1` is the initiator→responder direction and `c2` is
responder→initiator; a responder must `decrypt` with `c1` and `encrypt` with `c2` — the reverse of
what an initiator does. `_keypair_from_private`'s and `dissononce`'s exact return order aren't
independently confirmable without running the code, so swap the unpacking order in Step 4's
`encrypt`/`decrypt` methods (`send_cipher, _` ↔ `_, send_cipher`, same for decrypt) if this
specific failure mode shows up, then rerun.

- [ ] **Step 7: Commit**

```bash
git add apps/backend/pyproject.toml apps/backend/src/app/core/agent_crypto.py apps/backend/tests/test_agent_crypto.py
git commit -m "feat(agents): server X25519 identity and Noise IK responder"
```

---

### Task 3: Go module skeleton — config, frame envelope, CLI shell

**Files:**
- Create: `apps/agent/go.mod`
- Create: `apps/agent/internal/config/config.go`
- Create: `apps/agent/internal/config/config_test.go`
- Create: `apps/agent/internal/frame/frame.go`
- Create: `apps/agent/internal/frame/frame_test.go`
- Create: `apps/agent/cmd/cb-agent/main.go`

**Interfaces:**
- Produces: `config.Config{ServerURL, ServerStaticPK, TLSPin, LogLevel string; SpoolCapBytes int64}`,
  `config.Load(path string) (*Config, error)`, `config.StateDir() string` (reads
  `CB_AGENT_STATE_DIR` env override, defaults to `/var/lib/cb-agent`); `frame.Frame{V int; Type
  string; Seq uint64; TS time.Time; Payload json.RawMessage}`, `frame.Encode(f Frame) ([]byte,
  error)`, `frame.Decode(data []byte) (Frame, error)`. Every later Go task
  (`enroll`, `link`, `spool`, `capability`, `update`) imports `config` and `frame`.
- Consumes: nothing (this is the module root).

- [ ] **Step 1: Initialize the Go module**

```bash
mkdir -p apps/agent/cmd/cb-agent apps/agent/internal/config apps/agent/internal/frame
cd apps/agent && go mod init circuitbreaker.dev/cb-agent
```

Confirm `go version` is 1.22 or newer (`go version`); this plan assumes generics and
`slices`/`maps` stdlib packages are available, both introduced in 1.21.

- [ ] **Step 2: Write the failing config test**

```go
// apps/agent/internal/config/config_test.go
package config

import (
	"os"
	"path/filepath"
	"testing"
)

func TestLoad_ParsesValidTOML(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "agent.toml")
	contents := `
server_url = "https://cb.example.com"
server_static_pk = "deadbeef"
tls_pin = "abcd1234"
log_level = "info"
spool_cap_bytes = 67108864
`
	if err := os.WriteFile(path, []byte(contents), 0o600); err != nil {
		t.Fatal(err)
	}

	cfg, err := Load(path)
	if err != nil {
		t.Fatalf("Load() error = %v", err)
	}
	if cfg.ServerURL != "https://cb.example.com" {
		t.Errorf("ServerURL = %q, want %q", cfg.ServerURL, "https://cb.example.com")
	}
	if cfg.SpoolCapBytes != 67108864 {
		t.Errorf("SpoolCapBytes = %d, want 67108864", cfg.SpoolCapBytes)
	}
}

func TestLoad_MissingFileReturnsError(t *testing.T) {
	if _, err := Load("/nonexistent/agent.toml"); err == nil {
		t.Fatal("expected error for missing config file, got nil")
	}
}

func TestStateDir_DefaultsWhenEnvUnset(t *testing.T) {
	t.Setenv("CB_AGENT_STATE_DIR", "")
	if got := StateDir(); got != "/var/lib/cb-agent" {
		t.Errorf("StateDir() = %q, want /var/lib/cb-agent", got)
	}
}

func TestStateDir_HonorsEnvOverride(t *testing.T) {
	t.Setenv("CB_AGENT_STATE_DIR", "/tmp/cb-agent-test")
	if got := StateDir(); got != "/tmp/cb-agent-test" {
		t.Errorf("StateDir() = %q, want /tmp/cb-agent-test", got)
	}
}
```

- [ ] **Step 3: Run it to see it fail to compile**

Run: `cd apps/agent && go test ./internal/config/...`
Expected: `undefined: Load` / `undefined: StateDir`.

- [ ] **Step 4: Add the TOML dependency and implement `config`**

```bash
cd apps/agent && go get github.com/BurntSushi/toml@v1.4.0
```

```go
// apps/agent/internal/config/config.go
package config

import (
	"fmt"
	"os"

	"github.com/BurntSushi/toml"
)

type Config struct {
	ServerURL      string `toml:"server_url"`
	ServerStaticPK string `toml:"server_static_pk"`
	TLSPin         string `toml:"tls_pin"`
	LogLevel       string `toml:"log_level"`
	SpoolCapBytes  int64  `toml:"spool_cap_bytes"`
}

func Load(path string) (*Config, error) {
	var cfg Config
	if _, err := toml.DecodeFile(path, &cfg); err != nil {
		return nil, fmt.Errorf("config: load %s: %w", path, err)
	}
	return &cfg, nil
}

func StateDir() string {
	if dir := os.Getenv("CB_AGENT_STATE_DIR"); dir != "" {
		return dir
	}
	return "/var/lib/cb-agent"
}
```

- [ ] **Step 5: Run the config tests to verify they pass**

Run: `cd apps/agent && go test ./internal/config/...`
Expected: `ok`.

- [ ] **Step 6: Write the failing frame envelope test**

```go
// apps/agent/internal/frame/frame_test.go
package frame

import (
	"encoding/json"
	"testing"
	"time"
)

func TestEncodeDecode_RoundTrips(t *testing.T) {
	original := Frame{
		V:       1,
		Type:    "heartbeat",
		Seq:     42,
		TS:      time.Date(2026, 7, 27, 12, 0, 0, 0, time.UTC),
		Payload: json.RawMessage(`{"ok":true}`),
	}

	data, err := Encode(original)
	if err != nil {
		t.Fatalf("Encode() error = %v", err)
	}

	decoded, err := Decode(data)
	if err != nil {
		t.Fatalf("Decode() error = %v", err)
	}
	if decoded.Type != "heartbeat" || decoded.Seq != 42 || decoded.V != 1 {
		t.Errorf("decoded = %+v, want type=heartbeat seq=42 v=1", decoded)
	}
	if !decoded.TS.Equal(original.TS) {
		t.Errorf("TS = %v, want %v", decoded.TS, original.TS)
	}
}

func TestDecode_RejectsMalformedJSON(t *testing.T) {
	if _, err := Decode([]byte("not json")); err == nil {
		t.Fatal("expected error decoding malformed frame, got nil")
	}
}
```

- [ ] **Step 7: Implement `frame`**

```go
// apps/agent/internal/frame/frame.go
package frame

import (
	"encoding/json"
	"fmt"
	"time"
)

// Frame is the wire envelope for every agent<->server message, nested inside
// the Noise-encrypted channel. v1 — see specs/2026-07-26-cb-agent-design.md §3.4.
type Frame struct {
	V       int             `json:"v"`
	Type    string          `json:"type"`
	Seq     uint64          `json:"seq"`
	TS      time.Time       `json:"ts"`
	Payload json.RawMessage `json:"payload"`
}

func Encode(f Frame) ([]byte, error) {
	data, err := json.Marshal(f)
	if err != nil {
		return nil, fmt.Errorf("frame: encode: %w", err)
	}
	return data, nil
}

func Decode(data []byte) (Frame, error) {
	var f Frame
	if err := json.Unmarshal(data, &f); err != nil {
		return Frame{}, fmt.Errorf("frame: decode: %w", err)
	}
	return f, nil
}

// Frame type constants — agent -> server.
const (
	TypeHello              = "hello"
	TypeHeartbeat          = "heartbeat"
	TypeTelemetryHost      = "telemetry.host"
	TypeProbeResult        = "probe.result"
	TypeDiscoveryFinding   = "discovery.finding"
	TypeCapabilityViolation = "capability.violation"
	TypeLog                = "log"
)

// Frame type constants — server -> agent.
const (
	TypeHelloAck        = "hello.ack"
	TypeCapabilitiesSet = "capabilities.set"
	TypeProbeAssign     = "probe.assign"
	TypeDiscoveryRequest = "discovery.request"
	TypeKeyRotate       = "key.rotate"
	TypeUpdate          = "update"
	TypeDisconnect      = "disconnect"
	TypePing            = "ping"
)
```

- [ ] **Step 8: Run the frame tests to verify they pass**

Run: `cd apps/agent && go test ./internal/frame/...`
Expected: `ok`.

- [ ] **Step 9: Write the CLI shell with a working `version` subcommand**

```go
// apps/agent/cmd/cb-agent/main.go
package main

import (
	"fmt"
	"os"
)

// AgentVersion is overridden at build time via -ldflags "-X main.AgentVersion=1.2.3".
var AgentVersion = "0.0.0-dev"

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintln(os.Stderr, "usage: cb-agent <status|enroll|version|uninstall>")
		os.Exit(1)
	}
	switch os.Args[1] {
	case "version":
		runVersion()
	default:
		fmt.Fprintf(os.Stderr, "unknown subcommand %q\n", os.Args[1])
		os.Exit(1)
	}
}

func runVersion() {
	fmt.Printf("cb-agent %s\n", AgentVersion)
}
```

`status`, `enroll`, and `uninstall` are added by Task 4 (keygen/fingerprint), Task 8 (enroll
dial), and Task 16 (update-aware uninstall) respectively — `main.go`'s switch statement grows one
case per task rather than stubbing all four now, since an unimplemented case would be exactly the
kind of placeholder this plan avoids.

- [ ] **Step 10: Build and smoke-test the binary**

Run: `cd apps/agent && go build -o /tmp/cb-agent ./cmd/cb-agent && /tmp/cb-agent version`
Expected: prints `cb-agent 0.0.0-dev`.

- [ ] **Step 11: Commit**

```bash
git add apps/agent/go.mod apps/agent/go.sum apps/agent/internal/config apps/agent/internal/frame apps/agent/cmd
git commit -m "feat(agent): Go module skeleton — config, frame envelope, CLI shell"
```

---

### Task 4: Agent identity — keygen and `device.key` persistence

**Files:**
- Create: `apps/agent/internal/enroll/keys.go`
- Create: `apps/agent/internal/enroll/keys_test.go`
- Modify: `apps/agent/cmd/cb-agent/main.go` (add `status` subcommand)

**Interfaces:**
- Consumes: `config.StateDir()` (Task 3).
- Produces: `enroll.LoadOrCreateDeviceKey(stateDir string) (*DeviceKey, error)`,
  `DeviceKey{Private [32]byte; Public [32]byte}`, `(*DeviceKey) Fingerprint() string` (32
  lowercase hex chars — same derivation as the Python side's `server_fingerprint()` in Task 2:
  first 16 bytes of SHA-256 over the public key, hex-encoded), `(*DeviceKey) FingerprintGrouped()
  string` (the same 32 hex chars split into 4-char groups joined by `-`, matching spec §2.1's
  display format). Task 8 (`enroll.Run`) and Task 11 (`link.Run`) both call
  `LoadOrCreateDeviceKey`.

- [ ] **Step 1: Write the failing test**

```go
// apps/agent/internal/enroll/keys_test.go
package enroll

import (
	"os"
	"path/filepath"
	"testing"
)

func TestLoadOrCreateDeviceKey_GeneratesOnFirstRun(t *testing.T) {
	dir := t.TempDir()

	key, err := LoadOrCreateDeviceKey(dir)
	if err != nil {
		t.Fatalf("LoadOrCreateDeviceKey() error = %v", err)
	}
	if key.Public == ([32]byte{}) {
		t.Fatal("public key is all-zero, generation likely failed")
	}

	info, err := os.Stat(filepath.Join(dir, "device.key"))
	if err != nil {
		t.Fatalf("device.key not written: %v", err)
	}
	if info.Mode().Perm() != 0o600 {
		t.Errorf("device.key mode = %v, want 0600", info.Mode().Perm())
	}
}

func TestLoadOrCreateDeviceKey_IsStableAcrossCalls(t *testing.T) {
	dir := t.TempDir()

	first, err := LoadOrCreateDeviceKey(dir)
	if err != nil {
		t.Fatalf("first call error = %v", err)
	}
	second, err := LoadOrCreateDeviceKey(dir)
	if err != nil {
		t.Fatalf("second call error = %v", err)
	}
	if first.Public != second.Public {
		t.Error("public key changed across calls — device.key not being reused")
	}
}

func TestFingerprint_Is32LowercaseHexCharsGroupedInFours(t *testing.T) {
	dir := t.TempDir()
	key, err := LoadOrCreateDeviceKey(dir)
	if err != nil {
		t.Fatalf("LoadOrCreateDeviceKey() error = %v", err)
	}

	fp := key.Fingerprint()
	if len(fp) != 32 {
		t.Errorf("Fingerprint() len = %d, want 32", len(fp))
	}

	grouped := key.FingerprintGrouped()
	wantLen := 32 + 7 // 8 groups of 4 chars + 7 separators
	if len(grouped) != wantLen {
		t.Errorf("FingerprintGrouped() len = %d, want %d (got %q)", len(grouped), wantLen, grouped)
	}
}
```

- [ ] **Step 2: Run it to see it fail to compile**

Run: `cd apps/agent && go test ./internal/enroll/...`
Expected: `undefined: LoadOrCreateDeviceKey`.

- [ ] **Step 3: Add the X25519 dependency and implement `keys.go`**

```bash
cd apps/agent && go get golang.org/x/crypto@v0.31.0
```

```go
// apps/agent/internal/enroll/keys.go
package enroll

import (
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"golang.org/x/crypto/curve25519"
)

type DeviceKey struct {
	Private [32]byte
	Public  [32]byte
}

const deviceKeyFilename = "device.key"

// LoadOrCreateDeviceKey reads <stateDir>/device.key if present, else generates
// an X25519 keypair and persists the private key (mode 0600).
func LoadOrCreateDeviceKey(stateDir string) (*DeviceKey, error) {
	path := filepath.Join(stateDir, deviceKeyFilename)

	if data, err := os.ReadFile(path); err == nil {
		if len(data) != 32 {
			return nil, fmt.Errorf("enroll: device.key at %s has length %d, want 32", path, len(data))
		}
		var priv [32]byte
		copy(priv[:], data)
		return deviceKeyFromPrivate(priv)
	} else if !os.IsNotExist(err) {
		return nil, fmt.Errorf("enroll: read %s: %w", path, err)
	}

	var priv [32]byte
	if _, err := rand.Read(priv[:]); err != nil {
		return nil, fmt.Errorf("enroll: generate private key: %w", err)
	}

	if err := os.MkdirAll(stateDir, 0o700); err != nil {
		return nil, fmt.Errorf("enroll: create state dir %s: %w", stateDir, err)
	}
	if err := os.WriteFile(path, priv[:], 0o600); err != nil {
		return nil, fmt.Errorf("enroll: write %s: %w", path, err)
	}

	return deviceKeyFromPrivate(priv)
}

func deviceKeyFromPrivate(priv [32]byte) (*DeviceKey, error) {
	pub, err := curve25519.X25519(priv[:], curve25519.Basepoint)
	if err != nil {
		return nil, fmt.Errorf("enroll: derive public key: %w", err)
	}
	var pubArr [32]byte
	copy(pubArr[:], pub)
	return &DeviceKey{Private: priv, Public: pubArr}, nil
}

// Fingerprint returns 32 lowercase hex chars — the first 16 bytes of SHA-256
// over the public key. Matches app.core.agent_crypto.server_fingerprint()'s
// derivation on the Python side.
func (k *DeviceKey) Fingerprint() string {
	sum := sha256.Sum256(k.Public[:])
	return hex.EncodeToString(sum[:16])
}

// FingerprintGrouped renders Fingerprint() as eight 4-char groups joined by
// "-", the display form shown on stdout and compared against the approval
// screen (spec §2.1).
func (k *DeviceKey) FingerprintGrouped() string {
	fp := k.Fingerprint()
	groups := make([]string, 0, 8)
	for i := 0; i < len(fp); i += 4 {
		groups = append(groups, fp[i:i+4])
	}
	return strings.Join(groups, "-")
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd apps/agent && go test ./internal/enroll/...`
Expected: `ok`.

- [ ] **Step 5: Wire a `status` subcommand that prints the fingerprint**

```go
// apps/agent/cmd/cb-agent/main.go — add to the switch in main() and below runVersion
	case "status":
		runStatus()
```

```go
func runStatus() {
	dir := config.StateDir()
	key, err := enroll.LoadOrCreateDeviceKey(dir)
	if err != nil {
		fmt.Fprintf(os.Stderr, "cb-agent: %v\n", err)
		os.Exit(1)
	}
	fmt.Printf("fingerprint: %s\n", key.FingerprintGrouped())
	fmt.Println("link: not yet implemented (Task 11)")
}
```

Add the two new imports (`circuitbreaker.dev/cb-agent/internal/config`,
`circuitbreaker.dev/cb-agent/internal/enroll`) to `main.go`'s import block.

- [ ] **Step 6: Smoke-test**

Run: `cd apps/agent && go build -o /tmp/cb-agent ./cmd/cb-agent && CB_AGENT_STATE_DIR=/tmp/cb-agent-state /tmp/cb-agent status`
Expected: prints an 8-group hex fingerprint, then the "not yet implemented" line; a second run
prints the same fingerprint (key reused).

- [ ] **Step 7: Commit**

```bash
git add apps/agent/internal/enroll apps/agent/cmd/cb-agent/main.go apps/agent/go.mod apps/agent/go.sum
git commit -m "feat(agent): X25519 device identity and status subcommand"
```

---

### Task 5: Pairing-code lifecycle — `agent_enrollment.py`

**Files:**
- Create: `apps/backend/src/app/services/agent_enrollment.py`
- Test: `apps/backend/tests/services/test_agent_enrollment.py`

**Interfaces:**
- Consumes: `app.core.redis.get_redis()` (`apps/backend/src/app/core/redis.py:113`, returns
  `aioredis.Redis | None`, imported locally inside each function per the existing
  `discovery_service.py:141` convention so it can be monkeypatched per-test).
- Produces: `generate_pairing_code() -> str` (`XXXX-XXXX-XXXX`, Crockford base32),
  `mint_pairing_code(agent_id: int) -> str`, `resolve_pairing_code(code: str) -> int | None`,
  `consume_pairing_code(code: str) -> int | None` (single-use — deletes on read),
  `record_pairing_miss(ip: str) -> None`, `is_pairing_locked_out(ip: str) -> bool`. Task 7
  (`ws_agents.py` `/enroll`) calls `mint_pairing_code`; Task 9 (`agents.py`
  `POST /pairing/lookup`) calls `resolve_pairing_code`/`record_pairing_miss`/
  `is_pairing_locked_out`; the approval flow (Task 9) calls `consume_pairing_code`.

- [ ] **Step 1: Write the failing tests**

```python
# apps/backend/tests/services/test_agent_enrollment.py
from unittest.mock import AsyncMock

import pytest

from app.services import agent_enrollment as svc


def test_generate_pairing_code_format():
    code = svc.generate_pairing_code()
    parts = code.split("-")
    assert len(parts) == 3
    assert all(len(p) == 4 for p in parts)
    assert all(c in svc.CROCKFORD_ALPHABET for p in parts for c in p)


def test_generate_pairing_code_is_random():
    codes = {svc.generate_pairing_code() for _ in range(50)}
    assert len(codes) == 50  # 60 bits of entropy — collisions astronomically unlikely


@pytest.mark.asyncio
async def test_mint_then_resolve_pairing_code(monkeypatch):
    store: dict[str, str] = {}
    redis_client = AsyncMock()
    redis_client.setex.side_effect = lambda k, ttl, v: store.__setitem__(k, v) or True
    redis_client.get.side_effect = lambda k: store.get(k)
    redis_client.delete.side_effect = lambda k: (store.pop(k, None) is not None)
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=redis_client))

    code = await svc.mint_pairing_code(agent_id=42)
    resolved = await svc.resolve_pairing_code(code)

    assert resolved == 42
    redis_client.setex.assert_called_once()
    ttl_arg = redis_client.setex.call_args[0][1]
    assert ttl_arg == svc.PAIRING_CODE_TTL_SECONDS


@pytest.mark.asyncio
async def test_resolve_unknown_code_returns_none(monkeypatch):
    redis_client = AsyncMock()
    redis_client.get.return_value = None
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=redis_client))

    assert await svc.resolve_pairing_code("ZZZZ-ZZZZ-ZZZZ") is None


@pytest.mark.asyncio
async def test_consume_pairing_code_is_single_use(monkeypatch):
    store: dict[str, str] = {}
    redis_client = AsyncMock()
    redis_client.setex.side_effect = lambda k, ttl, v: store.__setitem__(k, v) or True
    redis_client.get.side_effect = lambda k: store.get(k)
    redis_client.delete.side_effect = lambda k: (store.pop(k, None) is not None)
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=redis_client))

    code = await svc.mint_pairing_code(agent_id=7)
    first = await svc.consume_pairing_code(code)
    second = await svc.consume_pairing_code(code)

    assert first == 7
    assert second is None


@pytest.mark.asyncio
async def test_pairing_lockout_after_repeated_misses(monkeypatch):
    counts: dict[str, int] = {}

    async def _incr(key):
        counts[key] = counts.get(key, 0) + 1
        return counts[key]

    redis_client = AsyncMock()
    redis_client.incr.side_effect = _incr
    redis_client.get.side_effect = lambda k: str(counts.get(k, 0)) if k in counts else None
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=redis_client))

    for _ in range(svc._MISS_LIMIT - 1):
        await svc.record_pairing_miss("10.0.0.5")
    assert await svc.is_pairing_locked_out("10.0.0.5") is False

    await svc.record_pairing_miss("10.0.0.5")
    assert await svc.is_pairing_locked_out("10.0.0.5") is True
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `cd apps/backend && pytest tests/services/test_agent_enrollment.py -v`
Expected: `ModuleNotFoundError: No module named 'app.services.agent_enrollment'`.

- [ ] **Step 3: Implement `agent_enrollment.py`**

```python
# apps/backend/src/app/services/agent_enrollment.py
"""Pairing-code lifecycle for agent enrollment — Redis-backed, single-use.

The pairing code is a selector, not a credential: both approval routes require
an authenticated session with a role permitted to approve agents (§2.4 of
specs/2026-07-26-cb-agent-design.md), so a leaked code alone buys an attacker
nothing.
"""

from __future__ import annotations

import hashlib
import logging
import secrets

_logger = logging.getLogger(__name__)

CROCKFORD_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
PAIRING_CODE_BITS = 60
PAIRING_CODE_TTL_SECONDS = 15 * 60

_MISS_LIMIT = 10
_MISS_WINDOW_SECONDS = 15 * 60


def generate_pairing_code() -> str:
    n = secrets.randbits(PAIRING_CODE_BITS)
    chars = []
    for _ in range(12):
        chars.append(CROCKFORD_ALPHABET[n & 0x1F])
        n >>= 5
    chars.reverse()
    raw = "".join(chars)
    return f"{raw[0:4]}-{raw[4:8]}-{raw[8:12]}"


def _hash_code(code: str) -> str:
    normalized = code.strip().upper().replace("-", "")
    return hashlib.sha256(normalized.encode()).hexdigest()


async def mint_pairing_code(agent_id: int) -> str:
    from app.core.redis import get_redis

    code = generate_pairing_code()
    r = await get_redis()
    if r is not None:
        await r.setex(f"agent_pairing:{_hash_code(code)}", PAIRING_CODE_TTL_SECONDS, str(agent_id))
    else:
        _logger.warning("Redis unavailable — minted pairing code will not resolve")
    return code


async def resolve_pairing_code(code: str) -> int | None:
    from app.core.redis import get_redis

    r = await get_redis()
    if r is None:
        return None
    val = await r.get(f"agent_pairing:{_hash_code(code)}")
    return int(val) if val is not None else None


async def consume_pairing_code(code: str) -> int | None:
    """Resolve then delete — makes the code single-use."""
    from app.core.redis import get_redis

    agent_id = await resolve_pairing_code(code)
    if agent_id is not None:
        r = await get_redis()
        if r is not None:
            await r.delete(f"agent_pairing:{_hash_code(code)}")
    return agent_id


async def record_pairing_miss(ip: str) -> None:
    from app.core.redis import get_redis

    r = await get_redis()
    if r is None:
        return
    key = f"agent_pairing_miss:{ip}"
    count = await r.incr(key)
    if count == 1:
        await r.expire(key, _MISS_WINDOW_SECONDS)


async def is_pairing_locked_out(ip: str) -> bool:
    from app.core.redis import get_redis

    r = await get_redis()
    if r is None:
        return False
    count = await r.get(f"agent_pairing_miss:{ip}")
    return count is not None and int(count) >= _MISS_LIMIT
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd apps/backend && pytest tests/services/test_agent_enrollment.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/src/app/services/agent_enrollment.py apps/backend/tests/services/test_agent_enrollment.py
git commit -m "feat(agents): pairing-code lifecycle service"
```

---

### Task 6: Agent CRUD, presence, and host linkage — `agent_registry.py`

**Files:**
- Create: `apps/backend/src/app/services/agent_registry.py`
- Test: `apps/backend/tests/services/test_agent_registry.py`

**Interfaces:**
- Consumes: `Agent`, `AgentCapabilityGrant`, `AgentEvent`, `Hardware` (`app.db.models`, Task 1),
  `app.core.redis.get_redis()`.
- Produces: `create_pending_agent(db, **fields) -> Agent`,
  `get_agent(db, agent_id) -> Agent | None`, `get_agent_by_device_pk(db, device_pk) -> Agent |
  None`, `list_agents(db, *, status=None) -> list[Agent]`,
  `approve_agent(db, agent_id, *, approving_user_id, hardware_id=None, capability_overrides=None)
  -> Agent`, `reject_agent(db, agent_id, *, actor_user_id) -> Agent`,
  `revoke_agent(db, agent_id, *, actor_user_id, reason=None) -> Agent`,
  `set_capability_grants(db, agent_id, grants: dict[str, bool], *, actor_user_id) ->
  list[AgentCapabilityGrant]`, `propose_hardware_match(db, agent: Agent) -> Hardware | None`,
  `record_event(db, agent_id, event_type, *, actor_user_id=None, detail=None) -> AgentEvent`,
  `DEFAULT_CAPABILITY_GRANTS = {"host_telemetry": True, "remote_probe": False,
  "local_discovery": False}`, `async mark_presence_connected(agent_id, worker: str) -> None`,
  `async mark_presence_disconnected(agent_id: int) -> None`,
  `async refresh_presence_heartbeat(db, agent_id: int, worker: str) -> None` (Redis TTL refresh +
  throttled `last_seen_at` write), `async is_agent_online(agent_id: int) -> bool`. Task 7, Task 9,
  Task 12, and Task 15 all import from this module — it is the single place agent state mutates.

- [ ] **Step 1: Write the failing CRUD/grants/host-linkage tests**

```python
# apps/backend/tests/services/test_agent_registry.py
import pytest
from sqlalchemy.exc import NoResultFound

from app.services import agent_registry as svc


def test_create_pending_agent_defaults_to_pending_status(db_session):
    agent = svc.create_pending_agent(
        db_session,
        device_pk="ab" * 32,
        fingerprint="cd" * 16,
        hostname="box1",
        machine_id_hash=None,
        os="linux",
        os_version="6.1",
        arch="amd64",
        agent_version="0.1.0",
        primary_macs=["aa:bb:cc:dd:ee:ff"],
        reported_ip="10.0.0.5",
    )
    assert agent.status == "pending"
    assert agent.id is not None


def test_approve_agent_applies_default_capability_grants(db_session, factories):
    agent = factories.agent(status="pending")
    admin = factories.user(role="admin")

    approved = svc.approve_agent(db_session, agent.id, approving_user_id=admin.id)

    assert approved.status == "active"
    assert approved.approved_by_user_id == admin.id

    from app.db.models import AgentCapabilityGrant
    grants = {
        g.capability: g.enabled
        for g in db_session.query(AgentCapabilityGrant).filter_by(agent_id=agent.id).all()
    }
    assert grants == svc.DEFAULT_CAPABILITY_GRANTS


def test_approve_agent_honors_capability_overrides(db_session, factories):
    agent = factories.agent(status="pending")
    admin = factories.user(role="admin")

    svc.approve_agent(
        db_session, agent.id, approving_user_id=admin.id,
        capability_overrides={"remote_probe": True},
    )

    from app.db.models import AgentCapabilityGrant
    grant = (
        db_session.query(AgentCapabilityGrant)
        .filter_by(agent_id=agent.id, capability="remote_probe")
        .one()
    )
    assert grant.enabled is True


def test_revoke_agent_records_reason_and_actor(db_session, factories):
    agent = factories.agent(status="active")
    admin = factories.user(role="admin")

    revoked = svc.revoke_agent(db_session, agent.id, actor_user_id=admin.id, reason="lost device")

    assert revoked.status == "revoked"
    assert revoked.revoke_reason == "lost device"
    assert revoked.revoked_by_user_id == admin.id


def test_record_event_persists_detail(db_session, factories):
    agent = factories.agent()
    event = svc.record_event(db_session, agent.id, "capability_violation", detail={"type": "probe.result"})
    assert event.event_type == "capability_violation"
    assert event.detail == {"type": "probe.result"}


def test_propose_hardware_match_by_machine_id_hash_beats_mac(db_session, factories):
    from app.db.models import Hardware

    hw_by_mac = Hardware(name="by-mac", mac_address="aa:bb:cc:dd:ee:ff")
    hw_by_machine_id = Hardware(name="by-machine-id")
    db_session.add_all([hw_by_mac, hw_by_machine_id])
    db_session.flush()

    agent = factories.agent(
        machine_id_hash="deadbeef", primary_macs=["aa:bb:cc:dd:ee:ff"],
    )
    # Simulate a machine_id_hash match by monkeypatching the lookup table the
    # service consults — see Step 3's implementation for the exact match order
    # (machine_id_hash -> MAC -> hostname) before finalizing this assertion.
    match = svc.propose_hardware_match(db_session, agent)
    assert match is None or match.id in (hw_by_mac.id, hw_by_machine_id.id)
```

> The `test_propose_hardware_match_by_machine_id_hash_beats_mac` assertion above is deliberately
> loose (`match is None or ...`) because `Hardware` has no `machine_id_hash` column in the current
> schema — confirm this while implementing Step 3 (`grep -n machine_id_hash
> apps/backend/src/app/db/models.py`) and tighten the test once the real match source for
> `machine_id_hash` (likely a join through `hardware_telemetry` or a dedicated column added by a
> future slice) is confirmed. Do not skip this test; narrow it once the source is known.

- [ ] **Step 2: Run the tests to see them fail**

Run: `cd apps/backend && pytest tests/services/test_agent_registry.py -v`
Expected: `ModuleNotFoundError: No module named 'app.services.agent_registry'`.

- [ ] **Step 3: Implement the CRUD/grants/host-linkage half of `agent_registry.py`**

```python
# apps/backend/src/app/services/agent_registry.py
"""Agent CRUD, presence, capability grants, and host linkage.

This module owns all mutation of `agents` / `agent_capability_grants` /
`agent_events`. No collector domain logic lives here — see
specs/2026-07-26-cb-agent-design.md §1.2 on agent_link.py's boundary, which
this module sits directly behind.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.db.models import Agent, AgentCapabilityGrant, AgentEvent, Hardware

_logger = logging.getLogger(__name__)

DEFAULT_CAPABILITY_GRANTS: dict[str, bool] = {
    "host_telemetry": True,
    "remote_probe": False,
    "local_discovery": False,
}


def create_pending_agent(db: Session, **fields: Any) -> Agent:
    agent = Agent(status="pending", **fields)
    db.add(agent)
    db.flush()
    record_event(db, agent.id, "enrolled")
    return agent


def get_agent(db: Session, agent_id: int) -> Agent | None:
    return db.get(Agent, agent_id)


def get_agent_by_device_pk(db: Session, device_pk: str) -> Agent | None:
    return db.execute(select(Agent).where(Agent.device_pk == device_pk)).scalar_one_or_none()


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
    capability_overrides: dict[str, bool] | None = None,
) -> Agent:
    agent = db.get(Agent, agent_id)
    if agent is None:
        raise ValueError(f"agent {agent_id} not found")

    agent.status = "active"
    agent.approved_at = utcnow()
    agent.approved_by_user_id = approving_user_id
    if hardware_id is not None:
        agent.hardware_id = hardware_id

    grants = dict(DEFAULT_CAPABILITY_GRANTS)
    grants.update(capability_overrides or {})
    for capability, enabled in grants.items():
        db.add(
            AgentCapabilityGrant(
                agent_id=agent.id, capability=capability, enabled=enabled,
                granted_by_user_id=approving_user_id,
            )
        )

    record_event(db, agent.id, "approved", actor_user_id=approving_user_id)
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


def revoke_agent(db: Session, agent_id: int, *, actor_user_id: int, reason: str | None = None) -> Agent:
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


def set_capability_grants(
    db: Session, agent_id: int, grants: dict[str, bool], *, actor_user_id: int
) -> list[AgentCapabilityGrant]:
    existing = {
        g.capability: g
        for g in db.execute(
            select(AgentCapabilityGrant).where(AgentCapabilityGrant.agent_id == agent_id)
        ).scalars()
    }
    result = []
    for capability, enabled in grants.items():
        grant = existing.get(capability)
        if grant is None:
            grant = AgentCapabilityGrant(agent_id=agent_id, capability=capability)
            db.add(grant)
        grant.enabled = enabled
        grant.granted_by_user_id = actor_user_id
        grant.granted_at = utcnow()
        result.append(grant)
    record_event(db, agent_id, "capability_changed", actor_user_id=actor_user_id, detail=grants)
    db.flush()
    return result


def propose_hardware_match(db: Session, agent: Agent) -> Hardware | None:
    """Descending-confidence match: machine_id_hash -> MAC -> hostname (spec §3.3)."""
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
        return db.execute(select(Hardware).where(Hardware.name == agent.hostname)).scalar_one_or_none()

    return None


def record_event(
    db: Session, agent_id: int, event_type: str, *, actor_user_id: int | None = None,
    detail: dict | None = None,
) -> AgentEvent:
    event = AgentEvent(agent_id=agent_id, event_type=event_type, actor_user_id=actor_user_id, detail=detail)
    db.add(event)
    db.flush()
    return event
```

> **Verification note for the implementer:** `Hardware.machine_id_hash` is referenced above on
> the assumption a matching column exists or is added; run `grep -n "machine_id_hash\|mac_address"
> apps/backend/src/app/db/models.py` before writing this step. If `Hardware` has no
> `machine_id_hash` column, drop that branch of `propose_hardware_match` for slice 1 (fall through
> to MAC → hostname only) and note the gap in the PR description — adding the column is a
> reasonable candidate for a follow-up migration but is not spec'd here and must not be invented
> silently.

- [ ] **Step 4: Run the CRUD/grants/host-linkage tests to verify they pass**

Run: `cd apps/backend && pytest tests/services/test_agent_registry.py -v`
Expected: 6 passed (after adjusting `propose_hardware_match` per the verification note if
`machine_id_hash` doesn't exist on `Hardware`).

- [ ] **Step 5: Write the failing presence tests**

```python
# apps/backend/tests/services/test_agent_registry.py — append
import json
from unittest.mock import AsyncMock


@pytest.mark.asyncio
async def test_mark_presence_connected_writes_redis_with_ttl(monkeypatch):
    redis_client = AsyncMock()
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=redis_client))

    await svc.mark_presence_connected(agent_id=5, worker="worker-1")

    redis_client.setex.assert_called_once()
    key, ttl, payload = redis_client.setex.call_args[0]
    assert key == "agent:presence:5"
    assert ttl == 60
    assert json.loads(payload)["worker"] == "worker-1"


@pytest.mark.asyncio
async def test_mark_presence_disconnected_deletes_redis_key(monkeypatch):
    redis_client = AsyncMock()
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=redis_client))

    await svc.mark_presence_disconnected(agent_id=5)

    redis_client.delete.assert_called_once_with("agent:presence:5")


@pytest.mark.asyncio
async def test_is_agent_online_reflects_redis_key_presence(monkeypatch):
    redis_client = AsyncMock()
    redis_client.exists.return_value = 1
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=redis_client))

    assert await svc.is_agent_online(5) is True
    redis_client.exists.assert_called_once_with("agent:presence:5")


@pytest.mark.asyncio
async def test_refresh_presence_heartbeat_throttles_postgres_write(db_session, factories, monkeypatch):
    from app.core.time import utcnow

    agent = factories.agent(status="active", last_seen_at=utcnow())
    db_session.flush()
    original_last_seen = agent.last_seen_at

    redis_client = AsyncMock()
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=redis_client))

    await svc.refresh_presence_heartbeat(db_session, agent.id, worker="worker-1")

    redis_client.setex.assert_called_once()
    assert agent.last_seen_at == original_last_seen  # throttled — no write within 60s
```

- [ ] **Step 6: Implement the presence half**

Append to `apps/backend/src/app/services/agent_registry.py`:

```python
import json

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
    if agent.last_seen_at is None or (now - agent.last_seen_at).total_seconds() >= _LAST_SEEN_WRITE_THROTTLE_SECONDS:
        agent.last_seen_at = now
        db.flush()
```

- [ ] **Step 7: Run the full test file to verify everything passes**

Run: `cd apps/backend && pytest tests/services/test_agent_registry.py -v`
Expected: 10 passed.

- [ ] **Step 8: Commit**

```bash
git add apps/backend/src/app/services/agent_registry.py apps/backend/tests/services/test_agent_registry.py
git commit -m "feat(agents): agent CRUD, presence, capability grants, host linkage"
```

---

### Task 7: Unauthenticated enrollment socket — `WS /api/agents/enroll`

This is the first WebSocket route in the codebase to skip session auth (research confirmed no
existing precedent — every current `ws_*.py` router is wrapped in
`dependencies=[Depends(require_auth)]` at `main.py`'s `include_router` call). `ws_agents.py`
therefore exports **two** `APIRouter` instances so `main.py` can gate them differently: an
unauthenticated one for `/enroll` and `/link` (Noise **is** the authentication), and an
authenticated one for `/stream` (added in Task 15).

**Files:**
- Create: `apps/backend/src/app/schemas/agent_frame.py`
- Create: `apps/backend/src/app/api/ws_agents.py`
- Create: `apps/backend/tests/helpers/__init__.py`
- Create: `apps/backend/tests/helpers/agent_noise_client.py`
- Modify: `apps/backend/tests/conftest.py` (add a sync `TestClient`-based `ws_client` fixture — no
  existing test in this repo exercises a WebSocket route; `client` is an async `httpx.AsyncClient`
  over `ASGITransport`, which does not support the WS upgrade)
- Modify: `apps/backend/src/app/main.py` (import + register both `ws_agents` routers)
- Test: `apps/backend/tests/api/test_ws_agents_enroll.py`

**Interfaces:**
- Consumes: `agent_crypto.NoiseIKResponder`, `agent_crypto.get_server_static_keypair`,
  `agent_crypto.check_clock_skew`, `agent_crypto.ClockSkewError` (Task 2);
  `agent_enrollment.mint_pairing_code` (Task 5); `agent_registry.create_pending_agent`,
  `agent_registry.get_agent_by_device_pk`, `agent_registry.get_agent` (Task 6).
- Produces: `AgentFrame` pydantic model (`v`, `type`, `seq`, `ts`, `payload`) in
  `schemas/agent_frame.py` — the Python-side definition of the same envelope Task 3 defined in Go
  (`internal/frame.Frame`), consumed by every later backend agent task. `ws_agents.py` exports
  `unauthenticated_router` (mounted without `Depends(require_auth)`) and `authenticated_router`
  (mounted with it, populated by Task 15). `tests/helpers/agent_noise_client.py` exports
  `TestNoiseInitiator` (`__init__(self, agent_private: bytes, server_public: bytes)`,
  `write_message() -> bytes`, `read_message(self, data: bytes) -> None`,
  `encrypt(self, plaintext: bytes) -> bytes`, `decrypt(self, ciphertext: bytes) -> bytes`) — reused
  by Task 9, Task 10, and Task 12's tests to simulate the agent side of a handshake without
  needing the real Go binary.

- [ ] **Step 1: Define the shared frame schema**

```python
# apps/backend/src/app/schemas/agent_frame.py
"""The agent protocol v1 frame envelope — defined once here and in
apps/agent/internal/frame/frame.go, nowhere else, per
specs/2026-07-26-cb-agent-design.md §1's `agent_link.py` boundary note."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

FRAME_VERSION = 1

# agent -> server
TYPE_HELLO = "hello"
TYPE_HEARTBEAT = "heartbeat"
TYPE_TELEMETRY_HOST = "telemetry.host"
TYPE_PROBE_RESULT = "probe.result"
TYPE_DISCOVERY_FINDING = "discovery.finding"
TYPE_CAPABILITY_VIOLATION = "capability.violation"
TYPE_LOG = "log"

# server -> agent
TYPE_HELLO_ACK = "hello.ack"
TYPE_CAPABILITIES_SET = "capabilities.set"
TYPE_PROBE_ASSIGN = "probe.assign"
TYPE_DISCOVERY_REQUEST = "discovery.request"
TYPE_KEY_ROTATE = "key.rotate"
TYPE_UPDATE = "update"
TYPE_DISCONNECT = "disconnect"
TYPE_PING = "ping"


class AgentFrame(BaseModel):
    v: int = FRAME_VERSION
    type: str
    seq: int = 0
    ts: datetime
    payload: dict[str, Any] = Field(default_factory=dict)
```

- [ ] **Step 2: Write the test-only Noise initiator helper**

```python
# apps/backend/tests/helpers/agent_noise_client.py
"""Python-side Noise IK *initiator*, used only by tests to simulate the Go
agent's handshake behavior against the real ws_agents.py responder — see
app.core.agent_crypto.NoiseIKResponder for the server-side half."""

from __future__ import annotations

from dissononce.cipher.chachapoly import ChaChaPolyCipher
from dissononce.dh.x25519.x25519 import X25519DH
from dissononce.hash.sha256 import SHA256Hash
from dissononce.processing.handshakepatterns.interactive.IK import IKHandshakePattern
from dissononce.processing.impl.cipherstate import CipherState
from dissononce.processing.impl.handshakestate import HandshakeState
from dissononce.processing.impl.symmetricstate import SymmetricState

from app.core.agent_crypto import _keypair_from_private


class TestNoiseInitiator:
    def __init__(self, agent_private: bytes, server_public: bytes) -> None:
        self._state = HandshakeState(
            SymmetricState(CipherState(ChaChaPolyCipher()), SHA256Hash()), X25519DH(),
        )
        self._state.initialize(
            IKHandshakePattern(), True, b"",
            s=_keypair_from_private(agent_private),
            rs=server_public,
        )
        self._ciphers: tuple[CipherState, CipherState] | None = None

    def write_message(self) -> bytes:
        buf = bytearray()
        self._state.write_message(b"", buf)
        return bytes(buf)

    def read_message(self, data: bytes) -> None:
        payload = bytearray()
        self._ciphers = self._state.read_message(data, payload)

    def encrypt(self, plaintext: bytes) -> bytes:
        send_cipher, _ = self._ciphers
        return send_cipher.encrypt_with_ad(b"", plaintext)

    def decrypt(self, ciphertext: bytes) -> bytes:
        _, recv_cipher = self._ciphers
        return recv_cipher.decrypt_with_ad(b"", ciphertext)
```

> Same verification note as Task 2 Step 4 applies — confirm exact `dissononce` call signatures
> against the installed version; both files must use identical conventions since they perform the
> two halves of one handshake.

- [ ] **Step 3: Add the sync WebSocket test client fixture**

```python
# apps/backend/tests/conftest.py — add near the `client` fixture
@pytest.fixture
def ws_client(db_session):
    """Sync TestClient for WebSocket routes — httpx's ASGITransport (used by
    the async `client` fixture) does not support the WS upgrade."""
    from starlette.testclient import TestClient

    from app.db.session import get_db
    from app.main import app

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as tc:
        yield tc
    app.dependency_overrides.pop(get_db, None)
```

- [ ] **Step 4: Write the failing enrollment test**

```python
# apps/backend/tests/api/test_ws_agents_enroll.py
from datetime import UTC, datetime

from app.core.agent_crypto import get_server_static_keypair
from app.services import agent_enrollment
from tests.helpers.agent_noise_client import TestNoiseInitiator


def _make_hello_frame_bytes(**overrides) -> bytes:
    import json

    payload = {
        "hostname": "test-box",
        "machine_id_hash": None,
        "os": "linux",
        "os_version": "6.1",
        "arch": "amd64",
        "agent_version": "0.1.0",
        "primary_macs": ["aa:bb:cc:dd:ee:ff"],
    }
    payload.update(overrides)
    frame = {
        "v": 1, "type": "hello", "seq": 0,
        "ts": datetime.now(UTC).isoformat(), "payload": payload,
    }
    return json.dumps(frame).encode()


def test_enroll_creates_pending_agent_and_returns_pairing_code(db_session, ws_client):
    import secrets

    _, server_pub = get_server_static_keypair()
    agent_priv = secrets.token_bytes(32)

    with ws_client.websocket_connect("/api/v1/agents/enroll") as ws:
        initiator = TestNoiseInitiator(agent_priv, server_pub)
        ws.send_bytes(initiator.write_message())
        initiator.read_message(ws.receive_bytes())

        ws.send_bytes(initiator.encrypt(_make_hello_frame_bytes()))

        ack_ct = ws.receive_bytes()
        ack_pt = initiator.decrypt(ack_ct)

    import json

    ack = json.loads(ack_pt)
    assert ack["type"] == "hello.ack"
    assert "pairing_code" in ack["payload"]
    assert len(ack["payload"]["pairing_code"].split("-")) == 3

    from app.db.models import Agent

    agent = db_session.query(Agent).filter_by(status="pending").one()
    assert agent.hostname == "test-box"


def test_enroll_rejects_stale_handshake_timestamp(db_session, ws_client):
    import secrets
    from datetime import timedelta

    _, server_pub = get_server_static_keypair()
    agent_priv = secrets.token_bytes(32)

    with ws_client.websocket_connect("/api/v1/agents/enroll") as ws:
        initiator = TestNoiseInitiator(agent_priv, server_pub)
        ws.send_bytes(initiator.write_message())
        initiator.read_message(ws.receive_bytes())

        stale_ts = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
        import json

        payload = {"hostname": "test-box", "os": "linux", "arch": "amd64", "agent_version": "0.1.0"}
        frame = {"v": 1, "type": "hello", "seq": 0, "ts": stale_ts, "payload": payload}
        ws.send_bytes(initiator.encrypt(json.dumps(frame).encode()))

        # Server sends a clock-skew error frame before closing 1008.
        err_ct = ws.receive_bytes()
        err = json.loads(initiator.decrypt(err_ct))
        assert err["payload"]["error"] == "clock_skew"
```

- [ ] **Step 5: Run the tests to see them fail**

Run: `cd apps/backend && pytest tests/api/test_ws_agents_enroll.py -v`
Expected: `ModuleNotFoundError: No module named 'app.api.ws_agents'` (or a 404 once the route simply
doesn't exist yet).

- [ ] **Step 6: Implement `ws_agents.py`'s enroll endpoint**

```python
# apps/backend/src/app/api/ws_agents.py
"""Agent-facing WebSocket endpoints. /enroll and /link bypass session auth
entirely — the Noise handshake IS their authentication (spec §3.5). /stream
(added in Task 15) is session-authenticated and carries presence to the UI.

No domain logic lives here beyond decode/dispatch — see agent_link.py's
boundary note in specs/2026-07-26-cb-agent-design.md §1.2.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.agent_crypto import (
    ClockSkewError,
    NoiseIKResponder,
    check_clock_skew,
    get_server_static_keypair,
)
from app.db.session import SessionLocal
from app.schemas.agent_frame import TYPE_HELLO_ACK
from app.services import agent_enrollment, agent_registry

_logger = logging.getLogger(__name__)

unauthenticated_router = APIRouter()
authenticated_router = APIRouter()

_HANDSHAKE_TIMEOUT_SECONDS = 10.0


def _ack_bytes(responder: NoiseIKResponder, payload: dict) -> bytes:
    frame = {
        "v": 1, "type": TYPE_HELLO_ACK, "seq": 0,
        "ts": datetime.utcnow().isoformat(), "payload": payload,
    }
    return responder.encrypt(json.dumps(frame).encode())


def _error_bytes(responder: NoiseIKResponder, error: str) -> bytes:
    return _ack_bytes(responder, {"error": error})


@unauthenticated_router.websocket("/enroll")
async def enroll_stream(websocket: WebSocket) -> None:
    await websocket.accept()
    client_ip = websocket.client.host if websocket.client else "unknown"

    try:
        handshake_msg = await asyncio.wait_for(
            websocket.receive_bytes(), timeout=_HANDSHAKE_TIMEOUT_SECONDS
        )
    except (TimeoutError, WebSocketDisconnect):
        await websocket.close(code=1008)
        return

    server_priv, _ = get_server_static_keypair()
    responder = NoiseIKResponder(server_priv)
    try:
        response = responder.read_message(handshake_msg)
    except Exception:
        _logger.info("agent enroll: handshake failed from %s", client_ip)
        await websocket.close(code=1008)
        return
    await websocket.send_bytes(response)

    try:
        hello_ct = await asyncio.wait_for(
            websocket.receive_bytes(), timeout=_HANDSHAKE_TIMEOUT_SECONDS
        )
        hello = json.loads(responder.decrypt(hello_ct))
    except Exception:
        await websocket.close(code=1008)
        return

    try:
        check_clock_skew(datetime.fromisoformat(hello["ts"]).replace(tzinfo=None))
    except ClockSkewError:
        await websocket.send_bytes(_error_bytes(responder, "clock_skew"))
        await websocket.close(code=1008)
        return

    payload = hello.get("payload", {})
    device_pk_hex = responder.remote_static().hex()
    fingerprint = hashlib.sha256(bytes.fromhex(device_pk_hex)).hexdigest()[:32]

    with SessionLocal() as db:
        existing = agent_registry.get_agent_by_device_pk(db, device_pk_hex)
        if existing is not None and existing.status == "revoked":
            await websocket.close(code=1008)
            return
        if existing is not None and existing.status == "active":
            await websocket.send_bytes(
                _ack_bytes(responder, {"already_enrolled": True, "status": "active"})
            )
            await websocket.close(code=1000)
            return
        if existing is not None and existing.status == "pending":
            agent = existing
        else:
            agent = agent_registry.create_pending_agent(
                db,
                device_pk=device_pk_hex,
                fingerprint=fingerprint,
                hostname=payload.get("hostname"),
                machine_id_hash=payload.get("machine_id_hash"),
                os=payload.get("os"),
                os_version=payload.get("os_version"),
                arch=payload.get("arch"),
                agent_version=payload.get("agent_version"),
                primary_macs=payload.get("primary_macs"),
                reported_ip=client_ip,
            )
        db.commit()
        agent_id = agent.id
        code = await agent_enrollment.mint_pairing_code(agent_id)

    await websocket.send_bytes(
        _ack_bytes(
            responder,
            {"agent_id": agent_id, "pairing_code": code, "magic_link": f"/agents/enroll?c={code}"},
        )
    )

    # Hold the connection, polling for the approval decision every 2s (fast enough that
    # "click approve, done" in §5.2 doesn't visibly lag) and re-minting the pairing code only
    # when its 15-minute TTL actually lapses.
    _POLL_SECONDS = 2.0
    last_minted_at = datetime.utcnow()
    while True:
        try:
            await asyncio.wait_for(websocket.receive_bytes(), timeout=_POLL_SECONDS)
        except TimeoutError:
            with SessionLocal() as db:
                fresh = agent_registry.get_agent(db, agent_id)
                if fresh is None:
                    break
                if fresh.status != "pending":
                    await websocket.send_bytes(
                        _ack_bytes(responder, {"agent_id": agent_id, "status": fresh.status})
                    )
                    await websocket.close(code=1000)
                    return
                elapsed = (datetime.utcnow() - last_minted_at).total_seconds()
                if elapsed >= agent_enrollment.PAIRING_CODE_TTL_SECONDS:
                    code = await agent_enrollment.mint_pairing_code(agent_id)
                    last_minted_at = datetime.utcnow()
                    await websocket.send_bytes(
                        _ack_bytes(responder, {"agent_id": agent_id, "pairing_code": code})
                    )
        except WebSocketDisconnect:
            break
```

- [ ] **Step 7: Wire both routers into `main.py`**

```python
# apps/backend/src/app/main.py — imports section, near the other ws_* imports
from app.api.ws_agents import authenticated_router as ws_agents_authenticated_router
from app.api.ws_agents import unauthenticated_router as ws_agents_unauthenticated_router
```

```python
# apps/backend/src/app/main.py — registration section, near the other app.include_router(...) calls
app.include_router(
    ws_agents_unauthenticated_router,
    prefix=f"{_V1}/agents",
    tags=["agents-ws"],
)
app.include_router(
    ws_agents_authenticated_router,
    prefix=f"{_V1}/agents",
    tags=["agents-ws"],
    dependencies=[Depends(require_auth)],
)
```

Note the deliberate **absence** of `dependencies=[Depends(require_auth)]` on the first
`include_router` call — this is the one router in the codebase that must not have it, since the
Noise handshake is its authentication.

- [ ] **Step 8: Run the tests to verify they pass**

Run: `cd apps/backend && pytest tests/api/test_ws_agents_enroll.py -v`
Expected: 2 passed. If the `dissononce` API names from Task 2/Task 7-Step-2 don't match the
installed version, fix the call sites in both `agent_crypto.py` and `agent_noise_client.py`
together — they must stay in lockstep since they're the two ends of one handshake.

- [ ] **Step 9: Commit**

```bash
git add apps/backend/src/app/schemas/agent_frame.py apps/backend/src/app/api/ws_agents.py \
        apps/backend/src/app/main.py apps/backend/tests/conftest.py \
        apps/backend/tests/helpers apps/backend/tests/api/test_ws_agents_enroll.py
git commit -m "feat(agents): unauthenticated WS /api/agents/enroll endpoint"
```

---

### Task 8: Go Noise initiator and the enroll dial — `noiseconn`, `internal/enroll.Run`

**Files:**
- Create: `apps/agent/internal/noiseconn/noiseconn.go`
- Create: `apps/agent/internal/noiseconn/noiseconn_test.go`
- Create: `apps/agent/internal/enroll/enroll.go`
- Modify: `apps/agent/cmd/cb-agent/main.go` (add the `enroll` subcommand)

**Interfaces:**
- Consumes: `enroll.LoadOrCreateDeviceKey` (Task 4), `frame.Frame`/`frame.Encode`/`frame.Decode`
  (Task 3), `config.Config` (Task 3).
- Produces: `noiseconn.NewInitiator(localPriv, localPub, remotePub [32]byte) (*Session, error)`,
  `(*Session) WriteHandshakeMessage() ([]byte, error)`,
  `(*Session) ReadHandshakeMessage(data []byte) error`,
  `(*Session) Encrypt(plaintext []byte) []byte`, `(*Session) Decrypt(ciphertext []byte) ([]byte,
  error)` — Task 11 (`internal/link`) reuses this same package for the `/link` dial.
  `enroll.Run(cfg *config.Config, key *DeviceKey, agentVersion string) error` — dials `/enroll`,
  completes the handshake, sends `hello`, prints the pairing code/magic link/fingerprint, and
  blocks until the server reports a non-pending status, returning `nil` on `"active"` (caller then
  starts the link loop — Task 11) or an error on `"rejected"`/`"revoked"`.

- [ ] **Step 1: Add the Noise and WebSocket dependencies**

```bash
cd apps/agent && go get github.com/flynn/noise@v1.1.0 github.com/gorilla/websocket@v1.5.3
```

- [ ] **Step 2: Write the failing round-trip test for `noiseconn`**

```go
// apps/agent/internal/noiseconn/noiseconn_test.go
package noiseconn

import (
	"bytes"
	"crypto/rand"
	"testing"

	"github.com/flynn/noise"
)

func generateKeypair(t *testing.T) (priv, pub [32]byte) {
	t.Helper()
	dhKey, err := noise.DH25519.GenerateKeypair(rand.Reader)
	if err != nil {
		t.Fatalf("GenerateKeypair() error = %v", err)
	}
	copy(priv[:], dhKey.Private)
	copy(pub[:], dhKey.Public)
	return priv, pub
}

// newTestResponder builds a bare noise.HandshakeState in the responder role,
// standing in for the Python agent_crypto.NoiseIKResponder this initiator
// will really talk to (proven in Task 10's cross-language conformance test).
func newTestResponder(t *testing.T, priv, pub [32]byte) *noise.HandshakeState {
	t.Helper()
	cs := noise.NewCipherSuite(noise.DH25519, noise.CipherChaChaPoly, noise.HashSHA256)
	hs, err := noise.NewHandshakeState(noise.Config{
		CipherSuite:   cs,
		Pattern:       noise.HandshakeIK,
		Initiator:     false,
		StaticKeypair: noise.DHKey{Private: priv[:], Public: pub[:]},
	})
	if err != nil {
		t.Fatalf("NewHandshakeState() error = %v", err)
	}
	return hs
}

func TestInitiator_CompletesHandshakeAndExchangesTransportMessage(t *testing.T) {
	serverPriv, serverPub := generateKeypair(t)
	agentPriv, agentPub := generateKeypair(t)

	initiator, err := NewInitiator(agentPriv, agentPub, serverPub)
	if err != nil {
		t.Fatalf("NewInitiator() error = %v", err)
	}

	responder := newTestResponder(t, serverPriv, serverPub)

	msg1, err := initiator.WriteHandshakeMessage()
	if err != nil {
		t.Fatalf("WriteHandshakeMessage() error = %v", err)
	}

	if _, err := responder.ReadMessage(nil, msg1); err != nil {
		t.Fatalf("responder.ReadMessage() error = %v", err)
	}
	msg2, respSend, respRecv, err := responder.WriteMessage(nil, nil)
	if err != nil {
		t.Fatalf("responder.WriteMessage() error = %v", err)
	}

	if err := initiator.ReadHandshakeMessage(msg2); err != nil {
		t.Fatalf("ReadHandshakeMessage() error = %v", err)
	}

	ct := initiator.Encrypt([]byte("hello from agent"))
	pt, err := respSend.Decrypt(nil, nil, ct)
	// respSend is the responder's send cipher; per Noise's directional
	// convention the initiator's Encrypt and the responder's matching
	// decrypt cipher must be the SAME direction's CipherState (c1, the
	// initiator->responder cipher). If this decrypt fails with an auth
	// error, swap which of respSend/respRecv is used here — the flynn/noise
	// c1/c2 return order needs confirming against the installed version,
	// exactly as app.core.agent_crypto's dissononce equivalent does on the
	// Python side (Task 2, Step 6's note).
	if err != nil {
		t.Fatalf("responder decrypt error = %v", err)
	}
	if !bytes.Equal(pt, []byte("hello from agent")) {
		t.Errorf("decrypted = %q, want %q", pt, "hello from agent")
	}
	_ = respRecv
}
```

- [ ] **Step 3: Run it to see it fail to compile**

Run: `cd apps/agent && go test ./internal/noiseconn/...`
Expected: `undefined: NewInitiator`.

- [ ] **Step 4: Implement `noiseconn`**

```go
// apps/agent/internal/noiseconn/noiseconn.go
package noiseconn

import (
	"fmt"

	"github.com/flynn/noise"
)

// Session wraps a Noise_IK_25519_ChaChaPoly_SHA256 handshake in the
// initiator role — the agent's role per spec §2.2. The responder counterpart
// is app.core.agent_crypto.NoiseIKResponder on the Python side.
type Session struct {
	hs   *noise.HandshakeState
	send *noise.CipherState
	recv *noise.CipherState
}

func NewInitiator(localPriv, localPub, remotePub [32]byte) (*Session, error) {
	cs := noise.NewCipherSuite(noise.DH25519, noise.CipherChaChaPoly, noise.HashSHA256)
	hs, err := noise.NewHandshakeState(noise.Config{
		CipherSuite:   cs,
		Pattern:       noise.HandshakeIK,
		Initiator:     true,
		StaticKeypair: noise.DHKey{Private: localPriv[:], Public: localPub[:]},
		PeerStatic:    remotePub[:],
	})
	if err != nil {
		return nil, fmt.Errorf("noiseconn: new handshake state: %w", err)
	}
	return &Session{hs: hs}, nil
}

func (s *Session) WriteHandshakeMessage() ([]byte, error) {
	msg, _, _, err := s.hs.WriteMessage(nil, nil)
	if err != nil {
		return nil, fmt.Errorf("noiseconn: write handshake message: %w", err)
	}
	return msg, nil
}

func (s *Session) ReadHandshakeMessage(data []byte) error {
	_, send, recv, err := s.hs.ReadMessage(nil, data)
	if err != nil {
		return fmt.Errorf("noiseconn: read handshake message: %w", err)
	}
	s.send, s.recv = send, recv
	return nil
}

func (s *Session) Encrypt(plaintext []byte) []byte {
	return s.send.Encrypt(nil, nil, plaintext)
}

func (s *Session) Decrypt(ciphertext []byte) ([]byte, error) {
	pt, err := s.recv.Decrypt(nil, nil, ciphertext)
	if err != nil {
		return nil, fmt.Errorf("noiseconn: decrypt: %w", err)
	}
	return pt, nil
}
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd apps/agent && go test ./internal/noiseconn/... -v`
Expected: `PASS`. If it fails on `respSend.Decrypt` with an authentication error specifically (not a
compile error), swap `respSend`/`respRecv` in the test per the comment in Step 2 — this is the
`c1`/`c2` directional-convention risk flagged for the Python side too.

- [ ] **Step 6: Write the failing enroll test**

This test dials a real `httptest.Server` wrapping a minimal Go stand-in for the Python responder
(a full Go<->Python interop dial is Task 10's job; this proves `enroll.Run`'s client-side
behavior in isolation, the same layering Task 7's test used on the Python side).

```go
// apps/agent/internal/enroll/enroll_test.go
package enroll

import (
	"encoding/hex"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/gorilla/websocket"

	"circuitbreaker.dev/cb-agent/internal/config"
)

func TestRun_PrintsPairingCodeAndReturnsOnActive(t *testing.T) {
	serverPriv, serverPub := generateTestKeypair(t)

	upgrader := websocket.Upgrader{}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			t.Fatalf("upgrade error: %v", err)
		}
		defer conn.Close()

		responder := newTestResponderSession(t, serverPriv, serverPub)

		_, msg1, err := conn.ReadMessage()
		if err != nil {
			t.Fatalf("read handshake msg1: %v", err)
		}
		msg2, err := responder.ReadHandshakeMessage(msg1)
		if err != nil {
			t.Fatalf("responder handshake: %v", err)
		}
		if err := conn.WriteMessage(websocket.BinaryMessage, msg2); err != nil {
			t.Fatalf("write handshake msg2: %v", err)
		}

		_, helloCt, err := conn.ReadMessage()
		if err != nil {
			t.Fatalf("read hello: %v", err)
		}
		if _, err := responder.Decrypt(helloCt); err != nil {
			t.Fatalf("decrypt hello: %v", err)
		}

		ack := map[string]any{
			"v": 1, "type": "hello.ack", "seq": 0, "ts": time.Now().UTC(),
			"payload": map[string]any{"agent_id": 1, "pairing_code": "ABCD-EFGH-JKMN"},
		}
		ackBytes, _ := json.Marshal(ack)
		conn.WriteMessage(websocket.BinaryMessage, responder.Encrypt(ackBytes))

		final := map[string]any{
			"v": 1, "type": "hello.ack", "seq": 0, "ts": time.Now().UTC(),
			"payload": map[string]any{"agent_id": 1, "status": "active"},
		}
		finalBytes, _ := json.Marshal(final)
		conn.WriteMessage(websocket.BinaryMessage, responder.Encrypt(finalBytes))
	}))
	defer srv.Close()

	wsURL := "ws" + strings.TrimPrefix(srv.URL, "http")
	dir := t.TempDir()
	key, err := LoadOrCreateDeviceKey(dir)
	if err != nil {
		t.Fatalf("LoadOrCreateDeviceKey() error = %v", err)
	}

	cfg := &config.Config{ServerURL: wsURL, ServerStaticPK: hex.EncodeToString(serverPub[:])}
	if err := Run(cfg, key, "0.1.0-test"); err != nil {
		t.Fatalf("Run() error = %v, want nil (status=active)", err)
	}
}
```

> This test needs a `newTestResponderSession` helper mirroring `noiseconn.Session` but in the
> responder role, plus `generateTestKeypair` — both small enough to define locally in
> `enroll_test.go` (mirroring `noiseconn_test.go`'s `newTestResponder`/`generateKeypair`, adjusted
> for the responder's `Encrypt`/`Decrypt`/`ReadHandshakeMessage` shape). Write them as
> unexported test helpers before running this test; they are direct analogues of
> `noiseconn.Session`, just wired for `Initiator: false`.

- [ ] **Step 7: Run it to see it fail to compile**

Run: `cd apps/agent && go test ./internal/enroll/...`
Expected: `undefined: Run`.

- [ ] **Step 8: Implement `enroll.Run`**

```go
// apps/agent/internal/enroll/enroll.go
package enroll

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"net/url"
	"os"
	"strings"
	"time"

	"github.com/gorilla/websocket"

	"circuitbreaker.dev/cb-agent/internal/config"
	"circuitbreaker.dev/cb-agent/internal/frame"
	"circuitbreaker.dev/cb-agent/internal/noiseconn"
)

// Run dials WS /api/agents/enroll, completes the Noise IK handshake, sends
// the hello frame, prints the pairing code / magic link / fingerprint to
// stdout, and blocks until the server reports the agent is no longer
// pending. Returns nil once status is "active" (caller proceeds to
// internal/link.Run); returns an error for "rejected" or "revoked".
func Run(cfg *config.Config, key *DeviceKey, agentVersion string) error {
	remotePub, err := hex.DecodeString(cfg.ServerStaticPK)
	if err != nil || len(remotePub) != 32 {
		return fmt.Errorf("enroll: invalid server_static_pk in config: %w", err)
	}
	var remotePubArr [32]byte
	copy(remotePubArr[:], remotePub)

	session, err := noiseconn.NewInitiator(key.Private, key.Public, remotePubArr)
	if err != nil {
		return fmt.Errorf("enroll: %w", err)
	}

	u, err := url.Parse(cfg.ServerURL)
	if err != nil {
		return fmt.Errorf("enroll: invalid server_url: %w", err)
	}
	u.Scheme = strings.Replace(u.Scheme, "http", "ws", 1)
	u.Path = "/api/v1/agents/enroll"

	conn, _, err := websocket.DefaultDialer.Dial(u.String(), nil)
	if err != nil {
		return fmt.Errorf("enroll: dial %s: %w", u.String(), err)
	}
	defer conn.Close()

	msg1, err := session.WriteHandshakeMessage()
	if err != nil {
		return fmt.Errorf("enroll: %w", err)
	}
	if err := conn.WriteMessage(websocket.BinaryMessage, msg1); err != nil {
		return fmt.Errorf("enroll: send handshake message: %w", err)
	}

	_, msg2, err := conn.ReadMessage()
	if err != nil {
		return fmt.Errorf("enroll: read handshake response: %w", err)
	}
	if err := session.ReadHandshakeMessage(msg2); err != nil {
		return fmt.Errorf("enroll: %w", err)
	}

	hostname, _ := os.Hostname()
	helloPayload := map[string]any{
		"hostname":      hostname,
		"machine_id_hash": readMachineIDHash(),
		"os":            "linux",
		"os_version":    "",
		"arch":          runtimeArch(),
		"agent_version": agentVersion,
		"primary_macs":  []string{},
	}
	helloFrame := frame.Frame{V: 1, Type: frame.TypeHello, Seq: 0, TS: time.Now().UTC()}
	helloFrame.Payload, _ = json.Marshal(helloPayload)
	helloBytes, err := frame.Encode(helloFrame)
	if err != nil {
		return fmt.Errorf("enroll: %w", err)
	}
	if err := conn.WriteMessage(websocket.BinaryMessage, session.Encrypt(helloBytes)); err != nil {
		return fmt.Errorf("enroll: send hello: %w", err)
	}

	fp := key.FingerprintGrouped()
	fmt.Printf("device fingerprint: %s\n", fp)
	fmt.Println("compare this fingerprint against the one shown on the approval screen")

	for {
		_, ct, err := conn.ReadMessage()
		if err != nil {
			return fmt.Errorf("enroll: connection closed while awaiting approval: %w", err)
		}
		pt, err := session.Decrypt(ct)
		if err != nil {
			return fmt.Errorf("enroll: %w", err)
		}
		f, err := frame.Decode(pt)
		if err != nil {
			return fmt.Errorf("enroll: %w", err)
		}
		var payload map[string]any
		if err := json.Unmarshal(f.Payload, &payload); err != nil {
			return fmt.Errorf("enroll: %w", err)
		}
		if code, ok := payload["pairing_code"].(string); ok {
			fmt.Printf("pairing code: %s\n", code)
			link, _ := payload["magic_link"].(string)
			if link != "" {
				fmt.Printf("magic link:   %s%s\n", cfg.ServerURL, link)
			}
			continue
		}
		status, _ := payload["status"].(string)
		switch status {
		case "active":
			fmt.Println("approved — connecting")
			return nil
		case "rejected":
			return errors.New("enroll: enrollment was rejected")
		case "revoked":
			return errors.New("enroll: agent was revoked")
		}
	}
}

func readMachineIDHash() string {
	data, err := os.ReadFile("/etc/machine-id")
	if err != nil {
		data, err = os.ReadFile("/var/lib/dbus/machine-id")
		if err != nil {
			return ""
		}
	}
	sum := sha256.Sum256(data)
	return hex.EncodeToString(sum[:])
}

func runtimeArch() string {
	// Populated properly via runtime.GOARCH; kept as a named function so
	// Task 21's cross-compile step has one obvious place to verify arch
	// reporting for both amd64 and arm64 builds.
	return goArch()
}
```

```go
// apps/agent/internal/enroll/arch.go
package enroll

import "runtime"

func goArch() string { return runtime.GOARCH }
```

- [ ] **Step 9: Run the enroll test to verify it passes**

Run: `cd apps/agent && go test ./internal/enroll/... -v`
Expected: `PASS`.

- [ ] **Step 10: Wire the `enroll` subcommand into the CLI**

```go
// apps/agent/cmd/cb-agent/main.go — add to the switch in main()
	case "enroll":
		runEnroll()
```

```go
func runEnroll() {
	cfg, err := config.Load("/etc/circuit-breaker/agent.toml")
	if err != nil {
		fmt.Fprintf(os.Stderr, "cb-agent: %v\n", err)
		os.Exit(1)
	}
	key, err := enroll.LoadOrCreateDeviceKey(config.StateDir())
	if err != nil {
		fmt.Fprintf(os.Stderr, "cb-agent: %v\n", err)
		os.Exit(1)
	}
	if err := enroll.Run(cfg, key, AgentVersion); err != nil {
		fmt.Fprintf(os.Stderr, "cb-agent: %v\n", err)
		os.Exit(1)
	}
}
```

- [ ] **Step 11: Build the binary end to end**

Run: `cd apps/agent && go build -o /tmp/cb-agent ./cmd/cb-agent && /tmp/cb-agent version`
Expected: builds cleanly (the `enroll` subcommand needs a running server to exercise manually —
Task 10 proves it against the real Python responder).

- [ ] **Step 12: Commit**

```bash
git add apps/agent/internal/noiseconn apps/agent/internal/enroll apps/agent/cmd/cb-agent/main.go \
        apps/agent/go.mod apps/agent/go.sum
git commit -m "feat(agent): Noise IK initiator and the enroll dial"
```

---

### Task 9: Fleet REST API — `agents.py`

Presence/online status is deliberately **not** computed inline here — following the
`MonitorsPage`/`useMonitorStream` pattern (REST fetch + a live WS overlay merged client-side,
research item 8), REST responses carry persisted fields only; live status comes from
`WS /api/agents/stream` (Task 15) merged in the frontend (Task 18-19).

**Files:**
- Create: `apps/backend/src/app/schemas/agents.py`
- Create: `apps/backend/src/app/api/agents.py`
- Modify: `apps/backend/src/app/main.py` (import + register `agents_router`)
- Test: `apps/backend/tests/api/test_agents_api.py`

**Interfaces:**
- Consumes: everything in `agent_registry.py` (Task 6) and
  `agent_enrollment.consume_pairing_code` / `record_pairing_miss` / `is_pairing_locked_out`
  (Task 5, single-use — see Task 5's interface note); `app.core.rbac.require_role`;
  `app.core.rate_limit.limiter` / `get_limit`
  (`apps/backend/src/app/core/rate_limit.py:16`, used exactly as `api/auth.py:96` does).
- Produces: `agents_router` (`APIRouter`), mounted at `{_V1}/agents` in `main.py`. No later slice-1
  task imports from this module — it is a leaf.

- [ ] **Step 1: Write the schemas**

```python
# apps/backend/src/app/schemas/agents.py
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class AgentSummary(BaseModel):
    id: int
    name: str | None
    hostname: str | None
    status: str
    os: str | None
    arch: str | None
    agent_version: str | None
    fingerprint: str
    hardware_id: int | None
    last_seen_at: datetime | None

    model_config = {"from_attributes": True}


class AgentRead(AgentSummary):
    device_pk: str
    machine_id_hash: str | None
    reported_ip: str | None
    tenant_id: int | None
    notes: str | None
    enrolled_at: datetime
    approved_at: datetime | None
    connected_since: datetime | None
    capabilities: dict[str, bool] = {}


class AgentPatch(BaseModel):
    name: str | None = None
    notes: str | None = None
    hardware_id: int | None = None


class AgentEventRead(BaseModel):
    id: int
    event_type: str
    actor_user_id: int | None
    detail: dict[str, Any] | None
    created_at: datetime

    model_config = {"from_attributes": True}


class PairingLookupRequest(BaseModel):
    code: str


class PairingLookupResponse(BaseModel):
    agent_id: int
    hostname: str | None
    os: str | None
    arch: str | None
    fingerprint: str
    proposed_hardware_id: int | None
    proposed_hardware_name: str | None
    duplicate_machine_id: bool


class ApproveRequest(BaseModel):
    hardware_id: int | None = None
    capabilities: dict[str, bool] | None = None


class RevokeRequest(BaseModel):
    reason: str | None = None


class CapabilitiesUpdateRequest(BaseModel):
    capabilities: dict[str, bool]
```

- [ ] **Step 2: Write the failing tests**

```python
# apps/backend/tests/api/test_agents_api.py
import pytest


@pytest.mark.asyncio
async def test_list_agents_requires_viewer_auth(client):
    resp = await client.get("/api/v1/agents/")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_list_agents_returns_summaries(client, factories, viewer_headers):
    factories.agent(status="active", hostname="box1")
    factories.agent(status="pending", hostname="box2")

    resp = await client.get("/api/v1/agents/", headers=viewer_headers)
    assert resp.status_code == 200
    hostnames = {a["hostname"] for a in resp.json()}
    assert hostnames == {"box1", "box2"}


@pytest.mark.asyncio
async def test_pending_endpoint_only_returns_pending(client, factories, viewer_headers):
    factories.agent(status="active", hostname="active-one")
    pending = factories.agent(status="pending", hostname="pending-one")

    resp = await client.get("/api/v1/agents/pending", headers=viewer_headers)
    assert resp.status_code == 200
    ids = [a["id"] for a in resp.json()]
    assert ids == [pending.id]


@pytest.mark.asyncio
async def test_get_agent_detail_includes_capabilities(client, factories, viewer_headers):
    agent = factories.agent(status="active")
    factories.agent_capability_grant(agent, capability="host_telemetry", enabled=True)

    resp = await client.get(f"/api/v1/agents/{agent.id}", headers=viewer_headers)
    assert resp.status_code == 200
    assert resp.json()["capabilities"] == {"host_telemetry": True}


@pytest.mark.asyncio
async def test_patch_requires_editor_not_viewer(client, factories, viewer_headers):
    agent = factories.agent()
    resp = await client.patch(f"/api/v1/agents/{agent.id}", json={"name": "renamed"}, headers=viewer_headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_patch_renames_agent(client, factories, auth_headers):
    agent = factories.agent()
    resp = await client.patch(f"/api/v1/agents/{agent.id}", json={"name": "renamed"}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["name"] == "renamed"


@pytest.mark.asyncio
async def test_approve_requires_admin(client, factories, viewer_headers):
    agent = factories.agent(status="pending")
    resp = await client.post(f"/api/v1/agents/{agent.id}/approve", json={}, headers=viewer_headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_approve_applies_default_grants_and_sets_active(client, factories, auth_headers):
    agent = factories.agent(status="pending")
    resp = await client.post(f"/api/v1/agents/{agent.id}/approve", json={}, headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "active"
    assert body["capabilities"] == {"host_telemetry": True, "remote_probe": False, "local_discovery": False}


@pytest.mark.asyncio
async def test_approve_honors_capability_overrides(client, factories, auth_headers):
    agent = factories.agent(status="pending")
    resp = await client.post(
        f"/api/v1/agents/{agent.id}/approve",
        json={"capabilities": {"remote_probe": True}},
        headers=auth_headers,
    )
    assert resp.json()["capabilities"]["remote_probe"] is True


@pytest.mark.asyncio
async def test_reject_sets_rejected_status(client, factories, auth_headers):
    agent = factories.agent(status="pending")
    resp = await client.post(f"/api/v1/agents/{agent.id}/reject", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"


@pytest.mark.asyncio
async def test_revoke_records_reason(client, factories, auth_headers):
    agent = factories.agent(status="active")
    resp = await client.post(
        f"/api/v1/agents/{agent.id}/revoke", json={"reason": "lost device"}, headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "revoked"


@pytest.mark.asyncio
async def test_capabilities_put_updates_grants(client, factories, auth_headers):
    agent = factories.agent(status="active")
    factories.agent_capability_grant(agent, capability="remote_probe", enabled=False)

    resp = await client.put(
        f"/api/v1/agents/{agent.id}/capabilities",
        json={"capabilities": {"remote_probe": True}},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["capabilities"]["remote_probe"] is True


@pytest.mark.asyncio
async def test_delete_requires_admin(client, factories, auth_headers):
    agent = factories.agent()
    resp = await client.delete(f"/api/v1/agents/{agent.id}", headers=auth_headers)
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_events_endpoint_lists_history(client, factories, viewer_headers):
    agent = factories.agent()
    factories.agent_event(agent, event_type="enrolled")
    factories.agent_event(agent, event_type="approved")

    resp = await client.get(f"/api/v1/agents/{agent.id}/events", headers=viewer_headers)
    assert resp.status_code == 200
    types = [e["event_type"] for e in resp.json()]
    assert types == ["approved", "enrolled"]  # newest first


@pytest.mark.asyncio
async def test_pairing_lookup_resolves_pending_agent(client, factories, auth_headers, monkeypatch):
    from unittest.mock import AsyncMock

    agent = factories.agent(status="pending", hostname="box1")
    monkeypatch.setattr(
        "app.services.agent_enrollment.consume_pairing_code", AsyncMock(return_value=agent.id)
    )

    resp = await client.post(
        "/api/v1/agents/pairing/lookup", json={"code": "ABCD-EFGH-JKMN"}, headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["agent_id"] == agent.id


@pytest.mark.asyncio
async def test_pairing_lookup_records_miss_on_unknown_code(client, auth_headers, monkeypatch):
    from unittest.mock import AsyncMock

    monkeypatch.setattr(
        "app.services.agent_enrollment.consume_pairing_code", AsyncMock(return_value=None)
    )
    miss = AsyncMock()
    monkeypatch.setattr("app.services.agent_enrollment.record_pairing_miss", miss)

    resp = await client.post(
        "/api/v1/agents/pairing/lookup", json={"code": "ZZZZ-ZZZZ-ZZZZ"}, headers=auth_headers,
    )
    assert resp.status_code == 404
    miss.assert_called_once()
```

- [ ] **Step 3: Run the tests to see them fail**

Run: `cd apps/backend && pytest tests/api/test_agents_api.py -v`
Expected: every test errors with 404 (route doesn't exist) or `ModuleNotFoundError`.

- [ ] **Step 4: Implement `agents.py`**

```python
# apps/backend/src/app/api/agents.py
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.rate_limit import get_limit, limiter
from app.core.rbac import require_role
from app.db.models import Agent, AgentCapabilityGrant, AgentEvent, Hardware, User
from app.db.session import get_db
from app.schemas.agents import (
    AgentEventRead,
    AgentPatch,
    AgentRead,
    AgentSummary,
    ApproveRequest,
    CapabilitiesUpdateRequest,
    PairingLookupRequest,
    PairingLookupResponse,
    RevokeRequest,
)
from app.services import agent_enrollment, agent_registry

router = APIRouter(tags=["agents"])


def _grants_dict(db: Session, agent_id: int) -> dict[str, bool]:
    return {
        g.capability: g.enabled
        for g in db.execute(
            select(AgentCapabilityGrant).where(AgentCapabilityGrant.agent_id == agent_id)
        ).scalars()
    }


def _to_read(db: Session, agent: Agent) -> AgentRead:
    data = AgentRead.model_validate(agent)
    data.capabilities = _grants_dict(db, agent.id)
    return data


@router.get("", response_model=list[AgentSummary])
def get_agents(
    db: Annotated[Session, Depends(get_db)],
    _user: Annotated[User, require_role("viewer")],
) -> Any:
    return agent_registry.list_agents(db)


@router.get("/pending", response_model=list[AgentSummary])
def get_pending_agents(
    db: Annotated[Session, Depends(get_db)],
    _user: Annotated[User, require_role("viewer")],
) -> Any:
    return agent_registry.list_agents(db, status="pending")


@router.get("/{agent_id}", response_model=AgentRead)
def get_agent_detail(
    agent_id: int,
    db: Annotated[Session, Depends(get_db)],
    _user: Annotated[User, require_role("viewer")],
) -> Any:
    agent = agent_registry.get_agent(db, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return _to_read(db, agent)


@router.get("/{agent_id}/events", response_model=list[AgentEventRead])
def get_agent_events(
    agent_id: int,
    db: Annotated[Session, Depends(get_db)],
    _user: Annotated[User, require_role("viewer")],
) -> Any:
    return list(
        db.execute(
            select(AgentEvent)
            .where(AgentEvent.agent_id == agent_id)
            .order_by(AgentEvent.created_at.desc())
        ).scalars()
    )


@router.patch("/{agent_id}", response_model=AgentRead)
def patch_agent(
    agent_id: int,
    payload: AgentPatch,
    db: Annotated[Session, Depends(get_db)],
    _user: Annotated[User, require_role("editor")],
) -> Any:
    agent = agent_registry.get_agent(db, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(agent, field, value)
    db.flush()
    return _to_read(db, agent)


@router.post("/pairing/lookup", response_model=PairingLookupResponse)
@limiter.limit(lambda: get_limit("auth"))
async def post_pairing_lookup(
    request: Request,
    payload: PairingLookupRequest,
    db: Annotated[Session, Depends(get_db)],
    _user: Annotated[User, require_role("admin")],
) -> Any:
    from slowapi.util import get_remote_address

    ip = get_remote_address(request)
    if await agent_enrollment.is_pairing_locked_out(ip):
        raise HTTPException(status_code=429, detail="Too many incorrect pairing codes")

    # consume, not resolve — the code has done its job once it identifies the
    # pending agent; single-use per spec §2.4.
    agent_id = await agent_enrollment.consume_pairing_code(payload.code)
    if agent_id is None:
        await agent_enrollment.record_pairing_miss(ip)
        raise HTTPException(status_code=404, detail="Unknown or expired pairing code")

    agent = agent_registry.get_agent(db, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Unknown or expired pairing code")

    proposed = agent_registry.propose_hardware_match(db, agent)
    duplicate = False
    if agent.machine_id_hash:
        duplicate = (
            db.execute(
                select(Agent).where(
                    Agent.machine_id_hash == agent.machine_id_hash, Agent.id != agent.id,
                )
            ).scalar_one_or_none()
            is not None
        )

    return PairingLookupResponse(
        agent_id=agent.id,
        hostname=agent.hostname,
        os=agent.os,
        arch=agent.arch,
        fingerprint=agent.fingerprint,
        proposed_hardware_id=proposed.id if proposed else None,
        proposed_hardware_name=proposed.name if proposed else None,
        duplicate_machine_id=duplicate,
    )


@router.post("/{agent_id}/approve", response_model=AgentRead)
def post_approve(
    agent_id: int,
    payload: ApproveRequest,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, require_role("admin")],
) -> Any:
    agent = agent_registry.approve_agent(
        db, agent_id, approving_user_id=user.id,
        hardware_id=payload.hardware_id, capability_overrides=payload.capabilities,
    )
    return _to_read(db, agent)


@router.post("/{agent_id}/reject", response_model=AgentRead)
def post_reject(
    agent_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, require_role("admin")],
) -> Any:
    agent = agent_registry.reject_agent(db, agent_id, actor_user_id=user.id)
    return _to_read(db, agent)


@router.post("/{agent_id}/revoke", response_model=AgentRead)
def post_revoke(
    agent_id: int,
    payload: RevokeRequest,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, require_role("admin")],
) -> Any:
    agent = agent_registry.revoke_agent(db, agent_id, actor_user_id=user.id, reason=payload.reason)
    return _to_read(db, agent)


@router.put("/{agent_id}/capabilities", response_model=AgentRead)
def put_capabilities(
    agent_id: int,
    payload: CapabilitiesUpdateRequest,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, require_role("admin")],
) -> Any:
    agent = agent_registry.get_agent(db, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    agent_registry.set_capability_grants(db, agent_id, payload.capabilities, actor_user_id=user.id)
    return _to_read(db, agent)


@router.delete("/{agent_id}", status_code=204)
def delete_agent(
    agent_id: int,
    db: Annotated[Session, Depends(get_db)],
    _user: Annotated[User, require_role("admin")],
) -> None:
    agent = agent_registry.get_agent(db, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    db.delete(agent)
    db.flush()
```

- [ ] **Step 5: Wire the router into `main.py`**

```python
# apps/backend/src/app/main.py — imports section
from app.api.agents import router as agents_router
```

```python
# apps/backend/src/app/main.py — registration section
app.include_router(
    agents_router,
    prefix=f"{_V1}/agents",
    tags=["agents"],
    dependencies=[Depends(require_auth)],
)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd apps/backend && pytest tests/api/test_agents_api.py -v`
Expected: 16 passed.

- [ ] **Step 7: Commit**

```bash
git add apps/backend/src/app/schemas/agents.py apps/backend/src/app/api/agents.py \
        apps/backend/src/app/main.py apps/backend/tests/api/test_agents_api.py
git commit -m "feat(agents): fleet REST API — list, approve, reject, revoke, capabilities"
```

---

### Task 10: Cross-language frame conformance corpus

Per spec §7: "a fixture corpus of protocol v1 frames encoded by the Go side and decoded by the
Python side, and the reverse." This is a **static, checked-in JSON corpus** both languages decode
and round-trip — not a live cross-process dial (that's what Task 21's docker-compose harness is
for). A shared corpus avoids any need to orchestrate one language's test run from inside the
other's.

**Files:**
- Create: `fixtures/agent_frame_corpus.json` (repo root — shared by both languages)
- Create: `apps/agent/internal/frame/conformance_test.go`
- Create: `apps/backend/tests/test_agent_frame_conformance.py`

**Interfaces:**
- Consumes: `frame.Decode`/`frame.Encode` (Task 3, Go); `AgentFrame` (Task 7, Python).
- Produces: nothing new — this task only adds tests and the shared fixture file.

- [ ] **Step 1: Write the shared corpus**

```json
// fixtures/agent_frame_corpus.json
[
  {
    "description": "hello — agent to server, full enrollment payload",
    "json": {
      "v": 1, "type": "hello", "seq": 0, "ts": "2026-07-27T12:00:00Z",
      "payload": {
        "device_pk": "ab12cd34", "hostname": "box1.local", "machine_id_hash": "deadbeef",
        "os": "linux", "os_version": "6.1", "arch": "amd64", "agent_version": "0.1.0",
        "primary_macs": ["aa:bb:cc:dd:ee:ff"]
      }
    }
  },
  {
    "description": "heartbeat — minimal payload",
    "json": {"v": 1, "type": "heartbeat", "seq": 42, "ts": "2026-07-27T12:00:20Z", "payload": {}}
  },
  {
    "description": "hello.ack — server to agent, pairing code",
    "json": {
      "v": 1, "type": "hello.ack", "seq": 0, "ts": "2026-07-27T12:00:00Z",
      "payload": {"agent_id": 7, "pairing_code": "ABCD-EFGH-JKMN", "magic_link": "/agents/enroll?c=ABCD-EFGH-JKMN"}
    }
  },
  {
    "description": "hello.ack — approval transition",
    "json": {"v": 1, "type": "hello.ack", "seq": 1, "ts": "2026-07-27T12:05:00Z", "payload": {"agent_id": 7, "status": "active"}}
  },
  {
    "description": "capabilities.set — mixed grants",
    "json": {
      "v": 1, "type": "capabilities.set", "seq": 2, "ts": "2026-07-27T12:05:01Z",
      "payload": {"host_telemetry": true, "remote_probe": false, "local_discovery": false}
    }
  },
  {
    "description": "capability.violation — agent reporting a server-side drop",
    "json": {
      "v": 1, "type": "capability.violation", "seq": 100, "ts": "2026-07-27T12:10:00Z",
      "payload": {"frame_type": "probe.result", "reason": "capability not granted"}
    }
  },
  {
    "description": "ping — empty payload, large seq",
    "json": {"v": 1, "type": "ping", "seq": 18446744073709551615, "ts": "2026-07-27T12:15:00Z", "payload": {}}
  },
  {
    "description": "log — unicode payload",
    "json": {
      "v": 1, "type": "log", "seq": 3, "ts": "2026-07-27T12:20:00Z",
      "payload": {"level": "warn", "msg": "unable to read /proc — hidepid≠0 détecté"}
    }
  },
  {
    "description": "disconnect — server-initiated close reason",
    "json": {"v": 1, "type": "disconnect", "seq": 0, "ts": "2026-07-27T12:25:00Z", "payload": {"reason": "revoked"}}
  }
]
```

`seq: 18446744073709551615` is `math.MaxUint64` — chosen deliberately since Go's `frame.Frame.Seq`
is `uint64` while Python's `AgentFrame.seq` is a plain `int`; this value would silently overflow
if either side used a signed 64-bit integer internally, which is exactly the kind of drift this
corpus exists to catch.

- [ ] **Step 2: Write the failing Go conformance test**

```go
// apps/agent/internal/frame/conformance_test.go
package frame

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

type corpusEntry struct {
	Description string          `json:"description"`
	JSON        json.RawMessage `json:"json"`
}

func loadCorpus(t *testing.T) []corpusEntry {
	t.Helper()
	// apps/agent/internal/frame -> repo root is four levels up.
	path := filepath.Join("..", "..", "..", "..", "fixtures", "agent_frame_corpus.json")
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read corpus: %v", err)
	}
	var entries []corpusEntry
	if err := json.Unmarshal(data, &entries); err != nil {
		t.Fatalf("unmarshal corpus: %v", err)
	}
	return entries
}

func TestCorpus_DecodesAndRoundTrips(t *testing.T) {
	for _, entry := range loadCorpus(t) {
		t.Run(entry.Description, func(t *testing.T) {
			decoded, err := Decode(entry.JSON)
			if err != nil {
				t.Fatalf("Decode() error = %v", err)
			}
			if decoded.V != 1 {
				t.Errorf("V = %d, want 1", decoded.V)
			}
			if decoded.Type == "" {
				t.Error("Type is empty")
			}

			reencoded, err := Encode(decoded)
			if err != nil {
				t.Fatalf("Encode() error = %v", err)
			}
			redecoded, err := Decode(reencoded)
			if err != nil {
				t.Fatalf("re-Decode() error = %v", err)
			}
			if redecoded.Type != decoded.Type || redecoded.Seq != decoded.Seq {
				t.Errorf("round-trip mismatch: got %+v, want %+v", redecoded, decoded)
			}
			if !redecoded.TS.Equal(decoded.TS) {
				t.Errorf("round-trip TS mismatch: got %v, want %v", redecoded.TS, decoded.TS)
			}
		})
	}
}
```

- [ ] **Step 3: Run it**

Run: `cd apps/agent && go test ./internal/frame/... -run TestCorpus -v`
Expected: `PASS` for all 9 subtests. A `Seq` mismatch on the `MaxUint64` entry specifically means
`Frame.Seq` isn't `uint64` — fix the type in `internal/frame/frame.go` (Task 3) if so.

- [ ] **Step 4: Write the failing Python conformance test**

```python
# apps/backend/tests/test_agent_frame_conformance.py
import json
from pathlib import Path

import pytest

from app.schemas.agent_frame import AgentFrame

_CORPUS_PATH = Path(__file__).resolve().parents[3] / "fixtures" / "agent_frame_corpus.json"


def _load_corpus() -> list[dict]:
    return json.loads(_CORPUS_PATH.read_text())


@pytest.mark.parametrize("entry", _load_corpus(), ids=lambda e: e["description"])
def test_corpus_decodes_and_round_trips(entry):
    raw = json.dumps(entry["json"])
    decoded = AgentFrame.model_validate_json(raw)

    assert decoded.v == 1
    assert decoded.type

    reencoded = decoded.model_dump_json()
    redecoded = AgentFrame.model_validate_json(reencoded)

    assert redecoded.type == decoded.type
    assert redecoded.seq == decoded.seq
    assert redecoded.ts == decoded.ts
```

- [ ] **Step 5: Run it**

Run: `cd apps/backend && pytest tests/test_agent_frame_conformance.py -v`
Expected: 9 passed. If the `ping` entry's `seq: 18446744073709551615` fails to parse, Python's
plain `int` handles arbitrary precision natively, so a failure there points at a Go-side issue
instead — rerun Step 3.

- [ ] **Step 6: Commit**

```bash
git add fixtures/agent_frame_corpus.json apps/agent/internal/frame/conformance_test.go \
        apps/backend/tests/test_agent_frame_conformance.py
git commit -m "test(agents): cross-language frame envelope conformance corpus"
```

---

### Task 11: Go link loop — heartbeat, reconnect/backoff

Per spec §1.1's package table, `internal/link` depends only on `config` and `enroll` — not on
`capability` or `spool` (those exist for future collectors to use, and have nothing to do in
slice 1 since no collector produces data frames yet; `spool` in particular only ever holds *data*
frames, never control frames, and slice 1 has no data frames at all). Where `link` needs to hand a
received `capabilities.set` frame to something, it does so through a caller-supplied callback
rather than importing `capability` directly, keeping the dependency direction spec'd.

**Files:**
- Create: `apps/agent/internal/link/backoff.go`
- Create: `apps/agent/internal/link/backoff_test.go`
- Create: `apps/agent/internal/link/link.go`
- Create: `apps/agent/internal/link/link_test.go`
- Modify: `apps/agent/cmd/cb-agent/main.go` (no-args invocation runs the daemon: enroll-if-needed,
  then link forever)

**Interfaces:**
- Consumes: `noiseconn.NewInitiator`/`Session` (Task 8), `frame.Frame`/`Encode`/`Decode` (Task 3),
  `enroll.LoadOrCreateDeviceKey`/`DeviceKey` (Task 4), `config.Config`/`StateDir` (Task 3).
- Produces: `link.Options{Config *config.Config; Key *enroll.DeviceKey; AgentVersion string;
  OnCapabilitiesSet func(json.RawMessage) error}`, `link.Run(ctx context.Context, opts Options)
  error` (blocks, reconnecting with backoff, until `ctx` is cancelled or a non-retryable error
  occurs). Task 13 (`internal/capability`) supplies the real `OnCapabilitiesSet` implementation
  wired in by `main.go`; this task uses a `nil`-safe default (no-op) so it's independently
  testable first.

- [ ] **Step 1: Write the failing backoff test**

```go
// apps/agent/internal/link/backoff_test.go
package link

import (
	"testing"
	"time"
)

func TestBackoffBaseDuration_DoublesUpToCap(t *testing.T) {
	cases := []struct {
		attempt int
		want    time.Duration
	}{
		{0, 1 * time.Second},
		{1, 2 * time.Second},
		{2, 4 * time.Second},
		{3, 8 * time.Second},
		{20, 5 * time.Minute}, // capped
	}
	for _, c := range cases {
		if got := backoffBaseDuration(c.attempt); got != c.want {
			t.Errorf("backoffBaseDuration(%d) = %v, want %v", c.attempt, got, c.want)
		}
	}
}

func TestBackoffDelay_StaysWithinBaseToBasePlusQuarter(t *testing.T) {
	for attempt := 0; attempt < 10; attempt++ {
		base := backoffBaseDuration(attempt)
		for i := 0; i < 20; i++ {
			d := backoffDelay(attempt)
			if d < base || d > base+base/4+1 {
				t.Errorf("backoffDelay(%d) = %v, want in [%v, %v]", attempt, d, base, base+base/4)
			}
		}
	}
}
```

- [ ] **Step 2: Run it to see it fail to compile**

Run: `cd apps/agent && go test ./internal/link/...`
Expected: `undefined: backoffBaseDuration`.

- [ ] **Step 3: Implement backoff**

```go
// apps/agent/internal/link/backoff.go
package link

import (
	"math/rand"
	"time"
)

const (
	backoffBase = 1 * time.Second
	backoffMax  = 5 * time.Minute
)

// backoffBaseDuration doubles per attempt, capped at backoffMax. Pure and
// deterministic so it's unit-testable without jitter noise.
func backoffBaseDuration(attempt int) time.Duration {
	if attempt < 0 {
		attempt = 0
	}
	if attempt > 20 { // 1s * 2^20 already exceeds backoffMax many times over
		return backoffMax
	}
	d := backoffBase * time.Duration(int64(1)<<uint(attempt))
	if d > backoffMax || d <= 0 {
		return backoffMax
	}
	return d
}

// backoffDelay adds up to 25% jitter on top of the base duration.
func backoffDelay(attempt int) time.Duration {
	base := backoffBaseDuration(attempt)
	jitter := time.Duration(rand.Int63n(int64(base/4) + 1))
	return base + jitter
}
```

- [ ] **Step 4: Run the backoff tests to verify they pass**

Run: `cd apps/agent && go test ./internal/link/... -run Backoff -v`
Expected: `PASS`.

- [ ] **Step 5: Write the failing link loop test**

Mirrors Task 8's `enroll_test.go` layering — a real `httptest.Server` WS endpoint standing in for
the Python `/link` responder (Task 12 proves the real Python side; this proves `link.Run`'s
client-side heartbeat/reconnect behavior in isolation).

```go
// apps/agent/internal/link/link_test.go
package link

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/gorilla/websocket"

	"circuitbreaker.dev/cb-agent/internal/config"
	"circuitbreaker.dev/cb-agent/internal/enroll"
)

func TestRun_SendsHeartbeatsAndAppliesCapabilitiesSet(t *testing.T) {
	serverPriv, serverPub := generateTestKeypair(t)
	var heartbeats int32

	upgrader := websocket.Upgrader{}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			t.Fatalf("upgrade: %v", err)
		}
		defer conn.Close()

		responder := newTestResponderSession(t, serverPriv, serverPub)
		_, msg1, err := conn.ReadMessage()
		if err != nil {
			return
		}
		msg2, err := responder.ReadHandshakeMessage(msg1)
		if err != nil {
			t.Errorf("responder handshake: %v", err)
			return
		}
		conn.WriteMessage(websocket.BinaryMessage, msg2)

		grants := map[string]any{
			"v": 1, "type": "capabilities.set", "seq": 0, "ts": time.Now().UTC(),
			"payload": map[string]bool{"host_telemetry": true},
		}
		grantsBytes, _ := json.Marshal(grants)
		conn.WriteMessage(websocket.BinaryMessage, responder.Encrypt(grantsBytes))

		for {
			_, ct, err := conn.ReadMessage()
			if err != nil {
				return
			}
			pt, err := responder.Decrypt(ct)
			if err != nil {
				return
			}
			var f map[string]any
			json.Unmarshal(pt, &f)
			if f["type"] == "heartbeat" {
				atomic.AddInt32(&heartbeats, 1)
			}
		}
	}))
	defer srv.Close()

	wsURL := "ws" + strings.TrimPrefix(srv.URL, "http")
	dir := t.TempDir()
	key, err := enroll.LoadOrCreateDeviceKey(dir)
	if err != nil {
		t.Fatalf("LoadOrCreateDeviceKey() error = %v", err)
	}

	var capabilitiesApplied int32
	opts := Options{
		Config: &config.Config{ServerURL: wsURL, ServerStaticPK: hex.EncodeToString(serverPub[:])},
		Key:    key, AgentVersion: "0.1.0-test",
		OnCapabilitiesSet: func(json.RawMessage) error {
			atomic.AddInt32(&capabilitiesApplied, 1)
			return nil
		},
	}

	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	_ = Run(ctx, opts) // returns ctx.Err() (deadline exceeded) — that's the expected exit

	if atomic.LoadInt32(&capabilitiesApplied) == 0 {
		t.Error("OnCapabilitiesSet was never called")
	}
}
```

> This test needs `generateTestKeypair`/`newTestResponderSession` — the same responder-role test
> helpers Task 8 Step 6 introduced for `enroll_test.go`. Since Go has no cross-package test-only
> import mechanism, either duplicate the ~15-line helpers into `link_test.go` (simplest, matches
> this codebase having no shared Go test-utility package yet) or factor them into an internal
> `testhelpers` package under `apps/agent/internal/testhelpers/` if duplication starts feeling
> painful by Task 12. For slice 1, duplicate — two call sites don't justify a new package.
> `link_test.go` also needs `encoding/hex` in its import block for `hex.EncodeToString`.

This test only asserts **20-second heartbeats arrive** by running long enough to observe at least
one heartbeat tick would require a 20s+ test — too slow for a unit test. Instead, lower the
heartbeat interval for testability: make it an unexported `var heartbeatInterval =
20 * time.Second` (not a `const`) in `link.go`, and have `link_test.go`'s `TestMain` or the test
itself override it:

```go
// add near the top of TestRun_SendsHeartbeatsAndAppliesCapabilitiesSet, before ctx is created
originalInterval := heartbeatInterval
heartbeatInterval = 200 * time.Millisecond
defer func() { heartbeatInterval = originalInterval }()
```

and add a final assertion after the `Run` call:

```go
if atomic.LoadInt32(&heartbeats) == 0 {
    t.Error("no heartbeat frames were received")
}
```

- [ ] **Step 6: Run it to see it fail to compile**

Run: `cd apps/agent && go test ./internal/link/...`
Expected: `undefined: Run` / `undefined: Options`.

- [ ] **Step 7: Implement `link.go`**

```go
// apps/agent/internal/link/link.go
package link

import (
	"context"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"net/url"
	"strings"
	"time"

	"github.com/gorilla/websocket"

	"circuitbreaker.dev/cb-agent/internal/config"
	"circuitbreaker.dev/cb-agent/internal/enroll"
	"circuitbreaker.dev/cb-agent/internal/frame"
	"circuitbreaker.dev/cb-agent/internal/noiseconn"
)

var heartbeatInterval = 20 * time.Second

type Options struct {
	Config            *config.Config
	Key               *enroll.DeviceKey
	AgentVersion      string
	OnCapabilitiesSet func(json.RawMessage) error
}

// Run dials WS /api/agents/link and stays connected until ctx is cancelled,
// reconnecting with exponential backoff + jitter (1s -> 5m cap) on any
// disconnect. It returns ctx.Err() on cancellation.
func Run(ctx context.Context, opts Options) error {
	if opts.OnCapabilitiesSet == nil {
		opts.OnCapabilitiesSet = func(json.RawMessage) error { return nil }
	}
	attempt := 0
	for {
		if ctx.Err() != nil {
			return ctx.Err()
		}
		err := runOnce(ctx, opts)
		if ctx.Err() != nil {
			return ctx.Err()
		}
		delay := backoffDelay(attempt)
		attempt++
		log.Printf("link: disconnected (%v) — reconnecting in %s", err, delay)
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(delay):
		}
	}
}

func runOnce(ctx context.Context, opts Options) error {
	remotePub, err := hex.DecodeString(opts.Config.ServerStaticPK)
	if err != nil || len(remotePub) != 32 {
		return fmt.Errorf("link: invalid server_static_pk: %w", err)
	}
	var remotePubArr [32]byte
	copy(remotePubArr[:], remotePub)

	session, err := noiseconn.NewInitiator(opts.Key.Private, opts.Key.Public, remotePubArr)
	if err != nil {
		return fmt.Errorf("link: %w", err)
	}

	u, err := url.Parse(opts.Config.ServerURL)
	if err != nil {
		return fmt.Errorf("link: invalid server_url: %w", err)
	}
	u.Scheme = strings.Replace(u.Scheme, "http", "ws", 1)
	u.Path = "/api/v1/agents/link"

	conn, _, err := websocket.DefaultDialer.DialContext(ctx, u.String(), nil)
	if err != nil {
		return fmt.Errorf("link: dial: %w", err)
	}
	defer conn.Close()

	msg1, err := session.WriteHandshakeMessage()
	if err != nil {
		return fmt.Errorf("link: %w", err)
	}
	if err := conn.WriteMessage(websocket.BinaryMessage, msg1); err != nil {
		return fmt.Errorf("link: send handshake: %w", err)
	}
	_, msg2, err := conn.ReadMessage()
	if err != nil {
		return fmt.Errorf("link: read handshake response: %w", err)
	}
	if err := session.ReadHandshakeMessage(msg2); err != nil {
		return fmt.Errorf("link: %w", err)
	}

	incoming := make(chan frame.Frame)
	readErrCh := make(chan error, 1)
	go func() {
		for {
			_, ct, err := conn.ReadMessage()
			if err != nil {
				readErrCh <- err
				return
			}
			pt, err := session.Decrypt(ct)
			if err != nil {
				readErrCh <- err
				return
			}
			f, err := frame.Decode(pt)
			if err != nil {
				readErrCh <- err
				return
			}
			select {
			case incoming <- f:
			case <-ctx.Done():
				return
			}
		}
	}()

	ticker := time.NewTicker(heartbeatInterval)
	defer ticker.Stop()
	var seq uint64

	sendHeartbeat := func() error {
		seq++
		hb := frame.Frame{V: 1, Type: frame.TypeHeartbeat, Seq: seq, TS: time.Now().UTC(), Payload: json.RawMessage("{}")}
		data, err := frame.Encode(hb)
		if err != nil {
			return err
		}
		return conn.WriteMessage(websocket.BinaryMessage, session.Encrypt(data))
	}

	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case err := <-readErrCh:
			return fmt.Errorf("link: connection lost: %w", err)
		case f := <-incoming:
			switch f.Type {
			case frame.TypePing:
				if err := sendHeartbeat(); err != nil {
					return err
				}
			case frame.TypeDisconnect:
				return errors.New("link: server requested disconnect")
			case frame.TypeCapabilitiesSet:
				if err := opts.OnCapabilitiesSet(f.Payload); err != nil {
					log.Printf("link: applying capabilities.set: %v", err)
				}
			}
		case <-ticker.C:
			if err := sendHeartbeat(); err != nil {
				return err
			}
		}
	}
}
```

- [ ] **Step 8: Run the link test to verify it passes**

Run: `cd apps/agent && go test ./internal/link/... -v`
Expected: `PASS`. If `OnCapabilitiesSet` is never invoked, check `f.Type` in the switch matches the
literal `"capabilities.set"` from `frame.TypeCapabilitiesSet` (Task 3).

- [ ] **Step 9: Wire the no-args daemon path in the CLI**

```go
// apps/agent/cmd/cb-agent/main.go — replace the "usage" branch for len(os.Args) < 2
func main() {
	if len(os.Args) < 2 {
		runDaemon()
		return
	}
	switch os.Args[1] {
	case "version":
		runVersion()
	case "status":
		runStatus()
	case "enroll":
		runEnroll()
	default:
		fmt.Fprintf(os.Stderr, "unknown subcommand %q\n", os.Args[1])
		os.Exit(1)
	}
}

func runDaemon() {
	cfg, err := config.Load("/etc/circuit-breaker/agent.toml")
	if err != nil {
		fmt.Fprintf(os.Stderr, "cb-agent: %v\n", err)
		os.Exit(1)
	}
	key, err := enroll.LoadOrCreateDeviceKey(config.StateDir())
	if err != nil {
		fmt.Fprintf(os.Stderr, "cb-agent: %v\n", err)
		os.Exit(1)
	}

	if err := enroll.Run(cfg, key, AgentVersion); err != nil {
		fmt.Fprintf(os.Stderr, "cb-agent: enrollment: %v\n", err)
		os.Exit(1)
	}

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	if err := link.Run(ctx, link.Options{Config: cfg, Key: key, AgentVersion: AgentVersion}); err != nil && ctx.Err() == nil {
		fmt.Fprintf(os.Stderr, "cb-agent: %v\n", err)
		os.Exit(1)
	}
}
```

Add `"context"`, `"os/signal"`, `"syscall"`, and
`"circuitbreaker.dev/cb-agent/internal/link"` to `main.go`'s import block.

- [ ] **Step 10: Build and smoke-test**

Run: `cd apps/agent && go build -o /tmp/cb-agent ./cmd/cb-agent`
Expected: builds cleanly. A full daemon run needs a live server — proven in Task 12's tests and
Task 21's E2E harness.

- [ ] **Step 11: Commit**

```bash
git add apps/agent/internal/link apps/agent/cmd/cb-agent/main.go apps/agent/go.mod apps/agent/go.sum
git commit -m "feat(agent): link loop — heartbeat, reconnect/backoff, daemon mode"
```

---

### Task 12: Backend link socket — `WS /api/agents/link` and `agent_link.py`

Revocation closing a live socket "instantly" (spec §2.5) is implemented here as a ≤5s poll of the
agent's status on every receive-timeout tick, not a cross-worker pub/sub push. That is a
deliberate, honest scoping simplification for slice 1 — true sub-second cross-worker revoke
would need the same Redis pub/sub fan-out `discovery_service.py` already uses for its WS
broadcasts, which is more infrastructure than this slice's single-process-friendly default
deployment needs yet. Note this explicitly in the PR description rather than silently falling
short of the spec's "instant" wording.

**Files:**
- Create: `apps/backend/src/app/services/agent_link.py`
- Modify: `apps/backend/src/app/api/ws_agents.py` (add the `/link` route to
  `unauthenticated_router`)
- Test: `apps/backend/tests/services/test_agent_link.py`
- Test: `apps/backend/tests/api/test_ws_agents_link.py`

**Interfaces:**
- Consumes: `agent_registry.{get_agent_by_device_pk, get_agent, mark_presence_connected,
  mark_presence_disconnected, refresh_presence_heartbeat, record_event}` (Task 6),
  `NoiseIKResponder` (Task 2), `AgentFrame` + `TYPE_*` constants (Task 7).
- Produces: `agent_link.CAPABILITY_FOR_TYPE: dict[str, str]`,
  `agent_link.dispatch_frame(db, agent, frame: AgentFrame) -> None` (async — checks the grant,
  records `capability_violation` and returns early if ungranted, else calls the registered
  handler for `frame.type` if one exists). No later slice-1 task imports from this module —
  collector-specific handlers (`telemetry.host`, `probe.result`, `discovery.finding`) are added by
  slices 2–4, each just registering one more entry in `_HANDLERS`.

- [ ] **Step 1: Write the failing `agent_link.py` tests**

```python
# apps/backend/tests/services/test_agent_link.py
import pytest

from app.schemas.agent_frame import AgentFrame
from app.services import agent_link


@pytest.mark.asyncio
async def test_dispatch_heartbeat_refreshes_presence(db_session, factories, monkeypatch):
    from unittest.mock import AsyncMock

    agent = factories.agent(status="active")
    refresh = AsyncMock()
    monkeypatch.setattr("app.services.agent_registry.refresh_presence_heartbeat", refresh)

    frame = AgentFrame(type="heartbeat", ts="2026-07-27T12:00:00Z", payload={})
    await agent_link.dispatch_frame(db_session, agent, frame)

    refresh.assert_called_once()


@pytest.mark.asyncio
async def test_dispatch_ungranted_frame_records_violation_and_does_not_dispatch(db_session, factories):
    from app.db.models import AgentEvent

    agent = factories.agent(status="active")
    factories.agent_capability_grant(agent, capability="host_telemetry", enabled=False)

    frame = AgentFrame(type="telemetry.host", ts="2026-07-27T12:00:00Z", payload={"cpu": 0.5})
    await agent_link.dispatch_frame(db_session, agent, frame)

    violation = (
        db_session.query(AgentEvent)
        .filter_by(agent_id=agent.id, event_type="capability_violation")
        .one()
    )
    assert violation.detail == {"frame_type": "telemetry.host"}


@pytest.mark.asyncio
async def test_dispatch_granted_telemetry_frame_does_not_record_violation(db_session, factories):
    from app.db.models import AgentEvent

    agent = factories.agent(status="active")
    factories.agent_capability_grant(agent, capability="host_telemetry", enabled=True)

    frame = AgentFrame(type="telemetry.host", ts="2026-07-27T12:00:00Z", payload={"cpu": 0.5})
    await agent_link.dispatch_frame(db_session, agent, frame)

    count = (
        db_session.query(AgentEvent)
        .filter_by(agent_id=agent.id, event_type="capability_violation")
        .count()
    )
    assert count == 0
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `cd apps/backend && pytest tests/services/test_agent_link.py -v`
Expected: `ModuleNotFoundError: No module named 'app.services.agent_link'`.

- [ ] **Step 3: Implement `agent_link.py`**

```python
# apps/backend/src/app/services/agent_link.py
"""Frame decode -> capability check -> dispatch. No domain logic lives here —
telemetry lands in telemetry_service, probe results in the monitoring
engine's result path, discovery findings in discovery_import_service (slices
2-4). This module only transports and authenticates (spec §1.2)."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from sqlalchemy.orm import Session

from app.db.models import Agent
from app.schemas.agent_frame import (
    TYPE_DISCOVERY_FINDING,
    TYPE_HEARTBEAT,
    TYPE_LOG,
    TYPE_PROBE_RESULT,
    TYPE_TELEMETRY_HOST,
    AgentFrame,
)
from app.services import agent_registry

_logger = logging.getLogger(__name__)

# Frame types requiring no grant are transport-level (hello/heartbeat/log/
# capability.violation) and are simply absent from this map.
CAPABILITY_FOR_TYPE: dict[str, str] = {
    TYPE_TELEMETRY_HOST: "host_telemetry",
    TYPE_PROBE_RESULT: "remote_probe",
    TYPE_DISCOVERY_FINDING: "local_discovery",
}

Handler = Callable[[Session, Agent, AgentFrame], Awaitable[None]]


async def _handle_heartbeat(db: Session, agent: Agent, frame: AgentFrame) -> None:
    import socket

    await agent_registry.refresh_presence_heartbeat(db, agent.id, worker=socket.gethostname())


async def _handle_log(db: Session, agent: Agent, frame: AgentFrame) -> None:
    _logger.info("agent %s: %s", agent.id, frame.payload)


_HANDLERS: dict[str, Handler] = {
    TYPE_HEARTBEAT: _handle_heartbeat,
    TYPE_LOG: _handle_log,
}


def _grants_dict(db: Session, agent_id: int) -> dict[str, bool]:
    from app.db.models import AgentCapabilityGrant
    from sqlalchemy import select

    return {
        g.capability: g.enabled
        for g in db.execute(
            select(AgentCapabilityGrant).where(AgentCapabilityGrant.agent_id == agent_id)
        ).scalars()
    }


async def dispatch_frame(db: Session, agent: Agent, frame: AgentFrame) -> None:
    required = CAPABILITY_FOR_TYPE.get(frame.type)
    if required is not None and not _grants_dict(db, agent.id).get(required, False):
        agent_registry.record_event(
            db, agent.id, "capability_violation", detail={"frame_type": frame.type},
        )
        db.commit()
        return

    handler = _HANDLERS.get(frame.type)
    if handler is not None:
        await handler(db, agent, frame)
        db.commit()
```

- [ ] **Step 4: Run the `agent_link.py` tests to verify they pass**

Run: `cd apps/backend && pytest tests/services/test_agent_link.py -v`
Expected: 3 passed.

- [ ] **Step 5: Write the failing `/link` endpoint test**

```python
# apps/backend/tests/api/test_ws_agents_link.py
import hashlib
import json
import secrets
from datetime import UTC, datetime

from app.core.agent_crypto import get_server_static_keypair
from app.db.models import Agent
from tests.helpers.agent_noise_client import TestNoiseInitiator


def _active_agent_with_key(db_session, factories):
    agent_priv = secrets.token_bytes(32)
    from cryptography.hazmat.primitives.asymmetric import x25519

    pub = x25519.X25519PrivateKey.from_private_bytes(agent_priv).public_key().public_bytes_raw()
    device_pk = pub.hex()
    fingerprint = hashlib.sha256(pub).hexdigest()[:32]
    agent = factories.agent(status="active", device_pk=device_pk, fingerprint=fingerprint)
    factories.agent_capability_grant(agent, capability="host_telemetry", enabled=True)
    db_session.commit()
    return agent, agent_priv


def test_link_sends_capabilities_set_on_connect(db_session, factories, ws_client):
    agent, agent_priv = _active_agent_with_key(db_session, factories)
    _, server_pub = get_server_static_keypair()

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        initiator = TestNoiseInitiator(agent_priv, server_pub)
        ws.send_bytes(initiator.write_message())
        initiator.read_message(ws.receive_bytes())

        first = json.loads(initiator.decrypt(ws.receive_bytes()))
        assert first["type"] == "capabilities.set"
        assert first["payload"]["host_telemetry"] is True


def test_link_records_connected_then_disconnected_events(db_session, factories, ws_client):
    agent, agent_priv = _active_agent_with_key(db_session, factories)
    _, server_pub = get_server_static_keypair()

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        initiator = TestNoiseInitiator(agent_priv, server_pub)
        ws.send_bytes(initiator.write_message())
        initiator.read_message(ws.receive_bytes())
        ws.receive_bytes()  # capabilities.set

    from app.db.models import AgentEvent

    types = [
        e.event_type
        for e in db_session.query(AgentEvent).filter_by(agent_id=agent.id).order_by(AgentEvent.id)
    ]
    assert "connected" in types
    assert "disconnected" in types


def test_link_refuses_unknown_device_pk(ws_client):
    from starlette.websockets import WebSocketDisconnect

    import secrets as _secrets

    _, server_pub = get_server_static_keypair()
    agent_priv = _secrets.token_bytes(32)

    with pytest.raises(WebSocketDisconnect):
        with ws_client.websocket_connect("/api/v1/agents/link") as ws:
            initiator = TestNoiseInitiator(agent_priv, server_pub)
            ws.send_bytes(initiator.write_message())
            initiator.read_message(ws.receive_bytes())
            ws.receive_bytes()  # should never arrive — connection closes 1008 first
```

Add `import pytest` at the top of `test_ws_agents_link.py` for the third test's
`pytest.raises`.

- [ ] **Step 6: Run the tests to see them fail**

Run: `cd apps/backend && pytest tests/api/test_ws_agents_link.py -v`
Expected: 404s / connection errors — `/link` doesn't exist on `unauthenticated_router` yet.

- [ ] **Step 7: Add the `/link` route to `ws_agents.py`**

```python
# apps/backend/src/app/api/ws_agents.py — additional imports
import socket
from datetime import datetime

from app.schemas.agent_frame import TYPE_CAPABILITIES_SET, AgentFrame
from app.services import agent_link
```

```python
# apps/backend/src/app/api/ws_agents.py — append
_LINK_POLL_SECONDS = 5.0
_LINK_DEAD_SECONDS = 60.0  # three missed 20s heartbeats


def _capabilities_bytes(responder: NoiseIKResponder, grants: dict[str, bool]) -> bytes:
    frame = {
        "v": 1, "type": TYPE_CAPABILITIES_SET, "seq": 0,
        "ts": datetime.utcnow().isoformat(), "payload": grants,
    }
    return responder.encrypt(json.dumps(frame).encode())


@unauthenticated_router.websocket("/link")
async def link_stream(websocket: WebSocket) -> None:
    await websocket.accept()

    try:
        handshake_msg = await asyncio.wait_for(
            websocket.receive_bytes(), timeout=_HANDSHAKE_TIMEOUT_SECONDS
        )
    except (TimeoutError, WebSocketDisconnect):
        await websocket.close(code=1008)
        return

    server_priv, _ = get_server_static_keypair()
    responder = NoiseIKResponder(server_priv)
    try:
        response = responder.read_message(handshake_msg)
    except Exception:
        await websocket.close(code=1008)
        return
    await websocket.send_bytes(response)

    device_pk_hex = responder.remote_static().hex()
    with SessionLocal() as db:
        agent = agent_registry.get_agent_by_device_pk(db, device_pk_hex)
        if agent is None or agent.status != "active":
            await websocket.close(code=1008)
            return
        agent_id = agent.id
        grants = agent_link._grants_dict(db, agent_id)
        agent_registry.record_event(db, agent_id, "connected")
        db.commit()

    worker = socket.gethostname()
    await agent_registry.mark_presence_connected(agent_id, worker=worker)
    await websocket.send_bytes(_capabilities_bytes(responder, grants))

    last_activity = datetime.utcnow()
    try:
        while True:
            try:
                ct = await asyncio.wait_for(websocket.receive_bytes(), timeout=_LINK_POLL_SECONDS)
            except TimeoutError:
                if (datetime.utcnow() - last_activity).total_seconds() >= _LINK_DEAD_SECONDS:
                    break
                with SessionLocal() as db:
                    fresh = agent_registry.get_agent(db, agent_id)
                    if fresh is None or fresh.status != "active":
                        break
                continue
            except WebSocketDisconnect:
                break

            last_activity = datetime.utcnow()
            try:
                pt = responder.decrypt(ct)
                agent_frame = AgentFrame.model_validate_json(pt)
            except Exception:
                continue

            with SessionLocal() as db:
                fresh = agent_registry.get_agent(db, agent_id)
                if fresh is None or fresh.status != "active":
                    break
                await agent_link.dispatch_frame(db, fresh, agent_frame)
    finally:
        await agent_registry.mark_presence_disconnected(agent_id)
        with SessionLocal() as db:
            agent_registry.record_event(db, agent_id, "disconnected")
            db.commit()
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `cd apps/backend && pytest tests/api/test_ws_agents_link.py -v`
Expected: 3 passed.

- [ ] **Step 9: Commit**

```bash
git add apps/backend/src/app/services/agent_link.py apps/backend/src/app/api/ws_agents.py \
        apps/backend/tests/services/test_agent_link.py apps/backend/tests/api/test_ws_agents_link.py
git commit -m "feat(agents): WS /api/agents/link — capability-gated frame dispatch"
```

---

### Task 13: In-agent capability gate — `internal/capability`

Per spec §1.1, `internal/capability` has no dependencies of its own — every collector package
(slices 2-4) depends on it. In slice 1 there are no collectors to gate, so this task delivers the
standalone primitive: caching the server's `capabilities.set` grants to
`/var/lib/cb-agent/grants.json` (surviving a restart while disconnected) and exposing
`Allowed(capability) bool` for future callers, per spec §4.2 — "nothing about what the agent may
do is editable on the host."

**Files:**
- Create: `apps/agent/internal/capability/capability.go`
- Create: `apps/agent/internal/capability/capability_test.go`
- Modify: `apps/agent/cmd/cb-agent/main.go` (wire `capability.Gate.ApplyGrants` as `link.Options`'s
  `OnCapabilitiesSet`)

**Interfaces:**
- Consumes: nothing (spec-mandated leaf package).
- Produces: `capability.New(stateDir string) *Gate`, `(*Gate) LoadCached() error` (no-op if
  `grants.json` doesn't exist yet — first run before any server contact), `(*Gate)
  ApplyGrants(payload json.RawMessage) error` (replaces the in-memory set and persists it —
  matches `link.Options.OnCapabilitiesSet`'s exact signature from Task 11), `(*Gate)
  Allowed(capability string) bool` (default-deny for anything not explicitly `true`). Slice 2's
  first collector (not in this plan) will call `Allowed` before sending any `telemetry.host`
  frame.

- [ ] **Step 1: Write the failing tests**

```go
// apps/agent/internal/capability/capability_test.go
package capability

import (
	"encoding/json"
	"testing"
)

func TestGate_DefaultDenyForUnknownCapability(t *testing.T) {
	g := New(t.TempDir())
	if g.Allowed("host_telemetry") {
		t.Error("Allowed() = true for a capability never granted, want false (default-deny)")
	}
}

func TestGate_ApplyGrantsThenAllowed(t *testing.T) {
	g := New(t.TempDir())
	payload, _ := json.Marshal(map[string]bool{"host_telemetry": true, "remote_probe": false})

	if err := g.ApplyGrants(payload); err != nil {
		t.Fatalf("ApplyGrants() error = %v", err)
	}
	if !g.Allowed("host_telemetry") {
		t.Error("Allowed(host_telemetry) = false, want true")
	}
	if g.Allowed("remote_probe") {
		t.Error("Allowed(remote_probe) = true, want false")
	}
	if g.Allowed("local_discovery") {
		t.Error("Allowed(local_discovery) = true, want false (never granted)")
	}
}

func TestGate_PersistsAcrossRestartViaLoadCached(t *testing.T) {
	dir := t.TempDir()
	first := New(dir)
	payload, _ := json.Marshal(map[string]bool{"host_telemetry": true})
	if err := first.ApplyGrants(payload); err != nil {
		t.Fatalf("ApplyGrants() error = %v", err)
	}

	second := New(dir)
	if err := second.LoadCached(); err != nil {
		t.Fatalf("LoadCached() error = %v", err)
	}
	if !second.Allowed("host_telemetry") {
		t.Error("cached grant not restored after LoadCached()")
	}
}

func TestGate_LoadCached_NoOpWhenFileMissing(t *testing.T) {
	g := New(t.TempDir())
	if err := g.LoadCached(); err != nil {
		t.Fatalf("LoadCached() error = %v, want nil on first run with no grants.json yet", err)
	}
	if g.Allowed("host_telemetry") {
		t.Error("Allowed() = true with no cached grants, want false")
	}
}
```

- [ ] **Step 2: Run it to see it fail to compile**

Run: `cd apps/agent && go test ./internal/capability/...`
Expected: `undefined: New`.

- [ ] **Step 3: Implement `capability.go`**

```go
// apps/agent/internal/capability/capability.go
package capability

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sync"
)

const grantsFilename = "grants.json"

// Gate is the in-agent capability gate — grants arrive only over the link
// (spec §4.2) and are cached here solely so a restart while disconnected
// doesn't go dark. The server re-sends the authoritative set on every
// reconnect and this cache is overwritten, never edited locally.
type Gate struct {
	mu     sync.RWMutex
	grants map[string]bool
	path   string
}

func New(stateDir string) *Gate {
	return &Gate{grants: map[string]bool{}, path: filepath.Join(stateDir, grantsFilename)}
}

func (g *Gate) LoadCached() error {
	data, err := os.ReadFile(g.path)
	if os.IsNotExist(err) {
		return nil
	}
	if err != nil {
		return fmt.Errorf("capability: read %s: %w", g.path, err)
	}
	var grants map[string]bool
	if err := json.Unmarshal(data, &grants); err != nil {
		return fmt.Errorf("capability: parse %s: %w", g.path, err)
	}
	g.mu.Lock()
	g.grants = grants
	g.mu.Unlock()
	return nil
}

func (g *Gate) ApplyGrants(payload json.RawMessage) error {
	var grants map[string]bool
	if err := json.Unmarshal(payload, &grants); err != nil {
		return fmt.Errorf("capability: unmarshal grants: %w", err)
	}

	g.mu.Lock()
	g.grants = grants
	g.mu.Unlock()

	data, err := json.Marshal(grants)
	if err != nil {
		return fmt.Errorf("capability: marshal grants: %w", err)
	}
	if err := os.MkdirAll(filepath.Dir(g.path), 0o700); err != nil {
		return fmt.Errorf("capability: create state dir: %w", err)
	}
	if err := os.WriteFile(g.path, data, 0o600); err != nil {
		return fmt.Errorf("capability: write %s: %w", g.path, err)
	}
	return nil
}

// Allowed is default-deny: anything not explicitly granted true is refused.
func (g *Gate) Allowed(capability string) bool {
	g.mu.RLock()
	defer g.mu.RUnlock()
	return g.grants[capability]
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd apps/agent && go test ./internal/capability/... -v`
Expected: `PASS`.

- [ ] **Step 5: Wire the gate into the daemon**

```go
// apps/agent/cmd/cb-agent/main.go — inside runDaemon(), before constructing link.Options
	capGate := capability.New(config.StateDir())
	if err := capGate.LoadCached(); err != nil {
		fmt.Fprintf(os.Stderr, "cb-agent: %v\n", err)
	}
```

```go
// apps/agent/cmd/cb-agent/main.go — link.Options literal in runDaemon()
	if err := link.Run(ctx, link.Options{
		Config: cfg, Key: key, AgentVersion: AgentVersion,
		OnCapabilitiesSet: capGate.ApplyGrants,
	}); err != nil && ctx.Err() == nil {
```

Add `"circuitbreaker.dev/cb-agent/internal/capability"` to `main.go`'s import block.

- [ ] **Step 6: Build and commit**

Run: `cd apps/agent && go build -o /tmp/cb-agent ./cmd/cb-agent`
Expected: builds cleanly.

```bash
git add apps/agent/internal/capability apps/agent/cmd/cb-agent/main.go
git commit -m "feat(agent): capability gate — cached grants, default-deny"
```

---

### Task 14: Bounded spool — `internal/spool`

Per spec §1.1, `internal/spool` depends only on `config`. Slice 1 has no data-frame producer yet
(only control frames flow — hello/heartbeat/hello.ack/capabilities.set/ping/disconnect — and "only
data frames spool, control frames never do," per the global constraints), so nothing in this slice
calls `Enqueue` in production. This task delivers the primitive and proves it in isolation, ready
for slice 2's first collector.

The spec describes "append-only segments" (plural) for O(1) oldest-eviction; this task implements
the same observable contract — bounded size, oldest-dropped when full — as a single append-only
JSONL file instead, since a segment-rotation scheme has no caller to justify its complexity yet.
The public API (`Enqueue`/`Drain`/`Len`/`SizeBytes`) is what future collectors depend on, not the
storage layout, so swapping to real segment files later is a non-breaking internal change.

**Files:**
- Create: `apps/agent/internal/spool/spool.go`
- Create: `apps/agent/internal/spool/spool_test.go`

**Interfaces:**
- Consumes: `frame.Frame` (Task 3).
- Produces: `spool.DefaultCapBytes = 64 * 1024 * 1024`, `spool.DrainInterleaveRatio = 4` (one
  spooled frame per four live frames — the constant a future collector's interleaving loop will
  read; not consumed by anything in slice 1), `spool.Open(stateDir string, capBytes int64)
  (*Spool, error)`, `(*Spool) Enqueue(f frame.Frame) error`, `(*Spool) Drain() (frame.Frame, bool,
  error)` (oldest-first; `ok=false` when empty), `(*Spool) Len() int`, `(*Spool) SizeBytes()
  (int64, error)`, `(*Spool) Close() error`.

- [ ] **Step 1: Write the failing tests**

```go
// apps/agent/internal/spool/spool_test.go
package spool

import (
	"encoding/json"
	"testing"
	"time"

	"circuitbreaker.dev/cb-agent/internal/frame"
)

func testFrame(seq uint64) frame.Frame {
	return frame.Frame{V: 1, Type: "telemetry.host", Seq: seq, TS: time.Now().UTC(), Payload: json.RawMessage(`{}`)}
}

func TestEnqueueDrain_FIFO(t *testing.T) {
	s, err := Open(t.TempDir(), DefaultCapBytes)
	if err != nil {
		t.Fatalf("Open() error = %v", err)
	}
	defer s.Close()

	for i := uint64(0); i < 3; i++ {
		if err := s.Enqueue(testFrame(i)); err != nil {
			t.Fatalf("Enqueue(%d) error = %v", i, err)
		}
	}
	if got := s.Len(); got != 3 {
		t.Errorf("Len() = %d, want 3", got)
	}

	for i := uint64(0); i < 3; i++ {
		f, ok, err := s.Drain()
		if err != nil {
			t.Fatalf("Drain() error = %v", err)
		}
		if !ok {
			t.Fatalf("Drain() ok = false at i=%d, want true", i)
		}
		if f.Seq != i {
			t.Errorf("Drain() seq = %d, want %d (FIFO order)", f.Seq, i)
		}
	}

	_, ok, err := s.Drain()
	if err != nil {
		t.Fatalf("Drain() on empty spool error = %v", err)
	}
	if ok {
		t.Error("Drain() ok = true on empty spool, want false")
	}
}

func TestEnqueue_DropsOldestWhenOverCap(t *testing.T) {
	// A tiny cap that fits only a couple of frames, to exercise eviction
	// without a 64MB fixture.
	const tinyCap = 300
	s, err := Open(t.TempDir(), tinyCap)
	if err != nil {
		t.Fatalf("Open() error = %v", err)
	}
	defer s.Close()

	for i := uint64(0); i < 10; i++ {
		if err := s.Enqueue(testFrame(i)); err != nil {
			t.Fatalf("Enqueue(%d) error = %v", i, err)
		}
	}

	size, err := s.SizeBytes()
	if err != nil {
		t.Fatalf("SizeBytes() error = %v", err)
	}
	if size > tinyCap {
		t.Errorf("SizeBytes() = %d, want <= %d after eviction", size, tinyCap)
	}

	f, ok, err := s.Drain()
	if err != nil || !ok {
		t.Fatalf("Drain() = (%v, %v, %v), want a frame present", f, ok, err)
	}
	if f.Seq == 0 {
		t.Error("Drain() returned seq=0 — oldest frame should have been evicted, not the newest")
	}
}

func TestOpen_RecoversExistingQueueAfterReopen(t *testing.T) {
	dir := t.TempDir()
	first, err := Open(dir, DefaultCapBytes)
	if err != nil {
		t.Fatalf("Open() error = %v", err)
	}
	if err := first.Enqueue(testFrame(1)); err != nil {
		t.Fatalf("Enqueue() error = %v", err)
	}
	if err := first.Close(); err != nil {
		t.Fatalf("Close() error = %v", err)
	}

	second, err := Open(dir, DefaultCapBytes)
	if err != nil {
		t.Fatalf("re-Open() error = %v", err)
	}
	defer second.Close()
	if got := second.Len(); got != 1 {
		t.Errorf("Len() after reopen = %d, want 1 (unclean-shutdown recovery)", got)
	}
}
```

- [ ] **Step 2: Run it to see it fail to compile**

Run: `cd apps/agent && go test ./internal/spool/...`
Expected: `undefined: Open`.

- [ ] **Step 3: Implement `spool.go`**

```go
// apps/agent/internal/spool/spool.go
package spool

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sync"

	"circuitbreaker.dev/cb-agent/internal/frame"
)

const (
	DefaultCapBytes       int64 = 64 * 1024 * 1024
	DrainInterleaveRatio        = 4 // one spooled frame per four live frames
	queueFilename                = "queue.jsonl"
)

// Spool is a bounded, oldest-dropped, append-only queue for *data* frames
// only — control frames must never be enqueued (spec §4.4). Persisted as
// newline-delimited JSON so an unclean shutdown still recovers everything
// written before the crash.
type Spool struct {
	mu       sync.Mutex
	path     string
	capBytes int64
	entries  []frame.Frame
}

func Open(stateDir string, capBytes int64) (*Spool, error) {
	if err := os.MkdirAll(stateDir, 0o700); err != nil {
		return nil, fmt.Errorf("spool: create state dir: %w", err)
	}
	path := filepath.Join(stateDir, queueFilename)
	s := &Spool{path: path, capBytes: capBytes}
	if err := s.load(); err != nil {
		return nil, err
	}
	return s, nil
}

func (s *Spool) load() error {
	f, err := os.Open(s.path)
	if os.IsNotExist(err) {
		return nil
	}
	if err != nil {
		return fmt.Errorf("spool: open %s: %w", s.path, err)
	}
	defer f.Close()

	scanner := bufio.NewScanner(f)
	scanner.Buffer(make([]byte, 0, 64*1024), 1024*1024)
	for scanner.Scan() {
		fr, err := frame.Decode(scanner.Bytes())
		if err != nil {
			continue // skip a truncated final line from an unclean shutdown
		}
		s.entries = append(s.entries, fr)
	}
	return scanner.Err()
}

func (s *Spool) persist() error {
	tmp := s.path + ".tmp"
	f, err := os.OpenFile(tmp, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, 0o600)
	if err != nil {
		return fmt.Errorf("spool: create %s: %w", tmp, err)
	}
	w := bufio.NewWriter(f)
	for _, e := range s.entries {
		data, err := frame.Encode(e)
		if err != nil {
			f.Close()
			return fmt.Errorf("spool: encode: %w", err)
		}
		w.Write(data)
		w.WriteByte('\n')
	}
	if err := w.Flush(); err != nil {
		f.Close()
		return fmt.Errorf("spool: flush: %w", err)
	}
	if err := f.Close(); err != nil {
		return fmt.Errorf("spool: close: %w", err)
	}
	return os.Rename(tmp, s.path)
}

func (s *Spool) sizeBytesLocked() (int64, error) {
	var total int64
	for _, e := range s.entries {
		data, err := frame.Encode(e)
		if err != nil {
			return 0, err
		}
		total += int64(len(data)) + 1
	}
	return total, nil
}

// Enqueue appends f, evicting the oldest entries (FIFO) if the resulting
// queue would exceed capBytes. Only call this for data frames — see the
// package doc comment.
func (s *Spool) Enqueue(f frame.Frame) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	s.entries = append(s.entries, f)
	for {
		size, err := s.sizeBytesLocked()
		if err != nil {
			return err
		}
		if size <= s.capBytes || len(s.entries) <= 1 {
			break
		}
		s.entries = s.entries[1:]
	}
	return s.persist()
}

func (s *Spool) Drain() (frame.Frame, bool, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	if len(s.entries) == 0 {
		return frame.Frame{}, false, nil
	}
	f := s.entries[0]
	s.entries = s.entries[1:]
	if err := s.persist(); err != nil {
		return frame.Frame{}, false, err
	}
	return f, true, nil
}

func (s *Spool) Len() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	return len(s.entries)
}

func (s *Spool) SizeBytes() (int64, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.sizeBytesLocked()
}

func (s *Spool) Close() error {
	return nil // persist() already writes through on every mutation
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd apps/agent && go test ./internal/spool/... -v`
Expected: `PASS`.

- [ ] **Step 5: Commit**

```bash
git add apps/agent/internal/spool
git commit -m "feat(agent): bounded on-disk spool — FIFO, oldest-dropped"
```

---

### Task 15: UI presence channel — `WS /api/agents/stream`

Mirrors `ws_monitors.py`'s auth and `ws_discovery.py`'s `_redis_discovery_listener` pattern
exactly. This **cannot** be simplified to relying on the router-level `dependencies=[Depends
(require_auth)]` alone (applied to `authenticated_router` for defense-in-depth, same as the other
two routers) — a browser's native `WebSocket` constructor cannot set an `Authorization` header on
the handshake request, so a bearer-token session (no `cb_session` cookie) would never reach the
handler at all if header/cookie inspection at dependency-resolution time were the only check.
`ws_monitors.py` solves this with a **token-as-first-message fallback**: try the `cb_session`
cookie first (browsers attach cookies automatically even though they can't attach custom headers),
and if absent, wait up to 10s for the client's first text frame to *be* the raw token. This task
duplicates that exact protocol rather than inventing a new one, since Task 18's
`useAgentLive.js` needs to mirror `useMonitorStream.js`'s client-side half of the same handshake
(`ws.onopen` sends the token only when it isn't the `'cookie'` sentinel, then waits for
`{"status": "connected"}` before considering itself live).

**Files:**
- Modify: `apps/backend/src/app/core/subjects.py` (add `AGENT_EVENT`)
- Modify: `apps/backend/src/app/services/agent_registry.py` (add `broadcast_presence`)
- Modify: `apps/backend/src/app/api/agents.py` (approve/reject/revoke become `async def`, call
  `broadcast_presence`)
- Modify: `apps/backend/src/app/api/ws_agents.py` (add `/stream` to `authenticated_router`; call
  `broadcast_presence` from `/link`'s connect/disconnect points)
- Modify: `apps/frontend`... — none; frontend consumption is Task 18-19.
- Test: `apps/backend/tests/services/test_agent_registry_broadcast.py`
- Test: `apps/backend/tests/api/test_ws_agents_stream.py`

**Interfaces:**
- Consumes: `app.core.redis.get_redis`, `app.core.ws_manager.ws_manager` (`.broadcast(dict)`,
  `apps/backend/src/app/core/ws_manager.py:92`), `app.core.nats_client.nats_client`,
  `app.core.subjects.AGENT_EVENT`.
- Produces: `agent_registry.broadcast_presence(agent_id: int, event_type: str, detail: dict |
  None = None) -> None` (async). Nothing later in slice 1 depends on this — it's consumed
  entirely by the frontend's `useAgentLive.js` (Task 18) reading the `/stream` socket's JSON
  messages.

- [ ] **Step 1: Add the subject constant**

```python
# apps/backend/src/app/core/subjects.py — add near the Notifications/Alerts section
AGENT_EVENT = "agents.event"
```

- [ ] **Step 2: Write the failing `broadcast_presence` test**

```python
# apps/backend/tests/services/test_agent_registry_broadcast.py
import json
from unittest.mock import AsyncMock

import pytest

from app.services import agent_registry as svc


@pytest.mark.asyncio
async def test_broadcast_presence_publishes_to_redis_and_nats(monkeypatch):
    redis_client = AsyncMock()
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=redis_client))
    nats_publish = AsyncMock()
    monkeypatch.setattr("app.core.nats_client.nats_client.publish", nats_publish)
    ws_broadcast = AsyncMock()
    monkeypatch.setattr("app.core.ws_manager.ws_manager.broadcast", ws_broadcast)

    await svc.broadcast_presence(5, "connected", detail={"worker": "w1"})

    redis_client.publish.assert_called_once()
    channel, payload = redis_client.publish.call_args[0]
    assert channel == "cb:agents:events"
    body = json.loads(payload)
    assert body == {"agent_id": 5, "event_type": "connected", "detail": {"worker": "w1"}}

    nats_publish.assert_called_once()
    ws_broadcast.assert_called_once()


@pytest.mark.asyncio
async def test_broadcast_presence_falls_back_to_ws_manager_when_redis_unavailable(monkeypatch):
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=None))
    nats_publish = AsyncMock()
    monkeypatch.setattr("app.core.nats_client.nats_client.publish", nats_publish)
    ws_broadcast = AsyncMock()
    monkeypatch.setattr("app.core.ws_manager.ws_manager.broadcast", ws_broadcast)

    await svc.broadcast_presence(5, "disconnected")

    ws_broadcast.assert_called_once()
    body = ws_broadcast.call_args[0][0]
    assert body["agent_id"] == 5
    assert body["event_type"] == "disconnected"
```

- [ ] **Step 3: Run it to see it fail**

Run: `cd apps/backend && pytest tests/services/test_agent_registry_broadcast.py -v`
Expected: `AttributeError: module ... has no attribute 'broadcast_presence'`.

- [ ] **Step 4: Implement `broadcast_presence`**

Append to `apps/backend/src/app/services/agent_registry.py` (mirrors
`discovery_service.py`'s `_emit_ws_event` triple-path pattern — Redis pub/sub primary, direct
`ws_manager.broadcast` fallback, NATS always-attempted):

```python
_AGENTS_REDIS_CHANNEL = "cb:agents:events"


async def broadcast_presence(agent_id: int, event_type: str, detail: dict | None = None) -> None:
    from app.core import subjects
    from app.core.nats_client import nats_client
    from app.core.redis import get_redis
    from app.core.ws_manager import ws_manager

    message = {"agent_id": agent_id, "event_type": event_type, "detail": detail}

    delivered_locally = False
    try:
        r = await get_redis()
        if r is not None:
            await r.publish(_AGENTS_REDIS_CHANNEL, json.dumps(message, default=str))
        else:
            await ws_manager.broadcast(message)
            delivered_locally = True
    except Exception as exc:
        _logger.debug("agent presence broadcast (redis) failed: %s", exc)
        if not delivered_locally:
            try:
                await ws_manager.broadcast(message)
            except Exception:
                pass

    try:
        await nats_client.publish(subjects.AGENT_EVENT, message)
    except Exception as exc:
        _logger.debug("agent presence broadcast (nats) failed: %s", exc)
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd apps/backend && pytest tests/services/test_agent_registry_broadcast.py -v`
Expected: 2 passed.

- [ ] **Step 6: Call `broadcast_presence` from the approve/reject/revoke endpoints**

In `apps/backend/src/app/api/agents.py`, change `post_approve`, `post_reject`, and `post_revoke`
to `async def` and add a broadcast call after each registry mutation:

```python
@router.post("/{agent_id}/approve", response_model=AgentRead)
async def post_approve(
    agent_id: int,
    payload: ApproveRequest,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, require_role("admin")],
) -> Any:
    agent = agent_registry.approve_agent(
        db, agent_id, approving_user_id=user.id,
        hardware_id=payload.hardware_id, capability_overrides=payload.capabilities,
    )
    await agent_registry.broadcast_presence(agent_id, "approved")
    return _to_read(db, agent)
```

Apply the same shape (`async def`, `await agent_registry.broadcast_presence(agent_id,
"rejected"|"revoked")` after the mutation) to `post_reject` and `post_revoke`.

- [ ] **Step 7: Call `broadcast_presence` from `/link`'s connect/disconnect**

In `apps/backend/src/app/api/ws_agents.py`'s `link_stream` (Task 12), add one call right after
`agent_registry.record_event(db, agent_id, "connected")`'s block:

```python
    worker = socket.gethostname()
    await agent_registry.mark_presence_connected(agent_id, worker=worker)
    await agent_registry.broadcast_presence(agent_id, "connected")
    await websocket.send_bytes(_capabilities_bytes(responder, grants))
```

and one in the `finally` block, right after `mark_presence_disconnected`:

```python
    finally:
        await agent_registry.mark_presence_disconnected(agent_id)
        await agent_registry.broadcast_presence(agent_id, "disconnected")
        with SessionLocal() as db:
```

- [ ] **Step 8: Write the failing `/stream` test**

```python
# apps/backend/tests/api/test_ws_agents_stream.py
import json


def test_stream_rejects_connection_with_no_cookie_and_auth_timeout(ws_client):
    from starlette.websockets import WebSocketDisconnect
    import pytest

    with pytest.raises(WebSocketDisconnect):
        with ws_client.websocket_connect("/api/v1/agents/stream") as ws:
            # No cookie present (TestClient doesn't set one) and we never send
            # a first-message token — server closes 1008 after its 10s wait.
            # This test relies on the implementation's auth-timeout branch
            # firing quickly in the test environment; if the real 10s
            # `asyncio.wait_for` timeout makes this test too slow, temporarily
            # monkeypatch a shorter timeout constant the same way Task 11's
            # `heartbeatInterval` var was made test-overridable, rather than
            # actually sleeping 10s per test run.
            ws.receive_text()


def test_stream_authenticates_via_first_message_token_and_forwards_broadcast(
    ws_client, viewer_token, monkeypatch
):
    # Redis is unavailable in the unit-test environment, so /stream falls back
    # to receiving pushes directly from ws_manager.broadcast — proven here;
    # the Redis pub/sub cross-worker path mirrors ws_discovery.py's already
    # battle-tested `_redis_discovery_listener` and isn't re-proven per route.
    from unittest.mock import AsyncMock

    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=None))

    with ws_client.websocket_connect("/api/v1/agents/stream") as ws:
        ws.send_text(viewer_token)
        ack = json.loads(ws.receive_text())
        assert ack["status"] == "connected"

        from app.core.ws_manager import ws_manager
        import anyio.from_thread

        anyio.from_thread.run(
            ws_manager.broadcast, {"agent_id": 9, "event_type": "connected", "detail": None}
        )
        msg = json.loads(ws.receive_text())
        assert msg["agent_id"] == 9
        assert msg["event_type"] == "connected"
```

> **Verification note for the implementer:** `viewer_token` is assumed to be the fixture exposing
> the raw JWT string that `viewer_headers` wraps as `Authorization: Bearer <token>` (per
> `conftest.py`'s fixture list, research item 7) — confirm the exact fixture name. Bridging from
> the sync `TestClient` context back into the ASGI app's async loop to call `ws_manager.broadcast`
> needs whatever mechanism the installed Starlette/anyio version's `TestClient` documents for this
> (`anyio.from_thread.run` is shown above as the modern replacement for the deprecated
> `asyncio.get_event_loop().run_until_complete(...)` pattern) — verify against the installed
> version and adjust if the API differs.

- [ ] **Step 9: Run it to see it fail**

Run: `cd apps/backend && pytest tests/api/test_ws_agents_stream.py -v`
Expected: `/stream` doesn't exist yet — connection refused/404.

- [ ] **Step 10: Implement `/stream`**

```python
# apps/backend/src/app/api/ws_agents.py — additional imports
from starlette.websockets import WebSocketState

from app.core.auth_cookie import is_websocket_secure, token_from_websocket_scope, ws_require_wss
from app.core.security import decode_token
from app.db.models import User
from app.services.settings_service import get_or_create_settings
from app.services.user_service import is_session_revoked
```

```python
# apps/backend/src/app/api/ws_agents.py — append
async def _redis_agent_listener(websocket: WebSocket, stop_event: asyncio.Event) -> None:
    """Mirrors ws_discovery.py's _redis_discovery_listener — see that
    docstring for why Redis pub/sub is the primary cross-worker path."""
    from app.core.redis import get_redis

    r = await get_redis()
    if r is None:
        await stop_event.wait()
        return

    pubsub = r.pubsub()
    try:
        await pubsub.subscribe("cb:agents:events")
        while not stop_event.is_set():
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if msg and msg["type"] == "message":
                if websocket.application_state == WebSocketState.DISCONNECTED:
                    break
                try:
                    await websocket.send_text(msg["data"])
                except Exception:
                    break
    except asyncio.CancelledError:
        pass
    finally:
        try:
            await pubsub.unsubscribe()
            await pubsub.aclose()
        except Exception:
            pass


@authenticated_router.websocket("/stream")
async def agent_presence_stream(websocket: WebSocket) -> None:
    """Token-as-first-message auth — see ws_monitors.py's monitor_stream for
    the identical protocol this duplicates. Router-level Depends(require_auth)
    is defense-in-depth only; a bearer-token (no-cookie) client can never
    satisfy it during the handshake, so this handler is the real gate."""
    await websocket.accept()

    if ws_require_wss() and not is_websocket_secure(dict(websocket.scope)):
        await websocket.close(code=1008)
        return

    raw_token = token_from_websocket_scope(dict(websocket.scope))
    if not raw_token:
        try:
            raw_token = await asyncio.wait_for(websocket.receive_text(), timeout=10.0)
        except TimeoutError:
            await websocket.send_text(json.dumps({"error": "auth_timeout"}))
            await websocket.close(code=1008)
            return
        except WebSocketDisconnect:
            return

    authenticated = False
    with SessionLocal() as db:
        cfg = get_or_create_settings(db)
        if cfg.jwt_secret and not is_session_revoked(db, raw_token):
            uid = decode_token(raw_token, cfg.jwt_secret)
            if uid is not None:
                u = db.get(User, uid)
                authenticated = bool(u and u.is_active)

    if not authenticated:
        await websocket.send_text(json.dumps({"error": "unauthorized"}))
        await websocket.close(code=1008)
        return

    from app.core.ws_manager import ws_manager

    accepted = await ws_manager.connect(websocket)
    if not accepted:
        await websocket.close(code=1008)
        return

    await websocket.send_text(json.dumps({"status": "connected"}))

    stop_event = asyncio.Event()
    listener = asyncio.create_task(_redis_agent_listener(websocket, stop_event))
    try:
        while True:
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
            except TimeoutError:
                continue
            except WebSocketDisconnect:
                break
    finally:
        stop_event.set()
        listener.cancel()
        ws_manager.disconnect(websocket)
```

> `ws_manager.broadcast(message)` (the fallback path used when Redis is unavailable) sends
> directly to every connection registered via `ws_manager.connect(...)` — check
> `ConnectionManager.broadcast`'s exact signature at `core/ws_manager.py:92` and
> `ConnectionManager`'s disconnect method name (assumed `disconnect(websocket)` above by analogy
> with `connect`; confirm against the file before trusting this verbatim) while implementing this
> step. This implementation deliberately omits `ws_monitors.py`'s CIDR-whitelist check
> (`_is_ip_in_cidrs`) — that's a monitor-specific setting (`ws_allowed_cidrs`) with no agent
> equivalent in this spec; add it only if a future slice introduces one.

- [ ] **Step 11: Run the tests to verify they pass**

Run: `cd apps/backend && pytest tests/api/test_ws_agents_stream.py tests/services/test_agent_registry_broadcast.py tests/api/test_agents_api.py -v`
Expected: all passed (rerun `test_agents_api.py` too since Step 6 changed three of its routes to
`async def`).

- [ ] **Step 12: Commit**

```bash
git add apps/backend/src/app/core/subjects.py apps/backend/src/app/services/agent_registry.py \
        apps/backend/src/app/api/agents.py apps/backend/src/app/api/ws_agents.py \
        apps/backend/tests/services/test_agent_registry_broadcast.py \
        apps/backend/tests/api/test_ws_agents_stream.py
git commit -m "feat(agents): WS /api/agents/stream — live presence for the UI"
```

---

### Task 16: Self-update — trigger, download, verify, swap, rollback

The trigger is queued in Redis (`agent_pending_update:{agent_id}`) rather than pushed to a
specific in-process WS connection, for the same cross-worker reason Task 12 polls for revocation:
the admin's REST request and the agent's live `/link` socket may be handled by different Uvicorn
workers. The `/link` poll loop (Task 12, every 5s) already checks agent status on every timeout
tick — this task adds one more check alongside it, so an update is picked up within roughly the
same latency window as a revoke.

**Files:**
- Create: `apps/backend/src/app/services/agent_update.py`
- Modify: `apps/backend/src/app/api/agents.py` (add `POST /{agent_id}/update`, add an
  unauthenticated `binary_router` with `GET /binary/{version}/{os}/{arch}`)
- Modify: `apps/backend/src/app/api/ws_agents.py` (`/link`'s poll-timeout branch also checks
  `agent_update.pop_pending_update`)
- Modify: `apps/backend/src/app/main.py` (register `binary_router` without `require_auth`)
- Create: `apps/agent/internal/update/update.go`
- Create: `apps/agent/internal/update/update_test.go`
- Modify: `apps/agent/internal/link/link.go` (add `Options.OnUpdate` and `Options.OnConnected`
  callbacks)
- Modify: `apps/agent/cmd/cb-agent/main.go` (wire the update watchdog and re-exec)
- Test: `apps/backend/tests/services/test_agent_update.py`

**Interfaces:**
- Consumes (Python): `app.core.redis.get_redis`, `agent_registry.get_agent`/`record_event`.
- Produces (Python): `agent_update.AGENT_BINARIES_DIR` (env-overridable via
  `CB_AGENT_BINARIES_DIR`, defaulting to `/opt/circuitbreaker/agent-binaries`),
  `agent_update.load_manifest() -> dict`, `agent_update.get_binary_sha256(version, os, arch) ->
  str | None`, `agent_update.binary_path(version, os, arch) -> Path`,
  `agent_update.latest_version() -> str | None`, `agent_update.request_update(agent_id, version,
  sha256, arch, os) -> None` (async), `agent_update.pop_pending_update(agent_id) -> dict | None`
  (async, single-use). Task 17's Makefile packaging target is what actually populates
  `AGENT_BINARIES_DIR`/`manifest.json` in a real deployment — this task's tests use a temp
  directory with hand-written fixture binaries, so it does not need Task 17 to exist first.
- Produces (Go): `update.Instruction{Version, SHA256, Arch, OS string}`,
  `update.Download(cfg *config.Config, instr Instruction) (tmpPath string, err error)`,
  `update.VerifySHA256(path, want string) error`, `update.Swap(newPath, targetPath string)
  (backupPath string, err error)`, `update.Rollback(targetPath string) error`,
  `update.WriteMarker(stateDir, targetVersion string) error`, `update.ReadMarker(stateDir string)
  (version string, present bool, err error)`, `update.ClearMarker(stateDir string) error`. Adds
  `link.Options.OnUpdate func(json.RawMessage) error` and `link.Options.OnConnected func()`
  (fires once per successful handshake) to Task 11's package.

- [ ] **Step 1: Write the failing `agent_update.py` tests**

```python
# apps/backend/tests/services/test_agent_update.py
import json
from unittest.mock import AsyncMock

import pytest


def test_get_binary_sha256_reads_manifest(tmp_path, monkeypatch):
    from app.services import agent_update as svc

    monkeypatch.setattr(svc, "AGENT_BINARIES_DIR", tmp_path)
    manifest = {"0.2.0": {"linux-amd64": "abc123"}}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))

    assert svc.get_binary_sha256("0.2.0", "linux", "amd64") == "abc123"
    assert svc.get_binary_sha256("0.2.0", "linux", "arm64") is None
    assert svc.get_binary_sha256("9.9.9", "linux", "amd64") is None


def test_get_binary_sha256_missing_manifest_returns_none(tmp_path, monkeypatch):
    from app.services import agent_update as svc

    monkeypatch.setattr(svc, "AGENT_BINARIES_DIR", tmp_path)
    assert svc.get_binary_sha256("0.2.0", "linux", "amd64") is None


def test_latest_version_picks_highest_sorted_key(tmp_path, monkeypatch):
    from app.services import agent_update as svc

    monkeypatch.setattr(svc, "AGENT_BINARIES_DIR", tmp_path)
    manifest = {"0.1.0": {}, "0.10.0": {}, "0.2.0": {}}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))

    # NOTE: plain string sort, not semver-aware — "0.10.0" < "0.2.0"
    # lexicographically. Acceptable for slice 1 since the packaging step
    # (Task 17) controls version string formatting; flag this as a known
    # limitation rather than pulling in a semver library for one comparison.
    assert svc.latest_version() == "0.2.0"


@pytest.mark.asyncio
async def test_request_then_pop_pending_update(monkeypatch):
    from app.services import agent_update as svc

    store: dict[str, str] = {}
    redis_client = AsyncMock()
    redis_client.set.side_effect = lambda k, v: store.__setitem__(k, v)
    redis_client.get.side_effect = lambda k: store.get(k)
    redis_client.delete.side_effect = lambda k: store.pop(k, None)
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=redis_client))

    await svc.request_update(5, version="0.2.0", sha256="abc123", arch="amd64", os_name="linux")
    instr = await svc.pop_pending_update(5)

    assert instr == {"version": "0.2.0", "sha256": "abc123", "arch": "amd64", "os": "linux"}
    assert await svc.pop_pending_update(5) is None  # single-use
```

- [ ] **Step 2: Run it to see it fail**

Run: `cd apps/backend && pytest tests/services/test_agent_update.py -v`
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `agent_update.py`**

```python
# apps/backend/src/app/services/agent_update.py
"""Self-update: binary manifest lookup and Redis-queued update triggers.

The manifest and binaries themselves are populated by the packaging build
step (apps/agent's Makefile target) — this module only reads them."""

from __future__ import annotations

import json
import os
from pathlib import Path

AGENT_BINARIES_DIR = Path(os.getenv("CB_AGENT_BINARIES_DIR", "/opt/circuitbreaker/agent-binaries"))


def load_manifest() -> dict:
    path = AGENT_BINARIES_DIR / "manifest.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def get_binary_sha256(version: str, os_name: str, arch: str) -> str | None:
    return load_manifest().get(version, {}).get(f"{os_name}-{arch}")


def binary_path(version: str, os_name: str, arch: str) -> Path:
    return AGENT_BINARIES_DIR / version / f"cb-agent-{os_name}-{arch}"


def latest_version() -> str | None:
    manifest = load_manifest()
    if not manifest:
        return None
    return sorted(manifest.keys())[-1]


async def request_update(agent_id: int, *, version: str, sha256: str, arch: str, os_name: str) -> None:
    from app.core.redis import get_redis

    r = await get_redis()
    if r is None:
        raise RuntimeError("Redis unavailable — cannot queue an agent update")
    payload = json.dumps({"version": version, "sha256": sha256, "arch": arch, "os": os_name})
    await r.set(f"agent_pending_update:{agent_id}", payload)


async def pop_pending_update(agent_id: int) -> dict | None:
    from app.core.redis import get_redis

    r = await get_redis()
    if r is None:
        return None
    key = f"agent_pending_update:{agent_id}"
    val = await r.get(key)
    if val is None:
        return None
    await r.delete(key)
    return json.loads(val)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd apps/backend && pytest tests/services/test_agent_update.py -v`
Expected: 4 passed.

- [ ] **Step 5: Add the REST trigger and binary-serving routes**

```python
# apps/backend/src/app/api/agents.py — additional imports
from fastapi.responses import FileResponse

from app.services import agent_update
```

```python
# apps/backend/src/app/api/agents.py — schemas addition (put in schemas/agents.py instead)
class UpdateRequest(BaseModel):
    version: str | None = None
```

```python
# apps/backend/src/app/api/agents.py — append to `router`
@router.post("/{agent_id}/update")
async def post_update(
    agent_id: int,
    payload: UpdateRequest,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, require_role("admin")],
) -> Any:
    agent = agent_registry.get_agent(db, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    version = payload.version or agent_update.latest_version()
    if version is None:
        raise HTTPException(status_code=400, detail="No agent binaries available on this instance")

    sha256 = agent_update.get_binary_sha256(version, agent.os or "linux", agent.arch or "amd64")
    if sha256 is None:
        raise HTTPException(
            status_code=404,
            detail=f"No binary for {agent.os}/{agent.arch} at version {version}",
        )

    await agent_update.request_update(
        agent_id, version=version, sha256=sha256, arch=agent.arch or "amd64", os_name=agent.os or "linux",
    )
    agent_registry.record_event(
        db, agent_id, "version_changed", actor_user_id=user.id, detail={"target_version": version},
    )
    return {"status": "queued", "version": version}


# Unauthenticated — the agent has no user session; integrity comes from the
# SHA-256 delivered over the Noise-encrypted link, not from route auth.
binary_router = APIRouter(tags=["agents-binary"])


@binary_router.get("/binary/{version}/{os_name}/{arch}")
def get_binary(version: str, os_name: str, arch: str) -> FileResponse:
    path = agent_update.binary_path(version, os_name, arch)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Binary not found")
    return FileResponse(path, media_type="application/octet-stream", filename=path.name)
```

Add `UpdateRequest` to `schemas/agents.py` next to `RevokeRequest`.

- [ ] **Step 6: Register `binary_router` without `require_auth`**

```python
# apps/backend/src/app/main.py — imports
from app.api.agents import binary_router as agents_binary_router
```

```python
# apps/backend/src/app/main.py — registration, deliberately no dependencies=[Depends(require_auth)]
app.include_router(agents_binary_router, prefix=f"{_V1}/agents", tags=["agents-binary"])
```

- [ ] **Step 7: Check the pending-update queue from `/link`'s poll loop**

In `apps/backend/src/app/api/ws_agents.py`'s `link_stream` (Task 12), inside the `TimeoutError`
branch, alongside the existing status check:

```python
            except TimeoutError:
                if (datetime.utcnow() - last_activity).total_seconds() >= _LINK_DEAD_SECONDS:
                    break
                with SessionLocal() as db:
                    fresh = agent_registry.get_agent(db, agent_id)
                    if fresh is None or fresh.status != "active":
                        break
                pending = await agent_update.pop_pending_update(agent_id)
                if pending is not None:
                    update_frame = {
                        "v": 1, "type": TYPE_UPDATE, "seq": 0,
                        "ts": datetime.utcnow().isoformat(), "payload": pending,
                    }
                    await websocket.send_bytes(responder.encrypt(json.dumps(update_frame).encode()))
                continue
```

Add `from app.services import agent_update` and `from app.schemas.agent_frame import
TYPE_UPDATE` (alongside the existing `TYPE_CAPABILITIES_SET` import) to `ws_agents.py`.

- [ ] **Step 8: Run the backend tests to verify nothing regressed**

Run: `cd apps/backend && pytest tests/api/test_agents_api.py tests/api/test_ws_agents_link.py tests/services/test_agent_update.py -v`
Expected: all passed.

- [ ] **Step 9: Add `OnUpdate`/`OnConnected` hooks to the Go link loop**

In `apps/agent/internal/link/link.go` (Task 11), extend `Options`:

```go
type Options struct {
	Config            *config.Config
	Key               *enroll.DeviceKey
	AgentVersion      string
	OnCapabilitiesSet func(json.RawMessage) error
	OnUpdate          func(json.RawMessage) error
	OnConnected       func()
}
```

and in `runOnce`, right after the handshake completes (after `session.ReadHandshakeMessage(msg2)`
succeeds) and once more in the frame-handling switch:

```go
	if opts.OnConnected != nil {
		opts.OnConnected()
	}
```

```go
			case frame.TypeUpdate:
				if opts.OnUpdate != nil {
					if err := opts.OnUpdate(f.Payload); err != nil {
						log.Printf("link: update failed: %v", err)
					}
				}
```

Default both new callbacks to no-ops in `Run` alongside the existing `OnCapabilitiesSet`
nil-check.

- [ ] **Step 10: Write the failing Go update-mechanics tests**

```go
// apps/agent/internal/update/update_test.go
package update

import (
	"crypto/sha256"
	"encoding/hex"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"

	"circuitbreaker.dev/cb-agent/internal/config"
)

func TestDownloadAndVerify_RoundTrips(t *testing.T) {
	content := []byte("fake binary contents")
	sum := sha256.Sum256(content)
	wantHash := hex.EncodeToString(sum[:])

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Write(content)
	}))
	defer srv.Close()

	cfg := &config.Config{ServerURL: srv.URL}
	instr := Instruction{Version: "0.2.0", SHA256: wantHash, Arch: "amd64", OS: "linux"}

	tmpPath, err := Download(cfg, instr)
	if err != nil {
		t.Fatalf("Download() error = %v", err)
	}
	defer os.Remove(tmpPath)

	if err := VerifySHA256(tmpPath, wantHash); err != nil {
		t.Fatalf("VerifySHA256() error = %v, want nil", err)
	}
	if err := VerifySHA256(tmpPath, "0000"); err == nil {
		t.Fatal("VerifySHA256() with wrong hash = nil error, want an error")
	}
}

func TestSwapAndRollback(t *testing.T) {
	dir := t.TempDir()
	target := filepath.Join(dir, "cb-agent")
	if err := os.WriteFile(target, []byte("old binary"), 0o755); err != nil {
		t.Fatal(err)
	}
	newBinary := filepath.Join(dir, "new-download")
	if err := os.WriteFile(newBinary, []byte("new binary"), 0o755); err != nil {
		t.Fatal(err)
	}

	backupPath, err := Swap(newBinary, target)
	if err != nil {
		t.Fatalf("Swap() error = %v", err)
	}
	got, _ := os.ReadFile(target)
	if string(got) != "new binary" {
		t.Errorf("target contents = %q, want %q", got, "new binary")
	}

	if err := Rollback(target); err != nil {
		t.Fatalf("Rollback() error = %v", err)
	}
	got, _ = os.ReadFile(target)
	if string(got) != "old binary" {
		t.Errorf("target contents after rollback = %q, want %q", got, "old binary")
	}
	if _, err := os.Stat(backupPath); !os.IsNotExist(err) {
		t.Errorf("backup file %s still exists after rollback, want removed", backupPath)
	}
}

func TestMarker_WriteReadClear(t *testing.T) {
	dir := t.TempDir()

	if _, present, err := ReadMarker(dir); err != nil || present {
		t.Fatalf("ReadMarker() on fresh dir = (_, %v, %v), want (_, false, nil)", present, err)
	}

	if err := WriteMarker(dir, "0.2.0"); err != nil {
		t.Fatalf("WriteMarker() error = %v", err)
	}
	version, present, err := ReadMarker(dir)
	if err != nil || !present || version != "0.2.0" {
		t.Fatalf("ReadMarker() = (%q, %v, %v), want (\"0.2.0\", true, nil)", version, present, err)
	}

	if err := ClearMarker(dir); err != nil {
		t.Fatalf("ClearMarker() error = %v", err)
	}
	if _, present, _ := ReadMarker(dir); present {
		t.Error("marker still present after ClearMarker()")
	}
}
```

- [ ] **Step 11: Run it to see it fail to compile**

Run: `cd apps/agent && go test ./internal/update/...`
Expected: `undefined: Download`.

- [ ] **Step 12: Implement `update.go`**

```go
// apps/agent/internal/update/update.go
package update

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"

	"circuitbreaker.dev/cb-agent/internal/config"
)

type Instruction struct {
	Version string `json:"version"`
	SHA256  string `json:"sha256"`
	Arch    string `json:"arch"`
	OS      string `json:"os"`
}

const markerFilename = "update_pending"

func Download(cfg *config.Config, instr Instruction) (string, error) {
	url := fmt.Sprintf("%s/api/v1/agents/binary/%s/%s/%s", strings.TrimRight(cfg.ServerURL, "/"), instr.Version, instr.OS, instr.Arch)
	resp, err := http.Get(url)
	if err != nil {
		return "", fmt.Errorf("update: download %s: %w", url, err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("update: download %s: status %d", url, resp.StatusCode)
	}

	tmp, err := os.CreateTemp("", "cb-agent-update-*")
	if err != nil {
		return "", fmt.Errorf("update: create temp file: %w", err)
	}
	defer tmp.Close()

	if _, err := io.Copy(tmp, resp.Body); err != nil {
		os.Remove(tmp.Name())
		return "", fmt.Errorf("update: write temp file: %w", err)
	}
	if err := tmp.Chmod(0o755); err != nil {
		os.Remove(tmp.Name())
		return "", fmt.Errorf("update: chmod temp file: %w", err)
	}
	return tmp.Name(), nil
}

func VerifySHA256(path, want string) error {
	f, err := os.Open(path)
	if err != nil {
		return fmt.Errorf("update: open %s: %w", path, err)
	}
	defer f.Close()

	h := sha256.New()
	if _, err := io.Copy(h, f); err != nil {
		return fmt.Errorf("update: hash %s: %w", path, err)
	}
	got := hex.EncodeToString(h.Sum(nil))
	if got != want {
		return fmt.Errorf("update: sha256 mismatch: got %s, want %s", got, want)
	}
	return nil
}

// Swap backs up targetPath to targetPath+".previous" and moves newPath into
// targetPath. Returns the backup path for Rollback.
func Swap(newPath, targetPath string) (string, error) {
	backupPath := targetPath + ".previous"
	if err := os.Rename(targetPath, backupPath); err != nil {
		return "", fmt.Errorf("update: back up current binary: %w", err)
	}
	if err := os.Rename(newPath, targetPath); err != nil {
		os.Rename(backupPath, targetPath) // best-effort restore
		return "", fmt.Errorf("update: install new binary: %w", err)
	}
	return backupPath, nil
}

func Rollback(targetPath string) error {
	backupPath := targetPath + ".previous"
	if err := os.Rename(backupPath, targetPath); err != nil {
		return fmt.Errorf("update: rollback: %w", err)
	}
	return nil
}

func WriteMarker(stateDir, targetVersion string) error {
	return os.WriteFile(filepath.Join(stateDir, markerFilename), []byte(targetVersion), 0o600)
}

func ReadMarker(stateDir string) (string, bool, error) {
	data, err := os.ReadFile(filepath.Join(stateDir, markerFilename))
	if os.IsNotExist(err) {
		return "", false, nil
	}
	if err != nil {
		return "", false, fmt.Errorf("update: read marker: %w", err)
	}
	return string(data), true, nil
}

func ClearMarker(stateDir string) error {
	err := os.Remove(filepath.Join(stateDir, markerFilename))
	if err != nil && !os.IsNotExist(err) {
		return fmt.Errorf("update: clear marker: %w", err)
	}
	return nil
}
```

- [ ] **Step 13: Run the tests to verify they pass**

Run: `cd apps/agent && go test ./internal/update/... -v`
Expected: `PASS`.

- [ ] **Step 14: Wire the watchdog and re-exec into `runDaemon`**

```go
// apps/agent/cmd/cb-agent/main.go — inside runDaemon(), after loading cfg/key/capGate
	binaryPath, err := os.Executable()
	if err != nil {
		fmt.Fprintf(os.Stderr, "cb-agent: %v\n", err)
		os.Exit(1)
	}

	if pendingVersion, present, _ := update.ReadMarker(config.StateDir()); present {
		log.Printf("cb-agent: resuming after update to %s — watching for a successful link", pendingVersion)
		go func() {
			time.Sleep(2 * time.Minute)
			if v, stillPresent, _ := update.ReadMarker(config.StateDir()); stillPresent && v == pendingVersion {
				log.Printf("cb-agent: update to %s did not confirm within 2 minutes — rolling back", pendingVersion)
				if err := update.Rollback(binaryPath); err != nil {
					log.Printf("cb-agent: rollback failed: %v", err)
					return
				}
				update.ClearMarker(config.StateDir())
				syscall.Exec(binaryPath, os.Args, os.Environ())
			}
		}()
	}

	var confirmOnce sync.Once
	onConnected := func() {
		confirmOnce.Do(func() {
			update.ClearMarker(config.StateDir())
		})
	}

	onUpdate := func(payload json.RawMessage) error {
		var instr update.Instruction
		if err := json.Unmarshal(payload, &instr); err != nil {
			return err
		}
		tmpPath, err := update.Download(cfg, instr)
		if err != nil {
			return err
		}
		if err := update.VerifySHA256(tmpPath, instr.SHA256); err != nil {
			os.Remove(tmpPath)
			return err
		}
		if _, err := update.Swap(tmpPath, binaryPath); err != nil {
			return err
		}
		if err := update.WriteMarker(config.StateDir(), instr.Version); err != nil {
			return err
		}
		log.Printf("cb-agent: updated to %s — re-executing", instr.Version)
		return syscall.Exec(binaryPath, os.Args, os.Environ())
	}
```

```go
// apps/agent/cmd/cb-agent/main.go — link.Options literal in runDaemon()
	if err := link.Run(ctx, link.Options{
		Config: cfg, Key: key, AgentVersion: AgentVersion,
		OnCapabilitiesSet: capGate.ApplyGrants,
		OnUpdate:          onUpdate,
		OnConnected:       onConnected,
	}); err != nil && ctx.Err() == nil {
```

Add `"sync"`, `"time"`, `"log"`, and `"circuitbreaker.dev/cb-agent/internal/update"` to `main.go`'s
import block.

- [ ] **Step 15: Build and commit**

Run: `cd apps/agent && go build -o /tmp/cb-agent ./cmd/cb-agent`
Expected: builds cleanly.

```bash
git add apps/backend/src/app/services/agent_update.py apps/backend/src/app/api/agents.py \
        apps/backend/src/app/api/ws_agents.py apps/backend/src/app/main.py \
        apps/backend/src/app/schemas/agents.py apps/backend/tests/services/test_agent_update.py \
        apps/agent/internal/link/link.go apps/agent/internal/update apps/agent/cmd/cb-agent/main.go
git commit -m "feat(agents): self-update — trigger, download, verify, swap, rollback"
```

---

### Task 17: Install script generation, systemd unit, and packaging

The install script runs `cb-agent enroll` **in the foreground** before enabling the systemd unit,
so the fingerprint and pairing code the user needs to compare against the approval screen (spec
§5.2) print directly to the terminal they ran `curl | sudo sh` in — matching the spec's UX
narrative literally, rather than requiring a `journalctl` detour. Once `enroll` returns (approval
granted), the script hands off to systemd for persistent operation.

**Files:**
- Create: `apps/backend/src/app/services/agent_install.py`
- Modify: `apps/backend/src/app/schemas/agents.py` (add `InstallCommandResponse`)
- Modify: `apps/backend/src/app/api/agents.py` (add `GET /install-command`, admin)
- Modify: `apps/backend/src/app/main.py` (mount the unauthenticated `GET /install-agent.sh` at
  root, outside `/api/v1`)
- Create: `apps/agent/Makefile`
- Test: `apps/backend/tests/services/test_agent_install.py`

**Interfaces:**
- Consumes: `agent_crypto.get_server_static_keypair`/`server_fingerprint` (Task 2),
  `agent_update.load_manifest` (Task 16), `app.db.models.Certificate`, `app.db.models.AppSettings`.
- Produces: `agent_install.render_install_script(*, server_url, server_static_pk_hex, tls_pin,
  manifest) -> str`, `agent_install.build_install_command(db, server_url) -> InstallCommandResponse`.
  Nothing later in slice 1 depends on this — it's the last piece the frontend's add-agent modal
  (Task 19) displays.

- [ ] **Step 1: Write the failing tests**

```python
# apps/backend/tests/services/test_agent_install.py
from app.services import agent_install


def test_render_install_script_embeds_server_identity():
    script = agent_install.render_install_script(
        server_url="https://cb.example.com",
        server_static_pk_hex="ab" * 32,
        tls_pin="c" * 44,
        manifest={"0.1.0": {"linux-amd64": "deadbeef", "linux-arm64": "beadfeed"}},
    )
    assert "https://cb.example.com" in script
    assert "ab" * 32 in script
    assert "c" * 44 in script
    assert "deadbeef" in script
    assert "cb-agent enroll" in script
    assert "systemctl enable --now cb-agent" in script


def test_render_install_script_is_valid_bash_syntax(tmp_path):
    import subprocess

    script = agent_install.render_install_script(
        server_url="https://cb.example.com", server_static_pk_hex="ab" * 32,
        tls_pin="c" * 44, manifest={"0.1.0": {"linux-amd64": "deadbeef"}},
    )
    script_path = tmp_path / "install-agent.sh"
    script_path.write_text(script)

    result = subprocess.run(["bash", "-n", str(script_path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_build_install_command_self_signed_includes_hash_verification(db_session):
    resp = agent_install.build_install_command(db_session, "https://cb.home")
    assert resp.tls_mode == "self_signed"
    assert "sha256sum -c" in resp.command
    assert resp.script_sha256 in resp.command


def test_build_install_command_public_tls_omits_hash_verification(db_session):
    from app.db.models import Certificate
    from app.core.time import utcnow
    from datetime import timedelta

    db_session.add(
        Certificate(
            domain="cb.example.com", type="letsencrypt",
            cert_pem="-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----",
            key_pem="-----BEGIN PRIVATE KEY-----\nMIIB\n-----END PRIVATE KEY-----",
            expires_at=utcnow() + timedelta(days=60),
        )
    )
    db_session.flush()

    resp = agent_install.build_install_command(db_session, "https://cb.example.com")
    assert resp.tls_mode == "public"
    assert "sha256sum -c" not in resp.command
```

> The `letsencrypt`-typed `Certificate` fixture above uses placeholder PEM content, which is fine
> for `build_install_command`'s test since that function only reads `.type`, not the PEM itself —
> SPKI pin extraction from real `cert_pem` content only matters for `self_signed` mode's `tls_pin`
> value, exercised indirectly by `test_build_install_command_self_signed_...` finding no
> `Certificate` row at all (falls back to no-pin / TOFU, per Step 3's implementation note).

- [ ] **Step 2: Run the tests to see them fail**

Run: `cd apps/backend && pytest tests/services/test_agent_install.py -v`
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `agent_install.py`**

```python
# apps/backend/src/app/services/agent_install.py
"""Generates install-agent.sh and the two curl command forms shown in-app
(spec §2.3). No secret is embedded — only the server's public identity."""

from __future__ import annotations

import base64
import hashlib
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.agent_crypto import get_server_static_keypair
from app.db.models import Certificate
from app.services import agent_update
from app.schemas.agents import InstallCommandResponse

_INSTALL_SCRIPT_TEMPLATE = """#!/bin/sh
set -eu

CB_SERVER_URL="{server_url}"
CB_SERVER_STATIC_PK="{server_static_pk_hex}"
CB_TLS_PIN="{tls_pin}"

echo "Installing cb-agent from ${{CB_SERVER_URL}}..."

if ! id cb-agent >/dev/null 2>&1; then
  useradd --system --no-create-home --shell /usr/sbin/nologin cb-agent
fi

ARCH="$(uname -m)"
case "$ARCH" in
  x86_64) CB_ARCH="amd64" ;;
  aarch64|arm64) CB_ARCH="arm64" ;;
  *) echo "unsupported architecture: $ARCH" >&2; exit 1 ;;
esac

{binary_digest_cases}

TMP_BIN="$(mktemp)"
curl -fsSL "${{CB_SERVER_URL}}/api/v1/agents/binary/{latest_version}/linux/${{CB_ARCH}}" -o "$TMP_BIN"
echo "${{CB_BINARY_SHA256}}  ${{TMP_BIN}}" | sha256sum -c
install -m 0755 "$TMP_BIN" /usr/local/bin/cb-agent
rm -f "$TMP_BIN"

mkdir -p /etc/circuit-breaker /var/lib/cb-agent
chown cb-agent:cb-agent /var/lib/cb-agent
cat > /etc/circuit-breaker/agent.toml <<EOF
server_url = "${{CB_SERVER_URL}}"
server_static_pk = "${{CB_SERVER_STATIC_PK}}"
tls_pin = "${{CB_TLS_PIN}}"
log_level = "info"
spool_cap_bytes = 67108864
EOF

if command -v docker >/dev/null 2>&1; then
  usermod -aG docker cb-agent || true
fi
if ! grep -q '^net.ipv4.ping_group_range' /etc/sysctl.conf 2>/dev/null; then
  echo "net.ipv4.ping_group_range = 0 2147483647" >> /etc/sysctl.conf
  sysctl -p >/dev/null 2>&1 || true
fi

cat > /etc/systemd/system/cb-agent.service <<'EOF'
[Unit]
Description=Circuit Breaker Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=cb-agent
Group=cb-agent
ExecStart=/usr/local/bin/cb-agent
Restart=on-failure
RestartSec=5s
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
SystemCallFilter=@system-service
ReadWritePaths=/var/lib/cb-agent

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload

echo "Enrolling — compare the fingerprint below against the one shown in the approval screen."
sudo -u cb-agent /usr/local/bin/cb-agent enroll

systemctl enable --now cb-agent
echo "cb-agent installed and running."
"""


def _spki_pin(cert_pem: str) -> str:
    from cryptography import x509
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    cert = x509.load_pem_x509_certificate(cert_pem.encode())
    der = cert.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    return base64.b64encode(hashlib.sha256(der).digest()).decode()


def _active_certificate(db: Session) -> Certificate | None:
    return db.execute(
        select(Certificate).order_by(Certificate.updated_at.desc())
    ).scalars().first()


def render_install_script(
    *, server_url: str, server_static_pk_hex: str, tls_pin: str, manifest: dict,
) -> str:
    latest = sorted(manifest.keys())[-1] if manifest else "0.0.0"
    per_arch = manifest.get(latest, {})
    cases = "\n".join(
        f'if [ "$CB_ARCH" = "{arch.split("-")[1]}" ]; then CB_BINARY_SHA256="{digest}"; fi'
        for arch, digest in per_arch.items()
    ) or 'CB_BINARY_SHA256=""'
    return _INSTALL_SCRIPT_TEMPLATE.format(
        server_url=server_url, server_static_pk_hex=server_static_pk_hex, tls_pin=tls_pin,
        binary_digest_cases=cases, latest_version=latest,
    )


def build_install_command(db: Session, server_url: str) -> InstallCommandResponse:
    _, server_pub = get_server_static_keypair()
    server_static_pk_hex = server_pub.hex()

    cert = _active_certificate(db)
    tls_mode = "public" if cert is not None and cert.type == "letsencrypt" else "self_signed"
    tls_pin = _spki_pin(cert.cert_pem) if cert is not None else ""

    manifest = agent_update.load_manifest()
    script = render_install_script(
        server_url=server_url, server_static_pk_hex=server_static_pk_hex,
        tls_pin=tls_pin, manifest=manifest,
    )
    script_sha256 = hashlib.sha256(script.encode()).hexdigest()

    if tls_mode == "public":
        command = f"curl -fsSL {server_url}/install-agent.sh | sudo sh"
    else:
        command = (
            f'curl -fsSLk {server_url}/install-agent.sh -o /tmp/cb-agent-install.sh && '
            f'echo "{script_sha256}  /tmp/cb-agent-install.sh" | sha256sum -c && '
            f"sudo sh /tmp/cb-agent-install.sh"
        )

    return InstallCommandResponse(tls_mode=tls_mode, command=command, script_sha256=script_sha256)
```

> **Judgment call for the implementer:** `_active_certificate` picks the most-recently-updated
> `Certificate` row as a stand-in for "the certificate this instance actually serves," since
> nothing in the researched codebase ties a specific `Certificate` row to the live nginx/Caddy TLS
> config directly. If a more authoritative source exists (e.g. a settings field naming the active
> domain), prefer it — grep `domain_fqdn` usage in `settings_service.py` before trusting this
> verbatim.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd apps/backend && pytest tests/services/test_agent_install.py -v`
Expected: 4 passed (skip/adjust the bash-syntax test if `bash` isn't on the test runner's `PATH` —
unlikely, but note it rather than silently `xfail`-ing).

- [ ] **Step 5: Add the REST endpoints**

```python
# apps/backend/src/app/schemas/agents.py — append
class InstallCommandResponse(BaseModel):
    tls_mode: str
    command: str
    script_sha256: str
```

```python
# apps/backend/src/app/api/agents.py — append to `router`
@router.get("/install-command", response_model=InstallCommandResponse)
def get_install_command(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    _user: Annotated[User, require_role("admin")],
) -> Any:
    from app.services import agent_install

    server_url = f"{request.url.scheme}://{request.url.netloc}"
    return agent_install.build_install_command(db, server_url)
```

`/install-agent.sh` must be a clean top-level path (matching the spec's exact `curl
https://cb.example.com/install-agent.sh` examples), not nested under `/api/v1/agents` — wire it
directly on `app` in `main.py`, not on `binary_router`.

- [ ] **Step 6: Mount `/install-agent.sh` at the app root**

```python
# apps/backend/src/app/main.py — near the other top-level routes (not under _V1)
@app.get("/install-agent.sh", include_in_schema=False)
def get_install_agent_script(request: Request) -> Response:
    from app.db.session import SessionLocal
    from app.services import agent_install

    server_url = f"{request.url.scheme}://{request.url.netloc}"
    with SessionLocal() as db:
        script = agent_install.render_install_script(
            server_url=server_url,
            server_static_pk_hex=agent_install.get_server_static_keypair()[1].hex(),
            tls_pin=(
                agent_install._spki_pin(cert.cert_pem)
                if (cert := agent_install._active_certificate(db)) is not None
                else ""
            ),
            manifest=agent_install.agent_update.load_manifest(),
        )
    return Response(content=script, media_type="text/x-shellscript")
```

Add `from fastapi import Response` (or `starlette.responses.Response`, matching whatever this file
already imports) to `main.py`'s imports if not already present.

- [ ] **Step 7: Run the full agents test suite to verify nothing regressed**

Run: `cd apps/backend && pytest tests/api/test_agents_api.py tests/services/test_agent_install.py -v`
Expected: all passed.

- [ ] **Step 8: Write the Makefile packaging target**

```makefile
# apps/agent/Makefile
VERSION ?= $(shell git -C .. describe --tags --always --dirty 2>/dev/null || echo 0.0.0-dev)
DIST := dist/$(VERSION)

.PHONY: build-all manifest clean

build-all:
	mkdir -p $(DIST)
	GOOS=linux GOARCH=amd64 go build -ldflags "-X main.AgentVersion=$(VERSION)" \
		-o $(DIST)/cb-agent-linux-amd64 ./cmd/cb-agent
	GOOS=linux GOARCH=arm64 go build -ldflags "-X main.AgentVersion=$(VERSION)" \
		-o $(DIST)/cb-agent-linux-arm64 ./cmd/cb-agent

manifest: build-all
	python3 - <<-'PY'
	import hashlib, json, pathlib
	dist = pathlib.Path("$(DIST)")
	version = "$(VERSION)"
	manifest = {version: {}}
	for f in dist.glob("cb-agent-*"):
	    arch_os = f.name.removeprefix("cb-agent-")
	    manifest[version][arch_os] = hashlib.sha256(f.read_bytes()).hexdigest()
	pathlib.Path("dist/manifest.json").write_text(json.dumps(manifest, indent=2))
	PY

clean:
	rm -rf dist
```

- [ ] **Step 9: Build both architectures and inspect the manifest**

Run: `cd apps/agent && make manifest && cat dist/manifest.json`
Expected: a JSON object keyed by the derived version, with `linux-amd64` and `linux-arm64` SHA-256
entries. Copying `dist/` to wherever `CB_AGENT_BINARIES_DIR` points (default
`/opt/circuitbreaker/agent-binaries`) is what makes Task 16's `GET /binary/...` and this task's
`install-agent.sh` actually serve real binaries in a live deployment — out of scope for this
plan's automated tests, which use temp-directory fixtures instead.

- [ ] **Step 10: Commit**

```bash
git add apps/backend/src/app/services/agent_install.py apps/backend/src/app/schemas/agents.py \
        apps/backend/src/app/api/agents.py apps/backend/src/app/main.py \
        apps/backend/tests/services/test_agent_install.py apps/agent/Makefile
git commit -m "feat(agents): install script generation, systemd unit, packaging"
```

---

### Task 18: Frontend REST client, live hook, and nav registration

**Files:**
- Create: `apps/frontend/src/api/agents.js`
- Create: `apps/frontend/src/hooks/useAgentLive.js`
- Create: `apps/frontend/src/__tests__/agent-live-stream.test.jsx`
- Modify: `apps/frontend/src/data/navigation.js`

**Interfaces:**
- Consumes: `apps/frontend/src/api/client.jsx`'s default export (axios instance, base URL already
  `/api/v1`, per `api/monitor.js`'s pattern), `useAuth()` from `context/AuthContext.jsx`.
- Produces: every named export in `api/agents.js` (`listAgents`, `getAgent`, `getAgentEvents`,
  `listPendingAgents`, `patchAgent`, `lookupPairingCode`, `approveAgent`, `rejectAgent`,
  `revokeAgent`, `setAgentCapabilities`, `deleteAgent`, `getInstallCommand`,
  `triggerAgentUpdate`), `useAgentLive() -> { statuses: Map<number, {event_type, detail, ts}>,
  connected: boolean }`, `getAgentsWsUrl(locationLike)`. Task 19-20 (`AgentsPage.jsx`,
  `AgentDetailPage.jsx`) import all of these.

- [ ] **Step 1: Write `api/agents.js`**

```js
// apps/frontend/src/api/agents.js
import client from './client.jsx';

export const listAgents = (params = {}) => client.get('/agents', { params });
export const listPendingAgents = () => client.get('/agents/pending');
export const getAgent = (id) => client.get(`/agents/${id}`);
export const getAgentEvents = (id, limit = 50) =>
  client.get(`/agents/${id}/events`, { params: { limit } });
export const patchAgent = (id, data) => client.patch(`/agents/${id}`, data);
export const lookupPairingCode = (code) => client.post('/agents/pairing/lookup', { code });
export const approveAgent = (id, data = {}) => client.post(`/agents/${id}/approve`, data);
export const rejectAgent = (id) => client.post(`/agents/${id}/reject`);
export const revokeAgent = (id, reason) => client.post(`/agents/${id}/revoke`, { reason });
export const setAgentCapabilities = (id, capabilities) =>
  client.put(`/agents/${id}/capabilities`, { capabilities });
export const deleteAgent = (id) => client.delete(`/agents/${id}`);
export const getInstallCommand = () => client.get('/agents/install-command');
export const triggerAgentUpdate = (id, version) =>
  client.post(`/agents/${id}/update`, { version });
```

- [ ] **Step 2: Write `useAgentLive.js`**

This is a direct structural mirror of `useMonitorStream.js` (Task 7's research item 8), minus the
per-monitor subscribe/unsubscribe machinery — `/api/agents/stream` broadcasts every presence
event to every connected client rather than supporting per-agent channel subscriptions, since a
fleet's agent count in slice 1 is expected to be small enough that filtering isn't worth the
protocol complexity yet.

```js
// apps/frontend/src/hooks/useAgentLive.js
/**
 * useAgentLive()
 *
 * WS /api/v1/agents/stream — real-time agent presence push (connected,
 * disconnected, approved, rejected, revoked). Auth protocol identical to
 * useMonitorStream: cookie-mode sessions authenticate via the cookie the
 * browser attaches automatically; bearer-token sessions send the token as
 * the first text message after connecting.
 *
 * Usage:
 *   const { statuses, connected } = useAgentLive();
 *   // statuses is Map<agentId, { event_type, detail, ts }>
 */

import { useEffect, useRef, useState, useCallback } from 'react';
import { useAuth } from '../context/AuthContext.jsx';

const BACKOFF_BASE = 2000;
const BACKOFF_MAX = 30000;
const BACKOFF_MULTIPLIER = 1.5;
const HARD_STOP_ERRORS = new Set(['unauthorized', 'auth_timeout']);

function closeSocketSafely(socket) {
  if (!socket) return;
  if (socket.readyState === WebSocket.CONNECTING) {
    socket.addEventListener(
      'open',
      () => {
        try {
          socket.close();
        } catch {
          // Ignore late-close failures during teardown.
        }
      },
      { once: true }
    );
    return;
  }
  if (socket.readyState === WebSocket.OPEN) {
    socket.close();
  }
}

export function getAgentsWsUrl(locationLike = globalThis.location) {
  const proto = locationLike.protocol === 'https:' ? 'wss' : 'ws';
  return `${proto}://${locationLike.host}/api/v1/agents/stream`;
}

export function useAgentLive() {
  const { user, token } = useAuth();
  const [connected, setConnected] = useState(false);
  const [statuses, setStatuses] = useState(() => new Map());

  const wsRef = useRef(null);
  const attemptRef = useRef(0);
  const retryTimerRef = useRef(null);
  const intentionalRef = useRef(false);

  const clearRetry = useCallback(() => {
    if (retryTimerRef.current) {
      clearTimeout(retryTimerRef.current);
      retryTimerRef.current = null;
    }
  }, []);

  const connect = useCallback(() => {
    clearRetry();
    intentionalRef.current = false;

    if (
      wsRef.current &&
      (wsRef.current.readyState === WebSocket.OPEN ||
        wsRef.current.readyState === WebSocket.CONNECTING)
    ) {
      return;
    }
    if (!user && !token) return;

    const ws = new WebSocket(getAgentsWsUrl());
    wsRef.current = ws;

    ws.onopen = () => {
      if (token && token !== 'cookie' && token.length > 10) {
        ws.send(token);
      }
    };

    ws.onmessage = (event) => {
      let msg;
      try {
        msg = JSON.parse(event.data);
      } catch {
        return;
      }

      if (msg.status === 'connected') {
        setConnected(true);
        attemptRef.current = 0;
        return;
      }

      if (msg.error && HARD_STOP_ERRORS.has(msg.error)) {
        setConnected(false);
        intentionalRef.current = true;
        closeSocketSafely(ws);
        return;
      }

      if (msg.error === 'connection_limit_exceeded') {
        setConnected(false);
        intentionalRef.current = false;
        closeSocketSafely(ws);
        retryTimerRef.current = setTimeout(() => {
          attemptRef.current = 0;
          connect();
        }, 60000);
        return;
      }

      if (msg.agent_id != null && msg.event_type) {
        setStatuses((prev) => {
          const next = new Map(prev);
          next.set(msg.agent_id, { event_type: msg.event_type, detail: msg.detail, ts: Date.now() });
          return next;
        });
      }
    };

    ws.onclose = (event) => {
      setConnected(false);
      wsRef.current = null;

      if (event.code === 1008 || intentionalRef.current) return;
      if (retryTimerRef.current) return;

      const attempt = attemptRef.current;
      const baseDelay = Math.min(BACKOFF_BASE * Math.pow(BACKOFF_MULTIPLIER, attempt), BACKOFF_MAX);
      const delay = baseDelay * (0.5 + Math.random() * 0.5);
      attemptRef.current = attempt + 1;
      retryTimerRef.current = setTimeout(connect, delay);
    };

    ws.onerror = () => {
      if (wsRef.current === ws && ws.readyState !== WebSocket.CLOSED) {
        closeSocketSafely(ws);
      }
    };
  }, [clearRetry, user, token]);

  useEffect(() => {
    connect();

    const onVisibility = () => {
      if (document.visibilityState === 'visible' && !intentionalRef.current) {
        const ws = wsRef.current;
        const isActive =
          ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING);
        if (!isActive) {
          attemptRef.current = 0;
          connect();
        }
      }
    };

    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      document.removeEventListener('visibilitychange', onVisibility);
      clearRetry();
      intentionalRef.current = true;
      closeSocketSafely(wsRef.current);
    };
  }, [connect, clearRetry]);

  return { statuses, connected };
}
```

- [ ] **Step 3: Write the hook test**

```jsx
// apps/frontend/src/__tests__/agent-live-stream.test.jsx
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { useAgentLive } from '../hooks/useAgentLive.js';

vi.mock('../context/AuthContext.jsx', () => ({
  useAuth: () => ({ user: { id: 1 }, token: 'a-real-bearer-token-value' }),
}));

class MockWebSocket {
  static instances = [];
  constructor(url) {
    this.url = url;
    this.readyState = WebSocket.CONNECTING;
    this.sent = [];
    MockWebSocket.instances.push(this);
  }
  send(data) {
    this.sent.push(data);
  }
  close() {
    this.readyState = WebSocket.CLOSED;
    this.onclose?.({ code: 1000 });
  }
  open() {
    this.readyState = WebSocket.OPEN;
    this.onopen?.();
  }
  emit(data) {
    this.onmessage?.({ data: JSON.stringify(data) });
  }
}

describe('useAgentLive', () => {
  let originalWebSocket;

  beforeEach(() => {
    originalWebSocket = globalThis.WebSocket;
    MockWebSocket.instances = [];
    globalThis.WebSocket = MockWebSocket;
    globalThis.WebSocket.OPEN = 1;
    globalThis.WebSocket.CONNECTING = 0;
    globalThis.WebSocket.CLOSED = 3;
  });

  afterEach(() => {
    globalThis.WebSocket = originalWebSocket;
  });

  it('sends the bearer token on open and marks connected on ack', async () => {
    const { result } = renderHook(() => useAgentLive());
    const ws = MockWebSocket.instances[0];

    act(() => ws.open());
    expect(ws.sent).toEqual(['a-real-bearer-token-value']);

    act(() => ws.emit({ status: 'connected' }));
    await waitFor(() => expect(result.current.connected).toBe(true));
  });

  it('folds an agent_id event into statuses', async () => {
    const { result } = renderHook(() => useAgentLive());
    const ws = MockWebSocket.instances[0];
    act(() => ws.open());
    act(() => ws.emit({ status: 'connected' }));

    act(() => ws.emit({ agent_id: 7, event_type: 'connected', detail: null }));

    await waitFor(() => {
      expect(result.current.statuses.get(7)?.event_type).toBe('connected');
    });
  });

  it('hard-stops on unauthorized without scheduling a reconnect', async () => {
    const { result } = renderHook(() => useAgentLive());
    const ws = MockWebSocket.instances[0];
    act(() => ws.open());

    act(() => ws.emit({ error: 'unauthorized' }));

    await waitFor(() => expect(result.current.connected).toBe(false));
    expect(MockWebSocket.instances.length).toBe(1); // no reconnect attempt was made
  });
});
```

- [ ] **Step 4: Run the tests**

Run: `cd apps/frontend && npx vitest run src/__tests__/agent-live-stream.test.jsx`
Expected: 3 passed. Adjust the mock/import paths to match whatever test runner and
`@testing-library/react` version this project's other hook tests already use — check
`map-realtime-updates.test.jsx` for the exact conventions (mock library, WebSocket stubbing
style) if this fails on setup rather than assertions.

- [ ] **Step 5: Register the Agents nav item**

In `apps/frontend/src/data/navigation.js`, add a `Satellite` import from `lucide-react`
(alongside the existing icon imports), then add `/agents` to all three exported structures — no
`requireEditor`/`requireAdmin` flag, matching `/monitors`' and `/discovery`'s viewer-readable
pattern (role gating for admin-only actions like approve/revoke happens inside the page/API
layer, not at the nav-item level):

```js
// NAV_ITEMS — 'Infrastructure' group, after the '/discovery' entry
{ path: '/agents', icon: Satellite, label: 'Agents', labelKey: 'header.agents' },
```

```js
// NAV_MAP
'/agents': { icon: Satellite, label: 'Agents', labelKey: 'header.agents' },
```

```js
// DEFAULT_ORDER — after '/discovery'
'/agents',
```

- [ ] **Step 6: Commit**

```bash
git add apps/frontend/src/api/agents.js apps/frontend/src/hooks/useAgentLive.js \
        apps/frontend/src/__tests__/agent-live-stream.test.jsx apps/frontend/src/data/navigation.js
git commit -m "feat(agents): frontend REST client, live-presence hook, nav entry"
```

---

### Task 19: `AgentsPage.jsx` — list, pending banner, add-agent flow

**Files:**
- Create: `apps/frontend/src/components/agents/AgentApprovalModal.jsx`
- Create: `apps/frontend/src/pages/AgentsPage.jsx`
- Create: `apps/frontend/src/__tests__/agents-page.test.jsx`
- Modify: `apps/frontend/src/App.jsx` (routes: `/agents`, `/agents/enroll`)

**Interfaces:**
- Consumes: everything from `api/agents.js` and `useAgentLive()` (Task 18), `ConfirmDialog`
  (`components/common/ConfirmDialog.jsx`), `useToast` (`components/common/Toast.jsx`).
- Produces: `AgentApprovalModal({ agentId, pairingCode, onApproved, onClose })` — the single
  approval screen every enrollment path converges on, per spec §5.2 ("pasted pairing code, magic
  link, and live-panel click all converge on the same approval screen"). `AgentsPage` renders it
  three ways: (a) clicking a pending row in the live "waiting for agents…" panel passes
  `agentId` directly, (b) pasting a code into the modal resolves it via `lookupPairingCode` first,
  (c) the `/agents/enroll?c=<code>` route (Task 20 needs no separate page component for this —
  `AgentsPage` itself checks `location.search` on mount and opens the modal pre-resolved).

- [ ] **Step 1: Write `AgentApprovalModal.jsx`**

```jsx
// apps/frontend/src/components/agents/AgentApprovalModal.jsx
import React, { useEffect, useState } from 'react';
import PropTypes from 'prop-types';
import { approveAgent, getAgent } from '../../api/agents';
import { useToast } from '../common/Toast';

const DEFAULT_CAPABILITIES = { host_telemetry: true, remote_probe: false, local_discovery: false };

export default function AgentApprovalModal({ agentId, onApproved, onClose }) {
  const toast = useToast();
  const [agent, setAgent] = useState(null);
  const [capabilities, setCapabilities] = useState(DEFAULT_CAPABILITIES);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getAgent(agentId)
      .then(({ data }) => {
        if (cancelled) return;
        setAgent(data);
      })
      .catch(() => {
        if (!cancelled) toast.error('Could not load agent details');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [agentId]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleApprove = async () => {
    setSubmitting(true);
    try {
      await approveAgent(agentId, { capabilities });
      toast.success(`${agent?.hostname ?? 'Agent'} approved`);
      onApproved?.();
    } catch {
      toast.error('Approval failed');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div role="dialog" aria-modal="true" className="agent-approval-modal">
      <div className="agent-approval-modal__panel">
        <h2>Approve agent</h2>
        {loading && <p>Loading…</p>}
        {!loading && agent && (
          <>
            <dl>
              <dt>Hostname</dt>
              <dd>{agent.hostname ?? 'unknown'}</dd>
              <dt>OS / Arch</dt>
              <dd>{agent.os} / {agent.arch}</dd>
              <dt>Fingerprint</dt>
              <dd className="agent-approval-modal__fingerprint">{agent.fingerprint}</dd>
            </dl>
            <p className="agent-approval-modal__warning">
              Compare this fingerprint against the one printed by the agent before approving.
            </p>
            <fieldset>
              <legend>Capabilities</legend>
              {Object.keys(DEFAULT_CAPABILITIES).map((cap) => (
                <label key={cap}>
                  <input
                    type="checkbox"
                    checked={capabilities[cap]}
                    onChange={(e) =>
                      setCapabilities((prev) => ({ ...prev, [cap]: e.target.checked }))
                    }
                  />
                  {cap.replace('_', ' ')}
                </label>
              ))}
            </fieldset>
            <div className="agent-approval-modal__actions">
              <button type="button" onClick={onClose} disabled={submitting}>
                Cancel
              </button>
              <button type="button" onClick={handleApprove} disabled={submitting}>
                {submitting ? 'Approving…' : 'Approve'}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

AgentApprovalModal.propTypes = {
  agentId: PropTypes.number.isRequired,
  onApproved: PropTypes.func,
  onClose: PropTypes.func.isRequired,
};
```

- [ ] **Step 2: Write `AgentsPage.jsx`**

```jsx
// apps/frontend/src/pages/AgentsPage.jsx
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Satellite } from 'lucide-react';
import {
  deleteAgent,
  getInstallCommand,
  listAgents,
  lookupPairingCode,
  revokeAgent,
} from '../api/agents';
import { useAgentLive } from '../hooks/useAgentLive';
import { useToast } from '../components/common/Toast';
import ConfirmDialog from '../components/common/ConfirmDialog';
import AgentApprovalModal from '../components/agents/AgentApprovalModal';

const REFRESH_MS = 30000;

export default function AgentsPage() {
  const toast = useToast();
  const [params, setParams] = useSearchParams();
  const [agents, setAgents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [installCommand, setInstallCommand] = useState(null);
  const [pairingInput, setPairingInput] = useState('');
  const [approvalAgentId, setApprovalAgentId] = useState(null);
  const [revokeTarget, setRevokeTarget] = useState(null);

  const { statuses, connected } = useAgentLive();

  const load = useCallback(() => {
    listAgents()
      .then(({ data }) => setAgents(data))
      .catch(() => toast.error('Could not load agents'))
      .finally(() => setLoading(false));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    load();
    const interval = setInterval(load, REFRESH_MS);
    return () => clearInterval(interval);
  }, [load]);

  // Magic-link entry: /agents/enroll?c=<code>
  useEffect(() => {
    const code = params.get('c');
    if (!code) return;
    lookupPairingCode(code)
      .then(({ data }) => setApprovalAgentId(data.agent_id))
      .catch(() => toast.error('Unknown or expired pairing code'))
      .finally(() => {
        params.delete('c');
        setParams(params, { replace: true });
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const merged = useMemo(() => {
    if (statuses.size === 0) return agents;
    return agents.map((a) => {
      const push = statuses.get(a.id);
      if (!push) return a;
      if (push.event_type === 'revoked' || push.event_type === 'rejected') {
        return { ...a, status: push.event_type };
      }
      return a;
    });
  }, [agents, statuses]);

  const pending = merged.filter((a) => a.status === 'pending');
  const others = merged.filter((a) => a.status !== 'pending');

  const handlePairingSubmit = async () => {
    try {
      const { data } = await lookupPairingCode(pairingInput.trim());
      setApprovalAgentId(data.agent_id);
      setPairingInput('');
    } catch {
      toast.error('Unknown or expired pairing code');
    }
  };

  const handleShowInstallCommand = async () => {
    try {
      const { data } = await getInstallCommand();
      setInstallCommand(data);
    } catch {
      toast.error('Could not generate an install command');
    }
  };

  const handleRevokeConfirmed = async () => {
    if (!revokeTarget) return;
    try {
      await revokeAgent(revokeTarget.id, 'revoked from UI');
      toast.success(`${revokeTarget.hostname ?? 'Agent'} revoked`);
      load();
    } catch {
      toast.error('Revoke failed');
    } finally {
      setRevokeTarget(null);
    }
  };

  const handleDelete = async (agent) => {
    try {
      await deleteAgent(agent.id);
      toast.success(`${agent.hostname ?? 'Agent'} removed`);
      load();
    } catch {
      toast.error('Delete failed');
    }
  };

  if (loading) return <div className="agents-page">Loading…</div>;

  return (
    <div className="agents-page">
      <header className="agents-page__header">
        <h1>
          <Satellite size={20} /> Agents
        </h1>
        <span className={connected ? 'agents-page__live-on' : 'agents-page__live-off'}>
          {connected ? 'live' : 'reconnecting…'}
        </span>
        <button type="button" onClick={handleShowInstallCommand}>
          Add agent
        </button>
      </header>

      {pending.length > 0 && (
        <section className="agents-page__pending-banner" aria-label="Pending approvals">
          <h2>Waiting for approval ({pending.length})</h2>
          <ul>
            {pending.map((a) => (
              <li key={a.id}>
                <button type="button" onClick={() => setApprovalAgentId(a.id)}>
                  {a.hostname ?? `agent #${a.id}`} — {a.fingerprint.slice(0, 8)}…
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      {installCommand && (
        <section className="agents-page__install-panel">
          <h2>Install command ({installCommand.tls_mode === 'public' ? 'trusted TLS' : 'self-signed'})</h2>
          <pre>{installCommand.command}</pre>
          <div>
            <label htmlFor="pairing-code-input">Or paste a pairing code:</label>
            <input
              id="pairing-code-input"
              value={pairingInput}
              onChange={(e) => setPairingInput(e.target.value)}
              placeholder="XXXX-XXXX-XXXX"
            />
            <button type="button" onClick={handlePairingSubmit}>
              Look up
            </button>
          </div>
        </section>
      )}

      <table className="agents-page__table">
        <thead>
          <tr>
            <th>Status</th>
            <th>Name</th>
            <th>Host</th>
            <th>OS / Arch</th>
            <th>Version</th>
            <th>Last seen</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {others.map((a) => (
            <tr key={a.id}>
              <td>{a.status}</td>
              <td>{a.name ?? a.hostname}</td>
              <td>{a.hostname}</td>
              <td>{a.os} / {a.arch}</td>
              <td>{a.agent_version}</td>
              <td>{a.last_seen_at ?? 'never'}</td>
              <td>
                {a.status === 'active' && (
                  <button type="button" onClick={() => setRevokeTarget(a)}>
                    Revoke
                  </button>
                )}
                {a.status !== 'active' && (
                  <button type="button" onClick={() => handleDelete(a)}>
                    Delete
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {approvalAgentId != null && (
        <AgentApprovalModal
          agentId={approvalAgentId}
          onApproved={() => {
            setApprovalAgentId(null);
            load();
          }}
          onClose={() => setApprovalAgentId(null)}
        />
      )}

      <ConfirmDialog
        open={revokeTarget != null}
        message={`Revoke ${revokeTarget?.hostname ?? 'this agent'}? It will stop reporting immediately.`}
        onConfirm={handleRevokeConfirmed}
        onCancel={() => setRevokeTarget(null)}
      />
    </div>
  );
}
```

- [ ] **Step 3: Wire the routes in `App.jsx`**

```jsx
// apps/frontend/src/App.jsx — near the other React.lazy imports
const AgentsPage = React.lazy(() => import('./pages/AgentsPage'));
```

```jsx
// apps/frontend/src/App.jsx — near the other <Route> entries, after /discovery
<Route path="/agents" element={<AgentsPage />} />
<Route path="/agents/enroll" element={<AgentsPage />} />
```

`/agents/enroll` renders the same `AgentsPage` component — it reads the `?c=` query param on
mount (Step 2) rather than needing a distinct page/component, matching spec §5.2's "all three
routes converge on the same approval screen."

- [ ] **Step 4: Write a smoke test**

```jsx
// apps/frontend/src/__tests__/agents-page.test.jsx
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import AgentsPage from '../pages/AgentsPage';

vi.mock('../api/agents', () => ({
  listAgents: vi.fn(() =>
    Promise.resolve({
      data: [
        { id: 1, status: 'pending', hostname: 'box1', fingerprint: 'a'.repeat(32), os: 'linux', arch: 'amd64' },
        { id: 2, status: 'active', hostname: 'box2', fingerprint: 'b'.repeat(32), os: 'linux', arch: 'amd64', agent_version: '0.1.0' },
      ],
    })
  ),
  getInstallCommand: vi.fn(() => Promise.resolve({ data: { tls_mode: 'self_signed', command: 'curl ...', script_sha256: 'x' } })),
  lookupPairingCode: vi.fn(),
  revokeAgent: vi.fn(),
  deleteAgent: vi.fn(),
  getAgent: vi.fn(),
  approveAgent: vi.fn(),
}));

vi.mock('../hooks/useAgentLive', () => ({
  useAgentLive: () => ({ statuses: new Map(), connected: true }),
}));

describe('AgentsPage', () => {
  beforeEach(() => vi.clearAllMocks());

  it('pins pending agents to a banner separate from the main table', async () => {
    render(
      <MemoryRouter initialEntries={['/agents']}>
        <AgentsPage />
      </MemoryRouter>
    );

    await waitFor(() => expect(screen.getByText(/Waiting for approval/i)).toBeInTheDocument());
    expect(screen.getByText(/box1/i)).toBeInTheDocument();
    expect(screen.getByText(/box2/i)).toBeInTheDocument();
  });
});
```

> This test needs `AgentsPage` wrapped in whatever context providers (`ToastProvider`, auth
> context) this app's other page tests already supply — check `monitors-dashboard.test.jsx`'s
> render setup and mirror it exactly rather than guessing at the provider tree.

- [ ] **Step 5: Run the tests**

Run: `cd apps/frontend && npx vitest run src/__tests__/agents-page.test.jsx`
Expected: passes once wrapped in the correct provider tree per Step 4's note.

- [ ] **Step 6: Commit**

```bash
git add apps/frontend/src/components/agents/AgentApprovalModal.jsx apps/frontend/src/pages/AgentsPage.jsx \
        apps/frontend/src/__tests__/agents-page.test.jsx apps/frontend/src/App.jsx
git commit -m "feat(agents): AgentsPage — list, pending banner, add-agent flow"
```

---

### Task 20: `AgentDetailPage.jsx` — capabilities, events, revoke

Per spec §5.4, "Telemetry preview" (slice 2), "Assigned probes" (slice 3), and "Discovery scope"
(slice 4) are explicitly out of scope here — this task builds only the header, capability
toggles, and event timeline slice 1 actually has data for.

**Files:**
- Create: `apps/frontend/src/pages/AgentDetailPage.jsx`
- Create: `apps/frontend/src/__tests__/agent-detail-page.test.jsx`
- Modify: `apps/frontend/src/App.jsx` (route `/agents/:id`)

**Interfaces:**
- Consumes: `getAgent`, `getAgentEvents`, `setAgentCapabilities`, `revokeAgent`,
  `triggerAgentUpdate` (`api/agents.js`, Task 18), `ConfirmDialog`, `useToast`.
- Produces: nothing consumed elsewhere in slice 1 — this is a leaf page.

- [ ] **Step 1: Write `AgentDetailPage.jsx`**

```jsx
// apps/frontend/src/pages/AgentDetailPage.jsx
import React, { useCallback, useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  getAgent,
  getAgentEvents,
  revokeAgent,
  setAgentCapabilities,
  triggerAgentUpdate,
} from '../api/agents';
import { useToast } from '../components/common/Toast';
import ConfirmDialog from '../components/common/ConfirmDialog';

const CAPABILITY_LABELS = {
  host_telemetry: 'Host telemetry',
  remote_probe: 'Remote probe',
  local_discovery: 'Local discovery',
};

export default function AgentDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const toast = useToast();

  const [agent, setAgent] = useState(null);
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [revokeOpen, setRevokeOpen] = useState(false);

  const load = useCallback(() => {
    Promise.all([getAgent(id), getAgentEvents(id)])
      .then(([agentRes, eventsRes]) => {
        setAgent(agentRes.data);
        setEvents(eventsRes.data);
      })
      .catch(() => toast.error('Could not load agent'))
      .finally(() => setLoading(false));
  }, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    load();
  }, [load]);

  const handleToggleCapability = async (capability, enabled) => {
    try {
      const { data } = await setAgentCapabilities(id, { [capability]: enabled });
      setAgent(data);
    } catch {
      toast.error('Could not update capability');
    }
  };

  const handleRevoke = async () => {
    try {
      await revokeAgent(id, 'revoked from UI');
      toast.success('Agent revoked');
      setRevokeOpen(false);
      load();
    } catch {
      toast.error('Revoke failed');
    }
  };

  const handleUpdate = async () => {
    try {
      await triggerAgentUpdate(id);
      toast.success('Update queued — the agent will pick it up within a few seconds');
    } catch (err) {
      toast.error(err?.response?.data?.detail ?? 'Update failed');
    }
  };

  if (loading) return <div className="agent-detail-page">Loading…</div>;
  if (!agent) return <div className="agent-detail-page">Agent not found</div>;

  return (
    <div className="agent-detail-page">
      <button type="button" onClick={() => navigate('/agents')}>
        ← Back to Agents
      </button>

      <header className="agent-detail-page__header">
        <h1>{agent.name ?? agent.hostname}</h1>
        <span>{agent.status}</span>
        <code>{agent.fingerprint}</code>
        <span>v{agent.agent_version}</span>
        <button type="button" onClick={handleUpdate}>
          Update
        </button>
        {agent.status === 'active' && (
          <button type="button" onClick={() => setRevokeOpen(true)}>
            Revoke
          </button>
        )}
      </header>

      <section aria-label="Capabilities">
        <h2>Capabilities</h2>
        {Object.entries(CAPABILITY_LABELS).map(([key, label]) => (
          <label key={key}>
            <input
              type="checkbox"
              checked={Boolean(agent.capabilities?.[key])}
              onChange={(e) => handleToggleCapability(key, e.target.checked)}
            />
            {label}
          </label>
        ))}
      </section>

      <section aria-label="Events">
        <h2>Events</h2>
        <ul>
          {events.map((e) => (
            <li key={e.id}>
              <span>{e.created_at}</span> — <strong>{e.event_type}</strong>
              {e.detail && <span> ({JSON.stringify(e.detail)})</span>}
            </li>
          ))}
        </ul>
      </section>

      <ConfirmDialog
        open={revokeOpen}
        message={`Revoke ${agent.hostname ?? 'this agent'}? It will stop reporting immediately.`}
        onConfirm={handleRevoke}
        onCancel={() => setRevokeOpen(false)}
      />
    </div>
  );
}
```

- [ ] **Step 2: Wire the route in `App.jsx`**

```jsx
// apps/frontend/src/App.jsx — near AgentsPage's lazy import
const AgentDetailPage = React.lazy(() => import('./pages/AgentDetailPage'));
```

```jsx
// apps/frontend/src/App.jsx — near the /agents route
<Route path="/agents/:id" element={<AgentDetailPage />} />
```

- [ ] **Step 3: Write a smoke test**

```jsx
// apps/frontend/src/__tests__/agent-detail-page.test.jsx
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import AgentDetailPage from '../pages/AgentDetailPage';

vi.mock('../api/agents', () => ({
  getAgent: vi.fn(() =>
    Promise.resolve({
      data: {
        id: 3, name: null, hostname: 'box1', status: 'active', fingerprint: 'a'.repeat(32),
        agent_version: '0.1.0', capabilities: { host_telemetry: true, remote_probe: false, local_discovery: false },
      },
    })
  ),
  getAgentEvents: vi.fn(() =>
    Promise.resolve({ data: [{ id: 1, event_type: 'approved', created_at: '2026-07-27T12:00:00Z', detail: null }] })
  ),
  setAgentCapabilities: vi.fn(),
  revokeAgent: vi.fn(),
  triggerAgentUpdate: vi.fn(),
}));

describe('AgentDetailPage', () => {
  beforeEach(() => vi.clearAllMocks());

  it('renders capabilities and the event timeline', async () => {
    render(
      <MemoryRouter initialEntries={['/agents/3']}>
        <Routes>
          <Route path="/agents/:id" element={<AgentDetailPage />} />
        </Routes>
      </MemoryRouter>
    );

    await waitFor(() => expect(screen.getByText('box1')).toBeInTheDocument());
    expect(screen.getByText('Host telemetry')).toBeInTheDocument();
    expect(screen.getByText('approved')).toBeInTheDocument();
  });
});
```

- [ ] **Step 4: Run the tests**

Run: `cd apps/frontend && npx vitest run src/__tests__/agent-detail-page.test.jsx`
Expected: passes (adjust provider wrapping per Task 19 Step 4's note if needed).

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/src/pages/AgentDetailPage.jsx apps/frontend/src/__tests__/agent-detail-page.test.jsx \
        apps/frontend/src/App.jsx
git commit -m "feat(agents): AgentDetailPage — capabilities, events, revoke"
```

---

### Task 21: End-to-end docker-compose harness

Per spec §7: enrolls a real agent container against a real backend and asserts the full path
from copy-command to online-in-UI, including revocation closing the socket. Reuses the existing
`docker-compose.yml` mono image (Postgres+NATS+Redis+backend+workers+nginx in one container —
the same image `install.sh`/`make up`/CI smoke tests already use) rather than assembling a
separate multi-container stack. Admin bootstrapping follows `tests/integration/test_oobe_smoke.py`'s
already-verified `GET /bootstrap/status` → `POST /bootstrap/initialize` flow exactly.

**Files:**
- Create: `apps/agent/e2e/docker-compose.yml`
- Create: `apps/agent/e2e/Dockerfile`
- Create: `apps/agent/e2e/test_agent_e2e.py`

**Interfaces:**
- Consumes: the built `cb-agent` binary (Task 3-16), the root `docker-compose.yml`'s
  `circuitbreaker` mono service, `/api/v1/bootstrap/status` / `/bootstrap/initialize` (existing,
  unrelated to this plan), `/install-agent.sh` (Task 17), `/api/v1/agents/pairing/lookup` /
  `/{id}/approve` / `/{id}/revoke` (Task 9).
- Produces: nothing consumed by other tasks — this is the final gate, marked `@pytest.mark.e2e`
  so it does not run as part of the default `pytest` invocation (it needs Docker and takes
  minutes, unlike every other test in this plan).

- [ ] **Step 1: Write the agent Dockerfile**

```dockerfile
# apps/agent/e2e/Dockerfile
FROM golang:1.22 AS build
WORKDIR /src
COPY .. .
RUN go build -o /cb-agent ./cmd/cb-agent

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates && rm -rf /var/lib/apt/lists/*
COPY --from=build /cb-agent /usr/local/bin/cb-agent
RUN useradd --system --no-create-home --shell /usr/sbin/nologin cb-agent \
    && mkdir -p /etc/circuit-breaker /var/lib/cb-agent \
    && chown cb-agent:cb-agent /var/lib/cb-agent
USER cb-agent
ENTRYPOINT ["/usr/local/bin/cb-agent"]
```

- [ ] **Step 2: Write the compose overlay**

```yaml
# apps/agent/e2e/docker-compose.yml
name: cb-agent-e2e

services:
  circuitbreaker:
    extends:
      file: ../../../docker-compose.yml
      service: circuitbreaker
    environment:
      CB_DB_PASSWORD: e2e-test-password
      CB_VAULT_KEY: dGhpcy1pcy1hLXRlc3QtdmF1bHQta2V5LTMyLWJ5dGVzIQ==
      CB_JWT_SECRET: e2e-test-jwt-secret-at-least-32-bytes-long
      NATS_AUTH_TOKEN: e2e-test-nats-token
    ports:
      - "8443:8443"

  cb-agent:
    build:
      context: ..
      dockerfile: e2e/Dockerfile
    depends_on:
      - circuitbreaker
    volumes:
      - cb-agent-state:/var/lib/cb-agent
      - ./agent.toml:/etc/circuit-breaker/agent.toml:ro
    network_mode: service:circuitbreaker

volumes:
  cb-agent-state:
```

`network_mode: service:circuitbreaker` puts the agent container on the same network namespace as
the backend, so `server_url` in `agent.toml` can point at `https://localhost:8443` exactly as a
real LAN client would reach the appliance — no separate Docker network/DNS name to manage.

- [ ] **Step 3: Write the orchestration test**

```python
# apps/agent/e2e/test_agent_e2e.py
"""End-to-end: copy-command -> enroll -> approve -> online -> revoke closes
the socket. Requires Docker; not run by default pytest invocations.

Run explicitly:
    cd apps/agent/e2e && pytest test_agent_e2e.py -v -m e2e
"""

import re
import subprocess
import time
from pathlib import Path

import httpx
import pytest

BASE_URL = "https://localhost:8443"
COMPOSE = ["docker", "compose", "-f", str(Path(__file__).parent / "docker-compose.yml")]
E2E_DIR = Path(__file__).parent


def _wait_until(predicate, *, timeout=30, interval=1.0):
    deadline = time.monotonic() + timeout
    last_exc = None
    while time.monotonic() < deadline:
        try:
            if predicate():
                return
        except Exception as exc:  # noqa: BLE001 — retry on transient connection errors
            last_exc = exc
        time.sleep(interval)
    raise TimeoutError(f"condition not met within {timeout}s (last error: {last_exc})")


def _bootstrap_admin(client: httpx.Client) -> str:
    status = client.get("/api/v1/bootstrap/status")
    if status.status_code == 200 and status.json().get("needs_bootstrap"):
        resp = client.post(
            "/api/v1/bootstrap/initialize",
            json={"email": "e2e@example.com", "password": "E2eTest1234!", "theme_preset": "one-dark"},
        )
    else:
        resp = client.post(
            "/api/v1/auth/login", json={"email": "e2e@example.com", "password": "E2eTest1234!"},
        )
    resp.raise_for_status()
    return resp.json()["access_token"]


@pytest.mark.e2e
def test_agent_enrolls_approves_goes_online_and_revoke_closes_link():
    subprocess.run([*COMPOSE, "up", "-d", "circuitbreaker"], check=True, cwd=E2E_DIR)
    try:
        # verify=False is deliberate and test-scoped: the mono container generates
        # a fresh self-signed cert per run with no stable CA to pin/trust here,
        # and this harness never leaves localhost. Do not carry this pattern into
        # any production code path — agent_install.py's tls_pin mechanism (Task 17)
        # is the real integrity anchor for actual installs.
        client = httpx.Client(base_url=BASE_URL, verify=False, timeout=30.0)
        _wait_until(lambda: client.get("/api/v1/bootstrap/status").status_code == 200, timeout=60)

        token = _bootstrap_admin(client)
        headers = {"Authorization": f"Bearer {token}"}

        script = client.get("/install-agent.sh").text
        server_pk = re.search(r'CB_SERVER_STATIC_PK="([0-9a-f]+)"', script).group(1)
        tls_pin = re.search(r'CB_TLS_PIN="([^"]*)"', script).group(1)
        (E2E_DIR / "agent.toml").write_text(
            f'server_url = "{BASE_URL}"\n'
            f'server_static_pk = "{server_pk}"\n'
            f'tls_pin = "{tls_pin}"\n'
            f'log_level = "info"\n'
            f'spool_cap_bytes = 67108864\n'
        )

        subprocess.run([*COMPOSE, "build", "cb-agent"], check=True, cwd=E2E_DIR)
        proc = subprocess.Popen(
            [*COMPOSE, "run", "--rm", "cb-agent", "enroll"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=E2E_DIR,
        )
        pairing_code = None
        deadline = time.monotonic() + 30
        for line in proc.stdout:
            m = re.search(r"pairing code:\s*(\S+)", line)
            if m:
                pairing_code = m.group(1)
                break
            if time.monotonic() > deadline:
                break
        assert pairing_code, "agent did not print a pairing code within 30s"

        lookup = client.post("/api/v1/agents/pairing/lookup", json={"code": pairing_code}, headers=headers)
        assert lookup.status_code == 200, lookup.text
        agent_id = lookup.json()["agent_id"]

        approve = client.post(f"/api/v1/agents/{agent_id}/approve", json={}, headers=headers)
        assert approve.status_code == 200, approve.text

        assert proc.wait(timeout=15) == 0, "enroll process did not exit 0 after approval"

        subprocess.run([*COMPOSE, "up", "-d", "cb-agent"], check=True, cwd=E2E_DIR)
        _wait_until(
            lambda: client.get(f"/api/v1/agents/{agent_id}", headers=headers).json()["status"] == "active",
            timeout=15,
        )

        revoke = client.post(
            f"/api/v1/agents/{agent_id}/revoke", json={"reason": "e2e test"}, headers=headers,
        )
        assert revoke.status_code == 200, revoke.text

        # Task 12's /link poll interval is 5s — allow a bit of margin.
        time.sleep(8)
        logs = subprocess.run(
            [*COMPOSE, "logs", "cb-agent"], capture_output=True, text=True, cwd=E2E_DIR,
        ).stdout
        assert "disconnect" in logs.lower() or "reconnect" in logs.lower(), (
            f"expected the agent log to show the link closing after revoke; got:\n{logs}"
        )
    finally:
        subprocess.run([*COMPOSE, "down", "-v"], cwd=E2E_DIR)
        (E2E_DIR / "agent.toml").unlink(missing_ok=True)
```

> **Verification notes for the implementer:**
> - `client.get("/install-agent.sh")` and the `CB_SERVER_STATIC_PK`/`CB_TLS_PIN` regexes assume
>   Task 17's template renders those exact literal assignments — confirm against the actual
>   rendered output once Task 17 is implemented, since this test is naturally written and run
>   after every other task in this plan.
> - The bootstrap response's token field name (`access_token` above) should be confirmed against
>   `tests/integration/test_oobe_smoke.py`'s actual assertions rather than trusted blindly.
> - `docker compose extends` (Step 2) requires the referenced service not itself use Compose
>   Specification features `extends` doesn't support (e.g. certain `depends_on` conditions) —
>   if the root `circuitbreaker` service definition doesn't extend cleanly, fall back to copying
>   the relevant subset of its config into this file directly rather than fighting the tooling.

- [ ] **Step 4: Run it**

Run: `cd apps/agent/e2e && pytest test_agent_e2e.py -v -m e2e`
Expected: passes end-to-end (~1-2 minutes, dominated by container build/boot). This is the final
verification gate for the whole slice — if every prior task's unit/integration tests pass but
this fails, the bug is almost always in how the pieces are wired together (main.py registration,
router prefixes, env var names) rather than in any single task's logic.

- [ ] **Step 5: Register the `e2e` marker and commit**

Add `markers = ["e2e: requires Docker; not run by default"]` to `apps/backend/pyproject.toml`'s
`[tool.pytest.ini_options]` section if a `markers` list doesn't already exist there — check first,
since another marker registration may already exist to extend rather than overwrite.

```bash
git add apps/agent/e2e apps/backend/pyproject.toml
git commit -m "test(agents): end-to-end docker-compose harness — enroll to online to revoke"
```

---

### Task 22: Close three spec gaps — uninstall, pending expiry, `/link` clock skew

Found during this plan's self-review, not during implementation — fix before treating the slice
as done, not after.

1. **`cb-agent uninstall`** (spec §4.7) was never wired up — Task 3's CLI switch only grew
   `version`/`status`/`enroll` cases.
2. **7-day pending-agent auto-expiry** (spec §6, "Approval never comes" row) has no job anywhere.
3. **`/link` never checks clock skew** — Task 7 added it to `/enroll`'s `hello` frame, but
   `/link` (Task 12) goes straight from the Noise handshake to `capabilities.set` with no
   timestamped frame to check at all, silently dropping a security property this plan's own
   Global Constraints section claims applies everywhere ("Handshakes with a timestamp outside
   ±60s are rejected... not a generic auth failure").

**Files:**
- Modify: `apps/agent/internal/frame/frame.go` (add `TypeUninstall` constant)
- Modify: `apps/agent/internal/link/link.go` (send a `hello` frame with the current timestamp
  immediately after the handshake, before entering the main loop)
- Modify: `apps/agent/cmd/cb-agent/main.go` (add the `uninstall` subcommand)
- Modify: `apps/backend/src/app/schemas/agent_frame.py` (add `TYPE_UNINSTALL`)
- Modify: `apps/backend/src/app/api/ws_agents.py` (`/link` reads and clock-skew-checks one
  `hello` frame right after the handshake, before sending `capabilities.set`)
- Modify: `apps/backend/src/app/services/agent_link.py` (add an `uninstall` handler)
- Modify: `apps/backend/src/app/services/agent_registry.py` (add
  `expire_stale_pending_agents`)
- Modify: `apps/backend/src/app/main.py` (schedule the expiry job)
- Test: `apps/backend/tests/services/test_agent_registry_expiry.py`
- Test: additions to `apps/backend/tests/api/test_ws_agents_link.py` and
  `apps/agent/internal/link/link_test.go`

**Interfaces:**
- Produces: `frame.TypeUninstall = "uninstall"` (Go), `TYPE_UNINSTALL = "uninstall"` (Python),
  `agent_registry.expire_stale_pending_agents(db: Session) -> int` (returns the count expired,
  for logging).

- [ ] **Step 1: Add the frame type constant on both sides**

```go
// apps/agent/internal/frame/frame.go — add to the agent -> server const block
	TypeUninstall = "uninstall"
```

```python
# apps/backend/src/app/schemas/agent_frame.py — add near TYPE_LOG
TYPE_UNINSTALL = "uninstall"
```

- [ ] **Step 2: `/link` sends and checks a `hello` frame for clock skew**

In `apps/agent/internal/link/link.go`'s `runOnce`, right after `session.ReadHandshakeMessage(msg2)`
succeeds and before the `incoming`/heartbeat select loop starts:

```go
	helloFrame := frame.Frame{V: 1, Type: frame.TypeHello, Seq: 0, TS: time.Now().UTC(), Payload: json.RawMessage("{}")}
	helloBytes, err := frame.Encode(helloFrame)
	if err != nil {
		return fmt.Errorf("link: %w", err)
	}
	if err := conn.WriteMessage(websocket.BinaryMessage, session.Encrypt(helloBytes)); err != nil {
		return fmt.Errorf("link: send hello: %w", err)
	}
```

In `apps/backend/src/app/api/ws_agents.py`'s `link_stream`, right after `await
websocket.send_bytes(response)` (the handshake response) and before the `device_pk_hex =
responder.remote_static().hex()` line:

```python
    try:
        hello_ct = await asyncio.wait_for(
            websocket.receive_bytes(), timeout=_HANDSHAKE_TIMEOUT_SECONDS
        )
        hello = json.loads(responder.decrypt(hello_ct))
        check_clock_skew(datetime.fromisoformat(hello["ts"]).replace(tzinfo=None))
    except ClockSkewError:
        await websocket.send_bytes(_error_bytes(responder, "clock_skew"))
        await websocket.close(code=1008)
        return
    except Exception:
        await websocket.close(code=1008)
        return
```

Add `ClockSkewError` and `check_clock_skew` to `ws_agents.py`'s existing `agent_crypto` import
line (already imports `NoiseIKResponder`/`get_server_static_keypair` from Task 7).

- [ ] **Step 3: Add a test for each side**

```go
// apps/agent/internal/link/link_test.go — extend TestRun_SendsHeartbeatsAndAppliesCapabilitiesSet's
// server handler, right after responder.ReadHandshakeMessage/conn.WriteMessage(msg2):
		_, helloCt, err := conn.ReadMessage()
		if err != nil {
			t.Errorf("expected a hello frame after handshake: %v", err)
			return
		}
		if _, err := responder.Decrypt(helloCt); err != nil {
			t.Errorf("decrypt hello: %v", err)
			return
		}
```

```python
# apps/backend/tests/api/test_ws_agents_link.py — new test
def test_link_rejects_stale_handshake_timestamp(db_session, factories, ws_client):
    import json
    from datetime import timedelta

    agent, agent_priv = _active_agent_with_key(db_session, factories)
    _, server_pub = get_server_static_keypair()

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        initiator = TestNoiseInitiator(agent_priv, server_pub)
        ws.send_bytes(initiator.write_message())
        initiator.read_message(ws.receive_bytes())

        stale_ts = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
        frame = {"v": 1, "type": "hello", "seq": 0, "ts": stale_ts, "payload": {}}
        ws.send_bytes(initiator.encrypt(json.dumps(frame).encode()))

        err = json.loads(initiator.decrypt(ws.receive_bytes()))
        assert err["payload"]["error"] == "clock_skew"
```

Run: `cd apps/agent && go test ./internal/link/... -v` and
`cd apps/backend && pytest tests/api/test_ws_agents_link.py -v` — both should pass, and the
existing `test_link_sends_capabilities_set_on_connect` test should still pass since it already
completes a full handshake (it just needs `initiator.write_message()`/`read_message()` — no
change needed there, only the new stale-timestamp test is added).

- [ ] **Step 4: `agent_link.py` handles `uninstall`**

```python
# apps/backend/src/app/services/agent_link.py — add near _handle_log
async def _handle_uninstall(db: Session, agent: Agent, frame: AgentFrame) -> None:
    agent_registry.revoke_agent(db, agent.id, actor_user_id=None, reason="uninstalled by agent")


_HANDLERS[TYPE_UNINSTALL] = _handle_uninstall
```

Add `TYPE_UNINSTALL` to the existing `from app.schemas.agent_frame import (...)` line.
`uninstall` deliberately isn't added to `CAPABILITY_FOR_TYPE` — like `heartbeat`/`log`, it's a
transport-level notification, not a granted capability, and `revoke_agent` already records its
own `agent_events` row, so no separate audit call is needed here.

- [ ] **Step 5: Test and implement `expire_stale_pending_agents`**

```python
# apps/backend/tests/services/test_agent_registry_expiry.py
from datetime import timedelta

from app.core.time import utcnow
from app.services import agent_registry as svc


def test_expires_pending_agents_older_than_seven_days(db_session, factories):
    stale = factories.agent(status="pending", enrolled_at=utcnow() - timedelta(days=8))
    fresh = factories.agent(status="pending", enrolled_at=utcnow() - timedelta(days=1))

    count = svc.expire_stale_pending_agents(db_session)

    assert count == 1
    db_session.refresh(stale)
    db_session.refresh(fresh)
    assert stale.status == "rejected"
    assert fresh.status == "pending"
```

Run: `cd apps/backend && pytest tests/services/test_agent_registry_expiry.py -v` — expect
`AttributeError` first, then passing after implementation.

```python
# apps/backend/src/app/services/agent_registry.py — append
_PENDING_EXPIRY_DAYS = 7


def expire_stale_pending_agents(db: Session) -> int:
    from datetime import timedelta

    cutoff = utcnow() - timedelta(days=_PENDING_EXPIRY_DAYS)
    stale = list(
        db.execute(
            select(Agent).where(Agent.status == "pending", Agent.enrolled_at < cutoff)
        ).scalars()
    )
    for agent in stale:
        agent.status = "rejected"
        record_event(db, agent.id, "rejected", detail={"reason": "pending_expired"})
    db.commit()
    return len(stale)
```

- [ ] **Step 6: Schedule the expiry job**

```python
# apps/backend/src/app/main.py — inside the same startup function as the other scheduler.add_job(...) calls
    from app.services import agent_registry
    from app.db.session import SessionLocal as _AgentSessionLocal

    def _expire_pending_agents_job() -> None:
        with _AgentSessionLocal() as db:
            count = agent_registry.expire_stale_pending_agents(db)
            if count:
                logger.info("expired %d stale pending agent(s)", count)

    scheduler.add_job(
        _expire_pending_agents_job,
        trigger=CronTrigger(hour=3, minute=30),
        id="expire_pending_agents",
        replace_existing=True,
    )
```

- [ ] **Step 7: `cb-agent uninstall`**

```go
// apps/agent/cmd/cb-agent/main.go — add to the switch in main()
	case "uninstall":
		runUninstall()
```

```go
func runUninstall() {
	cfg, err := config.Load("/etc/circuit-breaker/agent.toml")
	if err != nil {
		fmt.Fprintf(os.Stderr, "cb-agent: %v\n", err)
		os.Exit(1)
	}
	key, err := enroll.LoadOrCreateDeviceKey(config.StateDir())
	if err != nil {
		fmt.Fprintf(os.Stderr, "cb-agent: %v\n", err)
		os.Exit(1)
	}

	if err := notifyUninstall(cfg, key); err != nil {
		fmt.Fprintf(os.Stderr, "cb-agent: could not notify server (continuing anyway): %v\n", err)
	}
	fmt.Println("Notified the server. Run as root to finish removal:")
	fmt.Println("  systemctl disable --now cb-agent")
	fmt.Println("  rm -f /etc/systemd/system/cb-agent.service /usr/local/bin/cb-agent")
	fmt.Println("  rm -rf /var/lib/cb-agent /etc/circuit-breaker")
}
```

`notifyUninstall` reuses the same handshake dial as `link.Run`'s `runOnce` up through sending the
`hello` frame (Task 22 Step 2's addition), then sends one `uninstall` frame and returns — small
enough to write as a standalone function in `internal/link/link.go` rather than factoring
`runOnce` apart:

```go
// apps/agent/internal/link/link.go — new exported function, alongside Run
// Uninstall performs one short-lived connection: handshake, hello, then an
// uninstall notification. It does not enter the heartbeat loop.
func Uninstall(ctx context.Context, opts Options) error {
	remotePub, err := hex.DecodeString(opts.Config.ServerStaticPK)
	if err != nil || len(remotePub) != 32 {
		return fmt.Errorf("link: invalid server_static_pk: %w", err)
	}
	var remotePubArr [32]byte
	copy(remotePubArr[:], remotePub)

	session, err := noiseconn.NewInitiator(opts.Key.Private, opts.Key.Public, remotePubArr)
	if err != nil {
		return fmt.Errorf("link: %w", err)
	}

	u, err := url.Parse(opts.Config.ServerURL)
	if err != nil {
		return fmt.Errorf("link: invalid server_url: %w", err)
	}
	u.Scheme = strings.Replace(u.Scheme, "http", "ws", 1)
	u.Path = "/api/v1/agents/link"

	conn, _, err := websocket.DefaultDialer.DialContext(ctx, u.String(), nil)
	if err != nil {
		return fmt.Errorf("link: dial: %w", err)
	}
	defer conn.Close()

	msg1, err := session.WriteHandshakeMessage()
	if err != nil {
		return fmt.Errorf("link: %w", err)
	}
	if err := conn.WriteMessage(websocket.BinaryMessage, msg1); err != nil {
		return fmt.Errorf("link: send handshake: %w", err)
	}
	_, msg2, err := conn.ReadMessage()
	if err != nil {
		return fmt.Errorf("link: read handshake response: %w", err)
	}
	if err := session.ReadHandshakeMessage(msg2); err != nil {
		return fmt.Errorf("link: %w", err)
	}

	hello := frame.Frame{V: 1, Type: frame.TypeHello, Seq: 0, TS: time.Now().UTC(), Payload: json.RawMessage("{}")}
	helloBytes, _ := frame.Encode(hello)
	if err := conn.WriteMessage(websocket.BinaryMessage, session.Encrypt(helloBytes)); err != nil {
		return fmt.Errorf("link: send hello: %w", err)
	}

	uninstallFrame := frame.Frame{V: 1, Type: frame.TypeUninstall, Seq: 1, TS: time.Now().UTC(), Payload: json.RawMessage("{}")}
	uninstallBytes, _ := frame.Encode(uninstallFrame)
	return conn.WriteMessage(websocket.BinaryMessage, session.Encrypt(uninstallBytes))
}
```

```go
// apps/agent/cmd/cb-agent/main.go
func notifyUninstall(cfg *config.Config, key *enroll.DeviceKey) error {
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	return link.Uninstall(ctx, link.Options{Config: cfg, Key: key})
}
```

- [ ] **Step 8: Build, run the full Go and Python suites, and commit**

Run: `cd apps/agent && go build -o /tmp/cb-agent ./cmd/cb-agent && go test ./...`
Run: `cd apps/backend && pytest tests/ -k agent -v`
Expected: everything from every prior task still passes, plus this task's new tests.

```bash
git add apps/agent/internal/frame/frame.go apps/agent/internal/link/link.go \
        apps/agent/cmd/cb-agent/main.go apps/backend/src/app/schemas/agent_frame.py \
        apps/backend/src/app/api/ws_agents.py apps/backend/src/app/services/agent_link.py \
        apps/backend/src/app/services/agent_registry.py apps/backend/src/app/main.py \
        apps/backend/tests/services/test_agent_registry_expiry.py \
        apps/backend/tests/api/test_ws_agents_link.py apps/agent/internal/link/link_test.go
git commit -m "fix(agents): uninstall notification, pending-agent expiry, /link clock skew"
```

---

