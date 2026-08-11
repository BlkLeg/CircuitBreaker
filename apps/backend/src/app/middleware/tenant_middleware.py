"""Single-tenant compatibility middleware.

Circuit Breaker 1.0 intentionally does not support true multi-tenancy as a
security boundary. This middleware remains installed only to preserve imports
and reset the historical tenant ContextVar on every request.

Legacy tenant selectors such as ``X-Tenant-ID`` headers or JWT ``tenant_id``
claims are ignored. The database checkout hook consequently receives ``None``
and clears ``app.current_tenant`` instead of selecting tenant-scoped data.
"""

from __future__ import annotations

from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

current_tenant_id: ContextVar[int | None] = ContextVar("current_tenant_id", default=None)


class TenantMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        token = current_tenant_id.set(None)
        try:
            return await call_next(request)
        finally:
            current_tenant_id.reset(token)
