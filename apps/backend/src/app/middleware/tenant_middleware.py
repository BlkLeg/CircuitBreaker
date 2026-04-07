"""Tenant middleware -- extracts tenant from JWT and sets app.current_tenant.

Sets the PostgreSQL session variable ``app.current_tenant`` on each request
so that Row-Level Security policies can enforce tenant isolation at the
database layer.

Resolution order (authenticated requests):

1. ``X-Tenant-ID`` header when the user is a member of that tenant
   (``tenant_members`` or ``users.tenant_id``).
2. JWT ``tenant_id`` claim when the user may access that tenant.
3. ``request.state.user.tenant_id`` when the auth stack has populated it.
4. ``users.tenant_id`` from the database for the session user.

Unauthenticated requests ignore ``X-Tenant-ID`` (header spoofing).
"""

from __future__ import annotations

import logging
from contextvars import ContextVar

from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

_logger = logging.getLogger(__name__)

current_tenant_id: ContextVar[int | None] = ContextVar("current_tenant_id", default=None)


def _coerce_positive_tenant_id(raw: str | None) -> int | None:
    if not raw or not str(raw).strip():
        return None
    try:
        tid = int(str(raw).strip(), 10)
    except ValueError:
        return None
    return tid if tid > 0 else None


def _user_may_use_tenant(db, user_id: int | None, tenant_id: int) -> bool:
    if user_id is None:
        return False
    if user_id == 0:
        return True
    from app.db.models import User, tenant_members

    hit = db.execute(
        select(tenant_members.c.tenant_id).where(
            tenant_members.c.user_id == user_id,
            tenant_members.c.tenant_id == tenant_id,
        )
    ).first()
    if hit:
        return True
    u = db.get(User, user_id)
    return bool(u and u.tenant_id == tenant_id)


class TenantMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        tenant_id: int | None = None

        try:
            from app.core.security import (
                _extract_token,
                decode_access_token,
                resolve_optional_user_id_sync,
            )
            from app.db.models import User
            from app.db.session import SessionLocal
            from app.services.settings_service import get_or_create_settings

            with SessionLocal() as db:
                uid = resolve_optional_user_id_sync(db, request)
                cfg = get_or_create_settings(db)
                secret = cfg.jwt_secret or None

                payload: dict = {}
                raw_token = _extract_token(request)
                if raw_token and secret:
                    try:
                        payload = decode_access_token(raw_token, secret=secret)
                    except Exception:
                        _logger.warning(
                            "TenantMiddleware: JWT decode failed (tenant claim unavailable)",
                            exc_info=True,
                        )

                header_tid = _coerce_positive_tenant_id(request.headers.get("x-tenant-id"))
                if header_tid is not None:
                    if uid is not None:
                        if _user_may_use_tenant(db, uid, header_tid):
                            tenant_id = header_tid
                        else:
                            _logger.warning(
                                "Ignoring X-Tenant-ID=%s: user_id=%s has no access",
                                header_tid,
                                uid,
                            )
                    else:
                        _logger.debug("Ignoring X-Tenant-ID: unauthenticated request")

                raw_claim = payload.get("tenant_id")
                claim_tid = (
                    _coerce_positive_tenant_id(str(raw_claim)) if raw_claim is not None else None
                )
                if tenant_id is None and claim_tid is not None:
                    if _user_may_use_tenant(db, uid, claim_tid):
                        tenant_id = claim_tid
                    elif uid is not None:
                        _logger.warning(
                            "Ignoring JWT tenant_id=%s: user_id=%s has no access",
                            claim_tid,
                            uid,
                        )

                if tenant_id is None:
                    user = getattr(request.state, "user", None)
                    if user is not None:
                        tid = getattr(user, "tenant_id", None)
                        if tid is not None:
                            tenant_id = int(tid) if not isinstance(tid, int) else tid

                if tenant_id is None and uid is not None and uid > 0:
                    u = db.get(User, uid)
                    if u and u.tenant_id is not None:
                        tenant_id = u.tenant_id

        except Exception:
            _logger.warning("TenantMiddleware: failed to resolve tenant context", exc_info=True)

        token = current_tenant_id.set(tenant_id)
        try:
            return await call_next(request)
        finally:
            current_tenant_id.reset(token)
