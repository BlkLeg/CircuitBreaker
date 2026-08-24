# UI-5 — Access Tokens and Service Accounts

**Supports:** INC-14, and closes INC-04
**Depends on:** UI-2 (`HighRiskConfirmDialog`)
**Spec:** [Missing UIs](../10-missing-uis.md) §7

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make API tokens administrable — created with least privilege, inventoried fleet-wide, rotated, and revoked — and make the scopes they carry actually restrict what the token can do.

**Architecture:** Seven backend changes land first, in dependency order, because the UI cannot honestly exist without them. `require_role` becomes scope-aware with back-compatible defaults; a server-side scope catalog feeds the picker so the two cannot drift. The UI is one new Settings component; `ProfileModal` keeps a personal view but loses its duplicate create form.

**Tech Stack:** FastAPI, SQLAlchemy, PyJWT, pytest; React 18, vitest + @testing-library/react.

## Global Constraints

- **No control may claim a restriction the backend does not enforce.** This slice exists because a scope picker over today's backend would label a token "read-only" while it could delete every user.
- **Existing deployed tokens must keep working across the upgrade** (spec D9, back-compat defaults).
- **Every new surface is its own file.** `ProfileModal.jsx` is 1130 lines and `SettingsPage.jsx` is 1876; both shrink or stay flat here, neither grows.
- **A token secret is shown exactly once**, must be acknowledged explicitly, and must never re-render from state after dismissal.
- **Presets name what is enforced**, not a per-resource matrix nothing honours.
- **Admin only** — every route in this slice is `require_role("admin")`.

---

## Why the backend comes first

Tracing both token paths in the current code:

1. **Static UI token** — `core/security.py:523` sets `uid = api_token_row.created_by`, so `require_role("admin")` resolves the creating admin and passes.
2. **Service-account JWT** — `uid = 0`, and `core/rbac.py:141` returns `_service_user()` with `is_superuser=True` **before any scope check runs**.
3. `require_scope` is used on exactly **two** distinct checks in the whole backend: `require_scope("read", "*")` and `require_scope("write", "telemetry")`. Everything else is `require_role`.

So every token, whatever its scopes, is a superuser on every role-guarded route — settings, users, backups, vault, audit-chain repair. INC-04 records the 403 half ("authorized for nothing" on scope routes); this is the other half, and it fails in the dangerous direction.

### Two asymmetries that are easy to get wrong

**A. `[]` means "inherit the creator" for static tokens, and "deny" for service-account JWTs.**

The back-compat rule (D9) is that a stored `scopes == []` means *unscoped — inherit the creator*. That is correct for a **static** token, which has a real creating user to inherit from. It is **wrong** for a service-account JWT, whose `uid` is `0` and whose "creator" is the synthetic superuser `_service_user()` — inheriting there would silently promote an empty-scoped service account to full superuser, which is the exact bug this slice closes.

Therefore the back-compat reinterpretation is applied **at the static-token call site** (`security.py:524-527`), never inside `_normalise_token_scopes`, which the `uid == 0` branch also calls. Task 1 implements it that way and tests both directions.

**B. `admin:*` alone does not satisfy `require_scope("read", "*")`.**

`has_scope` (`rbac.py:92-105`) matches `action:resource`, `action:*`, `*:resource`, and `*:*`. A token holding only `admin:*` therefore fails `require_scope("read", "*")` — which guards hardware, discovery, clusters, monitors, graph and integrations. A "full access" preset built as `["admin:*"]` would produce a token that is superuser on role routes and 403 on read routes: a new lying control in the opposite direction.

**Full access is therefore `["*:*"]`**, which `has_scope` satisfies for every check. Task 2's presets encode this, and Task 2 has a test asserting the full-access preset satisfies both a role gate and a scope gate.

---

## File Structure

**Create**

| File | Responsibility |
|---|---|
| `apps/backend/src/app/core/token_scopes.py` | Grantable-scope catalog and presets. One source of truth. |
| `apps/frontend/src/api/tokens.js` | Token endpoints. |
| `apps/frontend/src/components/settings/AccessTokensManager.jsx` | Inventory, create, rotate, revoke, one-time reveal. |
| `apps/backend/tests/api/test_token_scopes.py` | B1–B4 enforcement and back-compat. |
| `apps/backend/tests/api/test_api_tokens_admin.py` | B5–B7 inventory, rotation, revocation. |
| `apps/frontend/src/__tests__/tokens-api.test.js` | Pins URLs and payloads. |
| `apps/frontend/src/__tests__/access-tokens-manager.test.jsx` | UI behaviour incl. one-time reveal. |
| `docs/api-tokens.md` | Operator documentation. |

**Modify**

| File | Change |
|---|---|
| `apps/backend/src/app/core/security.py:82-88, 524-527` | Back-compat `[]` handling at the static-token site. |
| `apps/backend/src/app/core/rbac.py:125-164` | `require_role` honours token scopes. |
| `apps/backend/src/app/api/auth.py:407-585` | Scopes on create, catalog route, richer list item, fleet-wide list/delete, rotation. |
| `apps/frontend/src/components/auth/ProfileModal.jsx` | Remove the create form; keep the personal list. |
| `apps/frontend/src/pages/SettingsPage.jsx` | One render line in the Security tab. |
| `docs/1.0.0-incomplete-features.md`, `docs/1.0.0-release-readiness-audit.md`, `mkdocs.yml` | Register, security audit, nav. |

---

## Task 1: B1 — make `require_role` scope-aware

**Files:**
- Modify: `apps/backend/src/app/core/security.py`, `apps/backend/src/app/core/rbac.py`
- Test: `apps/backend/tests/api/test_token_scopes.py`

**Interfaces:**
- Produces: `rbac.ROLE_SCOPE_REQUIREMENT: dict[str, tuple[str, str]]` mapping a role name to the `(action, resource)` a token must hold to satisfy a gate for that role.

- [ ] **Step 1: Write the failing tests**

Create `apps/backend/tests/api/test_token_scopes.py`:

```python
"""B1: token scopes must restrict role-guarded routes, not only scope-guarded ones.

Before this, a token created by an admin passed every require_role gate as that
admin, and a service-account JWT passed as a superuser before any scope check
ran (rbac.py:141) — so scopes narrowed only the two require_scope checks that
exist in the whole backend. See INC-04 / INC-14.
"""

from __future__ import annotations

import pytest

from app.core.security import create_salted_api_token_hash
from app.db.models import APIToken


def _token_headers(db_session, factories, raw_token: str, scopes) -> dict[str, str]:
    """A static API token owned by an admin, carrying `scopes` verbatim.

    Mirrors _api_token_headers in tests/api/test_monitor_api.py; `scopes` is
    passed through unchanged so a test can store [] to represent a legacy row.
    """
    owner = factories.user(role="admin")
    db_session.add(
        APIToken(
            token_hash=create_salted_api_token_hash(raw_token),
            label="scope test",
            created_by=owner.id,
            scopes=scopes,
        )
    )
    db_session.flush()
    return {"Authorization": f"Bearer {raw_token}"}


@pytest.mark.asyncio
async def test_read_only_token_is_refused_on_an_admin_route(
    client, db_session, factories
):
    """The headline: a read-only token must not be able to administer anything."""
    headers = _token_headers(db_session, factories, "tok-readonly", ["read:*"])

    resp = await client.get("/api/v1/kb/oui", headers=headers)

    assert resp.status_code == 403, (
        "a read:* token reached an admin-only route — this is the escalation B1 closes"
    )


@pytest.mark.asyncio
async def test_read_only_token_is_allowed_on_a_read_route(
    client, db_session, factories
):
    headers = _token_headers(db_session, factories, "tok-readonly-2", ["read:*"])
    resp = await client.get("/api/v1/hardware", headers=headers)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_full_access_token_is_allowed_everywhere(client, db_session, factories):
    """`*:*` satisfies has_scope for every check — role gates and scope gates."""
    headers = _token_headers(db_session, factories, "tok-full", ["*:*"])

    assert (await client.get("/api/v1/hardware", headers=headers)).status_code == 200
    assert (await client.get("/api/v1/kb/oui", headers=headers)).status_code == 200


@pytest.mark.asyncio
async def test_admin_only_scope_does_not_satisfy_a_read_gate(
    client, db_session, factories
):
    """Why the Full access preset is *:* and not admin:*.

    has_scope matches action:resource, action:*, *:resource and *:* — never
    "admin implies read". A token holding only admin:* passes role gates and
    fails require_scope("read", "*"), which would be a lying control in the
    opposite direction.
    """
    headers = _token_headers(db_session, factories, "tok-adminonly", ["admin:*"])

    assert (await client.get("/api/v1/kb/oui", headers=headers)).status_code == 200
    assert (await client.get("/api/v1/hardware", headers=headers)).status_code == 403


@pytest.mark.asyncio
async def test_legacy_scopeless_token_still_authenticates_as_its_creator(
    client, db_session, factories
):
    """D9 back-compat. APIToken.scopes is JSONB default=list, so every token
    created through the UI before this change stored [] — not NULL. Those must
    keep working across the upgrade, so [] means "unscoped, inherit the
    creator". This is ALSO INC-04's fix: _normalise_token_scopes returning ()
    rather than None for [] is exactly what made every such token 403 on
    require_scope routes.
    """
    headers = _token_headers(db_session, factories, "tok-legacy", [])

    assert (await client.get("/api/v1/hardware", headers=headers)).status_code == 200
    assert (await client.get("/api/v1/kb/oui", headers=headers)).status_code == 200


@pytest.mark.asyncio
async def test_legacy_scopeless_token_inherits_a_viewers_limits_too(
    client, db_session, factories
):
    """"Inherit the creator" must mean inherit, not escalate."""
    owner = factories.user(role="viewer")
    db_session.add(
        APIToken(
            token_hash=create_salted_api_token_hash("tok-legacy-viewer"),
            label="legacy viewer token",
            created_by=owner.id,
            scopes=[],
        )
    )
    db_session.flush()
    headers = {"Authorization": "Bearer tok-legacy-viewer"}

    assert (await client.get("/api/v1/hardware", headers=headers)).status_code == 200
    assert (await client.get("/api/v1/kb/oui", headers=headers)).status_code == 403


@pytest.mark.asyncio
async def test_service_account_jwt_with_empty_scopes_is_denied_not_promoted(
    client, db_session
):
    """The asymmetry that is easy to get wrong.

    A service-account JWT has user_id=0 and no real creator — rbac._service_user
    is a synthetic superuser. Applying the "[] inherits the creator" rule there
    would promote an empty-scoped service account to full superuser, which is
    the bug this slice closes. Back-compat applies to static tokens only.
    """
    from app.core.security import create_token
    from app.services.settings_service import get_or_create_settings

    cfg = get_or_create_settings(db_session)
    token = create_token(0, cfg.jwt_secret, 24, scopes=[], extra_claims={"label": "empty"})
    headers = {"Authorization": f"Bearer {token}"}

    assert (await client.get("/api/v1/kb/oui", headers=headers)).status_code == 403
    assert (await client.get("/api/v1/hardware", headers=headers)).status_code == 403


@pytest.mark.asyncio
async def test_a_normal_session_is_unaffected(client, auth_headers, viewer_headers):
    """B1 must change nothing for cookie/session users — token_scopes is None
    for them, so the new branch never runs."""
    assert (await client.get("/api/v1/kb/oui", headers=auth_headers)).status_code == 200
    assert (await client.get("/api/v1/kb/oui", headers=viewer_headers)).status_code == 403
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest apps/backend/tests/api/test_token_scopes.py -v`
Expected: FAIL — notably `test_read_only_token_is_refused_on_an_admin_route` returns 200, and `test_legacy_scopeless_token_still_authenticates_as_its_creator` returns 403 on `/hardware`.

- [ ] **Step 3: Apply the back-compat rule at the static-token site**

In `apps/backend/src/app/core/security.py`, in the static-token branch (line ~524), replace:

```python
        token_scopes = _normalise_token_scopes(api_token_row.scopes)
```

with:

```python
        token_scopes = _normalise_token_scopes(api_token_row.scopes)
        if token_scopes == ():
            # D9 back-compat, and INC-04's fix for existing rows.
            # APIToken.scopes is `mapped_column(JSONB, default=list)`, so every
            # token created through the UI before scopes were settable stored
            # [] — not NULL. Treating that as "no scopes granted" is what makes
            # those tokens 403 on every require_scope route today. None means
            # "unscoped: fall through to the creating user's own permissions",
            # which is what they have always effectively had.
            #
            # Deliberately NOT done inside _normalise_token_scopes: the
            # `uid == 0` service-account branch above calls it too, and a
            # service account has no real creator — inheriting there would
            # promote an empty-scoped service account to superuser.
            token_scopes = None
```

Leave `_normalise_token_scopes` itself unchanged.

- [ ] **Step 4: Make `require_role` honour token scopes**

In `apps/backend/src/app/core/rbac.py`, add below `ROLE_DEFAULT_SCOPES`:

```python
# What a TOKEN must hold to satisfy a require_role gate. Roles are a user
# concept; a token carries scopes, so a role gate has to be expressed as a
# scope check before it can mean anything for a token. The mapping mirrors
# ROLE_DEFAULT_SCOPES above — the scope each role's default set is defined by —
# so the two cannot describe different privilege ladders.
ROLE_SCOPE_REQUIREMENT: dict[str, tuple[str, str]] = {
    "viewer": ("read", "*"),
    "demo": ("read", "*"),
    "editor": ("write", "*"),
    "admin": ("admin", "*"),
}


def _role_scope_requirement(roles: tuple[str, ...]) -> tuple[str, str]:
    """The scope a token needs for a gate accepting any of `roles`.

    require_role passes if the user meets the LOWEST-ranked role listed
    (`user_rank < min(allowed_ranks)` below), so the token requirement is that
    same lowest role's scope. Anything stricter would refuse tokens that an
    equivalent user session would be allowed.
    """
    ranked = sorted(roles, key=lambda r: ROLE_HIERARCHY.get(r, 0))
    return ROLE_SCOPE_REQUIREMENT.get(ranked[0], ("admin", "*"))
```

Then change `require_role`'s inner dependency. Add `request: HTTPConnection` as its first parameter and insert the scope check immediately after the `user_id is None` guard, **before** the `user_id == 0` early return:

```python
    async def _dep(
        request: HTTPConnection,
        user_id: int | None = Depends(get_optional_user),
        db: Session = Depends(get_db),
    ) -> User:
        if user_id is None:
            raise HTTPException(status_code=401, detail="Authentication required")

        # A request authenticated by a scoped token is limited by that token,
        # even on role-guarded routes. Without this, scopes narrowed only the
        # two require_scope checks in the codebase and every token was a
        # superuser everywhere else (INC-14). token_scopes is None for session
        # users and for legacy unscoped tokens, so this branch never runs for
        # them and their behaviour is unchanged.
        token_scopes = _request_token_scopes(request)
        if token_scopes is not None and roles:
            action, resource = _role_scope_requirement(roles)
            if not has_scope(token_scopes, action, resource):
                raise HTTPException(status_code=403, detail="Insufficient permissions")

        if user_id == 0:
            return _service_user()
        # … rest of the function unchanged …
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest apps/backend/tests/api/test_token_scopes.py -v`
Expected: PASS — 8 tests.

- [ ] **Step 6: Run the whole backend suite — this change touches every route**

Run: `pytest apps/backend/tests -q`
Expected: PASS. Any failure here is a real behaviour change, not a flaky test: read it before adjusting anything. A test that constructed an `APIToken` with narrow scopes and then called an admin route was previously passing *because of* this bug.

- [ ] **Step 7: Commit**

```bash
git add apps/backend/src/app/core/security.py apps/backend/src/app/core/rbac.py apps/backend/tests/api/test_token_scopes.py
git commit -m "fix(security): honour token scopes on role-guarded routes (INC-04, INC-14)"
```

---

## Task 2: B2 + B3 — scope catalog, presets, validation

**Files:**
- Create: `apps/backend/src/app/core/token_scopes.py`
- Modify: `apps/backend/src/app/api/auth.py`
- Test: `apps/backend/tests/api/test_token_scopes.py` (append)

**Interfaces:**
- Produces:
  - `GRANTABLE_SCOPES: dict[str, str]` — scope → human description
  - `SCOPE_PRESETS: list[dict]` — `{key, label, description, scopes}`
  - `validate_scopes(scopes: list[str]) -> list[str]` — raises `ValueError` on unknown or empty
  - `GET /auth/scopes` → `{scopes: [{scope, description}], presets: [...]}`

- [ ] **Step 1: Write the failing tests**

Append to `apps/backend/tests/api/test_token_scopes.py`:

```python
# ── B2/B3: catalog, presets, validation ──────────────────────────────────────


@pytest.mark.asyncio
async def test_scope_catalog_is_served_to_admins(client, auth_headers):
    resp = await client.get("/api/v1/auth/scopes", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert {s["scope"] for s in body["scopes"]} >= {"read:*", "write:telemetry", "*:*"}
    assert [p["key"] for p in body["presets"]] == [
        "read_only",
        "telemetry_ingest",
        "read_write",
        "full_access",
    ]


def test_full_access_preset_is_star_star_not_admin_star():
    """Pins the reasoning in test_admin_only_scope_does_not_satisfy_a_read_gate:
    admin:* passes role gates and FAILS require_scope("read", "*")."""
    from app.core.token_scopes import SCOPE_PRESETS

    full = next(p for p in SCOPE_PRESETS if p["key"] == "full_access")
    assert full["scopes"] == ["*:*"]


def test_catalog_covers_every_scope_the_presets_grant():
    """A preset granting a scope the catalog does not list would be rejected by
    its own validator."""
    from app.core.token_scopes import GRANTABLE_SCOPES, SCOPE_PRESETS

    for preset in SCOPE_PRESETS:
        for scope in preset["scopes"]:
            assert scope in GRANTABLE_SCOPES, f"{preset['key']} grants uncatalogued {scope}"


def test_catalog_matches_the_role_scope_requirements():
    """Every scope B1 can demand must be grantable, or a preset could never
    satisfy an admin or editor gate."""
    from app.core.rbac import ROLE_SCOPE_REQUIREMENT
    from app.core.token_scopes import GRANTABLE_SCOPES

    for action, resource in ROLE_SCOPE_REQUIREMENT.values():
        assert f"{action}:{resource}" in GRANTABLE_SCOPES


@pytest.mark.asyncio
async def test_service_account_rejects_an_unknown_scope(client, auth_headers):
    """INC-04's failure mode reproduced through the endpoint that "works":
    CreateServiceAccountRequest.scopes was an unvalidated list[str], so
    `read:hardwrae` minted a token authorized for nothing."""
    resp = await client.post(
        "/api/v1/auth/service-account",
        headers=auth_headers,
        json={"label": "typo", "scopes": ["read:hardwrae"]},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_service_account_rejects_an_empty_scope_list(client, auth_headers):
    """Prevents re-creating the [] ambiguity B1's back-compat rule exists for."""
    resp = await client.post(
        "/api/v1/auth/service-account",
        headers=auth_headers,
        json={"label": "empty", "scopes": []},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_api_token_accepts_and_stores_scopes(client, auth_headers, db_session):
    """B4 — INC-04's fix for newly created tokens."""
    from app.db.models import APIToken

    resp = await client.post(
        "/api/v1/auth/api-token",
        headers=auth_headers,
        json={"label": "ci", "scopes": ["read:*"]},
    )
    assert resp.status_code == 200
    row = db_session.get(APIToken, resp.json()["id"])
    assert row.scopes == ["read:*"]


@pytest.mark.asyncio
async def test_api_token_without_scopes_defaults_to_the_creators_scopes(
    client, auth_headers, db_session
):
    """Not [] — that was INC-04. An omitted scopes field means "same as me"."""
    from app.db.models import APIToken

    resp = await client.post(
        "/api/v1/auth/api-token", headers=auth_headers, json={"label": "inherit"}
    )
    assert resp.status_code == 200
    row = db_session.get(APIToken, resp.json()["id"])
    assert row.scopes, "scopes must not be empty — an empty list is the INC-04 bug"
    assert "admin:*" in row.scopes
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest apps/backend/tests/api/test_token_scopes.py -k "catalog or preset or scope_list or unknown_scope or api_token" -v`
Expected: FAIL — no `app.core.token_scopes`, `/auth/scopes` 404s.

- [ ] **Step 3: Write the catalog**

Create `apps/backend/src/app/core/token_scopes.py`:

```python
"""The scopes a token may be granted, and the presets the UI offers.

One source of truth, served to the frontend by GET /auth/scopes, so the picker
cannot offer something the validator rejects or the enforcement ignores. Two
surfaces describing one field differently is INC-03 in miniature.

Deliberately NARROW. ROLE_DEFAULT_SCOPES contains per-resource write scopes
(write:hardware, write:services, …) for the editor role, but `require_scope` is
used on exactly two distinct checks in the whole backend — ("read", "*") and
("write", "telemetry") — so offering `write:hardware` as a token scope would
imply a per-resource granularity nothing enforces. After B1 the meaningful
distinctions are read / write / delete / admin, and this catalog says only that.
When more routes adopt require_scope, widen this list and the presets together.
"""

from __future__ import annotations

GRANTABLE_SCOPES: dict[str, str] = {
    "read:*": "Read every resource.",
    "write:*": "Create and modify every resource.",
    "delete:*": "Delete every resource.",
    "admin:*": "Administrative operations: settings, users, backups, vault.",
    "write:telemetry": "Submit telemetry samples. For collectors and agents.",
    "*:*": "Unrestricted. Equivalent to an administrator session.",
}

# `full_access` is *:* and NOT admin:* on purpose. has_scope (core/rbac.py:92)
# matches action:resource, action:*, *:resource and *:* — it never treats admin
# as implying read. A token holding only admin:* passes role gates and gets 403
# from require_scope("read", "*"), which guards hardware, discovery, clusters,
# monitors, graph and integrations. Pinned by
# test_full_access_preset_is_star_star_not_admin_star.
SCOPE_PRESETS: list[dict] = [
    {
        "key": "read_only",
        "label": "Read-only",
        "description": "Can read everything, change nothing.",
        "scopes": ["read:*"],
    },
    {
        "key": "telemetry_ingest",
        "label": "Telemetry ingest",
        "description": "Read access plus telemetry submission. For collectors.",
        "scopes": ["read:*", "write:telemetry"],
    },
    {
        "key": "read_write",
        "label": "Read and write",
        "description": "Can create and modify resources, but not administer the server.",
        "scopes": ["read:*", "write:*"],
    },
    {
        "key": "full_access",
        "label": "Full access",
        "description": "Unrestricted, including settings, users and the vault.",
        "scopes": ["*:*"],
    },
]


def validate_scopes(scopes: list[str]) -> list[str]:
    """Normalise and validate a requested scope list.

    An empty list is rejected rather than stored: `[]` is reserved as the
    legacy "unscoped, inherit the creator" marker (see core/security.py's
    static-token branch), and letting a caller store it deliberately would
    recreate the ambiguity that back-compat rule exists to absorb.
    """
    cleaned = [s.strip() for s in scopes if s and s.strip()]
    if not cleaned:
        raise ValueError("At least one scope is required.")
    unknown = sorted(set(cleaned) - set(GRANTABLE_SCOPES))
    if unknown:
        raise ValueError(
            f"Unknown scope(s): {', '.join(unknown)}. "
            f"Valid scopes: {', '.join(sorted(GRANTABLE_SCOPES))}."
        )
    return sorted(set(cleaned))
```

- [ ] **Step 4: Wire it into the auth API**

In `apps/backend/src/app/api/auth.py`:

Add the import:

```python
from app.core.token_scopes import GRANTABLE_SCOPES, SCOPE_PRESETS, validate_scopes
```

Give `CreateAPITokenRequest` a scopes field (line 407):

```python
class CreateAPITokenRequest(BaseModel):
    label: str | None = None
    expires_at: str | None = None  # ISO datetime or None for no expiry
    # B4 / INC-04: omitted means "the same access I have", NOT [] — an empty
    # list stored here is exactly what made every UI-created token 403.
    scopes: list[str] | None = None
```

Add validators to both request models:

```python
    @field_validator("scopes")
    @classmethod
    def _check_scopes(cls, v):
        if v is None:
            return v
        try:
            return validate_scopes(v)
        except ValueError as err:
            raise ValueError(str(err)) from err
```

(`CreateServiceAccountRequest.scopes` keeps its `["read:*"]` default and gains the same validator. Import `field_validator` from pydantic if it is not already imported in this module.)

Add the catalog route beside the other auth routes:

```python
@router.get("/scopes", tags=["auth"])
def list_grantable_scopes(
    _user: Annotated[User, require_role("admin")],
) -> dict[str, Any]:
    """The scopes a token may be granted, and the presets the UI offers.

    Served rather than duplicated in the frontend so the picker cannot drift
    from what validate_scopes accepts and require_role/require_scope enforce.
    """
    return {
        "scopes": [
            {"scope": scope, "description": description}
            for scope, description in sorted(GRANTABLE_SCOPES.items())
        ],
        "presets": SCOPE_PRESETS,
    }
```

In `create_api_token` (line 497), set the scopes on the row. Replace the `APIToken(...)` construction's argument list to include:

```python
        scopes=payload.scopes if payload.scopes else sorted(effective_scopes(current_user)),
```

and import `effective_scopes` from `app.core.rbac`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest apps/backend/tests/api/test_token_scopes.py -v`
Expected: PASS — 16 tests.

- [ ] **Step 6: Commit**

```bash
git add apps/backend/src/app/core/token_scopes.py apps/backend/src/app/api/auth.py apps/backend/tests/api/test_token_scopes.py
git commit -m "feat(auth): add scope catalog, presets, and scope validation (INC-04, INC-14)"
```

---

## Task 3: B5 + B6 — richer inventory, fleet-wide list and revoke

**Files:**
- Modify: `apps/backend/src/app/api/auth.py:412-418, 537-585`
- Test: `apps/backend/tests/api/test_api_tokens_admin.py`

**Interfaces:**
- Produces: `APITokenItem` gains `scopes: list[str]`, `created_by: int`, `created_by_name: str | None`, `is_service_account: bool`
- `GET /auth/api-tokens?scope=all|mine` — `mine` remains the default so no existing client changes behaviour
- `DELETE /auth/api-tokens/{id}` — an admin may revoke any token

- [ ] **Step 1: Write the failing tests**

Create `apps/backend/tests/api/test_api_tokens_admin.py`:

```python
"""B5–B7: fleet-wide token inventory, rotation, revocation. INC-14."""

from __future__ import annotations

import pytest

from app.core.security import create_salted_api_token_hash
from app.db.models import APIToken


def _token_for(db_session, owner, label: str, scopes=None) -> APIToken:
    row = APIToken(
        token_hash=create_salted_api_token_hash(f"raw-{label}"),
        label=label,
        created_by=owner.id,
        scopes=scopes if scopes is not None else ["read:*"],
    )
    db_session.add(row)
    db_session.flush()
    return row


@pytest.mark.asyncio
async def test_list_defaults_to_own_tokens(client, auth_headers, db_session, factories):
    other = factories.user(role="admin")
    _token_for(db_session, other, "someone-elses")

    resp = await client.get("/api/v1/auth/api-tokens", headers=auth_headers)

    assert resp.status_code == 200
    assert all(t["label"] != "someone-elses" for t in resp.json())


@pytest.mark.asyncio
async def test_list_all_shows_every_admins_tokens(
    client, auth_headers, db_session, factories
):
    """There was no fleet-wide inventory: GET /auth/api-tokens filtered on
    created_by == current_user.id, so one admin could not see another's."""
    other = factories.user(role="admin", email="peer@example.com")
    _token_for(db_session, other, "someone-elses")

    resp = await client.get("/api/v1/auth/api-tokens?scope=all", headers=auth_headers)

    assert resp.status_code == 200
    labels = [t["label"] for t in resp.json()]
    assert "someone-elses" in labels


@pytest.mark.asyncio
async def test_list_items_carry_scopes_and_creator(
    client, auth_headers, db_session, factories
):
    owner = factories.user(role="admin", email="owner@example.com")
    _token_for(db_session, owner, "ci-deploy", ["read:*", "write:telemetry"])

    resp = await client.get("/api/v1/auth/api-tokens?scope=all", headers=auth_headers)

    item = next(t for t in resp.json() if t["label"] == "ci-deploy")
    assert item["scopes"] == ["read:*", "write:telemetry"]
    assert item["created_by"] == owner.id
    assert item["created_by_name"]


@pytest.mark.asyncio
async def test_service_accounts_are_flagged_by_a_field_not_a_label_prefix(
    client, auth_headers, db_session, factories
):
    """Service accounts were identifiable only by the "[Service Account] "
    label prefix api/auth.py:478 writes — a string convention the UI would have
    had to parse, and which any operator could imitate in a plain label."""
    owner = factories.user(role="admin", email="sa@example.com")
    _token_for(db_session, owner, "[Service Account] metrics")
    _token_for(db_session, owner, "plain-token")

    resp = await client.get("/api/v1/auth/api-tokens?scope=all", headers=auth_headers)
    by_label = {t["label"]: t for t in resp.json()}

    assert by_label["[Service Account] metrics"]["is_service_account"] is True
    assert by_label["plain-token"]["is_service_account"] is False


@pytest.mark.asyncio
async def test_an_admin_can_revoke_another_admins_token(
    client, auth_headers, db_session, factories
):
    """DELETE had the same created_by filter as the list (api/auth.py:576-582),
    so an admin could not revoke a peer's token even knowing its id — the
    register cites only the list."""
    other = factories.user(role="admin", email="peer2@example.com")
    row = _token_for(db_session, other, "peers-token")

    resp = await client.delete(f"/api/v1/auth/api-tokens/{row.id}", headers=auth_headers)

    assert resp.status_code == 204
    assert db_session.get(APIToken, row.id) is None


@pytest.mark.asyncio
async def test_revoking_a_missing_token_is_404(client, auth_headers):
    resp = await client.delete("/api/v1/auth/api-tokens/999999", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_token_admin_requires_admin(client, viewer_headers):
    assert (
        await client.get("/api/v1/auth/api-tokens", headers=viewer_headers)
    ).status_code == 403
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest apps/backend/tests/api/test_api_tokens_admin.py -v`
Expected: FAIL — `KeyError: 'scopes'`, `?scope=all` ignored, cross-admin delete 404s.

- [ ] **Step 3: Extend the response model**

In `apps/backend/src/app/api/auth.py`, replace `APITokenItem` (line 412):

```python
# The "[Service Account] " label prefix create_service_account writes
# (see below) is how service accounts were distinguishable — a string
# convention. is_service_account derives from it once, here, so the UI never
# parses labels and a plain token whose label happens to start that way is
# still just a label to everything downstream.
_SERVICE_ACCOUNT_LABEL_PREFIX = "[Service Account] "


class APITokenItem(BaseModel):
    id: int
    label: str | None
    created_at: str
    expires_at: str | None
    last_used_at: str | None
    scopes: list[str] = []
    created_by: int | None = None
    created_by_name: str | None = None
    is_service_account: bool = False
```

- [ ] **Step 4: Rewrite the list and delete routes**

Replace `list_api_tokens` and `revoke_api_token` (lines 537-585):

```python
@router.get("/api-tokens", response_model=list[APITokenItem], tags=["auth"])
@limiter.limit(lambda: get_limit("auth"))
def list_api_tokens(
    request: Request,
    response: Response,
    current_user: Annotated[User, require_role("admin")],
    db: Session = Depends(get_db),
    scope: str = Query("mine", pattern="^(mine|all)$"),
) -> list[APITokenItem]:
    """List API tokens. `scope=all` returns the whole install's inventory.

    `mine` stays the default so existing clients see no change, but an admin
    can now see and revoke tokens they did not create — there was previously no
    fleet-wide inventory at all, which left SRV-06's revocation requirement
    unmet in practice (INC-14).
    """
    q = db.query(APIToken)
    if scope == "mine":
        q = q.filter(APIToken.created_by == current_user.id)
    tokens = q.order_by(APIToken.created_at.desc()).all()

    creator_ids = {t.created_by for t in tokens if t.created_by is not None}
    creators: dict[int, str] = {}
    if creator_ids:
        # One query for every creator, not one per token.
        for uid, email, name in db.query(User.id, User.email, User.name).filter(
            User.id.in_(creator_ids)
        ):
            creators[uid] = name or email

    return [
        APITokenItem(
            id=t.id,
            label=t.label,
            created_at=t.created_at.isoformat() if t.created_at else "",
            expires_at=t.expires_at.isoformat() if t.expires_at else None,
            last_used_at=t.last_used_at.isoformat() if t.last_used_at else None,
            scopes=list(t.scopes or []),
            created_by=t.created_by,
            created_by_name=creators.get(t.created_by),
            is_service_account=bool(
                t.label and t.label.startswith(_SERVICE_ACCOUNT_LABEL_PREFIX)
            ),
        )
        for t in tokens
    ]


@router.delete("/api-tokens/{token_id}", status_code=204, tags=["auth"])
@limiter.limit(lambda: get_limit("auth"))
def revoke_api_token(
    request: Request,
    response: Response,
    token_id: int,
    current_user: Annotated[User, require_role("admin")],
    db: Session = Depends(get_db),
) -> None:
    """Revoke an API token. Any admin may revoke any token.

    Previously filtered on created_by == current_user.id, so an admin could not
    revoke a colleague's token even knowing its id — which makes credential
    revocation depend on the availability of one specific person.
    """
    api_token = db.get(APIToken, token_id)
    if not api_token:
        raise HTTPException(status_code=404, detail="API token not found")
    db.delete(api_token)
    db.commit()
```

Add `Query` to the `fastapi` import line and ensure `User` is imported in this module.

- [ ] **Step 5: Use the constant where the prefix is written**

In `create_service_account` (line ~478), replace the literal with the constant so one edit changes both:

```python
        label=f"{_SERVICE_ACCOUNT_LABEL_PREFIX}{payload.label or 'unnamed'}",
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest apps/backend/tests/api/test_api_tokens_admin.py -v`
Expected: PASS — 7 tests.

- [ ] **Step 7: Commit**

```bash
git add apps/backend/src/app/api/auth.py apps/backend/tests/api/test_api_tokens_admin.py
git commit -m "feat(auth): fleet-wide token inventory and cross-admin revocation (INC-14)"
```

---

## Task 4: B7 — token rotation

**Files:**
- Modify: `apps/backend/src/app/api/auth.py`
- Test: `apps/backend/tests/api/test_api_tokens_admin.py` (append)

**Interfaces:**
- Produces: `POST /auth/api-tokens/{id}/rotate` → `CreateAPITokenResponse`. Mints a replacement carrying the same label, scopes and expiry; deletes the old row; returns the new secret once.

- [ ] **Step 1: Write the failing tests**

Append to `apps/backend/tests/api/test_api_tokens_admin.py`:

```python
@pytest.mark.asyncio
async def test_rotation_issues_a_new_secret_and_kills_the_old_one(
    client, auth_headers, db_session, factories
):
    owner = factories.user(role="admin", email="rot@example.com")
    row = _token_for(db_session, owner, "ci-deploy", ["read:*"])
    old_id = row.id

    resp = await client.post(
        f"/api/v1/auth/api-tokens/{old_id}/rotate", headers=auth_headers
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["token"]
    assert body["id"] != old_id
    assert db_session.get(APIToken, old_id) is None, "the predecessor must be revoked"


@pytest.mark.asyncio
async def test_rotation_preserves_label_and_scopes(
    client, auth_headers, db_session, factories
):
    """Rotation is a credential change, not a permission change — a rotated
    token that silently gained or lost access would be worse than no rotation."""
    owner = factories.user(role="admin", email="rot2@example.com")
    row = _token_for(db_session, owner, "collector", ["read:*", "write:telemetry"])

    resp = await client.post(
        f"/api/v1/auth/api-tokens/{row.id}/rotate", headers=auth_headers
    )

    new_row = db_session.get(APIToken, resp.json()["id"])
    assert new_row.label == "collector"
    assert new_row.scopes == ["read:*", "write:telemetry"]


@pytest.mark.asyncio
async def test_the_old_secret_stops_authenticating_after_rotation(
    client, auth_headers, db_session, factories
):
    owner = factories.user(role="admin", email="rot3@example.com")
    row = _token_for(db_session, owner, "ci-old", ["read:*"])
    old_headers = {"Authorization": "Bearer raw-ci-old"}

    assert (await client.get("/api/v1/hardware", headers=old_headers)).status_code == 200

    await client.post(f"/api/v1/auth/api-tokens/{row.id}/rotate", headers=auth_headers)

    assert (await client.get("/api/v1/hardware", headers=old_headers)).status_code == 401


@pytest.mark.asyncio
async def test_rotating_a_missing_token_is_404(client, auth_headers):
    resp = await client.post("/api/v1/auth/api-tokens/999999/rotate", headers=auth_headers)
    assert resp.status_code == 404
```

If the third test fails only because the previous secret is still cached, that is `_session_cache_set` in `core/security.py` holding the old hash. Invalidating that cache entry on rotation is part of the fix, not a test problem — a revoked credential that keeps working until a cache expires is a real defect.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest apps/backend/tests/api/test_api_tokens_admin.py -k rotat -v`
Expected: FAIL — 404, the route does not exist.

- [ ] **Step 3: Add the route**

In `apps/backend/src/app/api/auth.py`, after `revoke_api_token`:

```python
@router.post(
    "/api-tokens/{token_id}/rotate", response_model=CreateAPITokenResponse, tags=["auth"]
)
@limiter.limit(lambda: get_limit("auth"))
def rotate_api_token(
    request: Request,
    response: Response,
    token_id: int,
    current_user: Annotated[User, require_role("admin")],
    db: Session = Depends(get_db),
) -> CreateAPITokenResponse:
    """Replace a token's secret, keeping its label, scopes and expiry.

    SRV-06 lists rotation alongside creation, least privilege, revocation and
    expiry; only rotation had no endpoint, so the only way to change a leaked
    secret was to delete it and hand-rebuild an equivalent — which loses the
    scopes if whoever does it does not remember them.

    Deliberately NOT an overlap window like the agent server key: an API token
    has exactly one holder, who is standing in front of the new secret when it
    is issued, so there is nothing to converge. The predecessor dies here.
    """
    old = db.get(APIToken, token_id)
    if not old:
        raise HTTPException(status_code=404, detail="API token not found")

    raw_token = secrets.token_urlsafe(32)
    replacement = APIToken(
        token_hash=create_salted_api_token_hash(raw_token),
        label=old.label,
        created_by=current_user.id,
        scopes=list(old.scopes or []),
        expires_at=old.expires_at,
    )
    db.add(replacement)
    db.delete(old)
    db.commit()
    db.refresh(replacement)

    # The resolver caches token_hash -> (uid, scopes) for the process lifetime
    # (core/security.py's _session_cache_set). Without this, the rotated-away
    # secret keeps authenticating until that entry ages out, which would make
    # rotation useless for its main purpose — responding to a leak.
    from app.core.security import invalidate_token_cache

    invalidate_token_cache()

    return CreateAPITokenResponse(
        token=raw_token,
        id=replacement.id,
        label=replacement.label,
        expires_at=replacement.expires_at.isoformat() if replacement.expires_at else None,
    )
```

- [ ] **Step 4: Add the cache invalidation helper**

Inspect `core/security.py`'s session cache (`_session_cache_get` / `_session_cache_set`) and add a matching clear function beside them:

```python
def invalidate_token_cache() -> None:
    """Drop every cached token resolution.

    Called when a token is rotated or revoked. Coarse on purpose: the cache is
    keyed by a hash of the raw secret, which the rotation path does not have
    for the token it is retiring, and a token cache is small enough that
    rebuilding it costs far less than a revoked credential that still works.
    """
    _SESSION_CACHE.clear()
```

Use whatever the cache structure is actually named in that module — do not introduce a second cache. Call it from `revoke_api_token` too, for the same reason.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest apps/backend/tests/api/test_api_tokens_admin.py -v`
Expected: PASS — 11 tests.

- [ ] **Step 6: Run the whole backend suite**

Run: `pytest apps/backend/tests -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/backend/src/app/api/auth.py apps/backend/src/app/core/security.py apps/backend/tests/api/test_api_tokens_admin.py
git commit -m "feat(auth): add API token rotation (INC-14, SRV-06)"
```

---

## Task 5: Frontend API module

**Files:**
- Create: `apps/frontend/src/api/tokens.js`
- Test: `apps/frontend/src/__tests__/tokens-api.test.js`

- [ ] **Step 1: Write the failing test**

Create `apps/frontend/src/__tests__/tokens-api.test.js`:

```javascript
import { describe, expect, it, vi, beforeEach } from 'vitest';

vi.mock('../api/client.jsx', () => ({
  default: {
    get: vi.fn(() => Promise.resolve({ data: [] })),
    post: vi.fn(() => Promise.resolve({ data: {} })),
    delete: vi.fn(() => Promise.resolve({ data: null })),
  },
}));

import client from '../api/client.jsx';
import {
  listTokens,
  createToken,
  createServiceAccount,
  rotateToken,
  revokeToken,
  getScopeCatalog,
} from '../api/tokens';

beforeEach(() => vi.clearAllMocks());

describe('tokens api module', () => {
  it('lists the caller’s own tokens by default', () => {
    listTokens();
    expect(client.get).toHaveBeenCalledWith('/auth/api-tokens', { params: { scope: 'mine' } });
  });

  it('lists the whole install when asked', () => {
    listTokens('all');
    expect(client.get).toHaveBeenCalledWith('/auth/api-tokens', { params: { scope: 'all' } });
  });

  it('creates a token with scopes', () => {
    createToken({ label: 'ci', expires_at: null, scopes: ['read:*'] });
    expect(client.post).toHaveBeenCalledWith('/auth/api-token', {
      label: 'ci',
      expires_at: null,
      scopes: ['read:*'],
    });
  });

  it('creates a service account through its own endpoint', () => {
    createServiceAccount({ label: 'collector', expires_at: null, scopes: ['read:*'] });
    expect(client.post).toHaveBeenCalledWith('/auth/service-account', {
      label: 'collector',
      expires_at: null,
      scopes: ['read:*'],
    });
  });

  it('rotates and revokes by id', () => {
    rotateToken(4);
    expect(client.post).toHaveBeenCalledWith('/auth/api-tokens/4/rotate');
    revokeToken(4);
    expect(client.delete).toHaveBeenCalledWith('/auth/api-tokens/4');
  });

  it('reads the scope catalog from the server', () => {
    getScopeCatalog();
    expect(client.get).toHaveBeenCalledWith('/auth/scopes');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm --prefix apps/frontend test -- src/__tests__/tokens-api.test.js`
Expected: FAIL — cannot resolve `../api/tokens`.

- [ ] **Step 3: Write minimal implementation**

Create `apps/frontend/src/api/tokens.js`:

```javascript
import client from './client.jsx';

// INC-14. Every route here is require_role("admin").

// scope: 'mine' (default, unchanged for existing callers) | 'all' (install-wide).
export const listTokens = (scope = 'mine') =>
  client.get('/auth/api-tokens', { params: { scope } });

// The scope vocabulary and the presets come from the server so the picker can
// never offer something validate_scopes rejects or enforcement ignores.
export const getScopeCatalog = () => client.get('/auth/scopes');

// A plain token authenticates as its creating user, restricted by its scopes.
export const createToken = ({ label, expires_at, scopes }) =>
  client.post('/auth/api-token', { label, expires_at, scopes });

// A service account is a JWT with user_id=0 — no owning user at all. Prefer it
// for machine credentials that should outlive the person who created them.
export const createServiceAccount = ({ label, expires_at, scopes }) =>
  client.post('/auth/service-account', { label, expires_at, scopes });

// Returns a new secret once; the predecessor stops working immediately.
export const rotateToken = (id) => client.post(`/auth/api-tokens/${id}/rotate`);
export const revokeToken = (id) => client.delete(`/auth/api-tokens/${id}`);
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm --prefix apps/frontend test -- src/__tests__/tokens-api.test.js`
Expected: PASS — 6 tests.

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/src/api/tokens.js apps/frontend/src/__tests__/tokens-api.test.js
git commit -m "feat(tokens): add token administration API module (INC-14)"
```

---

## Task 6: AccessTokensManager

**Files:**
- Create: `apps/frontend/src/components/settings/AccessTokensManager.jsx`
- Test: `apps/frontend/src/__tests__/access-tokens-manager.test.jsx`

- [ ] **Step 1: Write the failing test**

Create `apps/frontend/src/__tests__/access-tokens-manager.test.jsx`:

```jsx
import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';

const mockToast = { success: vi.fn(), error: vi.fn(), info: vi.fn() };
vi.mock('../components/common/Toast', () => ({ useToast: () => mockToast }));

vi.mock('../api/tokens', () => ({
  listTokens: vi.fn(),
  getScopeCatalog: vi.fn(),
  createToken: vi.fn(),
  createServiceAccount: vi.fn(),
  rotateToken: vi.fn(),
  revokeToken: vi.fn(),
}));

import {
  listTokens,
  getScopeCatalog,
  createToken,
  rotateToken,
  revokeToken,
} from '../api/tokens';
import AccessTokensManager from '../components/settings/AccessTokensManager.jsx';

const CATALOG = {
  scopes: [
    { scope: 'read:*', description: 'Read every resource.' },
    { scope: '*:*', description: 'Unrestricted.' },
  ],
  presets: [
    { key: 'read_only', label: 'Read-only', description: 'Read, change nothing.', scopes: ['read:*'] },
    { key: 'full_access', label: 'Full access', description: 'Unrestricted.', scopes: ['*:*'] },
  ],
};

const TOKENS = [
  {
    id: 1,
    label: 'ci-deploy',
    created_at: '2026-08-01T00:00:00Z',
    expires_at: null,
    last_used_at: '2026-08-24T09:00:00Z',
    scopes: ['read:*'],
    created_by: 1,
    created_by_name: 'shawnji',
    is_service_account: true,
  },
  {
    id: 2,
    label: 'legacy-job',
    created_at: '2025-01-01T00:00:00Z',
    expires_at: null,
    last_used_at: null,
    scopes: [],
    created_by: 1,
    created_by_name: 'shawnji',
    is_service_account: false,
  },
];

beforeEach(() => {
  vi.clearAllMocks();
  listTokens.mockResolvedValue({ data: TOKENS });
  getScopeCatalog.mockResolvedValue({ data: CATALOG });
});

describe('AccessTokensManager', () => {
  it('lists tokens with their scopes and creator', async () => {
    render(<AccessTokensManager />);
    await waitFor(() => expect(screen.getByText('ci-deploy')).toBeInTheDocument());
    expect(screen.getByText('read:*')).toBeInTheDocument();
    expect(screen.getAllByText('shawnji').length).toBeGreaterThan(0);
  });

  it('marks a legacy scope-less token as inheriting its creator', async () => {
    render(<AccessTokensManager />);
    await waitFor(() => expect(screen.getByText('legacy-job')).toBeInTheDocument());
    expect(screen.getByText(/inherits creator/i)).toBeInTheDocument();
  });

  it('distinguishes service accounts by the flag, not the label', async () => {
    render(<AccessTokensManager />);
    await waitFor(() => expect(screen.getByTestId('token-row-1')).toHaveTextContent(/service account/i));
    expect(screen.getByTestId('token-row-2')).toHaveTextContent(/user token/i);
  });

  it('switches between own and install-wide inventory', async () => {
    render(<AccessTokensManager />);
    await waitFor(() => expect(listTokens).toHaveBeenCalledWith('mine'));

    fireEvent.change(screen.getByLabelText(/inventory/i), { target: { value: 'all' } });

    await waitFor(() => expect(listTokens).toHaveBeenLastCalledWith('all'));
  });

  it('offers presets from the server, never a hardcoded list', async () => {
    render(<AccessTokensManager />);
    await waitFor(() => expect(getScopeCatalog).toHaveBeenCalled());
    expect(screen.getByLabelText('Read-only')).toBeInTheDocument();
    expect(screen.getByLabelText('Full access')).toBeInTheDocument();
  });

  it('creates a token with the selected preset’s scopes', async () => {
    createToken.mockResolvedValue({ data: { id: 9, token: 'cb_secret', label: 'ci' } });

    render(<AccessTokensManager />);
    await waitFor(() => expect(screen.getByLabelText('Read-only')).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText(/^label$/i), { target: { value: 'ci' } });
    fireEvent.click(screen.getByLabelText('Full access'));
    fireEvent.click(screen.getByRole('button', { name: /create token/i }));

    await waitFor(() =>
      expect(createToken).toHaveBeenCalledWith(
        expect.objectContaining({ label: 'ci', scopes: ['*:*'] })
      )
    );
  });

  it('shows the secret once and hides it permanently after acknowledgement', async () => {
    createToken.mockResolvedValue({ data: { id: 9, token: 'cb_secret_value', label: 'ci' } });

    render(<AccessTokensManager />);
    await waitFor(() => expect(screen.getByLabelText('Read-only')).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/^label$/i), { target: { value: 'ci' } });
    fireEvent.click(screen.getByRole('button', { name: /create token/i }));

    await waitFor(() => expect(screen.getByText('cb_secret_value')).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: /stored it/i }));

    await waitFor(() => expect(screen.queryByText('cb_secret_value')).not.toBeInTheDocument());
    // And it must not come back — there is nowhere to retrieve it from.
    fireEvent.change(screen.getByLabelText(/inventory/i), { target: { value: 'all' } });
    await waitFor(() => expect(listTokens).toHaveBeenLastCalledWith('all'));
    expect(screen.queryByText('cb_secret_value')).not.toBeInTheDocument();
  });

  it('requires the token’s own label typed before revoking', async () => {
    revokeToken.mockResolvedValue({ data: null });

    render(<AccessTokensManager />);
    await waitFor(() => expect(screen.getByTestId('token-row-1')).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: 'Revoke ci-deploy' }));
    fireEvent.click(screen.getByRole('button', { name: /^confirm$/i }));
    expect(revokeToken).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText(/type ci-deploy to confirm/i), {
      target: { value: 'ci-deploy' },
    });
    fireEvent.click(screen.getByRole('button', { name: /^confirm$/i }));

    await waitFor(() => expect(revokeToken).toHaveBeenCalledWith(1));
  });

  it('reveals the replacement secret after a rotation', async () => {
    rotateToken.mockResolvedValue({ data: { id: 10, token: 'cb_rotated', label: 'ci-deploy' } });

    render(<AccessTokensManager />);
    await waitFor(() => expect(screen.getByTestId('token-row-1')).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: 'Rotate ci-deploy' }));
    fireEvent.change(screen.getByLabelText(/type ci-deploy to confirm/i), {
      target: { value: 'ci-deploy' },
    });
    fireEvent.click(screen.getByRole('button', { name: /^confirm$/i }));

    await waitFor(() => expect(screen.getByText('cb_rotated')).toBeInTheDocument());
  });

  it('renders an error with retry rather than an empty inventory', async () => {
    listTokens.mockRejectedValue(new Error('boom'));

    render(<AccessTokensManager />);

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm --prefix apps/frontend test -- src/__tests__/access-tokens-manager.test.jsx`
Expected: FAIL — cannot resolve the component.

- [ ] **Step 3: Write minimal implementation**

Create `apps/frontend/src/components/settings/AccessTokensManager.jsx`:

```jsx
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  createServiceAccount,
  createToken,
  getScopeCatalog,
  listTokens,
  revokeToken,
  rotateToken,
} from '../../api/tokens';
import HighRiskConfirmDialog from '../common/HighRiskConfirmDialog';
import { useToast } from '../common/Toast';

const EXPIRY_OPTIONS = [
  { label: '90 days', days: 90 },
  { label: '1 year', days: 365 },
  { label: 'Never', days: null },
];

function expiryToIso(days) {
  if (days == null) return null;
  return new Date(Date.now() + days * 86400000).toISOString();
}

function formatWhen(iso) {
  if (!iso) return 'never';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? 'never' : d.toLocaleDateString();
}

/**
 * Install-wide API token administration (INC-14).
 *
 * The presets come from GET /auth/scopes rather than being written here, so the
 * picker cannot offer something the server rejects. They name what B1 actually
 * enforces — read / write / admin — not a per-resource matrix, because
 * require_scope guards only two distinct checks in the backend and a finer
 * picker would imply distinctions nothing honours.
 */
function AccessTokensManager() {
  const toast = useToast();
  const [scope, setScope] = useState('mine');
  const [tokens, setTokens] = useState([]);
  const [catalog, setCatalog] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const [label, setLabel] = useState('');
  const [expiryDays, setExpiryDays] = useState(90);
  const [presetKey, setPresetKey] = useState(null);
  const [asServiceAccount, setAsServiceAccount] = useState(false);
  const [creating, setCreating] = useState(false);

  // Held in state only between issue and acknowledgement. There is nowhere to
  // retrieve it from afterwards, so it must not survive dismissal.
  const [revealed, setRevealed] = useState(null);
  const [confirm, setConfirm] = useState(null); // {mode: 'revoke'|'rotate', token}
  const [busy, setBusy] = useState(false);
  const [confirmError, setConfirmError] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [list, cat] = await Promise.all([listTokens(scope), getScopeCatalog()]);
      setTokens(list.data || []);
      setCatalog(cat.data);
      setPresetKey((current) => current ?? cat.data?.presets?.[0]?.key ?? null);
    } catch (err) {
      setError(err?.userMessage || 'Could not load API tokens.');
    } finally {
      setLoading(false);
    }
  }, [scope]);

  useEffect(() => {
    load();
  }, [load]);

  const presets = catalog?.presets || [];
  const selectedPreset = useMemo(
    () => presets.find((p) => p.key === presetKey) || presets[0],
    [presets, presetKey]
  );

  const handleCreate = useCallback(async () => {
    if (!selectedPreset) return;
    setCreating(true);
    try {
      const payload = {
        label: label.trim() || null,
        expires_at: expiryToIso(expiryDays),
        scopes: selectedPreset.scopes,
      };
      const fn = asServiceAccount ? createServiceAccount : createToken;
      const res = await fn(payload);
      setRevealed(res.data);
      setLabel('');
      toast.success('Token created.');
      await load();
    } catch (err) {
      toast.error(err?.userMessage || 'Could not create the token.');
    } finally {
      setCreating(false);
    }
  }, [selectedPreset, label, expiryDays, asServiceAccount, toast, load]);

  const handleConfirmed = useCallback(async () => {
    if (!confirm) return;
    setBusy(true);
    setConfirmError(null);
    try {
      if (confirm.mode === 'revoke') {
        await revokeToken(confirm.token.id);
        toast.success('Token revoked.');
      } else {
        const res = await rotateToken(confirm.token.id);
        setRevealed(res.data);
        toast.success('Token rotated. The previous secret no longer works.');
      }
      setConfirm(null);
      await load();
    } catch (err) {
      setConfirmError(err?.userMessage || 'Operation failed.');
    } finally {
      setBusy(false);
    }
  }, [confirm, toast, load]);

  if (loading) return <p>Loading…</p>;

  if (error) {
    return (
      <div role="alert">
        <p>{error}</p>
        <button type="button" className="btn btn-sm" onClick={load}>
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className="access-tokens">
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
        <label htmlFor="token-scope">Inventory</label>
        <select id="token-scope" value={scope} onChange={(e) => setScope(e.target.value)}>
          <option value="mine">My tokens</option>
          <option value="all">All tokens</option>
        </select>
      </div>

      {revealed && (
        <div className="access-tokens__reveal">
          <strong>Copy this now. It cannot be shown again.</strong>
          <code>{revealed.token}</code>
          <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
            <button
              type="button"
              className="btn btn-sm"
              onClick={() => navigator.clipboard?.writeText(revealed.token)}
            >
              Copy
            </button>
            <button
              type="button"
              className="btn btn-sm btn-primary"
              onClick={() => setRevealed(null)}
            >
              I&apos;ve stored it
            </button>
          </div>
        </div>
      )}

      <table className="entity-table">
        <thead>
          <tr>
            <th>Label</th>
            <th>Type</th>
            <th>Scopes</th>
            <th>Created by</th>
            <th>Expires</th>
            <th>Last used</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {tokens.map((t) => (
            <tr key={t.id} data-testid={`token-row-${t.id}`}>
              <td>{t.label || `token #${t.id}`}</td>
              <td>{t.is_service_account ? 'service account' : 'user token'}</td>
              <td>
                {t.scopes && t.scopes.length > 0 ? (
                  t.scopes.map((s) => (
                    <span key={s} className="access-tokens__chip">
                      {s}
                    </span>
                  ))
                ) : (
                  // A row stored before scopes were settable. It authenticates
                  // as its creator — see the back-compat rule in core/security.
                  <span className="access-tokens__chip">inherits creator</span>
                )}
              </td>
              <td>{t.created_by_name || '—'}</td>
              <td>{formatWhen(t.expires_at)}</td>
              <td>{t.last_used_at ? formatWhen(t.last_used_at) : 'never'}</td>
              <td>
                <button
                  type="button"
                  className="btn btn-sm"
                  onClick={() => {
                    setConfirmError(null);
                    setConfirm({ mode: 'rotate', token: t });
                  }}
                >
                  Rotate {t.label}
                </button>
                <button
                  type="button"
                  className="btn btn-sm btn-danger"
                  onClick={() => {
                    setConfirmError(null);
                    setConfirm({ mode: 'revoke', token: t });
                  }}
                >
                  Revoke {t.label}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <fieldset style={{ marginTop: 16 }}>
        <legend>Create token</legend>

        <label htmlFor="token-label">Label</label>
        <input id="token-label" value={label} onChange={(e) => setLabel(e.target.value)} />

        <label htmlFor="token-expiry">Expires</label>
        <select
          id="token-expiry"
          value={String(expiryDays)}
          onChange={(e) => setExpiryDays(e.target.value === 'null' ? null : Number(e.target.value))}
        >
          {EXPIRY_OPTIONS.map((o) => (
            <option key={o.label} value={String(o.days)}>
              {o.label}
            </option>
          ))}
        </select>

        <div role="radiogroup" aria-label="Access level">
          {presets.map((p) => (
            <div key={p.key}>
              <input
                type="radio"
                id={`preset-${p.key}`}
                name="token-preset"
                checked={presetKey === p.key}
                onChange={() => setPresetKey(p.key)}
              />
              <label htmlFor={`preset-${p.key}`}>{p.label}</label>
              <span className="access-tokens__hint">
                {p.description} ({p.scopes.join(', ')})
              </span>
            </div>
          ))}
        </div>

        <label>
          <input
            type="checkbox"
            checked={asServiceAccount}
            onChange={(e) => setAsServiceAccount(e.target.checked)}
          />
          Create as a service account (no owning user — outlives its creator)
        </label>

        <button
          type="button"
          className="btn btn-sm btn-primary"
          disabled={creating || !selectedPreset}
          onClick={handleCreate}
        >
          {creating ? 'Creating…' : 'Create token'}
        </button>
      </fieldset>

      <HighRiskConfirmDialog
        open={confirm != null}
        title={confirm?.mode === 'rotate' ? 'Rotate this token' : 'Revoke this token'}
        body={
          confirm?.mode === 'rotate' ? (
            <p>
              A new secret is issued and shown once. The current secret stops working immediately —
              anything still using it will start failing until it is updated.
            </p>
          ) : (
            <p>
              The token stops working immediately and cannot be restored. Anything using it will
              start failing.
            </p>
          )
        }
        // The token's own label is what stops you acting on the adjacent row.
        confirmPhrase={confirm?.token?.label || ''}
        busy={busy}
        error={confirmError}
        onConfirm={handleConfirmed}
        onCancel={() => setConfirm(null)}
      />
    </div>
  );
}

export default AccessTokensManager;
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm --prefix apps/frontend test -- src/__tests__/access-tokens-manager.test.jsx`
Expected: PASS — 11 tests.

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/src/components/settings/AccessTokensManager.jsx apps/frontend/src/__tests__/access-tokens-manager.test.jsx
git commit -m "feat(tokens): add access token administration UI (INC-14)"
```

---

## Task 7: Mount in Settings, retire the duplicate create form

**Files:**
- Modify: `apps/frontend/src/pages/SettingsPage.jsx`
- Modify: `apps/frontend/src/components/auth/ProfileModal.jsx`

- [ ] **Step 1: Mount the manager**

In `apps/frontend/src/pages/SettingsPage.jsx`, add the import beside the other component imports:

```javascript
import AccessTokensManager from '../components/settings/AccessTokensManager';
```

Inside the Security tab's `settings-sections-grid` (opens at line ~1366), add one section as the last child of that grid:

```jsx
                {isAdmin && (
                  <SettingSection title="Access Tokens">
                    <AccessTokensManager />
                  </SettingSection>
                )}
```

- [ ] **Step 2: Remove the duplicate create form from ProfileModal**

`ProfileModal.jsx`'s `apiTokens` tab (lines ~955-1100) currently both lists and creates. The create half is now a second path that cannot set scopes, which after Task 2 would mint tokens with the creator's full scope set from a form that never says so.

Remove from that tab:

- the create form block (label input and the "Create API token" button),
- the `apiTokenNewLabel`, `apiTokenCreating`, and `apiTokenOneTime` state and their handlers,
- the one-time reveal block.

Keep the listing and the per-row delete. Add above the list:

```jsx
            <p className="profile-modal__hint">
              These are the API tokens you created. To create, rotate, or review every token on
              this install, go to Settings → Security → Access Tokens.
            </p>
```

Search the file for each removed identifier afterwards and delete anything left orphaned:

```bash
grep -n "apiTokenOneTime\|apiTokenNewLabel\|apiTokenCreating" apps/frontend/src/components/auth/ProfileModal.jsx
```

Expected: no output when the removal is complete.

- [ ] **Step 3: Verify the file shrank**

```bash
wc -l apps/frontend/src/components/auth/ProfileModal.jsx
```

Expected: meaningfully fewer than 1130 lines. If it grew, the create form was duplicated rather than moved.

- [ ] **Step 4: Run tests and lint**

Run: `npm --prefix apps/frontend test`
Run: `npm --prefix apps/frontend run lint`
Expected: PASS. If an existing `ProfileModal` test asserts on the create form, update it to assert the pointer text instead — the behaviour intentionally moved.

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/src/pages/SettingsPage.jsx apps/frontend/src/components/auth/ProfileModal.jsx
git commit -m "feat(tokens): mount token admin in Settings and retire the duplicate create form (INC-14)"
```

---

## Task 8: Documentation, register, and security audit

- [ ] **Step 1: Write the token documentation**

Create `docs/api-tokens.md`:

```markdown
# API Tokens and Service Accounts

**Where:** Settings → Security → Access Tokens. Admin only.

## Two kinds of credential

| | User token | Service account |
|---|---|---|
| Authenticates as | The admin who created it | No user — a dedicated machine identity |
| Survives its creator's account | No | Yes |
| Use for | Personal CLI and scripting | CI, collectors, long-lived automation |

Prefer a service account for anything that should keep working after the person
who set it up leaves.

## Scopes

A token's scopes limit what it can do, on **every** route — both the
scope-guarded ones and the role-guarded ones. A read-only token cannot change
settings, users, or backups.

| Preset | Scopes | Can |
|---|---|---|
| Read-only | `read:*` | Read everything, change nothing |
| Telemetry ingest | `read:*`, `write:telemetry` | Read, plus submit telemetry samples |
| Read and write | `read:*`, `write:*` | Create and modify resources; not administer the server |
| Full access | `*:*` | Everything, including settings, users and the vault |

Grant the narrowest preset that works. **Full access** is `*:*` rather than
`admin:*` deliberately: administrative scope does not imply read scope, so a
token holding only `admin:*` would be refused on ordinary read routes.

## Tokens created before scopes existed

A token created before scopes were settable is shown as **inherits creator**.
It carries whatever access its creating user has, which is how it has always
behaved. Rotating it does not change that; create a replacement with an
explicit preset if you want it narrowed.

## Rotation and revocation

**Rotate** issues a new secret and invalidates the old one immediately, keeping
the label, scopes and expiry. Use it when a secret may have leaked. There is no
overlap window — a token has one holder, and you are standing in front of the
new secret when it is issued, so update the consumer straight away.

**Revoke** deletes the token. Any admin can revoke any token on the install,
including one another admin created — credential revocation should never depend
on one person being available.

Both ask you to type the token's own label. That is what prevents acting on the
row next to the one you meant.

## The secret is shown once

There is no way to retrieve it afterwards. If it is lost, rotate the token.
```

- [ ] **Step 2: Add the nav entry**

In `mkdocs.yml`, after the `Authentication & Access` entry, with **six spaces** of indentation:

```yaml
      - API Tokens: api-tokens.md
```

Verify:

```bash
grep -n "api-tokens.md" mkdocs.yml
python3 -c "import yaml; yaml.safe_load(open('mkdocs.yml')); print('mkdocs.yml parses')"
```

- [ ] **Step 3: File the escalation finding in the security audit**

This is a privilege-escalation issue, not an incomplete feature, so it belongs in `docs/1.0.0-release-readiness-audit.md`. Add to its findings, matching that document's existing heading style:

```markdown
### Token scopes were not enforced on role-guarded routes

**Severity:** High. **Status:** Fixed (see INC-14 / spec 10 §7.2 B1).

`require_scope` was used on exactly two distinct checks in the backend —
`("read", "*")` and `("write", "telemetry")`. Every other route used
`require_role`, which ignored token scopes entirely: a static API token resolved
to its creating user (`core/security.py:523`), and a service-account JWT
returned `_service_user()` with `is_superuser=True` before any scope check ran
(`core/rbac.py:141`).

A token therefore had full administrative access to settings, users, backups,
the vault and audit-chain repair regardless of the scopes it was issued with,
while INC-04 simultaneously made it 403 on the handful of scope-guarded routes.

`require_role` now maps the required role to a scope check via
`ROLE_SCOPE_REQUIREMENT` and refuses a token that does not hold it. Tokens
stored with `scopes == []` — every token created through the UI before this —
are treated as unscoped and inherit their creator, so deployed installs are
unaffected by the upgrade. That back-compat rule is applied to static tokens
only: a service-account JWT has no real creator, and inheriting there would
promote an empty-scoped service account to superuser.
```

- [ ] **Step 4: Update the register**

Set INC-14 to `Resolved` **and INC-04 to `Resolved`**, update `**Last updated:**`, and replace the INC-14 body with:

```markdown
### INC-14. Scoped service accounts are API-only; token admin is incomplete

**Resolved**, together with INC-04.

The blocker had to be fixed before any UI could honestly exist. `require_scope`
guards exactly two distinct checks in the backend; everything else is
`require_role`, which ignored token scopes — a static token resolved to its
creating admin and a service-account JWT returned a superuser before any scope
check ran. Every token was therefore a superuser on every role-guarded route
regardless of its scopes, while INC-04 made those same tokens 403 on the
scope-guarded ones. A scope picker over that backend would have labelled a token
"read-only" while it could delete every user.

- `core/rbac.py` — `require_role` now maps the required role to a scope through
  `ROLE_SCOPE_REQUIREMENT`, mirroring `ROLE_DEFAULT_SCOPES` so the two cannot
  describe different ladders, and refuses a token lacking it. It uses the
  *lowest* accepted role, matching `require_role`'s own `min(allowed_ranks)`.
- `core/security.py` — a stored `scopes == []` now means "unscoped, inherit the
  creator" rather than "no scopes". `APIToken.scopes` is
  `mapped_column(JSONB, default=list)`, so every UI-created token stored `[]`,
  and `_normalise_token_scopes` returning `()` for it **is** INC-04: that is
  what made them 403 everywhere. Applied at the static-token call site, not
  inside `_normalise_token_scopes`, because the `uid == 0` branch calls it too
  and a service account has no real creator — inheriting there would promote an
  empty-scoped service account to superuser. Both directions are tested.
- `core/token_scopes.py` — new, the only place that decides what a token may be
  granted. `GET /auth/scopes` serves it so the picker cannot drift from what
  `validate_scopes` accepts. Deliberately narrow: `ROLE_DEFAULT_SCOPES` has
  per-resource write scopes, but nothing enforces them, so offering
  `write:hardware` would imply granularity that does not exist. **Full access is
  `*:*`, not `admin:*`** — `has_scope` never treats admin as implying read, so
  an `admin:*` token would pass role gates and 403 on every read route.
- `api/auth.py` — `POST /auth/api-token` accepts scopes and defaults to the
  creator's effective scopes rather than `[]`; both create paths validate
  against the catalog and reject an empty list; `APITokenItem` carries scopes,
  creator, and an explicit `is_service_account` flag instead of the
  `"[Service Account] "` label prefix the UI would otherwise have parsed;
  `GET /auth/api-tokens?scope=all` gives the install-wide inventory that did not
  exist; `DELETE` dropped its `created_by` filter, which the register did not
  mention but which meant an admin could not revoke a peer's token even knowing
  its id; and `POST /auth/api-tokens/{id}/rotate` closes SRV-06's rotation gap.
  Rotation clears the token resolution cache — a revoked secret that keeps
  working until a cache ages out would defeat the point.
- `components/settings/AccessTokensManager.jsx` — inventory, create, rotate,
  revoke, and the one-time secret reveal, in Settings → Security. Presets come
  from the server. Rotate and revoke type the token's own label, which is what
  stops you acting on the adjacent row. `ProfileModal`'s tab keeps the personal
  list but lost its create form: two create paths that disagreed about scopes
  is the shape of this finding.

The privilege-escalation half is filed in
`docs/1.0.0-release-readiness-audit.md` as well — it is a security finding, not
an incomplete feature.

No migration: `APIToken.scopes` already existed and legacy `[]` rows are
reinterpreted on read.
```

And replace INC-04's body with:

```markdown
### INC-04. UI-created API tokens are authorized for nothing

**Resolved** as part of INC-14. `_normalise_token_scopes` returned `()` rather
than `None` for the `[]` that `mapped_column(JSONB, default=list)` stores, so
`require_scope` took the "token has scopes, none of them match" branch and
returned 403 on every scope-guarded router. `[]` now means "unscoped — inherit
the creator", which is what those tokens always effectively were, and
`POST /auth/api-token` accepts explicit scopes for new ones. See INC-14 for the
much larger problem found alongside it.
```

- [ ] **Step 5: Run everything**

Run: `pytest apps/backend/tests -q`
Run: `npm --prefix apps/frontend test`
Run: `npm --prefix apps/frontend run lint`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add docs/api-tokens.md mkdocs.yml docs/1.0.0-incomplete-features.md docs/1.0.0-release-readiness-audit.md
git commit -m "docs(tokens): document token administration and close INC-14 and INC-04"
```

---

## Self-Review

**Spec coverage (§7).** B1 ✓ Task 1. B2 ✓ Task 2. B3 ✓ Task 2. B4 ✓ Task 2. B5 ✓ Task 3. B6 ✓ Task 3 (list **and** delete). B7 ✓ Task 4. Inventory table with scopes, type, creator, expiry, last used ✓ Task 6. Create with label, expiry, server-fed preset picker ✓ Task 6. One-time reveal, acknowledged, never re-rendered ✓ Task 6 and asserted. Rotate/revoke via `HighRiskConfirmDialog` with the label as phrase ✓ Task 6. `ProfileModal` keeps the personal list, loses the create form ✓ Task 7. Preset honesty (§7.4) ✓ Task 2's catalog comment and Task 8's docs. Escalation filed to the security audit ✓ Task 8.

**Two things the spec did not anticipate**, both discovered by reading `has_scope` and the `uid == 0` branch, and both capable of silently producing the exact class of bug this slice closes: the `[]` back-compat rule must **not** apply to service-account JWTs, and Full access must be `*:*` rather than `admin:*`. Each has a dedicated test whose docstring explains it.

**Placeholder scan.** None. Where the code must match something already in the repo — the session cache's real name in `core/security.py`, whether `field_validator` is already imported, an existing `ProfileModal` test asserting the create form — the step names the exact check and the rule to apply.

**Type consistency.** `APITokenItem`'s fields are spelled identically in Task 3's model, Task 3's tests, and Task 6's rendering (`is_service_account`, `created_by_name`, `scopes`). `SCOPE_PRESETS` entries (`key`, `label`, `description`, `scopes`) match between Task 2's catalog, Task 2's tests, and Task 6's picker and its fixtures. `listTokens(scope)` takes the same `'mine' | 'all'` values as the route's `Query(..., pattern="^(mine|all)$")`. `HighRiskConfirmDialog`'s props match UI-2 Task 1 exactly; nothing here modifies that component.

**Execution note.** Task 1 changes authorization on every route in the application. Run the full backend suite at Task 1 Step 6 and read any failure carefully before touching it — a test that passed because a narrow-scoped token could reach an admin route was asserting the bug.
