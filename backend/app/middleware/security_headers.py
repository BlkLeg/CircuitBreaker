"""Middleware that adds HTTP security headers to every response."""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.types import ASGIApp

# Content-Security-Policy for a self-hosted SPA served from the same origin.
# - default-src 'self': only load resources from the same origin by default.
# - script-src 'self' 'unsafe-inline': Vite bundles require inline scripts.
# - style-src 'self' 'unsafe-inline': component libraries use inline styles.
# - img-src 'self' data: https://www.gravatar.com: local assets + Gravatar avatars.
# - connect-src 'self': API calls to same origin only.
# - frame-ancestors 'none': equivalent to X-Frame-Options: DENY.
_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: https://www.gravatar.com; "
    # wss: is required so WebSocket connections work when the app is served
    # over HTTPS (a browser will block wss:// otherwise under strict CSP).
    "connect-src 'self' ws: wss:; "
    "frame-ancestors 'none';"
)

_SECURITY_HEADERS = {
    "Content-Security-Policy": _CSP,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        # WebSocket handshakes don't support these headers in the same way 
        # and BaseHTTPMiddleware can interfere with the handshake.
        if request.scope.get("type") == "websocket":
            return await call_next(request)
            
        response = await call_next(request)
        for header, value in _SECURITY_HEADERS.items():
            response.headers[header] = value
        return response
