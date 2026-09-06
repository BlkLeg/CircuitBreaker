# Agent Endpoints (Slice A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an operator declare the address agents should dial, choose one per install, and see which address each agent actually used — so an agent can be deployed outside the LAN.

**Architecture:** A JSON list of `{id, label, url}` endpoints on `AppSettings`. The install-command API and `/install-agent.sh` accept `?endpoint=<id>` and render that URL as `server_url` instead of deriving it from the browsed `Host`. The agent reports the URL it dialed in its enroll hello, and the server stores it on the agent row. No protocol change, no new secret, no listener.

**Tech Stack:** FastAPI + SQLAlchemy + Alembic (Python 3.12), React + Vite (JSX), Go agent, pytest + vitest.

**Spec:** `docs/design/2026-09-05-agent-reachability-design.md` — read §1, §2.2, §2.3, §3.1, §3.3, §6, §7, §11 (slice A) before starting.

## Global Constraints

- Migrations are additive and existence-guarded: `ADD COLUMN IF NOT EXISTS`. Never rename or drop.
- Python: snake_case, full type annotations (`mypy --disallow-untyped-defs`), docstrings on classes and public functions. Services hold logic; routes stay thin. Sessions via `Depends(get_db)`.
- Frontend: `.jsx` components (PascalCase), `.js` for API modules. All HTTP through the axios client in `src/api/client.jsx` — no inline `fetch`. Always render loading and error states.
- API: snake_case JSON, errors as `{"detail": "..."}`, correct HTTP codes.
- Empty `agent_endpoints` must reproduce today's behaviour exactly. No upgrade may break on an unset field.
- Never lower the coverage gate in `apps/backend/pyproject.toml`.
- `make lint` and `make verify` before pushing.
- Backend tests run from `apps/backend`; add `--no-cov` when running a single file, never when running the suite.

---

### Task 1: `agent_endpoints` column

**Files:**
- Modify: `apps/backend/src/app/db/models.py` (class `AppSettings`, near `map_default_filters` at :1428)
- Create: `apps/backend/migrations/versions/<generated>_agent_endpoints.py`
- Test: `apps/backend/tests/unit/test_agent_endpoints_model.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `AppSettings.agent_endpoints: Mapped[list | None]` — a JSONB list of `{"id": str, "label": str, "url": str}`.

- [ ] **Step 1: Write the failing test**

```python
"""agent_endpoints stores the operator's declared agent-facing addresses."""

from __future__ import annotations

from app.db.models import AppSettings


def test_agent_endpoints_defaults_to_empty_list(db_session):
    row = AppSettings(id=1)
    db_session.add(row)
    db_session.flush()
    assert row.agent_endpoints == []


def test_agent_endpoints_round_trips_a_list_of_objects(db_session):
    row = AppSettings(id=1, agent_endpoints=[{"id": "a1b2c3", "label": "LAN", "url": "https://10.0.0.5"}])
    db_session.add(row)
    db_session.flush()
    db_session.expire(row)
    assert row.agent_endpoints[0]["label"] == "LAN"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && ../../.venv/bin/python -m pytest tests/unit/test_agent_endpoints_model.py -v --no-cov`
Expected: FAIL with `TypeError: 'agent_endpoints' is an invalid keyword argument for AppSettings`

- [ ] **Step 3: Add the column**

In `models.py`, inside `class AppSettings`, beside the other JSONB column:

```python
    # The addresses agents are told to dial, declared by the operator. Distinct
    # from `api_base_url` above, which is the browser-facing URL: the address a
    # browser uses and the address an agent uses can legitimately differ, and
    # that difference is the whole LAN-versus-FQDN case this exists for.
    # Entries are {"id": str, "label": str, "url": str}. `id` is minted once and
    # never reused, because a label is mutable and cannot identify an endpoint
    # in an install command generated days earlier.
    # Empty means "not configured" — the install flow then falls back to
    # forwarded_base_url exactly as it does today.
    agent_endpoints: Mapped[list | None] = mapped_column(JSONB, nullable=False, default=list)
```

- [ ] **Step 4: Generate and edit the migration**

```bash
cd apps/backend && PYTHONPATH=src ../../.venv/bin/alembic heads   # note the current head
cd apps/backend && PYTHONPATH=src ../../.venv/bin/alembic revision -m "agent endpoints"
```

Set `down_revision` to the head you just noted, then write:

```python
def upgrade() -> None:
    conn = op.get_bind()
    # Existence-guarded like every other migration here: 0001_init bootstraps
    # fresh databases from Base.metadata, which already carries this column.
    conn.execute(
        sa.text(
            "ALTER TABLE app_settings "
            "ADD COLUMN IF NOT EXISTS agent_endpoints JSONB NOT NULL DEFAULT '[]'::jsonb"
        )
    )


def downgrade() -> None:
    op.get_bind().execute(sa.text("ALTER TABLE app_settings DROP COLUMN IF EXISTS agent_endpoints"))
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd apps/backend && ../../.venv/bin/python -m pytest tests/unit/test_agent_endpoints_model.py -v --no-cov`
Expected: PASS (2 tests)

- [ ] **Step 6: Commit**

```bash
git add apps/backend/src/app/db/models.py apps/backend/migrations/versions/ apps/backend/tests/unit/test_agent_endpoints_model.py
git commit -m "feat(agents): store operator-declared agent endpoints"
```

---

### Task 2: Endpoint service — validate, mint, look up

**Files:**
- Create: `apps/backend/src/app/services/agent_endpoints.py`
- Test: `apps/backend/tests/services/test_agent_endpoints.py`

**Interfaces:**
- Consumes: `AppSettings.agent_endpoints` (Task 1).
- Produces:
  - `normalize_endpoints(raw: list[dict]) -> list[dict]` — validates and mints missing ids; raises `ValueError`.
  - `find_endpoint(db: Session, endpoint_id: str) -> dict | None`
  - `list_endpoints(db: Session) -> list[dict]`

- [ ] **Step 1: Write the failing test**

```python
"""Endpoints are operator-authored, so every field is validated and ids are ours."""

from __future__ import annotations

import pytest

from app.services import agent_endpoints


def test_mints_an_id_when_absent():
    result = agent_endpoints.normalize_endpoints([{"label": "LAN", "url": "https://10.0.0.5"}])
    assert result[0]["id"]
    assert result[0]["label"] == "LAN"


def test_keeps_an_existing_id_so_install_commands_keep_resolving():
    result = agent_endpoints.normalize_endpoints(
        [{"id": "keepme", "label": "LAN", "url": "https://10.0.0.5"}]
    )
    assert result[0]["id"] == "keepme"


def test_rejects_a_non_http_scheme():
    with pytest.raises(ValueError, match="scheme"):
        agent_endpoints.normalize_endpoints([{"label": "bad", "url": "file:///etc/passwd"}])


def test_rejects_a_blank_label():
    with pytest.raises(ValueError, match="label"):
        agent_endpoints.normalize_endpoints([{"label": "  ", "url": "https://10.0.0.5"}])


def test_rejects_duplicate_ids():
    with pytest.raises(ValueError, match="duplicate"):
        agent_endpoints.normalize_endpoints(
            [
                {"id": "same", "label": "a", "url": "https://a.example.com"},
                {"id": "same", "label": "b", "url": "https://b.example.com"},
            ]
        )


def test_strips_a_trailing_slash_so_urls_concatenate_predictably():
    result = agent_endpoints.normalize_endpoints([{"label": "LAN", "url": "https://10.0.0.5/"}])
    assert result[0]["url"] == "https://10.0.0.5"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && ../../.venv/bin/python -m pytest tests/services/test_agent_endpoints.py -v --no-cov`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.agent_endpoints'`

- [ ] **Step 3: Write the service**

```python
"""The addresses an operator declares for agents to dial.

Deliberately not `api_base_url`: that is the browser-facing URL, and the
address a browser uses can legitimately differ from the one an agent uses.
See docs/design/2026-09-05-agent-reachability-design.md §3.1.
"""

from __future__ import annotations

import secrets
from typing import Any
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.db.models import AppSettings

# A scheme-and-host check, deliberately NOT core.url_validation: its
# `_is_forbidden_address` rejects private addresses unless `allow_private` is
# set, so it would refuse https://192.168.0.51 — the LAN endpoint an operator
# most needs to declare. It also resolves DNS, which answers the wrong question:
# what matters is whether the address resolves from the *agent*.
_ALLOWED_SCHEMES = frozenset({"http", "https"})
_ID_BYTES = 6
_MAX_LABEL = 60


def _mint_id() -> str:
    """A short, opaque, never-reused endpoint id."""
    return secrets.token_hex(_ID_BYTES)


def normalize_endpoints(raw: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Validate operator-supplied endpoints, minting ids for new ones.

    Raises ValueError with an operator-readable message on any bad entry.
    """
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for entry in raw:
        label = str(entry.get("label") or "").strip()
        if not label:
            raise ValueError("each endpoint needs a label")
        if len(label) > _MAX_LABEL:
            raise ValueError(f"label is longer than {_MAX_LABEL} characters: {label[:20]}...")

        url = str(entry.get("url") or "").strip().rstrip("/")
        parsed = urlparse(url)
        if parsed.scheme not in _ALLOWED_SCHEMES:
            raise ValueError(f"endpoint '{label}' has an unsupported URL scheme: {parsed.scheme!r}")
        if not parsed.netloc:
            raise ValueError(f"endpoint '{label}' has no host")

        endpoint_id = str(entry.get("id") or "").strip() or _mint_id()
        if endpoint_id in seen:
            raise ValueError(f"duplicate endpoint id: {endpoint_id}")
        seen.add(endpoint_id)

        result.append({"id": endpoint_id, "label": label, "url": url})
    return result


def list_endpoints(db: Session) -> list[dict[str, str]]:
    """Every configured endpoint, or [] when none are."""
    row = db.get(AppSettings, 1)
    return list(row.agent_endpoints or []) if row is not None else []


def find_endpoint(db: Session, endpoint_id: str) -> dict[str, str] | None:
    """The endpoint with this id, or None when it does not exist.

    None is what makes the caller 404 rather than silently substituting a
    different address — see the design's §7 note on why falling back here would
    reintroduce the defect this work exists to fix.
    """
    for endpoint in list_endpoints(db):
        if endpoint.get("id") == endpoint_id:
            return endpoint
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/backend && ../../.venv/bin/python -m pytest tests/services/test_agent_endpoints.py -v --no-cov`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add apps/backend/src/app/services/agent_endpoints.py apps/backend/tests/services/test_agent_endpoints.py
git commit -m "feat(agents): validate and identify operator-declared endpoints"
```

---

### Task 3: Settings API round-trip

**Files:**
- Modify: `apps/backend/src/app/schemas/settings.py:452` (`AppSettingsUpdate`) and the read schema in the same file
- Modify: `apps/backend/src/app/services/settings_service.py:98` (`update_settings`)
- Test: `apps/backend/tests/api/test_settings_agent_endpoints.py`

**Interfaces:**
- Consumes: `agent_endpoints.normalize_endpoints` (Task 2).
- Produces: `PUT /api/v1/settings` accepts and returns `agent_endpoints`.

- [ ] **Step 1: Write the failing test**

```python
"""Endpoints are configured through the normal settings route."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_endpoints_round_trip_through_settings(client, auth_headers):
    resp = await client.put(
        "/api/v1/settings",
        json={"agent_endpoints": [{"label": "Public", "url": "https://cb.example.com"}]},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    stored = resp.json()["agent_endpoints"]
    assert stored[0]["label"] == "Public"
    assert stored[0]["id"], "the server mints the id"


@pytest.mark.asyncio
async def test_a_bad_url_is_rejected_with_a_readable_message(client, auth_headers):
    resp = await client.put(
        "/api/v1/settings",
        json={"agent_endpoints": [{"label": "bad", "url": "file:///etc/passwd"}]},
        headers=auth_headers,
    )
    assert resp.status_code == 422
    assert "scheme" in resp.json()["detail"].lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && ../../.venv/bin/python -m pytest tests/api/test_settings_agent_endpoints.py -v --no-cov`
Expected: FAIL — `agent_endpoints` is not returned (KeyError) because the schema does not carry it.

- [ ] **Step 3: Add the field to both schemas**

In `schemas/settings.py`, add to `AppSettingsUpdate`:

```python
    agent_endpoints: list[dict[str, str]] | None = None
```

and to the settings **read** model in the same file (the one the route returns), add:

```python
    agent_endpoints: list[dict[str, str]] = []
```

- [ ] **Step 4: Normalize on write**

In `settings_service.update_settings`, inside the `for field, value in data.items():` loop, before the generic `setattr`, add a branch beside the existing `branding` one:

```python
        if field == "agent_endpoints":
            # Validated here rather than in the schema so the error message names
            # the offending endpoint by label, which a pydantic type error cannot.
            from app.services.agent_endpoints import normalize_endpoints

            row.agent_endpoints = normalize_endpoints(value or [])
            continue
```

Then in `apps/backend/src/app/api/settings.py`, in the `PUT /settings` handler,
translate `ValueError` into a 422 (the service raises it with an
operator-readable message naming the offending endpoint):

```python
    try:
        row = settings_service.update_settings(db, payload, user_id=user.id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd apps/backend && ../../.venv/bin/python -m pytest tests/api/test_settings_agent_endpoints.py -v --no-cov`
Expected: PASS (2 tests)

- [ ] **Step 6: Commit**

```bash
git add apps/backend/src/app/schemas/settings.py apps/backend/src/app/services/settings_service.py apps/backend/src/app/api/settings.py apps/backend/tests/api/test_settings_agent_endpoints.py
git commit -m "feat(agents): configure agent endpoints through settings"
```

---

### Task 4: `agents.enrolled_via_endpoint` column

**Files:**
- Modify: `apps/backend/src/app/db/models.py` (class `Agent`, near `agent_version` at :409)
- Create: `apps/backend/migrations/versions/<generated>_agent_enrolled_via_endpoint.py`
- Test: `apps/backend/tests/unit/test_agent_endpoints_model.py` (append)

**Interfaces:**
- Produces: `Agent.enrolled_via_endpoint: Mapped[str | None]`.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_agent_endpoints_model.py`:

```python
def test_agent_records_the_endpoint_it_dialed(db_session, factories):
    agent = factories.agent(enrolled_via_endpoint="https://cb.example.com")
    db_session.flush()
    assert agent.enrolled_via_endpoint == "https://cb.example.com"


def test_enrolled_via_endpoint_is_optional_for_agents_from_before_this_feature(db_session, factories):
    agent = factories.agent()
    db_session.flush()
    assert agent.enrolled_via_endpoint is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && ../../.venv/bin/python -m pytest tests/unit/test_agent_endpoints_model.py -v --no-cov`
Expected: FAIL with `TypeError: 'enrolled_via_endpoint' is an invalid keyword argument for Agent`

- [ ] **Step 3: Add the column**

```python
    # The server_url this agent reported dialing at enrollment. The server has
    # no other way to know: it never connects to the agent, so an endpoint that
    # nothing can reach is otherwise invisible — the agent that would report the
    # failure is the one that cannot connect to report it.
    enrolled_via_endpoint: Mapped[str | None] = mapped_column(String, nullable=True)
```

- [ ] **Step 4: Write the migration**

Generate as in Task 1, then:

```python
def upgrade() -> None:
    op.get_bind().execute(
        sa.text("ALTER TABLE agents ADD COLUMN IF NOT EXISTS enrolled_via_endpoint VARCHAR")
    )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text("ALTER TABLE agents DROP COLUMN IF EXISTS enrolled_via_endpoint")
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd apps/backend && ../../.venv/bin/python -m pytest tests/unit/test_agent_endpoints_model.py -v --no-cov`
Expected: PASS (4 tests)

- [ ] **Step 6: Commit**

```bash
git add apps/backend/src/app/db/models.py apps/backend/migrations/versions/ apps/backend/tests/unit/test_agent_endpoints_model.py
git commit -m "feat(agents): record which endpoint an agent enrolled through"
```

---

### Task 5: Thread the endpoint through the install command

**Files:**
- Modify: `apps/backend/src/app/services/agent_install.py:341` (`build_install_command`)
- Modify: `apps/backend/src/app/api/agents.py:219` (`get_install_command`)
- Test: `apps/backend/tests/services/test_agent_install.py` (append)

**Interfaces:**
- Consumes: `agent_endpoints.find_endpoint` (Task 2).
- Produces: `build_install_command(db, server_url)` unchanged in signature; the **route** resolves the endpoint and passes its URL as `server_url`.

Keeping the resolution in the route, not the service, is deliberate: `build_install_command` already takes the URL it should render, and giving it a second way to decide would create two sources of truth for the same field.

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_install_command_uses_the_selected_endpoint_not_the_browsed_host(
    client, auth_headers, db_session
):
    """The whole point: the address an agent dials is not the address you browsed."""
    from app.services import settings_service
    from app.schemas.settings import AppSettingsUpdate

    settings_service.update_settings(
        db_session,
        AppSettingsUpdate(agent_endpoints=[{"id": "pub1", "label": "Public", "url": "https://cb.example.com"}]),
    )
    db_session.commit()

    resp = await client.get("/api/v1/agents/install-command?endpoint=pub1", headers=auth_headers)

    assert resp.status_code == 200, resp.text
    assert "https://cb.example.com" in resp.json()["command"]


@pytest.mark.asyncio
async def test_unknown_endpoint_id_is_refused_rather_than_silently_substituted(
    client, auth_headers
):
    """Falling back here would re-create the defect this feature exists to fix."""
    resp = await client.get("/api/v1/agents/install-command?endpoint=nope", headers=auth_headers)
    assert resp.status_code == 404
    assert "nope" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_absent_endpoint_falls_back_to_the_browsed_host(client, auth_headers):
    """Existing installs and existing commands keep working untouched."""
    resp = await client.get("/api/v1/agents/install-command", headers=auth_headers)
    assert resp.status_code in (200, 503)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && ../../.venv/bin/python -m pytest tests/services/test_agent_install.py -k endpoint -v --no-cov`
Expected: FAIL — the selected endpoint is ignored, so `https://cb.example.com` is not in the command.

- [ ] **Step 3: Resolve the endpoint in the route**

Replace the body of `get_install_command` in `api/agents.py`:

```python
@router.get("/install-command", response_model=InstallCommandResponse)
def get_install_command(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    _user: Annotated[User, require_role("admin")],
    endpoint: str | None = None,
) -> Any:
    from app.core.forwarded import forwarded_base_url
    from app.services import agent_endpoints, agent_install

    # An absent `endpoint` keeps today's behaviour, so existing commands and
    # unconfigured installs are untouched. A *named* endpoint that does not
    # exist is refused rather than falling back: silently substituting a
    # different address is exactly the defect this parameter exists to fix, and
    # it would return the moment an operator deleted an endpoint whose install
    # command was still open in someone's terminal.
    if endpoint is None:
        server_url = forwarded_base_url(request)
    else:
        selected = agent_endpoints.find_endpoint(db, endpoint)
        if selected is None:
            raise HTTPException(status_code=404, detail=f"No agent endpoint with id {endpoint!r}")
        server_url = selected["url"]

    try:
        return agent_install.build_install_command(db, server_url)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/backend && ../../.venv/bin/python -m pytest tests/services/test_agent_install.py -k endpoint -v --no-cov`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add apps/backend/src/app/api/agents.py apps/backend/tests/services/test_agent_install.py
git commit -m "feat(agents): build the install command for a chosen endpoint"
```

---

### Task 6: `/install-agent.sh?endpoint=`

**Files:**
- Modify: `apps/backend/src/app/main.py:2400` (`get_install_agent_script`)
- Test: `apps/backend/tests/api/test_install_agent_script_endpoint.py`

**Interfaces:**
- Consumes: `agent_endpoints.find_endpoint` (Task 2).
- Produces: the script's `CB_SERVER_URL` matches the selected endpoint, and its digest matches what Task 5's route reports.

- [ ] **Step 1: Write the failing test**

```python
"""The script an agent downloads must name the same address the UI promised."""

from __future__ import annotations

import hashlib
import re

import pytest


@pytest.mark.asyncio
async def test_script_renders_the_selected_endpoint(client, db_session):
    from app.schemas.settings import AppSettingsUpdate
    from app.services import settings_service

    settings_service.update_settings(
        db_session,
        AppSettingsUpdate(agent_endpoints=[{"id": "pub1", "label": "Public", "url": "https://cb.example.com"}]),
    )
    db_session.commit()

    resp = await client.get("/install-agent.sh?endpoint=pub1")

    assert resp.status_code == 200
    assert re.search(r'CB_SERVER_URL="https://cb\.example\.com"', resp.text)


@pytest.mark.asyncio
async def test_script_digest_matches_the_command_the_ui_showed(client, auth_headers, db_session):
    """The operator is told to verify this digest; the two must agree or the
    published check fails on a correct download."""
    from app.schemas.settings import AppSettingsUpdate
    from app.services import settings_service

    settings_service.update_settings(
        db_session,
        AppSettingsUpdate(agent_endpoints=[{"id": "pub1", "label": "Public", "url": "https://cb.example.com"}]),
    )
    db_session.commit()

    command = await client.get("/api/v1/agents/install-command?endpoint=pub1", headers=auth_headers)
    script = await client.get("/install-agent.sh?endpoint=pub1")

    assert command.json()["script_sha256"] == hashlib.sha256(script.text.encode()).hexdigest()


@pytest.mark.asyncio
async def test_unknown_endpoint_is_refused(client):
    resp = await client.get("/install-agent.sh?endpoint=nope")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && ../../.venv/bin/python -m pytest tests/api/test_install_agent_script_endpoint.py -v --no-cov`
Expected: FAIL — the script still renders `forwarded_base_url`.

- [ ] **Step 3: Resolve the endpoint in the route**

In `main.py`, change the signature and the `server_url` derivation:

```python
@app.get("/install-agent.sh", include_in_schema=False)
def get_install_agent_script(request: Request, endpoint: str | None = None) -> Response:
    from fastapi import HTTPException

    from app.core import agent_crypto
    from app.core.forwarded import forwarded_base_url
    from app.db.session import SessionLocal
    from app.services import agent_endpoints, agent_install

    with SessionLocal() as db:
        # Same rule as GET /api/v1/agents/install-command: absent falls back,
        # unknown is refused. The two must agree, because the digest the UI
        # publishes is computed over whatever this route renders.
        if endpoint is None:
            server_url = forwarded_base_url(request)
        else:
            selected = agent_endpoints.find_endpoint(db, endpoint)
            if selected is None:
                raise HTTPException(status_code=404, detail=f"No agent endpoint with id {endpoint!r}")
            server_url = selected["url"]

        cert = agent_install._active_certificate(db)
        tls_mode, tls_pin = agent_install._tls_mode_and_pin(cert)
        state = agent_crypto.load_server_key_rotation_state(db)
        server_pub = state.successor_pub if state.successor_pub is not None else state.current_pub
        script = agent_install.render_install_script(
            server_url=server_url,
            server_static_pk_hex=server_pub.hex(),
            tls_pin=tls_pin,
            manifest=agent_install.agent_update.load_manifest(),
        )
    return Response(content=script, media_type="text/x-shellscript")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/backend && ../../.venv/bin/python -m pytest tests/api/test_install_agent_script_endpoint.py -v --no-cov`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add apps/backend/src/app/main.py apps/backend/tests/api/test_install_agent_script_endpoint.py
git commit -m "feat(agents): serve install-agent.sh for a chosen endpoint"
```

---

### Task 7: Install-script reachability preflight

**Files:**
- Modify: `apps/backend/src/app/services/agent_install.py` (`_INSTALL_SCRIPT_TEMPLATE`)
- Test: `apps/backend/tests/services/test_agent_install.py` (append)

**Interfaces:**
- Produces: the rendered script exits non-zero, before `useradd`, when the server URL is unreachable.

- [ ] **Step 1: Write the failing test**

```python
def test_script_preflights_the_server_before_touching_the_machine():
    """A wrong address must fail at step one naming the address, not three
    steps later inside a binary download."""
    script = agent_install.render_install_script(
        server_url="https://cb.example.com",
        server_static_pk_hex="de" * 32,
        tls_pin="pin",
        manifest={"1.0.0": {"linux-amd64": "a" * 64}},
    )
    preflight_at = script.index("/api/v1/health")
    useradd_at = script.index("useradd")
    assert preflight_at < useradd_at, "preflight must run before the machine is modified"
    assert "Cannot reach" in script
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && ../../.venv/bin/python -m pytest tests/services/test_agent_install.py -k preflight -v --no-cov`
Expected: FAIL with `ValueError: substring not found` (no `/api/v1/health` in the script)

- [ ] **Step 3: Add the preflight**

In `_INSTALL_SCRIPT_TEMPLATE`, immediately after the `cb_curl()` function definition and **before** the `if ! id cb-agent` block:

```sh
# Reachability preflight. The server cannot test this for us: it never connects
# to an agent, so the first machine that can answer "is this address reachable
# from here?" is this one. Failing here, before a user or a systemd unit exists,
# means a wrong CB_SERVER_URL costs nothing and says so precisely.
if ! cb_curl "${{CB_SERVER_URL}}/api/v1/health" >/dev/null 2>&1; then
  echo "Cannot reach ${{CB_SERVER_URL}} from this machine." >&2
  echo "The agent would dial that address forever and never appear in the UI." >&2
  echo "Check that the address is correct for THIS network, that DNS resolves" >&2
  echo "it here, and that outbound HTTPS to it is permitted." >&2
  exit 1
fi
```

Note the doubled braces: this is a `str.format` template, so literal `${VAR}` must be written `${{VAR}}`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/backend && ../../.venv/bin/python -m pytest tests/services/test_agent_install.py -v --no-cov`
Expected: PASS — including the existing install-script tests, which must not regress.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/src/app/services/agent_install.py apps/backend/tests/services/test_agent_install.py
git commit -m "feat(agents): preflight server reachability before installing"
```

---

### Task 8: The agent reports the address it dialed

**Files:**
- Modify: `apps/agent/internal/frame/frame.go:202` (`HelloPayload`)
- Modify: `apps/agent/internal/hostinfo/hostinfo.go:33` (`Collect`)
- Modify: `apps/agent/internal/enroll/enroll.go:90`
- Modify: `apps/backend/src/app/api/ws_agents.py:256` (`create_pending_agent` call)
- Test: `apps/agent/internal/hostinfo/hostinfo_test.go`, `apps/backend/tests/api/test_ws_agents_enroll.py`

**Interfaces:**
- Consumes: `Agent.enrolled_via_endpoint` (Task 4).
- Produces: hello field `server_url` (JSON), stored as `agents.enrolled_via_endpoint`.

- [ ] **Step 1: Write the failing Go test**

```go
func TestCollectRecordsTheDialedServerURL(t *testing.T) {
	got := Collect("1.2.3", "https://cb.example.com")
	if got.ServerURL != "https://cb.example.com" {
		t.Errorf("ServerURL = %q, want https://cb.example.com", got.ServerURL)
	}
}
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd apps/agent && go test ./internal/hostinfo/ -run TestCollectRecordsTheDialedServerURL`
Expected: FAIL — `too many arguments in call to Collect`

- [ ] **Step 3: Add the field and thread it**

In `frame.go`, add to `HelloPayload`:

```go
	// ServerURL is the address this agent actually dialed. The server cannot
	// observe it — it never connects to an agent — so an endpoint that no
	// machine can reach is otherwise invisible.
	ServerURL string `json:"server_url,omitempty"`
```

In `hostinfo.go`, change the signature and set the field:

```go
func Collect(agentVersion string, serverURL string) frame.HelloPayload {
```

```go
		ServerURL:        serverURL,
```

In `enroll.go:90`, pass it:

```go
	helloPayload := hostinfo.Collect(agentVersion, cfg.ServerURL)
```

Then fix every other `hostinfo.Collect(` call site:

```bash
cd apps/agent && grep -rn "hostinfo.Collect(" --include=*.go .
```

- [ ] **Step 4: Run the Go tests**

Run: `cd apps/agent && go test ./...`
Expected: PASS

- [ ] **Step 5: Write the failing Python test**

```python
@pytest.mark.asyncio
async def test_enrollment_records_the_endpoint_the_agent_dialed(ws_client, db_session):
    """An endpoint nothing can reach is invisible unless the agent names it."""
    from app.db.models import Agent

    # Enroll using the harness helper already used by the tests in this file,
    # passing server_url in the hello payload.
    agent_id = enroll_agent(ws_client, hello_extra={"server_url": "https://cb.example.com"})

    agent = db_session.get(Agent, agent_id)
    assert agent.enrolled_via_endpoint == "https://cb.example.com"
```

- [ ] **Step 6: Store it server-side**

In `ws_agents.py`, add to the `create_pending_agent(...)` call:

```python
                    enrolled_via_endpoint=payload.get("server_url"),
```

- [ ] **Step 7: Run both suites**

Run: `cd apps/agent && go test ./...` then `cd apps/backend && ../../.venv/bin/python -m pytest tests/api/test_ws_agents_enroll.py -v --no-cov`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add apps/agent/internal/ apps/backend/src/app/api/ws_agents.py apps/backend/tests/api/test_ws_agents_enroll.py
git commit -m "feat(agents): report and store the address an agent dialed"
```

---

### Task 9: Endpoints settings screen

**Files:**
- Create: `apps/frontend/src/components/settings/AgentEndpointsSection.jsx`
- Modify: `apps/frontend/src/pages/SettingsPage.jsx` (render the new section)
- Modify: `apps/frontend/src/api/settings.js` (no change if it already PUTs the whole settings object — verify first)
- Test: `apps/frontend/src/__tests__/agent-endpoints-section.test.jsx`

**Interfaces:**
- Consumes: `PUT /api/v1/settings` with `agent_endpoints` (Task 3).
- Produces: `<AgentEndpointsSection />`.

- [ ] **Step 1: Write the failing test**

```jsx
import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import AgentEndpointsSection from '../components/settings/AgentEndpointsSection';

describe('AgentEndpointsSection', () => {
  it('renders the configured endpoints', () => {
    render(
      <AgentEndpointsSection
        endpoints={[{ id: 'a1', label: 'LAN', url: 'https://10.0.0.5' }]}
        onSave={vi.fn()}
      />
    );
    expect(screen.getByDisplayValue('LAN')).toBeInTheDocument();
    expect(screen.getByDisplayValue('https://10.0.0.5')).toBeInTheDocument();
  });

  it('explains what the address is for, because it is not the browser URL', () => {
    render(<AgentEndpointsSection endpoints={[]} onSave={vi.fn()} />);
    expect(screen.getByText(/agents will dial/i)).toBeInTheDocument();
  });

  it('saves an added endpoint', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<AgentEndpointsSection endpoints={[]} onSave={onSave} />);
    fireEvent.click(screen.getByRole('button', { name: /add endpoint/i }));
    fireEvent.change(screen.getByLabelText(/label/i), { target: { value: 'Public' } });
    fireEvent.change(screen.getByLabelText(/address/i), {
      target: { value: 'https://cb.example.com' },
    });
    fireEvent.click(screen.getByRole('button', { name: /save/i }));
    await waitFor(() =>
      expect(onSave).toHaveBeenCalledWith([{ label: 'Public', url: 'https://cb.example.com' }])
    );
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd apps/frontend && npx vitest run src/__tests__/agent-endpoints-section.test.jsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the component**

```jsx
import React, { useState } from 'react';
import PropTypes from 'prop-types';

/**
 * The addresses agents are told to dial.
 *
 * Separate from `api_base_url` on purpose: that is the browser-facing URL, and
 * the address a browser uses can legitimately differ from the one an agent
 * uses. Getting this wrong is an agent that dials a private address forever
 * and never appears, so the copy says plainly what the field is for.
 */
export default function AgentEndpointsSection({ endpoints, onSave }) {
  const [rows, setRows] = useState(endpoints ?? []);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState(null);

  const update = (index, field, value) =>
    setRows(rows.map((row, i) => (i === index ? { ...row, [field]: value } : row)));

  const handleSave = async () => {
    setIsSaving(true);
    setError(null);
    try {
      // Ids are the server's to mint, so a new row sends none and an existing
      // row keeps the one it has — an install command generated days ago still
      // resolves.
      await onSave(rows.map((r) => (r.id ? { id: r.id, label: r.label, url: r.url } : { label: r.label, url: r.url })));
    } catch (err) {
      setError(err?.response?.data?.detail ?? 'Could not save endpoints.');
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <section className="settings-section">
      <h2>Agent endpoints</h2>
      <p className="settings-hint">
        This is the address agents will dial. It is not necessarily the address you
        use in a browser — an agent on another network cannot reach a LAN address.
      </p>

      {rows.map((row, index) => (
        <div className="settings-row" key={row.id ?? `new-${index}`}>
          <label>
            Label
            <input value={row.label ?? ''} onChange={(e) => update(index, 'label', e.target.value)} />
          </label>
          <label>
            Address
            <input
              value={row.url ?? ''}
              placeholder="https://cb.example.com"
              onChange={(e) => update(index, 'url', e.target.value)}
            />
          </label>
          <button type="button" onClick={() => setRows(rows.filter((_, i) => i !== index))}>
            Remove
          </button>
        </div>
      ))}

      <button type="button" onClick={() => setRows([...rows, { label: '', url: '' }])}>
        Add endpoint
      </button>
      <button type="button" onClick={handleSave} disabled={isSaving}>
        {isSaving ? 'Saving...' : 'Save'}
      </button>
      {error ? <p role="alert" className="settings-error">{error}</p> : null}
    </section>
  );
}

AgentEndpointsSection.propTypes = {
  endpoints: PropTypes.arrayOf(
    PropTypes.shape({ id: PropTypes.string, label: PropTypes.string, url: PropTypes.string })
  ),
  onSave: PropTypes.func.isRequired,
};
```

- [ ] **Step 4: Run it to verify it passes**

Run: `cd apps/frontend && npx vitest run src/__tests__/agent-endpoints-section.test.jsx`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/src/components/settings/AgentEndpointsSection.jsx apps/frontend/src/pages/SettingsPage.jsx apps/frontend/src/__tests__/agent-endpoints-section.test.jsx
git commit -m "feat(agents): configure agent endpoints in settings"
```

---

### Task 10: Wizard endpoint step and fleet visibility

**Files:**
- Modify: `apps/frontend/src/components/agents/AddAgentPanel.jsx:70`
- Modify: `apps/frontend/src/components/agents/AddAgentInstallStep.jsx`
- Modify: `apps/frontend/src/api/agents.js:77` (`getInstallCommand`)
- Modify: `apps/frontend/src/pages/AgentDetailPage.jsx` (show `enrolled_via_endpoint`)
- Test: `apps/frontend/src/__tests__/add-agent-panel.test.jsx` (append)

**Interfaces:**
- Consumes: `GET /api/v1/agents/install-command?endpoint=<id>` (Task 5).
- Produces: nothing downstream.

- [ ] **Step 1: Write the failing test**

```jsx
it('requests the install command for the chosen endpoint', async () => {
  const getInstallCommand = vi.fn().mockResolvedValue({ data: { command: 'x', tls_mode: 'self_signed', script_sha256: 'y' } });
  // ...render AddAgentPanel with endpoints [{id:'pub1',label:'Public',url:'https://cb.example.com'}]
  fireEvent.change(screen.getByLabelText(/endpoint/i), { target: { value: 'pub1' } });
  await waitFor(() => expect(getInstallCommand).toHaveBeenCalledWith('pub1'));
});

it('warns when no endpoint is configured, because the browsed host will be used', () => {
  // ...render with endpoints []
  expect(screen.getByText(/address you are browsing/i)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd apps/frontend && npx vitest run src/__tests__/add-agent-panel.test.jsx`
Expected: FAIL — no endpoint control exists.

- [ ] **Step 3: Implement**

`apps/frontend/src/api/agents.js`:

```js
export const getInstallCommand = (endpointId) =>
  client.get('/agents/install-command', { params: endpointId ? { endpoint: endpointId } : {} });
```

In `AddAgentPanel.jsx`, add the selection state and the two pieces of copy:

```jsx
  const [endpoints, setEndpoints] = useState([]);
  const [selectedEndpoint, setSelectedEndpoint] = useState('');

  // Default to the endpoint matching the address this browser is on: it is the
  // one most likely correct for a LAN agent, and it reproduces today's
  // behaviour for an operator who never opens the picker.
  useEffect(() => {
    getSettings().then(({ data }) => {
      const configured = data.agent_endpoints ?? [];
      setEndpoints(configured);
      const match = configured.find((e) => e.url === window.location.origin);
      setSelectedEndpoint((match ?? configured[0])?.id ?? '');
    });
  }, []);
```

```jsx
      {endpoints.length === 0 ? (
        <p className="add-agent__warning">
          No agent endpoints are configured, so this command will use the address
          you are browsing ({window.location.origin}). An agent on another network
          will not be able to reach it. Add an endpoint in Settings.
        </p>
      ) : (
        <label htmlFor="add-agent-endpoint">
          Endpoint
          <select
            id="add-agent-endpoint"
            value={selectedEndpoint}
            onChange={(e) => setSelectedEndpoint(e.target.value)}
          >
            {endpoints.map((e) => (
              <option key={e.id} value={e.id}>{`${e.label} — ${e.url}`}</option>
            ))}
          </select>
        </label>
      )}
```

Spec §6 item 3 — after 90 seconds with no check-in, say what to verify rather than
spinning silently:

```jsx
  const [isOverdue, setIsOverdue] = useState(false);
  useEffect(() => {
    if (!installCommand || hasCheckedIn) return undefined;
    const timer = setTimeout(() => setIsOverdue(true), 90_000);
    return () => clearTimeout(timer);
  }, [installCommand, hasCheckedIn]);
```

```jsx
      {isOverdue && !hasCheckedIn ? (
        <p className="add-agent__warning">
          Nothing has checked in yet. The agent was told to dial{' '}
          <code>{selectedEndpointUrl}</code> — confirm that address resolves and is
          reachable from the machine you installed on.
        </p>
      ) : null}
```

In `AgentDetailPage.jsx`, beside the other identity facts:

```jsx
        <dt>Enrolled via</dt>
        <dd>{agent.enrolled_via_endpoint ?? EM_DASH}</dd>
```

- [ ] **Step 4: Run it to verify it passes**

Run: `cd apps/frontend && npx vitest run src/__tests__/add-agent-panel.test.jsx`
Expected: PASS

- [ ] **Step 5: Run everything and commit**

```bash
make lint
cd apps/backend && ../../.venv/bin/python -m pytest tests/ -q --maxfail=0
cd apps/frontend && npx vitest run src/__tests__/
git add -A && git commit -m "feat(agents): choose an endpoint when adding an agent"
```

Note: `tests/api/test_certificate_activation_gate.py` has two failures that pre-date this work (reproduced at `67943628`). They are not yours; do not fix them in this plan.

---

### Task 11: Endpoint usage counts

**Files:**
- Modify: `apps/backend/src/app/api/agents.py` (new route)
- Modify: `apps/frontend/src/components/settings/AgentEndpointsSection.jsx`
- Test: `apps/backend/tests/api/test_agent_endpoint_usage.py`

**Interfaces:**
- Consumes: `Agent.enrolled_via_endpoint` (Task 4).
- Produces: `GET /api/v1/agents/endpoint-usage` returning `{"<url>": <count>}`.

Spec §6 item 4: an endpoint no agent ever enrolled through is a smell an operator
can act on. Without this the only evidence is an agent that never appeared, which
is exactly the invisible failure this slice exists to end.

- [ ] **Step 1: Write the failing test**

```python
"""An endpoint nothing enrolled through is visible, not inferred from silence."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_usage_counts_group_by_endpoint(client, auth_headers, db_session, factories):
    factories.agent(enrolled_via_endpoint="https://cb.example.com")
    factories.agent(enrolled_via_endpoint="https://cb.example.com")
    factories.agent(enrolled_via_endpoint="https://10.0.0.5")
    db_session.commit()

    resp = await client.get("/api/v1/agents/endpoint-usage", headers=auth_headers)

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"https://cb.example.com": 2, "https://10.0.0.5": 1}


@pytest.mark.asyncio
async def test_agents_from_before_this_feature_are_not_counted(
    client, auth_headers, db_session, factories
):
    factories.agent(enrolled_via_endpoint=None)
    db_session.commit()
    resp = await client.get("/api/v1/agents/endpoint-usage", headers=auth_headers)
    assert resp.json() == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && ../../.venv/bin/python -m pytest tests/api/test_agent_endpoint_usage.py -v --no-cov`
Expected: FAIL with 404 — the route does not exist.

- [ ] **Step 3: Add the route**

In `api/agents.py`, declared **before** `"/{agent_id}"` so it is not parsed as an
agent id — the same reason `/pending`, `/install-command` and `/presence` are
declared where they are:

```python
@router.get("/endpoint-usage")
def get_endpoint_usage(
    db: Annotated[Session, Depends(get_db)],
    _user: Annotated[User, require_role("admin")],
) -> dict[str, int]:
    """How many agents enrolled through each endpoint.

    An endpoint with no agents is the only observable signal that it is
    unreachable: the agent that would report the failure is the one that
    cannot connect to report it.
    """
    rows = db.execute(
        select(Agent.enrolled_via_endpoint, func.count())
        .where(Agent.enrolled_via_endpoint.is_not(None))
        .group_by(Agent.enrolled_via_endpoint)
    ).all()
    return {url: count for url, count in rows}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/backend && ../../.venv/bin/python -m pytest tests/api/test_agent_endpoint_usage.py -v --no-cov`
Expected: PASS (2 tests)

- [ ] **Step 5: Show it in the settings section**

In `AgentEndpointsSection.jsx`, accept a `usage` prop and render beside each row:

```jsx
          <span className="settings-hint">
            {usage?.[row.url]
              ? `${usage[row.url]} agent(s) enrolled`
              : 'no agents have enrolled through this address yet'}
          </span>
```

- [ ] **Step 6: Commit**

```bash
git add apps/backend/src/app/api/agents.py apps/backend/tests/api/test_agent_endpoint_usage.py apps/frontend/src/components/settings/AgentEndpointsSection.jsx
git commit -m "feat(agents): show how many agents enrolled through each endpoint"
```
---

## Manual verification

After Task 10, on the dev box (`make dev` + `make dev-tls`):

1. Settings → add two endpoints: `LAN → https://<lan-ip>` and a deliberately wrong `Bad → https://192.0.2.1`.
2. Add Agent → choose `LAN` → run `make dev-agent`. It should enroll, and agent detail should show "Enrolled via `https://<lan-ip>`".
3. Add Agent → choose `Bad` → run the command by hand. It must fail at the preflight, printing `Cannot reach https://192.0.2.1`, **before** creating a `cb-agent` user.
4. Delete the `Bad` endpoint, then re-open its old install command URL: it must 404, not silently produce a LAN command.
