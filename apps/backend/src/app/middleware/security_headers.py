"""Middleware that adds HTTP security headers to every response."""

from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' 'strict-dynamic'; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "img-src 'self' data: blob: https://www.gravatar.com "
    "https://secure.gravatar.com https://avatars.githubusercontent.com; "
    "connect-src 'self' ws: wss: https://geocoding-api.open-meteo.com https://api.open-meteo.com; "
    "frame-ancestors 'none';"
)

_HSTS = "max-age=63072000; includeSubDomains"

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
    """Return True when the request arrived over TLS or via a TLS-terminating proxy."""
    if request.url.scheme == "https":
        return True
    if request.headers.get("x-forwarded-proto", "").lower() == "https":
        return True
    return False


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
