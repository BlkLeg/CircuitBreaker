"""SEC-2B: v1 single-tenant contract tests."""

from __future__ import annotations

import pytest
from starlette.requests import Request
from starlette.responses import Response

from app.middleware.tenant_middleware import TenantMiddleware, current_tenant_id


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/tenants"),
        ("POST", "/api/v1/tenants"),
        ("GET", "/api/v1/tenants/1"),
        ("PATCH", "/api/v1/tenants/1"),
        ("DELETE", "/api/v1/tenants/1"),
        ("GET", "/api/v1/tenants/1/members"),
        ("POST", "/api/v1/tenants/1/members"),
        ("DELETE", "/api/v1/tenants/1/members/2"),
    ],
)
async def test_legacy_tenant_api_returns_stable_410(client, auth_headers, method, path):
    response = await client.request(method, path, headers=auth_headers, json={})

    assert response.status_code == 410
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "detail": (
            "True multi-tenancy is not supported in Circuit Breaker 1.0. "
            "Use separate deployments for separate trust boundaries."
        )
    }


@pytest.mark.asyncio
async def test_tenant_header_does_not_select_request_context():
    seen_tenant_ids: list[int | None] = []

    async def call_next(request: Request) -> Response:
        seen_tenant_ids.append(current_tenant_id.get(None))
        return Response(status_code=204)

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def app(_scope, _receive, _send) -> None:
        return None

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/hardware",
            "headers": [(b"x-tenant-id", b"123")],
            "query_string": b"",
            "server": ("testserver", 80),
            "scheme": "http",
            "client": ("127.0.0.1", 12345),
        },
        receive=receive,
    )

    response = await TenantMiddleware(app=app).dispatch(request, call_next)

    assert response.status_code == 204
    assert seen_tenant_ids == [None]


@pytest.mark.asyncio
async def test_upgraded_tenant_shaped_rows_remain_inert(client, db_session, factories):
    from app.core.security import create_token
    from app.db.models import Hardware, Tenant, User, tenant_members
    from app.services.settings_service import get_or_create_settings

    tenant_a = Tenant(name="upgraded-tenant-a")
    tenant_b = Tenant(name="upgraded-tenant-b")
    db_session.add_all([tenant_a, tenant_b])
    db_session.flush()
    user = factories.user(role="viewer", tenant_id=tenant_b.id)
    db_session.execute(
        tenant_members.insert().values(
            tenant_id=tenant_b.id,
            user_id=user.id,
            tenant_role="member",
        )
    )
    hardware = factories.hardware(tenant_id=tenant_a.id, ip_address="192.0.2.177")
    cfg = get_or_create_settings(db_session)
    token = create_token(
        user.id,
        cfg.jwt_secret,
        1,
        role="viewer",
        extra_claims={"tenant_id": tenant_a.id},
    )
    headers = {"Authorization": f"Bearer {token}"}

    listed = await client.get("/api/v1/hardware", headers=headers)
    assert listed.status_code == 200
    assert any(row["id"] == hardware.id for row in listed.json())

    gone = await client.get(
        f"/api/v1/tenants/{tenant_a.id}",
        headers={**headers, "X-Tenant-ID": str(tenant_a.id)},
    )
    assert gone.status_code == 410

    db_session.expire_all()
    assert db_session.get(Tenant, tenant_a.id) is not None
    assert db_session.get(Tenant, tenant_b.id) is not None
    assert db_session.get(User, user.id).tenant_id == tenant_b.id
    assert db_session.get(Hardware, hardware.id).tenant_id == tenant_a.id
    assert (
        db_session.execute(
            tenant_members.select().where(
                tenant_members.c.tenant_id == tenant_b.id,
                tenant_members.c.user_id == user.id,
            )
        ).first()
        is not None
    )
