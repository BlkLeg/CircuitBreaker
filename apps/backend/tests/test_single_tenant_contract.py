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
