"""Middleware that adds HTTP security headers to every response."""

from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from app.core.forwarded import forwarded_proto

_CSP = (
    "default-src 'self'; "
    # Not 'strict-dynamic': under CSP Level 3 it makes the browser ignore
    # 'self' and every host source in this directive, so a policy naming no
    # nonce and no hash allows no script at all. apps/frontend/index.html ships
    # a plain <script type="module"> with no nonce, and spa_fallback serves that
    # very file, so this header white-paged the SPA on every deployment where
    # the backend fronts the frontend itself. Matches the four nginx configs
    # verbatim — see test_the_backend_csp_matches_the_nginx_configs.
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "img-src 'self' data: blob: https://www.gravatar.com "
    "https://secure.gravatar.com https://avatars.githubusercontent.com; "
    "connect-src 'self' ws: wss: https://geocoding-api.open-meteo.com https://api.open-meteo.com; "
    "frame-ancestors 'none';"
)

_HSTS = "max-age=63072000; includeSubDomains; preload"

_PERMISSIONS_POLICY = (
    "camera=(), microphone=(), geolocation=(), "
    "payment=(), usb=(), magnetometer=(), gyroscope=(), accelerometer=()"
)

_SECURITY_HEADERS = {
    "Content-Security-Policy": _CSP,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": _PERMISSIONS_POLICY,
}


def _is_secure_request(request: Request) -> bool:
    """Return True when the request arrived over TLS or via a TLS-terminating proxy.

    The forwarded header is trusted only from a configured proxy: HSTS is a
    sticky, browser-persisted commitment, so letting any peer trigger it lets an
    attacker pin a host to https that may not serve it.
    """
    if request.url.scheme == "https":
        return True
    return forwarded_proto(request).lower() == "https"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.scope.get("type") == "websocket":
            return await call_next(request)

        response = await call_next(request)
        for header, value in _SECURITY_HEADERS.items():
            response.headers[header] = value

        if _is_secure_request(request):
            response.headers["Strict-Transport-Security"] = _HSTS

        return response
