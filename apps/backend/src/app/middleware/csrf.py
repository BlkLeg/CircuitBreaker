"""CSRF double-submit cookie middleware.

Verifies that state-mutating requests (POST/PUT/DELETE/PATCH) include an
X-CSRF-Token header whose value matches the cb_csrf cookie set at login.

Safe methods (GET, HEAD, OPTIONS) are exempt.
Requests without a cb_session cookie are exempt (unauthenticated calls
handled by auth layer).
"""

import hmac
import logging
from collections.abc import Awaitable, Callable
from typing import cast

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from app.core.auth_cookie import COOKIE_NAME, CSRF_COOKIE_NAME

_logger = logging.getLogger(__name__)

_MUTATING_METHODS = {"POST", "PUT", "DELETE", "PATCH"}

# Paths exempt from CSRF check (unauthenticated public endpoints)
_CSRF_EXEMPT_PREFIXES = (
    "/api/v1/auth/login",
    "/api/v1/auth/register",
    "/api/v1/auth/demo",
    "/api/v1/auth/accept-invite",
    "/api/v1/auth/vault-reset",
    "/api/v1/auth/force-change-password",
    "/api/v1/auth/mfa/verify",
    "/api/v1/health",
)


class CSRFMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.method not in _MUTATING_METHODS:
            return cast(Response, await call_next(request))

        # Only enforce CSRF when the session cookie is present (authenticated)
        if not request.cookies.get(COOKIE_NAME):
            return cast(Response, await call_next(request))

        # Exempt login-flow endpoints that establish the session
        path = request.url.path
        if any(path.startswith(p) for p in _CSRF_EXEMPT_PREFIXES):
            return cast(Response, await call_next(request))

        csrf_cookie = request.cookies.get(CSRF_COOKIE_NAME, "")
        csrf_header = request.headers.get("X-CSRF-Token", "")

        if not csrf_cookie or not csrf_header:
            _logger.warning(  # nosemgrep: python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure  # noqa: E501
                # Logs request path, HTTP method, and client IP — no credential data
                "CSRF check failed: missing token (path=%s method=%s ip=%s)",
                path,
                request.method,
                request.client.host if request.client else "unknown",
            )
            return JSONResponse(
                status_code=403,
                content={"detail": "CSRF token missing"},
            )

        if not hmac.compare_digest(csrf_cookie, csrf_header):
            _logger.warning(  # nosemgrep: python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure  # noqa: E501
                # Logs request path, HTTP method, and client IP — no credential data
                "CSRF check failed: token mismatch (path=%s method=%s ip=%s)",
                path,
                request.method,
                request.client.host if request.client else "unknown",
            )
            return JSONResponse(
                status_code=403,
                content={"detail": "CSRF token invalid"},
            )

        return cast(Response, await call_next(request))
