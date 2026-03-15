"""Tenant middleware -- extracts tenant from JWT and sets app.current_tenant.

Sets the PostgreSQL session variable ``app.current_tenant`` on each request
so that Row-Level Security policies can enforce tenant isolation at the
database layer.

The tenant_id is extracted from the JWT ``tenant_id`` claim.  If no claim
is present (e.g. unauthenticated endpoints, health checks), the variable
is reset to empty string which causes RLS policies to match no rows unless
the table has NULL-tenant rows.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

_logger = logging.getLogger(__name__)

current_tenant_id: ContextVar[int | None] = ContextVar("current_tenant_id", default=None)


class TenantMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        tenant_id: int | None = None

        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            try:
                import jwt as pyjwt

                from app.core.security import SESSION_AUDIENCE
                from app.db.session import get_db
                from app.services.settings_service import get_or_create_settings

                db = next(get_db())
                try:
                    cfg = get_or_create_settings(db)
                    if cfg.jwt_secret:
                        payload = pyjwt.decode(
                            auth_header.split(" ", 1)[1],
                            cfg.jwt_secret,
                            algorithms=["HS256"],
                            audience=[SESSION_AUDIENCE],
                        )
                        tenant_id = payload.get("tenant_id")
                finally:
                    db.close()
            except Exception:  # noqa: BLE001
                pass

        if tenant_id is None:
            user = getattr(request.state, "user", None)
            if user is not None:
                tenant_id = getattr(user, "tenant_id", None)

        token = current_tenant_id.set(tenant_id)
        try:
            return await call_next(request)
        finally:
            current_tenant_id.reset(token)
