"""Changing a user's role through the API left their stored scopes behind.

`PATCH /api/v1/admin/users/{id}` set `role`, `is_admin` and `is_superuser` and stopped
there. Every path that *creates* a user derives `scopes` from the role
(`admin_users.py:195,267`, `auth_service.py:507,685`), and the CLI's `set_user_role`
re-derives it on change (`scripts/cli_admin.py:640`) — the API was the one mutation
path that did not.

`effective_scopes` (core/rbac.py) returns `defaults | explicit` whenever `explicit` is
non-empty, so a stale explicit set can only ever widen the result, never narrow it. A
demoted admin therefore kept `admin:*`, `write:*` and `delete:*` and stayed authorized
for every write on the install, while `/admin/users` and their own profile both showed
"viewer".
"""

from __future__ import annotations

import json

import pytest

from app.core.rbac import effective_scopes, has_scope


@pytest.mark.asyncio
async def test_demoting_an_admin_drops_the_admin_scopes(
    client, auth_headers, factories, db_session
):
    target = factories.user(
        role="admin", scopes=json.dumps(["admin:*", "delete:*", "read:*", "write:*"])
    )
    db_session.commit()

    resp = await client.patch(
        f"/api/v1/admin/users/{target.id}", json={"role": "viewer"}, headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["role"] == "viewer"

    db_session.expire_all()
    scopes = effective_scopes(db_session.get(type(target), target.id))
    assert not has_scope(scopes, "write", "*"), f"demoted admin kept write: {sorted(scopes)}"
    assert not has_scope(scopes, "delete", "*"), f"demoted admin kept delete: {sorted(scopes)}"
    assert not has_scope(scopes, "admin", "*"), f"demoted admin kept admin: {sorted(scopes)}"


@pytest.mark.asyncio
async def test_promoting_a_viewer_grants_the_editor_scopes(
    client, auth_headers, factories, db_session
):
    """Re-deriving unconditionally repairs upgrades too.

    A viewer promoted to editor previously kept only `read:*` in the column. That was
    harmless — `effective_scopes` unions the role defaults in — but it left the column
    disagreeing with the role, which is the same rot in the other direction.
    """
    target = factories.user(role="viewer", scopes=json.dumps(["read:*"]))
    db_session.commit()

    resp = await client.patch(
        f"/api/v1/admin/users/{target.id}", json={"role": "editor"}, headers=auth_headers
    )
    assert resp.status_code == 200, resp.text

    db_session.expire_all()
    stored = json.loads(db_session.get(type(target), target.id).scopes or "[]")
    # The editor default set is per-resource writes rather than a `write:*` wildcard,
    # so the claim is that the column now grants writing at all, not any one string.
    assert any(sc.startswith("write:") for sc in stored), (
        f"promoted editor did not gain any write scope in the column: {stored}"
    )


@pytest.mark.asyncio
async def test_a_demoted_admin_is_refused_a_write(client, auth_headers, factories, db_session):
    """The consequence, asserted end to end rather than inferred from the column.

    The demotion runs first and the target logs in afterwards: logging in rewrites the
    shared client's `cb_csrf` cookie, which would fail CSRF on any later admin request.
    `require_write_auth` reads the user row on every request, so the order changes
    nothing about what is being proven — before the fix the stored scopes still carried
    `write:*` and this POST returned 201.
    """
    target = factories.user(
        role="admin", scopes=json.dumps(["admin:*", "delete:*", "read:*", "write:*"])
    )
    db_session.commit()

    demoted = await client.patch(
        f"/api/v1/admin/users/{target.id}", json={"role": "viewer"}, headers=auth_headers
    )
    assert demoted.status_code == 200, demoted.text

    login = await client.post(
        "/api/v1/auth/login",
        json={"email": target.email, "password": "TestPassword123!"},
    )
    assert login.status_code == 200, login.text
    headers = {
        "Authorization": f"Bearer {login.json()['token']}",
        "X-CSRF-Token": login.cookies.get("cb_csrf", "test-csrf-token"),
    }

    wrote = await client.post(
        "/api/v1/hardware", json={"name": "demoted-admin-should-not-create-this"}, headers=headers
    )
    assert wrote.status_code == 403, (
        f"a demoted admin created hardware with {wrote.status_code}; the role change "
        "must revoke the write"
    )
