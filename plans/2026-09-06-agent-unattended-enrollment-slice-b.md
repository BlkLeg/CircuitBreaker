# Unattended Agent Enrollment (Slice B) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an operator mint a short-lived, scoped enrollment token so a machine can install
`cb-agent` and become an approved agent with no human at the approval screen.

**Architecture:** A hashed-at-rest token row carries an endpoint URL and a capability scope. The
install script writes the plaintext to `/etc/circuit-breaker/enroll-token`; the agent sends it
inside the already-authenticated Noise channel on its enroll hello and unlinks it on success.
The server consumes the token in one atomic `UPDATE ... RETURNING`, and a consumed token creates
the agent `active` with grant rows written at that moment — approval *is* what is happening.
Every failure mode is reported identically so the endpoint is not an oracle.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 + Alembic + Pydantic (Python 3.12), Go 1.2x agent,
React + Vite (JSX), PostgreSQL, pytest, `go test`, vitest.

**Spec:** `docs/design/2026-09-05-agent-reachability-design.md` — §2.4, §3.2, §3.3, §4, §5, §6,
§7, §8, §9, §10, §11 (Slice B). Read it before Task 1. Slice A shipped on 2026-09-06 and is not
re-litigated here.

---

## Global Constraints

Copied from the spec and `CLAUDE.md`. Every task's requirements implicitly include these.

- **No placeholders.** No `TODO`, bare `pass`, or `NotImplementedError` in shipped code.
- **Backward compatible.** Migrations use `CREATE TABLE IF NOT EXISTS` / `ADD COLUMN IF NOT
  EXISTS`. Fields are added alongside old ones, never renamed or dropped. A half-updated
  deployment must still work: an agent predating this slice sends no token and must enroll
  exactly as it does today.
- **Air-gap is first-class.** `CB_AIRGAP=true` must not be affected. This slice makes no new
  outbound call from the server; an agent dialing its own server was never internet egress.
- **Secrets.** The plaintext token is never stored, never logged, never rendered into the
  install *script*, and never passed as a script argument. `argv` is visible in `ps` and lands
  in shell history and cloud-init logs.
- **Token format:** `cbe_` + `base64url(32 random bytes)`, no padding. The prefix exists so
  secret scanners and log redaction have a stable thing to match. Exact value: `cbe_`.
- **TTL:** default `3600` seconds, maximum `86400`. **`max_uses`:** default `1`, minimum `1`.
  Both are required rather than optional — they are what bound a token's blast radius (§5).
- **Not an oracle.** Invalid, spent, revoked and expired are one indistinguishable failure to
  the caller. Never report which.
- **Python:** snake_case, full type annotations (`mypy --disallow-untyped-defs` runs on
  `src/app`), docstrings on classes and public functions. Services hold logic; routes stay thin.
- **Frontend:** `.jsx` components (PascalCase), `.js` hooks/API modules. All HTTP through the
  axios client in `src/api/client.jsx`. Always render loading and error states.
- **API:** snake_case JSON, errors as `{"detail": "..."}`, correct HTTP codes.
- **Commits:** `feat:` / `fix:` / `chore:` / `docs:` / `test:`.
- **Running backend tests:** `.venv/bin/python -m pytest <target> -q --no-cov`. The `--no-cov`
  is load-bearing — `pytest-cov` enforces a 56% *global* threshold, so any single-file run exits
  non-zero even when every test passes. **Never lower the gate.**
- **Route ordering:** in `api/agents.py`, literal paths must be declared **before**
  `@router.post("/{agent_id}/...")`, or `enrollment-tokens` is parsed as an agent id. `/pending`,
  `/install-command`, `/capability-defaults`, `/endpoint-usage` and `/probe-eligible` already do
  this; follow them.

### What already shipped in Slice A — do not rebuild

- `AppSettings.agent_endpoints` (JSON), `services/agent_endpoints.py` with `normalize_endpoints`,
  `list_endpoints`, `find_endpoint`, `usage_counts`.
- `agents.enrolled_via_endpoint` (migration `a191f689a082`), reported by the agent in its enroll
  hello and read at `api/ws_agents.py:268` as `payload.get("server_url")`.
- `GET /install-agent.sh?endpoint=<id>`, `build_install_command(db, server_url, endpoint_id=None)`,
  `_script_download_arg`, the script's reachability preflight, the endpoint picker in
  `AddAgentPanel.jsx`, and **Settings → Connectivity → Agent Endpoints**.

### One free simplification, already verified

`internal/enroll/enroll.go` already handles an ack whose payload carries `status: "active"` —
it prints `approved — connecting` and returns nil (that is how an already-enrolled agent starts
today). **The unattended ack therefore needs no Go change on the receive side.** Send
`{"agent_id": N, "status": "active"}` and the shipped agent does the right thing.

---

## File Structure

**Create:**

| File | Responsibility |
|---|---|
| `apps/backend/migrations/versions/<rev>_agent_enrollment_tokens.py` | The table and `agents.enrollment_token_id` |
| `apps/backend/src/app/services/agent_enrollment_tokens.py` | Mint, hash, list, consume, revoke. All token logic. |
| `apps/backend/tests/services/test_agent_enrollment_tokens.py` | Service unit tests incl. the consumption race |
| `apps/backend/tests/api/test_agent_enrollment_token_routes.py` | Admin route tests |
| `apps/backend/tests/api/test_ws_agents_unattended_enroll.py` | The enroll-path integration tests |
| `apps/frontend/src/components/settings/EnrollmentTokensSection.jsx` | List + revoke, beside the endpoints section |
| `apps/frontend/src/__tests__/enrollment-tokens-section.test.jsx` | Its tests |

**Modify:**

| File | Change |
|---|---|
| `apps/backend/src/app/db/models.py` | `AgentEnrollmentToken`; `Agent.enrollment_token_id` |
| `apps/backend/src/app/schemas/agents.py` | `EnrollmentTokenCreate`, `EnrollmentTokenRead`, `EnrollmentTokenMinted` |
| `apps/backend/src/app/api/agents.py` | Three routes, declared before `/{agent_id}` |
| `apps/backend/src/app/api/ws_agents.py` | The token branch in `enroll_stream` |
| `apps/backend/src/app/services/agent_install.py` | Token file in the script; `enroll_token` in the command |
| `apps/backend/src/app/main.py` | `/install-agent.sh` keeps rendering token-free scripts (assert, not change) |
| `apps/agent/internal/frame/frame.go` | `HelloPayload.EnrollToken` |
| `apps/agent/internal/enroll/enroll.go` | Read the token file, attach it, unlink on success |
| `apps/frontend/src/components/agents/AddAgentPanel.jsx` | Attended / unattended choice |
| `apps/frontend/src/api/agents.js` | Three API functions |
| `apps/frontend/src/pages/SettingsPage.jsx` | Mount `EnrollmentTokensSection` |
| `.gitleaks.toml` | A rule for the `cbe_` prefix |
| `docs/agent.md`, `docs/settings.md` | The unattended flow |
| `apps/agent/e2e/test_agent_e2e.py` | An unattended scenario |

## Task Dependency Order

```
1 (schema)
└─ 2 (mint/list) ── 3 (consume/revoke) ── 4 (routes) ──┬─ 10 (wizard) ── 11 (settings UI)
                                        └─ 5 (enroll) ─┴─ 6 (race test)
                                                       └─ 7 (script) ── 8 (command) ── 9 (Go) ── 12 (e2e + docs)
```

Tasks 1–5 are strictly ordered. 6 depends on 3. 7–9 depend on 5. 10–11 depend on 4. 12 is last.

---

### Task 1: The `agent_enrollment_tokens` table and `agents.enrollment_token_id`

**Files:**
- Modify: `apps/backend/src/app/db/models.py`
- Create: `apps/backend/migrations/versions/<rev>_agent_enrollment_tokens.py`
- Test: `apps/backend/tests/services/test_agent_enrollment_tokens.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `AgentEnrollmentToken` with columns `id, token_hash, label, endpoint_url,
  capabilities, max_uses, uses, expires_at, revoked_at, created_by_user_id, created_at`;
  `Agent.enrollment_token_id: Mapped[int | None]`.

- [ ] **Step 1: Write the failing test**

`apps/backend/tests/services/test_agent_enrollment_tokens.py`:

```python
"""Slice B: the enrollment-token table (design §3.2, §3.3)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.time import utcnow


def test_a_token_row_round_trips_every_column(db_session, factories):
    from app.db.models import AgentEnrollmentToken

    user = factories.user(role="admin")
    db_session.commit()

    row = AgentEnrollmentToken(
        token_hash="a" * 64,
        label="warehouse fleet",
        endpoint_url="https://cb.example.com",
        capabilities={"host_telemetry": True},
        max_uses=3,
        uses=0,
        expires_at=utcnow() + timedelta(hours=1),
        created_by_user_id=user.id,
    )
    db_session.add(row)
    db_session.commit()
    db_session.expire_all()

    stored = db_session.get(AgentEnrollmentToken, row.id)
    assert stored.token_hash == "a" * 64
    assert stored.capabilities == {"host_telemetry": True}
    assert stored.max_uses == 3
    assert stored.uses == 0
    assert stored.revoked_at is None
    assert stored.created_at is not None


def test_the_token_hash_is_unique(db_session, factories):
    """Two rows for one token would make consumption ambiguous."""
    from sqlalchemy.exc import IntegrityError

    from app.db.models import AgentEnrollmentToken

    user = factories.user(role="admin")
    db_session.commit()

    def _row() -> AgentEnrollmentToken:
        return AgentEnrollmentToken(
            token_hash="b" * 64,
            label="dup",
            endpoint_url="https://cb.example.com",
            capabilities={},
            max_uses=1,
            expires_at=utcnow() + timedelta(hours=1),
            created_by_user_id=user.id,
        )

    db_session.add(_row())
    db_session.commit()
    db_session.add(_row())
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_an_agent_can_name_the_token_it_came_from(db_session, factories):
    """Provenance survives revocation: tokens are revoked, never deleted."""
    from app.db.models import AgentEnrollmentToken

    user = factories.user(role="admin")
    db_session.commit()
    token = AgentEnrollmentToken(
        token_hash="c" * 64,
        label="provenance",
        endpoint_url="https://cb.example.com",
        capabilities={},
        max_uses=1,
        expires_at=utcnow() + timedelta(hours=1),
        created_by_user_id=user.id,
    )
    db_session.add(token)
    db_session.commit()

    agent = factories.agent(status="active")
    agent.enrollment_token_id = token.id
    db_session.commit()
    db_session.expire_all()

    assert db_session.get(type(agent), agent.id).enrollment_token_id == token.id
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest apps/backend/tests/services/test_agent_enrollment_tokens.py -q --no-cov`
Expected: FAIL with `ImportError: cannot import name 'AgentEnrollmentToken'`.

- [ ] **Step 3: Add the model**

In `apps/backend/src/app/db/models.py`, beside the other agent tables:

```python
class AgentEnrollmentToken(Base):
    """A short-lived bearer credential that enrolls an agent with no human present.

    The plaintext is returned once at mint and never stored — `token_hash` is
    SHA-256 of it, mirroring `user_service._hash_token`. `max_uses` exists
    because a single-use token breaks the case that motivates the feature: one
    token baked into a launch template, N instances booting, only the first
    enrolling (design §3.2).

    Rows are revoked, never deleted, so `agents.enrollment_token_id` stays
    resolvable for the life of every agent that came through one.
    """

    __tablename__ = "agent_enrollment_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    label: Mapped[str] = mapped_column(String, nullable=False)
    #: The address this token's agents are told to dial. Stored as the URL
    #: rather than the endpoint id so a deleted endpoint does not orphan a
    #: token that is still live, matching `agent_endpoints.usage_counts`.
    endpoint_url: Mapped[str] = mapped_column(String, nullable=False)
    #: The grant scope applied on auto-approval — the same shape
    #: `POST /{agent_id}/approve` accepts for `capabilities`.
    capabilities: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    max_uses: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    uses: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
```

Match the file's existing import names — it already imports `Integer`, `String`, `DateTime`,
`JSON`, `ForeignKey`, `Mapped`, `mapped_column`, `Any`, `datetime` and `utcnow`. Do not add
duplicate imports.

On the `Agent` class, directly under `enrolled_via_endpoint`:

```python
    # Which enrollment token this agent came through, when it came through one.
    # Nullable and never back-filled: every agent enrolled before this slice,
    # and every attended enrollment after it, has none.
    enrollment_token_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("agent_enrollment_tokens.id"), nullable=True
    )
```

- [ ] **Step 4: Write the migration**

Get the current head first: `git log --oneline -1 -- apps/backend/migrations/versions` and read
the newest file. At the time of writing the head is `a191f689a082`
(`agent_enrolled_via_endpoint`). **Verify this before writing `down_revision` — another slice may
have landed since.**

Create `apps/backend/migrations/versions/b3d7c1e05a44_agent_enrollment_tokens.py`:

```python
"""Add agent_enrollment_tokens and agents.enrollment_token_id.

Revision ID: b3d7c1e05a44
Revises: a191f689a082
Create Date: 2026-09-06

Slice B: unattended enrollment. Both statements are existence-guarded because a
self-hoster upgrades on their own schedule and a half-updated deployment must
still work — see CLAUDE.md's backward-compatibility rule.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b3d7c1e05a44"
down_revision: str | None = "a191f689a082"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create the token table and the agent's provenance column."""
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS agent_enrollment_tokens (
                id SERIAL PRIMARY KEY,
                token_hash VARCHAR(64) NOT NULL UNIQUE,
                label VARCHAR NOT NULL,
                endpoint_url VARCHAR NOT NULL,
                capabilities JSON NOT NULL DEFAULT '{}'::json,
                max_uses INTEGER NOT NULL DEFAULT 1,
                uses INTEGER NOT NULL DEFAULT 0,
                expires_at TIMESTAMPTZ NOT NULL,
                revoked_at TIMESTAMPTZ,
                created_by_user_id INTEGER REFERENCES users(id),
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
    )
    bind.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_agent_enrollment_tokens_token_hash "
            "ON agent_enrollment_tokens (token_hash)"
        )
    )
    bind.execute(
        sa.text(
            "ALTER TABLE agents ADD COLUMN IF NOT EXISTS enrollment_token_id INTEGER "
            "REFERENCES agent_enrollment_tokens(id)"
        )
    )


def downgrade() -> None:
    """Drop the column, then the table it references."""
    bind = op.get_bind()
    bind.execute(sa.text("ALTER TABLE agents DROP COLUMN IF EXISTS enrollment_token_id"))
    bind.execute(sa.text("DROP TABLE IF EXISTS agent_enrollment_tokens"))
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest apps/backend/tests/services/test_agent_enrollment_tokens.py -q --no-cov`
Expected: PASS (3 tests).

Then prove the migration itself runs against the real test database, rather than relying on the
test fixtures' `create_all`:

Run: `cd apps/backend && CB_DB_URL="$CB_TEST_DB_URL" ../../.venv/bin/python -m alembic upgrade head`
Expected: no error, and the chain is unforked — `../../.venv/bin/python -m alembic heads` prints
exactly one head.

- [ ] **Step 6: Lint and commit**

```bash
.venv/bin/python -m ruff format apps/backend/src/app/db/models.py apps/backend/migrations/versions/b3d7c1e05a44_agent_enrollment_tokens.py apps/backend/tests/services/test_agent_enrollment_tokens.py
make lint
git add apps/backend/src/app/db/models.py apps/backend/migrations/versions/b3d7c1e05a44_agent_enrollment_tokens.py apps/backend/tests/services/test_agent_enrollment_tokens.py
git commit -m "feat(agents): add the enrollment-token table"
```

---

### Task 2: Mint and list

**Files:**
- Create: `apps/backend/src/app/services/agent_enrollment_tokens.py`
- Test: `apps/backend/tests/services/test_agent_enrollment_tokens.py` (append)

**Interfaces:**
- Consumes: `AgentEnrollmentToken` from Task 1.
- Produces:
  - `TOKEN_PREFIX: str = "cbe_"`
  - `DEFAULT_TTL_SECONDS: int = 3600`, `MAX_TTL_SECONDS: int = 86400`
  - `hash_token(token: str) -> str`
  - `mint_token(db, *, label, endpoint_url, capabilities, ttl_seconds, max_uses, created_by_user_id) -> tuple[str, AgentEnrollmentToken]`
    — returns `(plaintext, row)`. Raises `ValueError` on a bad TTL or `max_uses`.
  - `list_tokens(db) -> list[AgentEnrollmentToken]` — newest first, revoked and expired included.

- [ ] **Step 1: Write the failing test**

Append to `apps/backend/tests/services/test_agent_enrollment_tokens.py`:

```python
def test_minting_returns_the_plaintext_once_and_stores_only_its_hash(db_session, factories):
    """The row must not be able to reproduce the credential it authorises."""
    from app.services import agent_enrollment_tokens as tokens

    user = factories.user(role="admin")
    db_session.commit()

    plaintext, row = tokens.mint_token(
        db_session,
        label="warehouse",
        endpoint_url="https://cb.example.com",
        capabilities={"host_telemetry": True},
        ttl_seconds=3600,
        max_uses=1,
        created_by_user_id=user.id,
    )
    db_session.commit()

    assert plaintext.startswith("cbe_")
    assert len(plaintext) > len("cbe_") + 40  # 32 bytes base64url
    assert row.token_hash == tokens.hash_token(plaintext)
    assert plaintext not in row.token_hash
    # Nothing on the row, in any column, is the plaintext.
    assert plaintext not in repr({c.name: getattr(row, c.name) for c in row.__table__.columns})


def test_two_mints_never_produce_the_same_token(db_session, factories):
    from app.services import agent_enrollment_tokens as tokens

    user = factories.user(role="admin")
    db_session.commit()

    minted = set()
    for i in range(5):
        plaintext, _ = tokens.mint_token(
            db_session,
            label=f"t{i}",
            endpoint_url="https://cb.example.com",
            capabilities={},
            ttl_seconds=3600,
            max_uses=1,
            created_by_user_id=user.id,
        )
        minted.add(plaintext)
    db_session.commit()

    assert len(minted) == 5


@pytest.mark.parametrize(
    "ttl_seconds,max_uses",
    [(0, 1), (-1, 1), (86401, 1), (3600, 0), (3600, -1)],
)
def test_a_token_outside_its_declared_bounds_is_refused(
    db_session, factories, ttl_seconds, max_uses
):
    """TTL and max_uses are what bound a token's blast radius (design §5), so
    both are validated at the only place a token can be created."""
    from app.services import agent_enrollment_tokens as tokens

    user = factories.user(role="admin")
    db_session.commit()

    with pytest.raises(ValueError):
        tokens.mint_token(
            db_session,
            label="bad",
            endpoint_url="https://cb.example.com",
            capabilities={},
            ttl_seconds=ttl_seconds,
            max_uses=max_uses,
            created_by_user_id=user.id,
        )


def test_listing_puts_the_newest_token_first(db_session, factories):
    from app.services import agent_enrollment_tokens as tokens

    user = factories.user(role="admin")
    db_session.commit()
    for label in ("first", "second", "third"):
        tokens.mint_token(
            db_session,
            label=label,
            endpoint_url="https://cb.example.com",
            capabilities={},
            ttl_seconds=3600,
            max_uses=1,
            created_by_user_id=user.id,
        )
    db_session.commit()

    assert [t.label for t in tokens.list_tokens(db_session)][0] == "third"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest apps/backend/tests/services/test_agent_enrollment_tokens.py -q --no-cov -k "mint or listing or bounds"`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.agent_enrollment_tokens'`.

- [ ] **Step 3: Write the module**

Create `apps/backend/src/app/services/agent_enrollment_tokens.py`:

```python
"""Short-lived bearer tokens that enroll an agent with no human present.

The attended flow — a human comparing a fingerprint and pressing approve — is
unchanged and remains the default. This is opt-in, and §5 of
`docs/design/2026-09-05-agent-reachability-design.md` states its cost plainly:
a multi-use token in a launch template is a credential that will enroll
anything presenting it for its whole TTL. Today's attended design has the
stronger property that no bearer secret exists at all.

Everything here exists to bound that: the plaintext is returned once and stored
only as a SHA-256 hash, a TTL is required and capped, `max_uses` defaults to 1,
the token is scoped to one endpoint and one capability set, revocation is
immediate, and consumption is a single atomic statement that cannot
over-consume under concurrent boots.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.db.models import AgentEnrollmentToken

#: Prefix on every minted token. Exists so secret scanners and log redaction
#: have a stable thing to match — see .gitleaks.toml.
TOKEN_PREFIX = "cbe_"

#: Bytes of entropy behind the prefix.
_TOKEN_BYTES = 32

#: An hour rather than minutes: the realistic path is a human pasting the value
#: into a launch template or a secrets store, not a script consuming it
#: immediately (design §4).
DEFAULT_TTL_SECONDS = 3600
MAX_TTL_SECONDS = 24 * 3600


def hash_token(token: str) -> str:
    """SHA-256 of `token`, hex. Mirrors `user_service._hash_token`."""
    return hashlib.sha256(token.encode()).hexdigest()


def _mint_plaintext() -> str:
    """A fresh token: the prefix plus 32 random bytes, base64url, unpadded."""
    raw = secrets.token_bytes(_TOKEN_BYTES)
    return TOKEN_PREFIX + base64.urlsafe_b64encode(raw).decode().rstrip("=")


def mint_token(
    db: Session,
    *,
    label: str,
    endpoint_url: str,
    capabilities: dict[str, Any],
    ttl_seconds: int,
    max_uses: int,
    created_by_user_id: int | None,
) -> tuple[str, AgentEnrollmentToken]:
    """Create a token, returning `(plaintext, row)`.

    The plaintext is returned to exactly one caller and is never recoverable
    afterwards — the row holds only its hash. Raises `ValueError` when the TTL
    or `max_uses` falls outside its declared bounds; the caller turns that into
    a 400. Validating here rather than only in the schema means the CLI and any
    future caller get the same bounds as the API.

    Does not commit: the caller owns the transaction, so a mint that is audited
    in the same transaction either lands with its audit row or not at all.
    """
    if not 0 < ttl_seconds <= MAX_TTL_SECONDS:
        raise ValueError(f"ttl_seconds must be between 1 and {MAX_TTL_SECONDS}")
    if max_uses < 1:
        raise ValueError("max_uses must be at least 1")

    plaintext = _mint_plaintext()
    row = AgentEnrollmentToken(
        token_hash=hash_token(plaintext),
        label=label,
        endpoint_url=endpoint_url,
        capabilities=capabilities,
        max_uses=max_uses,
        uses=0,
        expires_at=utcnow() + timedelta(seconds=ttl_seconds),
        created_by_user_id=created_by_user_id,
    )
    db.add(row)
    db.flush()
    return plaintext, row


def list_tokens(db: Session) -> list[AgentEnrollmentToken]:
    """Every token, newest first.

    Revoked and expired rows are included rather than filtered: an operator
    auditing what was minted needs to see the ones that are no longer live, and
    a token still names the agents that came through it.
    """
    return list(
        db.execute(
            select(AgentEnrollmentToken).order_by(
                AgentEnrollmentToken.created_at.desc(), AgentEnrollmentToken.id.desc()
            )
        )
        .scalars()
        .all()
    )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest apps/backend/tests/services/test_agent_enrollment_tokens.py -q --no-cov`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
make lint
git add apps/backend/src/app/services/agent_enrollment_tokens.py apps/backend/tests/services/test_agent_enrollment_tokens.py
git commit -m "feat(agents): mint enrollment tokens, storing only their hash"
```

---

### Task 3: Consume and revoke

**Files:**
- Modify: `apps/backend/src/app/services/agent_enrollment_tokens.py`
- Test: `apps/backend/tests/services/test_agent_enrollment_tokens.py` (append)

**Interfaces:**
- Consumes: Task 2's module.
- Produces:
  - `@dataclass(frozen=True) class ConsumedToken: id: int; endpoint_url: str; capabilities: dict[str, Any]; created_by_user_id: int | None`
  - `consume_token(db, token: str) -> ConsumedToken | None` — `None` for every failure.
  - `revoke_token(db, token_id: int) -> AgentEnrollmentToken | None`

- [ ] **Step 1: Write the failing test**

Append:

```python
def _mint(db_session, user, **overrides):
    from app.services import agent_enrollment_tokens as tokens

    kwargs = {
        "label": "t",
        "endpoint_url": "https://cb.example.com",
        "capabilities": {"host_telemetry": True},
        "ttl_seconds": 3600,
        "max_uses": 1,
        "created_by_user_id": user.id,
    }
    kwargs.update(overrides)
    plaintext, row = tokens.mint_token(db_session, **kwargs)
    db_session.commit()
    return plaintext, row


def test_consuming_a_live_token_returns_its_scope_and_spends_one_use(db_session, factories):
    from app.services import agent_enrollment_tokens as tokens

    user = factories.user(role="admin")
    db_session.commit()
    plaintext, row = _mint(db_session, user)

    consumed = tokens.consume_token(db_session, plaintext)

    assert consumed is not None
    assert consumed.id == row.id
    assert consumed.endpoint_url == "https://cb.example.com"
    assert consumed.capabilities == {"host_telemetry": True}
    assert consumed.created_by_user_id == user.id
    db_session.expire_all()
    assert db_session.get(type(row), row.id).uses == 1


def test_a_multi_use_token_is_spent_exactly_max_uses_times(db_session, factories):
    from app.services import agent_enrollment_tokens as tokens

    user = factories.user(role="admin")
    db_session.commit()
    plaintext, _ = _mint(db_session, user, max_uses=3)

    assert [tokens.consume_token(db_session, plaintext) is not None for _ in range(4)] == [
        True,
        True,
        True,
        False,
    ]


@pytest.mark.parametrize("case", ["unknown", "expired", "revoked", "spent"])
def test_every_failure_mode_is_the_same_answer(db_session, factories, case):
    """Not an oracle (design §4): a caller must not be able to tell an unknown
    token from a spent, revoked or expired one — the difference is exactly what
    would let someone probe for live tokens."""
    from app.services import agent_enrollment_tokens as tokens

    user = factories.user(role="admin")
    db_session.commit()

    if case == "unknown":
        assert tokens.consume_token(db_session, "cbe_nothing-like-this") is None
        return

    plaintext, row = _mint(db_session, user)
    if case == "expired":
        row.expires_at = utcnow() - timedelta(seconds=1)
    elif case == "revoked":
        row.revoked_at = utcnow()
    elif case == "spent":
        row.uses = row.max_uses
    db_session.commit()

    assert tokens.consume_token(db_session, plaintext) is None


def test_revoking_shuts_a_token_that_still_has_uses_left(db_session, factories):
    from app.services import agent_enrollment_tokens as tokens

    user = factories.user(role="admin")
    db_session.commit()
    plaintext, row = _mint(db_session, user, max_uses=5)

    revoked = tokens.revoke_token(db_session, row.id)
    db_session.commit()

    assert revoked is not None and revoked.revoked_at is not None
    assert tokens.consume_token(db_session, plaintext) is None


def test_revoking_an_unknown_token_is_none_not_an_error(db_session):
    from app.services import agent_enrollment_tokens as tokens

    assert tokens.revoke_token(db_session, 999_999) is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest apps/backend/tests/services/test_agent_enrollment_tokens.py -q --no-cov -k "consum or revok or failure_mode"`
Expected: FAIL with `AttributeError: module ... has no attribute 'consume_token'`.

- [ ] **Step 3: Implement consumption and revocation**

Add to `agent_enrollment_tokens.py` (and add `from dataclasses import dataclass` and
`from sqlalchemy import text, update as sa_update` to the imports):

```python
@dataclass(frozen=True)
class ConsumedToken:
    """What one successful consumption grants, read off the row as it was spent.

    Carries `created_by_user_id` because auto-approval needs an approver: the
    operator who minted the token is the person who authorised every agent it
    enrolls, and recording anyone else — or nobody — would make the audit trail
    say something untrue.
    """

    id: int
    endpoint_url: str
    capabilities: dict[str, Any]
    created_by_user_id: int | None


def consume_token(db: Session, token: str) -> ConsumedToken | None:
    """Spend one use of `token`, or return None.

    One atomic statement, deliberately. A read-then-write would let two
    machines booting from the same launch template both observe
    `uses < max_uses` before either wrote, and both enroll — over-consuming a
    token whose whole purpose is to bound how many agents it can create. The
    `WHERE` clause carries every liveness condition so the database, not this
    process, decides; Postgres re-evaluates it against the just-committed row
    for whichever caller waited on the other's row lock.

    Returns None for **every** failure — unknown, spent, revoked, expired.
    The caller must not distinguish them and neither does this: the token
    endpoint is not an oracle (design §4).
    """
    row = db.execute(
        text(
            """
            UPDATE agent_enrollment_tokens
               SET uses = uses + 1
             WHERE token_hash = :hash
               AND uses < max_uses
               AND revoked_at IS NULL
               AND expires_at > now()
         RETURNING id, endpoint_url, capabilities, created_by_user_id
            """
        ),
        {"hash": hash_token(token)},
    ).first()
    if row is None:
        return None
    return ConsumedToken(
        id=row.id,
        endpoint_url=row.endpoint_url,
        capabilities=dict(row.capabilities or {}),
        created_by_user_id=row.created_by_user_id,
    )


def revoke_token(db: Session, token_id: int) -> AgentEnrollmentToken | None:
    """Mark `token_id` revoked, or return None when it does not exist.

    Revoking does not affect agents already enrolled through it — they hold
    their own device identity and never present the token again. It is not a
    delete: `agents.enrollment_token_id` must stay resolvable.

    Re-revoking is a no-op rather than an error; the first `revoked_at` is the
    honest one and an operator clicking twice should not be told they failed.
    """
    row = db.get(AgentEnrollmentToken, token_id)
    if row is None:
        return None
    if row.revoked_at is None:
        row.revoked_at = utcnow()
        db.flush()
    return row
```

**Note for the implementer:** `capabilities` comes back from the raw `RETURNING` as whatever the
driver decodes `JSON` to — a `dict` on psycopg. `dict(row.capabilities or {})` normalises both
that and a `None` column into a plain dict, so `ConsumedToken.capabilities` is always safe to
`.update()` from.

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest apps/backend/tests/services/test_agent_enrollment_tokens.py -q --no-cov`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
make lint
git add apps/backend/src/app/services/agent_enrollment_tokens.py apps/backend/tests/services/test_agent_enrollment_tokens.py
git commit -m "feat(agents): consume and revoke enrollment tokens"
```

---

### Task 4: The admin routes

**Files:**
- Modify: `apps/backend/src/app/schemas/agents.py`
- Modify: `apps/backend/src/app/api/agents.py`
- Test: `apps/backend/tests/api/test_agent_enrollment_token_routes.py` (create)

**Interfaces:**
- Consumes: `agent_enrollment_tokens.mint_token`, `list_tokens`, `revoke_token`;
  `agent_endpoints.find_endpoint`.
- Produces:
  - `POST /api/v1/agents/enrollment-tokens` → `EnrollmentTokenMinted` (201)
  - `GET /api/v1/agents/enrollment-tokens` → `list[EnrollmentTokenRead]`
  - `POST /api/v1/agents/enrollment-tokens/{token_id}/revoke` → `EnrollmentTokenRead`
  - `EnrollmentTokenRead` fields: `id, label, endpoint_url, capabilities, max_uses, uses,
    expires_at, revoked_at, created_at, agent_count`.

- [ ] **Step 1: Write the failing test**

Create `apps/backend/tests/api/test_agent_enrollment_token_routes.py`:

```python
"""Slice B: minting, listing and revoking enrollment tokens over the API."""

from __future__ import annotations

import pytest


ENDPOINT = {"id": "pub1", "label": "Public", "url": "https://cb.example.com"}


@pytest.fixture
def configured_endpoint(db_session):
    from app.schemas.settings import AppSettingsUpdate
    from app.services import settings_service

    settings_service.update_settings(db_session, AppSettingsUpdate(agent_endpoints=[ENDPOINT]))
    db_session.commit()
    return ENDPOINT


@pytest.mark.asyncio
async def test_minting_returns_the_plaintext_exactly_once(
    client, auth_headers, configured_endpoint
):
    resp = await client.post(
        "/api/v1/agents/enrollment-tokens",
        json={"label": "warehouse", "endpoint_id": "pub1", "ttl_seconds": 3600, "max_uses": 1},
        headers=auth_headers,
    )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["token"].startswith("cbe_")
    token_id = body["id"]

    listed = await client.get("/api/v1/agents/enrollment-tokens", headers=auth_headers)
    assert listed.status_code == 200
    row = next(t for t in listed.json() if t["id"] == token_id)
    assert "token" not in row, "the plaintext must never be readable again"


@pytest.mark.asyncio
async def test_an_unknown_endpoint_is_refused_rather_than_defaulted(
    client, auth_headers, configured_endpoint
):
    """A token scoped to an address nobody declared would send its agents
    somewhere the operator never chose."""
    resp = await client.post(
        "/api/v1/agents/enrollment-tokens",
        json={"label": "x", "endpoint_id": "nope", "ttl_seconds": 3600, "max_uses": 1},
        headers=auth_headers,
    )

    assert resp.status_code == 404
    assert "nope" in resp.json()["detail"]


@pytest.mark.asyncio
@pytest.mark.parametrize("body_overrides", [{"ttl_seconds": 0}, {"ttl_seconds": 86401}, {"max_uses": 0}])
async def test_bounds_are_enforced_at_the_edge(
    client, auth_headers, configured_endpoint, body_overrides
):
    body = {"label": "x", "endpoint_id": "pub1", "ttl_seconds": 3600, "max_uses": 1}
    body.update(body_overrides)

    resp = await client.post(
        "/api/v1/agents/enrollment-tokens", json=body, headers=auth_headers
    )

    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_revoking_is_reflected_in_the_listing(client, auth_headers, configured_endpoint):
    minted = await client.post(
        "/api/v1/agents/enrollment-tokens",
        json={"label": "x", "endpoint_id": "pub1", "ttl_seconds": 3600, "max_uses": 1},
        headers=auth_headers,
    )
    token_id = minted.json()["id"]

    resp = await client.post(
        f"/api/v1/agents/enrollment-tokens/{token_id}/revoke", headers=auth_headers
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["revoked_at"] is not None


@pytest.mark.asyncio
async def test_revoking_an_unknown_token_is_404(client, auth_headers):
    resp = await client.post(
        "/api/v1/agents/enrollment-tokens/999999/revoke", headers=auth_headers
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,path",
    [
        ("post", "/api/v1/agents/enrollment-tokens"),
        ("get", "/api/v1/agents/enrollment-tokens"),
        ("post", "/api/v1/agents/enrollment-tokens/1/revoke"),
    ],
)
async def test_every_token_route_requires_admin(client, viewer_auth_headers, method, path):
    """A viewer who could mint one could enroll anything."""
    call = getattr(client, method)
    resp = await call(path, headers=viewer_auth_headers, **({"json": {}} if method == "post" else {}))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_the_listing_counts_the_agents_each_token_enrolled(
    client, auth_headers, db_session, factories, configured_endpoint
):
    """Provenance is the reason a revoked token is kept rather than deleted."""
    minted = await client.post(
        "/api/v1/agents/enrollment-tokens",
        json={"label": "x", "endpoint_id": "pub1", "ttl_seconds": 3600, "max_uses": 5},
        headers=auth_headers,
    )
    token_id = minted.json()["id"]
    agent = factories.agent(status="active")
    agent.enrollment_token_id = token_id
    db_session.commit()

    listed = await client.get("/api/v1/agents/enrollment-tokens", headers=auth_headers)
    row = next(t for t in listed.json() if t["id"] == token_id)

    assert row["agent_count"] == 1
```

**Note:** if the test suite's admin fixture is not named `auth_headers` / there is no
`viewer_auth_headers`, use whatever `apps/backend/tests/api/test_agents_tls_pin_routes.py`'s
`test_routes_require_admin` uses — copy that file's fixtures rather than inventing new ones.

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest apps/backend/tests/api/test_agent_enrollment_token_routes.py -q --no-cov`
Expected: FAIL with 404s — the routes do not exist.

- [ ] **Step 3: Add the schemas**

In `apps/backend/src/app/schemas/agents.py`:

```python
class EnrollmentTokenCreate(BaseModel):
    """Mint request. Bounds are declared here *and* in the service: the schema
    gives the API a 422 with a field name, the service gives every other caller
    the same limits."""

    label: str = Field(min_length=1, max_length=120)
    endpoint_id: str = Field(min_length=1)
    capabilities: dict[str, Any] | None = None
    ttl_seconds: int = Field(default=3600, ge=1, le=86400)
    max_uses: int = Field(default=1, ge=1)


class EnrollmentTokenRead(BaseModel):
    """A token as an operator sees it. Carries no key material — the plaintext
    is returned once, by the mint route, and is not recoverable afterwards."""

    id: int
    label: str
    endpoint_url: str
    capabilities: dict[str, Any]
    max_uses: int
    uses: int
    expires_at: datetime
    revoked_at: datetime | None
    created_at: datetime
    #: How many agents enrolled through this token. The reason a spent or
    #: revoked token is kept rather than deleted.
    agent_count: int


class EnrollmentTokenMinted(EnrollmentTokenRead):
    """The mint response, and the only place the plaintext ever appears."""

    token: str
```

- [ ] **Step 4: Add the routes**

In `apps/backend/src/app/api/agents.py`, **immediately after `get_endpoint_usage`** (so they sit
with the other literal paths, before `/{agent_id}`):

```python
def _token_to_read(db: Session, row: AgentEnrollmentToken) -> dict[str, Any]:
    """Render one token row, with the count of agents that came through it."""
    from sqlalchemy import func, select as sa_select

    from app.db.models import Agent

    count = db.execute(
        sa_select(func.count()).select_from(Agent).where(Agent.enrollment_token_id == row.id)
    ).scalar_one()
    return {
        "id": row.id,
        "label": row.label,
        "endpoint_url": row.endpoint_url,
        "capabilities": row.capabilities or {},
        "max_uses": row.max_uses,
        "uses": row.uses,
        "expires_at": row.expires_at,
        "revoked_at": row.revoked_at,
        "created_at": row.created_at,
        "agent_count": int(count),
    }


@router.post("/enrollment-tokens", response_model=EnrollmentTokenMinted, status_code=201)
def post_enrollment_token(
    payload: EnrollmentTokenCreate,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, require_role("admin")],
) -> Any:
    """Mint a token that enrolls an agent with no human at the approval screen.

    The plaintext is in this response and nowhere else, ever. Declared before
    "/{agent_id}" so "enrollment-tokens" is not parsed as an agent id.
    """
    from app.services import agent_endpoints, agent_enrollment_tokens

    endpoint = agent_endpoints.find_endpoint(db, payload.endpoint_id)
    if endpoint is None:
        # Never fall back to a derived address: a token scoped to an endpoint
        # nobody declared would send its agents somewhere the operator did not
        # choose, which is the defect the endpoint feature exists to remove.
        raise HTTPException(
            status_code=404, detail=f"No agent endpoint with id {payload.endpoint_id!r}"
        )

    try:
        plaintext, row = agent_enrollment_tokens.mint_token(
            db,
            label=payload.label,
            endpoint_url=endpoint["url"],
            capabilities=payload.capabilities or {},
            ttl_seconds=payload.ttl_seconds,
            max_uses=payload.max_uses,
            created_by_user_id=user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Chained audit (F17). Low-volume by nature — deliberately unlike the
    # high-volume agent events write_log's docstring warns against chaining.
    # The token itself is never in `diff`: this row is the record that one was
    # minted, not a copy of it.
    log_service.write_log(
        db,
        action="agent_enrollment_token_minted",
        entity_type="agent_enrollment_token",
        entity_id=row.id,
        entity_name=row.label,
        actor_id=user.id,
        actor_name=user.username,
        severity="warning",
        diff={
            "endpoint_url": row.endpoint_url,
            "max_uses": row.max_uses,
            "expires_at": row.expires_at.isoformat(),
        },
    )
    db.commit()
    return {**_token_to_read(db, row), "token": plaintext}


@router.get("/enrollment-tokens", response_model=list[EnrollmentTokenRead])
def get_enrollment_tokens(
    db: Annotated[Session, Depends(get_db)],
    _user: Annotated[User, require_role("admin")],
) -> Any:
    """Every token, newest first, including revoked and expired ones."""
    from app.services import agent_enrollment_tokens

    return [_token_to_read(db, row) for row in agent_enrollment_tokens.list_tokens(db)]


@router.post("/enrollment-tokens/{token_id}/revoke", response_model=EnrollmentTokenRead)
def post_revoke_enrollment_token(
    token_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, require_role("admin")],
) -> Any:
    """Shut a token immediately. Agents already enrolled through it are
    unaffected — they hold their own device identity."""
    from app.services import agent_enrollment_tokens

    row = agent_enrollment_tokens.revoke_token(db, token_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"No enrollment token with id {token_id}")

    log_service.write_log(
        db,
        action="agent_enrollment_token_revoked",
        entity_type="agent_enrollment_token",
        entity_id=row.id,
        entity_name=row.label,
        actor_id=user.id,
        actor_name=user.username,
        severity="warning",
    )
    db.commit()
    return _token_to_read(db, row)
```

Add `AgentEnrollmentToken` to the `app.db.models` import at the top of the file, and
`EnrollmentTokenCreate, EnrollmentTokenMinted, EnrollmentTokenRead` to the
`app.schemas.agents` import. If `log_service` is not already imported in this module, import it
at module level alongside the other services.

- [ ] **Step 5: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest apps/backend/tests/api/test_agent_enrollment_token_routes.py -q --no-cov`
Expected: PASS.

Then confirm the route ordering did not shadow an agent id:

Run: `.venv/bin/python -m pytest apps/backend/tests/api -q --no-cov -k agents`
Expected: PASS, no new failures.

- [ ] **Step 6: Commit**

```bash
make lint
git add apps/backend/src/app/schemas/agents.py apps/backend/src/app/api/agents.py apps/backend/tests/api/test_agent_enrollment_token_routes.py
git commit -m "feat(agents): mint, list and revoke enrollment tokens over the API"
```

---

### Task 5: Enrolling with a token

**Files:**
- Modify: `apps/backend/src/app/api/ws_agents.py`
- Modify: `apps/backend/src/app/services/agent_registry.py` — see Step 3
- Test: `apps/backend/tests/api/test_ws_agents_unattended_enroll.py` (create)

**Interfaces:**
- Consumes: `agent_enrollment_tokens.consume_token` → `ConsumedToken`.
- Produces: `agent_registry.create_enrolled_agent(db, *, device_pk, fingerprint, token,
  approving_user_id, hello_payload, reported_ip) -> Agent` — creates an `active` agent with grant
  rows, `enrollment_token_id` and `enrolled_via_endpoint` set.

**What the enroll path must do**, inserted after the existing `existing.status` checks and
**before** the concurrent-pending block:

- A hello carrying `enroll_token` takes the token branch. No token → today's path, untouched.
- Consume first. `None` → close `1008` with no encrypted error frame naming the reason. It must
  be indistinguishable from a handshake that simply failed.
- The concurrent-pending cap is **skipped** on this path and must be: a token-enrolled agent is
  never pending, so folding it in would deadlock every unattended boot (design §4). The per-IP
  and global attempt-rate limits at the top of `enroll_stream` still apply and are untouched.
- The ack is `{"agent_id": N, "status": "active"}` — no pairing code, no magic link. The shipped
  agent already handles this.
- `broadcast_presence(agent_id, "enrolled")` still fires so the UI sees the machine appear.

- [ ] **Step 1: Write the failing test**

Create `apps/backend/tests/api/test_ws_agents_unattended_enroll.py`. Copy the Noise-handshake
client helper from the existing enroll tests — find it with
`grep -rln "agents/enroll" apps/backend/tests` and reuse that module's helper verbatim rather
than writing a second one.

```python
"""Slice B: an agent presenting a valid token enrolls with no human present."""

from __future__ import annotations

import pytest

# from <the existing enroll test module> import enroll_handshake  # reuse, do not reimplement


@pytest.mark.asyncio
async def test_a_valid_token_enrolls_the_agent_active_with_its_scope(
    client, db_session, factories, minted_token
):
    """The whole feature: no pairing code, no approval screen, and the grants
    the token named are written at the moment of enrollment."""
    from app.db.models import Agent, AgentCapabilityGrant

    plaintext, token_row = minted_token

    ack = await enroll_handshake(
        client, payload={"hostname": "warehouse-01", "enroll_token": plaintext}
    )

    assert ack["status"] == "active"
    assert "pairing_code" not in ack
    db_session.expire_all()
    agent = db_session.get(Agent, ack["agent_id"])
    assert agent.status == "active"
    assert agent.approved_at is not None
    assert agent.enrollment_token_id == token_row.id
    assert agent.enrolled_via_endpoint == "https://cb.example.com"
    grants = (
        db_session.query(AgentCapabilityGrant)
        .filter(AgentCapabilityGrant.agent_id == agent.id)
        .all()
    )
    assert grants, "auto-approval must write grant rows, exactly as approve_agent does"
    assert {g.capability: g.enabled for g in grants}["host_telemetry"] is True


@pytest.mark.asyncio
async def test_the_approver_recorded_is_the_operator_who_minted_the_token(
    client, db_session, minted_token
):
    """Somebody authorised this. The audit trail must name them."""
    from app.db.models import Agent

    plaintext, token_row = minted_token

    ack = await enroll_handshake(client, payload={"enroll_token": plaintext})

    db_session.expire_all()
    agent = db_session.get(Agent, ack["agent_id"])
    assert agent.approved_by_user_id == token_row.created_by_user_id


@pytest.mark.asyncio
async def test_a_spent_token_is_refused_and_creates_nothing(client, db_session, minted_token):
    """And is refused the same way an unknown one is."""
    from app.db.models import Agent

    plaintext, _ = minted_token
    await enroll_handshake(client, payload={"enroll_token": plaintext})
    before = db_session.query(Agent).count()

    closed = await enroll_handshake_expecting_close(
        client, payload={"enroll_token": plaintext}
    )

    assert closed == 1008
    db_session.expire_all()
    assert db_session.query(Agent).count() == before


@pytest.mark.asyncio
async def test_an_unknown_token_is_refused_identically(client):
    closed = await enroll_handshake_expecting_close(
        client, payload={"enroll_token": "cbe_not-a-real-token"}
    )
    assert closed == 1008


@pytest.mark.asyncio
async def test_a_hello_with_no_token_still_enrolls_pending(client, db_session):
    """The attended flow is unchanged, and an agent predating this slice sends
    no token at all — a half-updated deployment must still work."""
    ack = await enroll_handshake(client, payload={"hostname": "attended-01"})

    assert "pairing_code" in ack
    from app.db.models import Agent

    db_session.expire_all()
    assert db_session.get(Agent, ack["agent_id"]).status == "pending"


@pytest.mark.asyncio
async def test_a_token_enrollment_is_not_subject_to_the_pending_cap(
    client, db_session, factories, minted_token, monkeypatch
):
    """A token-enrolled agent is never pending, so counting it against the cap
    would deadlock every unattended boot."""
    from app.services import agent_registry

    monkeypatch.setattr(agent_registry, "MAX_CONCURRENT_PENDING_AGENTS", 0)
    plaintext, _ = minted_token

    ack = await enroll_handshake(client, payload={"enroll_token": plaintext})

    assert ack["status"] == "active"


@pytest.mark.asyncio
async def test_the_token_never_reaches_the_logs(client, caplog, minted_token):
    """A credential in a log file outlives its TTL in every backup."""
    import logging

    plaintext, _ = minted_token
    with caplog.at_level(logging.DEBUG):
        await enroll_handshake(client, payload={"enroll_token": plaintext})

    assert plaintext not in caplog.text
```

Add a `minted_token` fixture to this module that configures the `pub1` endpoint (as in Task 4)
and calls `agent_enrollment_tokens.mint_token(...)` with
`capabilities={"host_telemetry": True}`, returning `(plaintext, row)`.

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest apps/backend/tests/api/test_ws_agents_unattended_enroll.py -q --no-cov`
Expected: FAIL — the token is ignored, so the agent comes back `pending` with a pairing code.

- [ ] **Step 3: Add `create_enrolled_agent` to `agent_registry`**

Beside `create_pending_agent` and `approve_agent`. It exists as its own function rather than
`create_pending_agent` + `approve_agent` because approval here is not a state transition an
operator performs later — the row is born approved, and two writes would leave a window in which
a token-enrolled agent is momentarily pending and visible as such:

```python
def create_enrolled_agent(
    db: Session,
    *,
    device_pk: str,
    fingerprint: str,
    token: "ConsumedToken",
    hello_payload: dict[str, Any],
    reported_ip: str | None,
) -> Agent:
    """Create an already-approved agent from a consumed enrollment token.

    Approval *is* what is happening here, which is why grant rows are written
    now: the `agent_capabilities` invariant governs never silently enabling a
    capability on an **already-approved** agent, and this agent has no prior
    approval to be surprised by.

    The approver recorded is the operator who minted the token. They authorised
    every agent it enrolls, and recording nobody would make the audit trail say
    an agent approved itself.
    """
    agent = create_pending_agent(
        db,
        device_pk=device_pk,
        fingerprint=fingerprint,
        hostname=hello_payload.get("hostname"),
        machine_id_hash=hello_payload.get("machine_id_hash"),
        os=hello_payload.get("os"),
        os_version=hello_payload.get("os_version"),
        arch=hello_payload.get("arch"),
        agent_version=hello_payload.get("agent_version"),
        primary_macs=hello_payload.get("primary_macs"),
        reported_ip=reported_ip,
        enrolled_via_endpoint=token.endpoint_url,
    )
    agent.enrollment_token_id = token.id
    db.flush()
    approve_agent(
        db,
        agent.id,
        approving_user_id=token.created_by_user_id,
        capability_overrides=token.capabilities or None,
        via="enrollment_token",
    )
    return agent
```

**Check first:** `approve_agent`'s signature is
`approve_agent(db, agent_id, *, approving_user_id: int, ...)`. If `created_by_user_id` can be
`None` (the minting user was deleted), widen `approving_user_id` to `int | None` in
`approve_agent` **and** confirm `Agent.approved_by_user_id` is nullable before doing so. If it is
not nullable, refuse the enrollment instead of inventing an approver — say so in the commit
message.

- [ ] **Step 4: Add the token branch to `enroll_stream`**

In `apps/backend/src/app/api/ws_agents.py`, inside the `with SessionLocal() as db:` block, after
the `existing.status == "active"` early return and **before** `pending_lock_token = None`:

```python
        # Slice B: unattended enrollment. A hello carrying a token takes this
        # branch entirely — no pairing code, no approval screen, no
        # concurrent-pending accounting (a token-enrolled agent is never
        # pending, so folding it into that cap would deadlock every unattended
        # boot). The per-IP and global attempt-rate gates at the top of this
        # handler still apply and are what bound abuse of this path.
        enroll_token = payload.get("enroll_token")
        if enroll_token:
            consumed = agent_enrollment_tokens.consume_token(db, str(enroll_token))
            if consumed is None:
                # Invalid, spent, revoked or expired — one indistinguishable
                # close, so this endpoint is not an oracle for live tokens
                # (design §4). Deliberately not an encrypted error frame: the
                # reason is exactly what must not travel.
                _logger.info("agent enroll: token rejected from %s", client_ip)
                await websocket.close(code=1008)
                return
            agent = agent_registry.create_enrolled_agent(
                db,
                device_pk=device_pk_hex,
                fingerprint=fingerprint,
                token=consumed,
                hello_payload=payload,
                reported_ip=client_ip,
            )
            agent_registry.record_server_key_pin(db, agent, server_key_kind)
            db.commit()
            agent_id = agent.id
            await agent_registry.broadcast_presence(agent_id, "enrolled")
            await websocket.send_bytes(
                _ack_bytes(responder, {"agent_id": agent_id, "status": "active"})
            )
            await websocket.close(code=1000)
            return
```

Import `agent_enrollment_tokens` alongside the module's other service imports. **Never log
`enroll_token`** — the log line above names only the client IP.

- [ ] **Step 5: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest apps/backend/tests/api/test_ws_agents_unattended_enroll.py -q --no-cov`
Expected: PASS.

Then prove the attended path did not regress:

Run: `.venv/bin/python -m pytest apps/backend/tests -q --no-cov -k "enroll or agent_registry"`
Expected: PASS, no new failures.

- [ ] **Step 6: Commit**

```bash
make lint
git add apps/backend/src/app/api/ws_agents.py apps/backend/src/app/services/agent_registry.py apps/backend/tests/api/test_ws_agents_unattended_enroll.py
git commit -m "feat(agents): enroll an agent from a token with no human present"
```

---

### Task 6: The consumption race

**Files:**
- Test: `apps/backend/tests/services/test_agent_enrollment_tokens.py` (append)

The design names this "the one genuine race" and §10 requires a test for it. It gets its own task
because a race test that does not actually race is worse than none — it reports safety it never
demonstrated.

**Interfaces:**
- Consumes: `consume_token` from Task 3.
- Produces: nothing.

- [ ] **Step 1: Write the failing test**

```python
def test_concurrent_boots_cannot_over_consume_a_token(db_session, factories, db_engine):
    """The race the atomic UPDATE exists to close.

    N instances boot from one launch template at once. A read-then-write would
    let several observe `uses < max_uses` before any wrote, and all enroll —
    over-consuming a token whose entire purpose is to bound how many agents it
    can create.

    Real threads on real connections, deliberately: a single-session loop
    re-runs the statement serially and would pass against the very
    check-then-write this test exists to reject.
    """
    import threading

    from sqlalchemy.orm import Session

    from app.services import agent_enrollment_tokens as tokens

    user = factories.user(role="admin")
    db_session.commit()
    plaintext, row = _mint(db_session, user, max_uses=3)

    results: list[bool] = []
    lock = threading.Lock()
    start = threading.Barrier(8)

    def _attempt() -> None:
        start.wait(timeout=10)
        with Session(db_engine) as session:
            got = tokens.consume_token(session, plaintext)
            session.commit()
        with lock:
            results.append(got is not None)

    threads = [threading.Thread(target=_attempt) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert sum(results) == 3, f"expected exactly 3 successes, got {results}"
    db_session.expire_all()
    assert db_session.get(type(row), row.id).uses == 3
```

**If there is no `db_engine` fixture**, add one to the backend `conftest.py` that returns the
engine the test database already uses — `grep -rn "create_engine" apps/backend/tests/conftest.py`
— rather than building a second engine against a different URL.

- [ ] **Step 2: Run the test to verify it passes, and prove it is not vacuous**

Run: `.venv/bin/python -m pytest apps/backend/tests/services/test_agent_enrollment_tokens.py -q --no-cov -k concurrent`
Expected: PASS.

**Then prove it can fail.** Temporarily replace `consume_token`'s body with a check-then-write:

```python
    row = db.execute(
        select(AgentEnrollmentToken).where(AgentEnrollmentToken.token_hash == hash_token(token))
    ).scalar_one_or_none()
    if row is None or row.uses >= row.max_uses or row.revoked_at or row.expires_at <= utcnow():
        return None
    row.uses += 1
    db.flush()
    return ConsumedToken(row.id, row.endpoint_url, dict(row.capabilities or {}), row.created_by_user_id)
```

Re-run. Expected: FAIL with more than 3 successes. **Restore the atomic version** and re-run to
confirm PASS. Record both outcomes in the commit message — a race test whose failure mode was
never observed has not been shown to work.

- [ ] **Step 3: Commit**

```bash
git add apps/backend/tests/services/test_agent_enrollment_tokens.py
git commit -m "test(agents): prove concurrent boots cannot over-consume a token"
```

---

### Task 7: The install script carries the token

**Files:**
- Modify: `apps/backend/src/app/services/agent_install.py`
- Test: `apps/backend/tests/services/test_agent_install.py` (append)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: an install script that writes `/etc/circuit-breaker/enroll-token` when
  `CB_ENROLL_TOKEN` is set in the environment, and does nothing when it is not.

**The rule that decides the shape:** the token is supplied **via the `CB_ENROLL_TOKEN`
environment variable**, never as a script argument and never baked into the rendered script.
`argv` is visible in `ps` and lands in shell history and cloud-init logs; a token compiled into
the script would also be served by an unauthenticated route.

- [ ] **Step 1: Write the failing test**

Append to `apps/backend/tests/services/test_agent_install.py`, using the `_run_preflight` harness
beside it as the model for executing a script fragment:

```python
def _run_token_block(tmp_path, *, env_token: str | None):
    """Execute the installer's enroll-token block against a scratch config dir."""
    import subprocess

    script = agent_install.render_install_script(
        server_url="https://cb.example.com",
        server_static_pk_hex="ab" * 32,
        tls_pin="",
        manifest={"0.1.0": {"linux-amd64": "deadbeef"}},
    )
    start = script.index("# Enrollment token")
    end = script.index("if command -v docker", start)
    snippet = script[start:end]

    conf_dir = tmp_path / "etc"
    conf_dir.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "chown").write_text("#!/bin/sh\nexit 0\n")
    (bin_dir / "chown").chmod(0o755)

    runner = tmp_path / "run.sh"
    runner.write_text(f"#!/bin/sh\nset -eu\nCB_CONF_DIR='{conf_dir}'\n{snippet}\n")
    runner.chmod(0o755)

    env = {"PATH": f"{bin_dir}:/usr/bin:/bin"}
    if env_token is not None:
        env["CB_ENROLL_TOKEN"] = env_token
    result = subprocess.run(
        ["/bin/sh", str(runner)], capture_output=True, text=True, env=env
    )
    assert result.returncode == 0, result.stderr
    written = conf_dir / "enroll-token"
    return written, result


def test_the_token_is_written_only_readable_by_its_owner(tmp_path):
    """It is a bearer credential on a machine other people may use."""
    written, _ = _run_token_block(tmp_path, env_token="cbe_abc123")

    assert written.exists()
    assert written.read_text().strip() == "cbe_abc123"
    assert oct(written.stat().st_mode)[-3:] == "600"


def test_no_token_in_the_environment_writes_no_file(tmp_path):
    """The attended flow is the default and must leave nothing behind."""
    written, _ = _run_token_block(tmp_path, env_token=None)

    assert not written.exists()


def test_the_token_never_appears_in_the_rendered_script(tmp_path):
    """The script is served by an unauthenticated route. A token compiled into
    it would be readable by anyone who can reach the server."""
    script = agent_install.render_install_script(
        server_url="https://cb.example.com",
        server_static_pk_hex="ab" * 32,
        tls_pin="",
        manifest={"0.1.0": {"linux-amd64": "deadbeef"}},
    )

    assert "cbe_" not in script
    assert "CB_ENROLL_TOKEN" in script, "the script reads it from the environment"


def test_the_token_is_not_echoed_to_the_terminal(tmp_path):
    """cloud-init captures stdout verbatim into a log that outlives the TTL."""
    _, result = _run_token_block(tmp_path, env_token="cbe_secret-value")

    assert "cbe_secret-value" not in result.stdout
    assert "cbe_secret-value" not in result.stderr
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest apps/backend/tests/services/test_agent_install.py -q --no-cov -k token`
Expected: FAIL with `ValueError: substring not found` — the block does not exist.

- [ ] **Step 3: Add the block to the script template**

In `_INSTALL_SCRIPT_TEMPLATE`, immediately after the `agent.toml` heredoc and before the
`if command -v docker` line. Note the doubled braces — this is a `str.format` template:

```sh
# Enrollment token (optional). Supplied through the environment, never as a
# script argument: argv is visible in `ps` and lands in shell history and
# cloud-init logs. It is also never rendered into this script, which is served
# by an unauthenticated route. The agent unlinks the file after a successful
# enroll; a spent token left on disk is a stale secret with no purpose.
if [ -n "${{CB_ENROLL_TOKEN:-}}" ]; then
  umask 077
  printf '%s\n' "${{CB_ENROLL_TOKEN}}" > "${{CB_CONF_DIR:-/etc/circuit-breaker}}/enroll-token"
  chmod 600 "${{CB_CONF_DIR:-/etc/circuit-breaker}}/enroll-token"
  chown cb-agent:cb-agent "${{CB_CONF_DIR:-/etc/circuit-breaker}}/enroll-token" 2>/dev/null || true
  echo "enrollment token installed — this agent will enroll unattended"
fi
```

`CB_CONF_DIR` defaults to the real path and exists only so the test above can point the block at
a scratch directory. It is not documented as an operator knob.

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest apps/backend/tests/services/test_agent_install.py -q --no-cov`
Expected: PASS (all of them — the preflight and ICMP tests must still pass, since the block sits
between them).

- [ ] **Step 5: Commit**

```bash
make lint
git add apps/backend/src/app/services/agent_install.py apps/backend/tests/services/test_agent_install.py
git commit -m "feat(agents): let the installer plant an enrollment token from the environment"
```

---

### Task 8: The unattended install command

**Files:**
- Modify: `apps/backend/src/app/services/agent_install.py`
- Modify: `apps/backend/src/app/api/agents.py`
- Test: `apps/backend/tests/services/test_agent_install.py` (append)

**Interfaces:**
- Consumes: `_script_download_arg` from Slice A.
- Produces: `build_install_command(db, server_url, endpoint_id=None, enroll_token=None)` — when
  `enroll_token` is given, the emitted command sets `CB_ENROLL_TOKEN` in the environment of the
  `sh` that runs the script. `GET /api/v1/agents/install-command` gains an
  `enrollment_token: str | None` query parameter.

**The shape:** `CB_ENROLL_TOKEN=... sudo -E sh` — `-E` because `sudo` scrubs the environment by
default and the variable must survive into the script. The assignment is a shell prefix, not an
argument to the script, so it never reaches `argv`.

- [ ] **Step 1: Write the failing test**

```python
def test_an_unattended_command_passes_the_token_through_the_environment(db_session):
    """Never as an argument: argv is visible in `ps`."""
    from app.services import agent_install

    result = agent_install.build_install_command(
        db_session, "https://cb.example.com", endpoint_id="pub1", enroll_token="cbe_abc"
    )

    assert "CB_ENROLL_TOKEN=cbe_abc" in result.command
    assert "sudo -E" in result.command
    # The token must not be an argument to anything.
    assert "install.sh cbe_abc" not in result.command
    assert "sh cbe_abc" not in result.command


def test_an_attended_command_is_unchanged_by_this_feature(db_session):
    """The default path must be byte-identical to what shipped."""
    from app.services import agent_install

    with_none = agent_install.build_install_command(
        db_session, "https://cb.example.com", endpoint_id="pub1"
    )

    assert "CB_ENROLL_TOKEN" not in with_none.command
    assert "sudo -E" not in with_none.command


def test_the_published_digest_is_unaffected_by_the_token(db_session):
    """The token lives in the command, not the script, so the same script — and
    the same digest — serves both flows."""
    from app.services import agent_install

    attended = agent_install.build_install_command(
        db_session, "https://cb.example.com", endpoint_id="pub1"
    )
    unattended = agent_install.build_install_command(
        db_session, "https://cb.example.com", endpoint_id="pub1", enroll_token="cbe_abc"
    )

    assert attended.script_sha256 == unattended.script_sha256
```

These need whatever certificate fixture the existing `build_install_command` tests use —
`grep -n "build_install_command" apps/backend/tests/services/test_agent_install.py` and copy it.

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest apps/backend/tests/services/test_agent_install.py -q --no-cov -k "unattended or attended_command or published_digest"`
Expected: FAIL with `TypeError: build_install_command() got an unexpected keyword argument 'enroll_token'`.

- [ ] **Step 3: Thread the token through**

In `build_install_command`, add `enroll_token: str | None = None` and, after `download` is built:

```python
    # The token rides in the environment of the shell that runs the script,
    # never in argv and never in the script itself. `sudo -E` because sudo
    # scrubs the environment by default, and without it the assignment would
    # be silently dropped and every unattended install would quietly fall back
    # to waiting for a human.
    prefix = f"CB_ENROLL_TOKEN={shlex.quote(enroll_token)} " if enroll_token else ""
    run_sh = "sudo -E sh" if enroll_token else "sudo sh"
```

Use `prefix` and `run_sh` in both TLS branches, replacing the literal `sudo sh` /
`sudo sh /tmp/cb-agent-install.sh`. For the self-signed branch the prefix goes on the final
segment only — the `curl` and `sha256sum -c` steps have no business seeing the token:

```python
        command = (
            f'curl -fsSL --insecure --pinnedpubkey "sha256//{tls_pin}" '
            f"{download} -o /tmp/cb-agent-install.sh && "
            f'echo "{script_sha256}  /tmp/cb-agent-install.sh" | sha256sum -c && '
            f"{prefix}{run_sh} /tmp/cb-agent-install.sh"
        )
```

In `api/agents.py`'s `get_install_command`, add `enrollment_token: str | None = None` and pass it
through as `enroll_token=enrollment_token`.

**Do not** have the route mint a token. The wizard mints via
`POST /agents/enrollment-tokens` and then asks for a command carrying it — two steps, so a
command re-fetch (an endpoint change, a re-render) never silently mints a second credential.

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest apps/backend/tests/services/test_agent_install.py apps/backend/tests/api/test_install_agent_script_endpoint.py -q --no-cov`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
make lint
git add apps/backend/src/app/services/agent_install.py apps/backend/src/app/api/agents.py apps/backend/tests/services/test_agent_install.py
git commit -m "feat(agents): emit an unattended install command carrying the token"
```

---

### Task 9: The agent presents the token

**Files:**
- Modify: `apps/agent/internal/frame/frame.go`
- Modify: `apps/agent/internal/enroll/enroll.go`
- Test: `apps/agent/internal/enroll/enroll_test.go`

**Interfaces:**
- Consumes: nothing from earlier tasks (the wire field name `enroll_token` must match Task 5).
- Produces: `HelloPayload.EnrollToken string \`json:"enroll_token,omitempty"\``.

**Three rules:**
1. The token goes in the **enroll** hello only. `hostinfo.Collect` is shared with
   `internal/link` (two call sites in `link.go`), so setting it there would put a bearer
   credential on every link hello for the life of the agent. Set it in `enroll.go` after
   `Collect` returns.
2. Unlink on success — after `Run` returns nil, not before.
3. A missing file is not an error. It is the attended flow, which is the default.

- [ ] **Step 1: Write the failing test**

In `apps/agent/internal/enroll/enroll_test.go`:

```go
func TestReadEnrollToken_ReturnsEmptyWhenTheFileIsAbsent(t *testing.T) {
	// The attended flow, which is the default and must not error.
	got, err := readEnrollToken(filepath.Join(t.TempDir(), "enroll-token"))
	if err != nil {
		t.Fatalf("absent token file must not be an error: %v", err)
	}
	if got != "" {
		t.Fatalf("want empty, got %q", got)
	}
}

func TestReadEnrollToken_TrimsTheTrailingNewlineTheInstallerWrites(t *testing.T) {
	path := filepath.Join(t.TempDir(), "enroll-token")
	if err := os.WriteFile(path, []byte("cbe_abc123\n"), 0o600); err != nil {
		t.Fatal(err)
	}

	got, err := readEnrollToken(path)
	if err != nil {
		t.Fatal(err)
	}
	if got != "cbe_abc123" {
		t.Fatalf("want %q, got %q", "cbe_abc123", got)
	}
}

func TestClearEnrollToken_RemovesASpentToken(t *testing.T) {
	// A spent token left on disk is a stale secret with no purpose.
	path := filepath.Join(t.TempDir(), "enroll-token")
	if err := os.WriteFile(path, []byte("cbe_abc123\n"), 0o600); err != nil {
		t.Fatal(err)
	}

	clearEnrollToken(path)

	if _, err := os.Stat(path); !os.IsNotExist(err) {
		t.Fatalf("token file survived: %v", err)
	}
}

func TestClearEnrollToken_IsSilentWhenThereIsNothingToRemove(t *testing.T) {
	clearEnrollToken(filepath.Join(t.TempDir(), "absent"))
}

func TestHelloPayload_CarriesTheTokenOnlyWhenThereIsOne(t *testing.T) {
	// omitempty: an attended agent's hello must be byte-identical to today's.
	var p frame.HelloPayload
	b, err := json.Marshal(p)
	if err != nil {
		t.Fatal(err)
	}
	if bytes.Contains(b, []byte("enroll_token")) {
		t.Fatalf("empty token must be omitted, got %s", b)
	}

	p.EnrollToken = "cbe_abc"
	b, err = json.Marshal(p)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Contains(b, []byte(`"enroll_token":"cbe_abc"`)) {
		t.Fatalf("token missing from hello: %s", b)
	}
}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd apps/agent && go test ./internal/enroll/... ./internal/frame/...`
Expected: FAIL — `undefined: readEnrollToken`, and `EnrollToken` is not a field.

- [ ] **Step 3: Add the field and the helpers**

In `apps/agent/internal/frame/frame.go`, at the end of `HelloPayload`:

```go
	// EnrollToken is a short-lived enrollment token that approves this agent
	// without a human at the approval screen. Sent on the ENROLL hello only —
	// internal/link builds its hello from the same struct, and a bearer
	// credential has no business travelling on every heartbeat for the life of
	// the agent. Omitted entirely by the attended flow, which is the default.
	EnrollToken string `json:"enroll_token,omitempty"`
```

In `apps/agent/internal/enroll/enroll.go`:

```go
// enrollTokenPath is where the installer plants a token supplied through
// CB_ENROLL_TOKEN. A var so tests can point it elsewhere.
var enrollTokenPath = "/etc/circuit-breaker/enroll-token"

// readEnrollToken returns the token at path, or "" when there is none.
//
// An absent file is not an error: it is the attended flow, which is the
// default and by far the common case. Only a file that exists and cannot be
// read is worth reporting, since that is a misconfiguration an operator can
// fix.
func readEnrollToken(path string) (string, error) {
	b, err := os.ReadFile(path)
	if errors.Is(err, os.ErrNotExist) {
		return "", nil
	}
	if err != nil {
		return "", fmt.Errorf("enroll: read token: %w", err)
	}
	return strings.TrimSpace(string(b)), nil
}

// clearEnrollToken removes a spent token, best-effort.
//
// It is spent the moment the server accepts it, so keeping it buys nothing and
// leaves a credential on disk for the life of the host. Failure to remove it
// must not fail an enrollment that has already succeeded — the agent is
// enrolled either way, and refusing to start over a leftover file would turn a
// cleanup problem into an outage.
func clearEnrollToken(path string) {
	if err := os.Remove(path); err != nil && !errors.Is(err, os.ErrNotExist) {
		log.Printf("enroll: could not remove spent token at %s: %v", path, err)
	}
}
```

In `Run`, after `helloPayload := hostinfo.Collect(agentVersion, cfg.ServerURL)`:

```go
	token, err := readEnrollToken(enrollTokenPath)
	if err != nil {
		return err
	}
	// Set here rather than inside hostinfo.Collect: internal/link builds its
	// hello from the same helper, and this credential belongs on exactly one
	// frame in the agent's lifetime.
	helloPayload.EnrollToken = token
```

And where `Run` returns nil on `status == "active"`:

```go
		case "active":
			// Unlinked only now, when the server has confirmed it accepted the
			// enrollment. Removing it earlier would strand an agent whose
			// enrollment then failed, with no credential left to retry.
			if token != "" {
				clearEnrollToken(enrollTokenPath)
			}
			fmt.Println("approved — connecting")
			return nil
```

Add `errors`, `os`, `strings` and `log` to the imports if they are not already there.

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd apps/agent && go test ./... -race`
Expected: PASS across the module. The frame corpus tests must still pass — `omitempty` means
existing corpus fixtures are unchanged.

- [ ] **Step 5: Commit**

```bash
cd apps/agent && gofmt -w internal/frame/frame.go internal/enroll/enroll.go internal/enroll/enroll_test.go
git add apps/agent/internal/frame/frame.go apps/agent/internal/enroll/enroll.go apps/agent/internal/enroll/enroll_test.go
git commit -m "feat(agent): present an enrollment token, once, and erase it"
```

---

### Task 10: Attended or unattended in the wizard

**Files:**
- Modify: `apps/frontend/src/api/agents.js`
- Modify: `apps/frontend/src/components/agents/AddAgentPanel.jsx`
- Test: `apps/frontend/src/__tests__/add-agent-panel.test.jsx` (append)

**Interfaces:**
- Consumes: the three routes from Task 4; `getInstallCommand` gains an
  `enrollmentToken` argument.
- Produces: `mintEnrollmentToken({ label, endpoint_id, ttl_seconds, max_uses })`,
  `listEnrollmentTokens()`, `revokeEnrollmentToken(id)` in `api/agents.js`.

**Behaviour:**
- A mode control with two options, **Attended** (default) and **Unattended**.
- Attended is exactly today's panel. Nothing about it changes.
- Choosing Unattended does **not** mint anything. A "Generate token" button does, once, and only
  then is the command re-fetched with it. Minting on selection would burn a credential every
  time an operator clicked around.
- The plaintext is shown once, in a copy field, with the `argv` warning beside it and a plain
  statement that it will not be shown again.
- Changing the endpoint after minting invalidates the shown command — re-mint, because a token
  is scoped to one endpoint.

- [ ] **Step 1: Write the failing test**

```jsx
describe('unattended enrollment', () => {
  it('defaults to attended, and mints nothing until asked', async () => {
    settingsMock.current = { agent_endpoints: ENDPOINTS };
    renderPanel();

    expect(await screen.findByRole('radio', { name: /attended/i })).toBeChecked();
    expect(mintEnrollmentToken).not.toHaveBeenCalled();
  });

  it('mints only when the operator asks, and shows the token once', async () => {
    settingsMock.current = { agent_endpoints: ENDPOINTS };
    mintEnrollmentToken.mockResolvedValue({ data: { id: 7, token: 'cbe_shown-once' } });
    renderPanel();

    await userEvent.click(await screen.findByRole('radio', { name: /unattended/i }));
    expect(mintEnrollmentToken).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole('button', { name: /generate token/i }));

    expect(await screen.findByText(/cbe_shown-once/)).toBeInTheDocument();
    expect(screen.getByText(/will not be shown again/i)).toBeInTheDocument();
  });

  it('warns that the token must not be passed as an argument', async () => {
    settingsMock.current = { agent_endpoints: ENDPOINTS };
    mintEnrollmentToken.mockResolvedValue({ data: { id: 7, token: 'cbe_x' } });
    renderPanel();

    await userEvent.click(await screen.findByRole('radio', { name: /unattended/i }));
    await userEvent.click(screen.getByRole('button', { name: /generate token/i }));

    expect(await screen.findByText(/visible in `?ps`?/i)).toBeInTheDocument();
  });

  it('re-fetches the command with the token so the copied command carries it', async () => {
    settingsMock.current = { agent_endpoints: ENDPOINTS };
    mintEnrollmentToken.mockResolvedValue({ data: { id: 7, token: 'cbe_x' } });
    renderPanel();

    await userEvent.click(await screen.findByRole('radio', { name: /unattended/i }));
    await userEvent.click(screen.getByRole('button', { name: /generate token/i }));

    await waitFor(() =>
      expect(getInstallCommand).toHaveBeenLastCalledWith('pub1', 'cbe_x')
    );
  });

  it('surfaces a mint failure inline rather than silently staying attended', async () => {
    settingsMock.current = { agent_endpoints: ENDPOINTS };
    mintEnrollmentToken.mockRejectedValue({ response: { data: { detail: 'nope' } } });
    renderPanel();

    await userEvent.click(await screen.findByRole('radio', { name: /unattended/i }));
    await userEvent.click(screen.getByRole('button', { name: /generate token/i }));

    expect(await screen.findByText(/nope/)).toBeInTheDocument();
  });
});
```

Adapt the helper names to the file's actual fixtures — it defines its own `renderPanel` and
`ENDPOINTS`; do not invent new ones. Add `mintEnrollmentToken` to the existing `vi.mock` of the
agents API module.

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd apps/frontend && npx vitest run src/__tests__/add-agent-panel.test.jsx`
Expected: FAIL — no radio named "unattended".

- [ ] **Step 3: Add the API functions**

In `apps/frontend/src/api/agents.js`, beside the existing `getInstallCommand`:

```js
/** Mint an enrollment token. The plaintext is in the response and nowhere else. */
export const mintEnrollmentToken = (body) => client.post('/agents/enrollment-tokens', body);

/** Every token, newest first, including revoked and expired ones. */
export const listEnrollmentTokens = () => client.get('/agents/enrollment-tokens');

/** Shut a token. Agents already enrolled through it are unaffected. */
export const revokeEnrollmentToken = (id) =>
  client.post(`/agents/enrollment-tokens/${id}/revoke`);
```

Extend `getInstallCommand` to take a second argument and send it as the `enrollment_token` query
parameter, omitting the parameter entirely when it is absent.

- [ ] **Step 4: Add the mode control**

In `AddAgentPanel.jsx`, inside the first `<li>`, after the endpoint `<select>`. Keep the state
minimal: `mode` (`'attended' | 'unattended'`), `mintedToken`, `mintError`, `isMinting`.

Key points for the implementer:
- `loadInstallCommand` already keys on `selectedEndpoint`; add `mintedToken` to its dependency
  list so the command re-fetches once a token exists.
- Clear `mintedToken` whenever `selectedEndpoint` changes — the token is scoped to one endpoint,
  and leaving a stale one would emit a command whose token the server will refuse.
- Switching back to attended clears `mintedToken` too, so the copied command stops carrying a
  credential the operator thinks they abandoned.
- Render the token in a copy field with two lines of prose: that it will not be shown again, and
  that it must reach the machine through the environment because `argv` is visible in `ps`.
- Render `mintError` inline **and** as a toast, matching how `installError` is already handled
  in this component (design §4 of the endpoints work: inline where they are looking, toast if
  they have scrolled past).
- The panel's second step ("Waiting for approval") should read differently when unattended: the
  machine will not appear as pending, it will appear active. Guard the existing copy on `mode`.

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd apps/frontend && npx vitest run src/__tests__/add-agent-panel.test.jsx`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd apps/frontend && npm run lint
git add apps/frontend/src/api/agents.js apps/frontend/src/components/agents/AddAgentPanel.jsx apps/frontend/src/__tests__/add-agent-panel.test.jsx
git commit -m "feat(agents): offer unattended enrollment in the add-agent panel"
```

---

### Task 11: Tokens in settings

**Files:**
- Create: `apps/frontend/src/components/settings/EnrollmentTokensSection.jsx`
- Create: `apps/frontend/src/__tests__/enrollment-tokens-section.test.jsx`
- Modify: `apps/frontend/src/pages/SettingsPage.jsx`

**Why this task exists, given §7 does not name it:** the design gives tokens a `revoke` endpoint.
Without a surface, revocation is a backend capability with no way to use it — the exact shape the
1.0.0 incomplete-feature register was opened to catch. This is the minimum surface that makes
`revoke` real: a list and a button. It is not a management console.

**Interfaces:**
- Consumes: `listEnrollmentTokens`, `revokeEnrollmentToken` from Task 10.
- Produces: nothing.

- [ ] **Step 1: Write the failing test**

```jsx
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import EnrollmentTokensSection from '../components/settings/EnrollmentTokensSection';
import { listEnrollmentTokens, revokeEnrollmentToken } from '../api/agents';

vi.mock('../api/agents', () => ({
  listEnrollmentTokens: vi.fn(),
  revokeEnrollmentToken: vi.fn(),
}));

const LIVE = {
  id: 1,
  label: 'warehouse',
  endpoint_url: 'https://cb.example.com',
  max_uses: 5,
  uses: 2,
  expires_at: '2099-01-01T00:00:00Z',
  revoked_at: null,
  created_at: '2026-09-06T00:00:00Z',
  agent_count: 2,
};

describe('EnrollmentTokensSection', () => {
  beforeEach(() => vi.clearAllMocks());

  it('renders a loading state before the list arrives', () => {
    listEnrollmentTokens.mockReturnValue(new Promise(() => {}));
    render(<EnrollmentTokensSection />);
    expect(screen.getByText(/loading/i)).toBeInTheDocument();
  });

  it('renders an error state when the list cannot be read', async () => {
    listEnrollmentTokens.mockRejectedValue({ response: { data: { detail: 'boom' } } });
    render(<EnrollmentTokensSection />);
    expect(await screen.findByText(/boom/)).toBeInTheDocument();
  });

  it('says plainly when there are no tokens', async () => {
    listEnrollmentTokens.mockResolvedValue({ data: [] });
    render(<EnrollmentTokensSection />);
    expect(await screen.findByText(/no enrollment tokens/i)).toBeInTheDocument();
  });

  it('shows a live token with its remaining uses and never its value', async () => {
    listEnrollmentTokens.mockResolvedValue({ data: [LIVE] });
    render(<EnrollmentTokensSection />);

    expect(await screen.findByText('warehouse')).toBeInTheDocument();
    expect(screen.getByText('2 / 5')).toBeInTheDocument();
    expect(screen.queryByText(/cbe_/)).not.toBeInTheDocument();
  });

  it('revokes a token and reflects it without a reload', async () => {
    listEnrollmentTokens.mockResolvedValue({ data: [LIVE] });
    revokeEnrollmentToken.mockResolvedValue({
      data: { ...LIVE, revoked_at: '2026-09-06T01:00:00Z' },
    });
    render(<EnrollmentTokensSection />);

    await userEvent.click(await screen.findByRole('button', { name: /revoke/i }));

    await waitFor(() => expect(revokeEnrollmentToken).toHaveBeenCalledWith(1));
    expect(await screen.findByText(/revoked/i)).toBeInTheDocument();
  });

  it('offers no revoke button on an already-revoked token', async () => {
    listEnrollmentTokens.mockResolvedValue({
      data: [{ ...LIVE, revoked_at: '2026-09-06T01:00:00Z' }],
    });
    render(<EnrollmentTokensSection />);

    await screen.findByText('warehouse');
    expect(screen.queryByRole('button', { name: /revoke/i })).not.toBeInTheDocument();
  });

  it('says how many agents came through a token, since that is why it is kept', async () => {
    listEnrollmentTokens.mockResolvedValue({ data: [LIVE] });
    render(<EnrollmentTokensSection />);
    expect(await screen.findByText(/2 agents/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd apps/frontend && npx vitest run src/__tests__/enrollment-tokens-section.test.jsx`
Expected: FAIL — the module does not exist.

- [ ] **Step 3: Write the component**

A table with columns: Label, Endpoint, Uses (`uses / max_uses`), Expires, Agents, State, and a
Revoke button on live rows only. State is derived: `revoked_at` → "Revoked"; `expires_at` in the
past → "Expired"; `uses >= max_uses` → "Spent"; else "Live". Loading and error states are
required (CLAUDE.md). Follow `AgentEndpointsSection.jsx` for markup and class conventions.

- [ ] **Step 4: Mount it**

In `SettingsPage.jsx`, directly after the existing `<SettingSection title="Agent Endpoints">`:

```jsx
                <SettingSection title="Enrollment Tokens" className="settings-section--full">
                  <EnrollmentTokensSection />
                </SettingSection>
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd apps/frontend && npx vitest run src/__tests__/enrollment-tokens-section.test.jsx && npx vitest run src/__tests__`
Expected: PASS, with no regressions elsewhere.

- [ ] **Step 6: Commit**

```bash
cd apps/frontend && npm run lint
git add apps/frontend/src/components/settings/EnrollmentTokensSection.jsx apps/frontend/src/__tests__/enrollment-tokens-section.test.jsx apps/frontend/src/pages/SettingsPage.jsx
git commit -m "feat(agents): list and revoke enrollment tokens in settings"
```

---

### Task 12: End to end, the scanner rule, and the docs

**Files:**
- Modify: `apps/agent/e2e/test_agent_e2e.py`
- Modify: `.gitleaks.toml`
- Modify: `docs/agent.md`, `docs/settings.md`
- Test: `tests/build/test_enrollment_token_never_shipped.py` (create)

**Interfaces:**
- Consumes: everything above.
- Produces: nothing.

- [ ] **Step 1: Write the failing tests**

`tests/build/test_enrollment_token_never_shipped.py` — a repo-policy gate:

```python
"""No enrollment token may be committed, and the scanner must be able to find one.

The `cbe_` prefix exists precisely so this is checkable. A rule that does not
match the format the code mints is a rule that will never fire.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_no_minted_token_is_committed():
    """A real token is `cbe_` plus 43 base64url characters."""
    tracked = subprocess.run(
        ["git", "ls-files", "-z"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout.split("\0")
    pattern = re.compile(r"cbe_[A-Za-z0-9_-]{43}")
    offenders = []
    for name in filter(None, tracked):
        path = REPO / name
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if pattern.search(text):
            offenders.append(name)
    assert not offenders, f"an enrollment token is committed in: {offenders}"


def test_gitleaks_carries_a_rule_for_the_prefix_the_code_mints():
    """Pins the scanner's regex against the minting code, so the two cannot
    drift apart in silence."""
    from app.services.agent_enrollment_tokens import TOKEN_PREFIX

    config = (REPO / ".gitleaks.toml").read_text()
    assert TOKEN_PREFIX in config, (
        f"gitleaks has no rule matching {TOKEN_PREFIX!r}; a minted token would "
        "not be caught on its way into a commit"
    )
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/build/test_enrollment_token_never_shipped.py -q --no-cov`
Expected: the second test FAILS — `.gitleaks.toml` has no `cbe_` rule.

- [ ] **Step 3: Add the gitleaks rule**

```toml
[[rules]]
id = "circuitbreaker-agent-enrollment-token"
description = "Circuit Breaker agent enrollment token (cbe_)"
regex = '''cbe_[A-Za-z0-9_-]{43}'''
keywords = ["cbe_"]
```

Match the file's existing rule style — read a neighbouring `[[rules]]` block first.

- [ ] **Step 4: Add the E2E scenario**

In `apps/agent/e2e/test_agent_e2e.py`, beside the attended scenario the harness already runs. It
must mint a token through the API, run the installer with `CB_ENROLL_TOKEN` in the container's
environment, and assert three things:

1. The agent reaches `active` with **no approval call made** — that is the feature.
2. `/etc/circuit-breaker/enroll-token` does **not** exist afterwards.
3. Re-running the same install with the same token fails, and the fleet gains no second agent.

- [ ] **Step 5: Document it**

In `docs/agent.md`, under `## Install`, after "Choose the address the agent will dial":

- A subsection **"Unattended enrollment"** covering: what a token is; that it is a bearer
  credential and §5's trade stated plainly, not buried; the `cbe_` format; TTL and `max_uses`
  bounds; that it is delivered through `CB_ENROLL_TOKEN` and never as an argument, with the `ps`
  reason; that the agent erases it after use; that revoking does not disturb agents already
  enrolled; and where to revoke (**Settings → Connectivity → Enrollment Tokens**).
- A line in the installer's numbered steps: the token file is written between `agent.toml` and
  the docker-group step, `0600`, owned by `cb-agent`.
- A troubleshooting entry: an agent that stays absent after an unattended install, with the
  ordered checks — token expired, `max_uses` spent, token revoked, `CB_ENROLL_TOKEN` scrubbed by
  a `sudo` without `-E`.

In `docs/settings.md`, one line under Connectivity for Enrollment Tokens, pointing at the above.

- [ ] **Step 6: Run everything**

```bash
.venv/bin/python -m pytest tests/build -q --no-cov
.venv/bin/python -m pytest apps/backend/tests -q --no-cov
cd apps/agent && go test ./... -race
cd apps/frontend && npx vitest run src/__tests__
make lint
make verify
```

Expected: all green. `make verify`'s default tier skips the backend suite
(`CB_VERIFY_BACKEND=off`), which is why the backend run above is listed separately and is not
optional.

- [ ] **Step 7: Commit**

```bash
git add tests/build/test_enrollment_token_never_shipped.py .gitleaks.toml apps/agent/e2e/test_agent_e2e.py docs/agent.md docs/settings.md
git commit -m "feat(agents): prove unattended enrollment end to end, and document it"
```

---

## Self-Review

**Spec coverage.** Every Slice B section maps to a task:

| Spec | Task |
|---|---|
| §2.4 tokens included, with eyes open | 2 (module docstring), 12 (docs state the trade) |
| §3.2 `agent_enrollment_tokens` table | 1 |
| §3.3 `agents.enrollment_token_id` | 1 |
| §3.3 `enrolled_via_endpoint` | shipped in Slice A; set from the token in 5 |
| §4 Mint | 2, 4 |
| §4 Carry (env/stdin, `0600`, `cb-agent`) | 7 |
| §4 Present (inside the Noise channel) | 9 |
| §4 Consume (atomic, not an oracle) | 3, 5, 6 |
| §4 Revoke | 3, 4, 11 |
| §4 Erase | 9 |
| §4 Audit (chained mint/revoke) | 4 |
| §4 Abuse (existing rate limits, no pending cap) | 5 |
| §5 the trade is stated, not discovered | 2, 12 |
| §6 no "verified" badge anywhere | nothing claims one; preflight shipped in Slice A |
| §7 wizard attended/unattended | 10 |
| §7 `/install-agent.sh?endpoint=` | shipped in Slice A |
| §8 agent-side changes | 9 |
| §9 additive migrations, unchanged attended flow | 1, 5 |
| §10 every listed test | 3, 5, 6, 7, 9, 10, 12 |
| §11 Slice B boundary | this plan; nothing here touches Slice A |

**Deviation from the spec, recorded.** §7 names only the wizard. Task 11 adds a tokens list with
a revoke button, because §4's revoke endpoint is otherwise unreachable from the product. Cost if
wrong: one settings section to delete.

**Deferred, and why.** §4 says the token may be supplied "via the `CB_ENROLL_TOKEN` environment
variable **or on stdin**". Only the environment variable is built. Stdin conflicts with the
shipped command form, which already pipes the *script* into `sh` — `curl … | sudo sh` leaves no
stdin for a token, and reworking that pipeline is a larger change than this slice needs. The
environment variable satisfies the requirement that matters (never in `argv`). If stdin is later
wanted, it is additive.

**Type consistency.** `ConsumedToken` is produced by Task 3 and consumed with the same field
names in Tasks 4 and 5. The wire field is `enroll_token` in Task 5 (Python, read from the raw
hello dict) and `enroll_token` in Task 9 (Go, `json:"enroll_token,omitempty"`) — these must
match and do. `build_install_command`'s new parameter is `enroll_token` in Task 8 and is fed by
the route's `enrollment_token` query parameter; the API body field is `endpoint_id` in Task 4's
schema and Task 10's client. `EnrollmentTokenRead.agent_count` is produced in Task 4 and read in
Task 11.

**One ordering constraint.** Task 9 (the agent sends the token) is useless before Task 5 (the
server reads it) and harmless after. Task 7 (the installer plants the file) is useless before
Task 9. Run 5 → 7 → 9 in that order or the E2E in Task 12 cannot pass.

---

## Execution Handoff

Two ways to run this:

**1. Subagent-driven (recommended)** — a fresh subagent per task with review between tasks. Each
task here is sized for that: one deliverable, its own test cycle, its own commit. Tasks 1–5 are
strictly ordered; 10 and 11 can run in parallel with 7–9 once 4 has landed.

**2. Inline execution** — work through the tasks in one session with checkpoints for review.

**Where this file lives.** Beside Slice A's plan in `plans/`, which is tracked. The
writing-plans skill defaults to `docs/superpowers/plans/`, which is gitignored here
(`.gitignore:142`).
