"""Legacy CB_API_TOKEN middleware.

Intercepts Bearer tokens that match the CB_API_TOKEN environment variable
before FastAPI-Users processes them.  Sets request.state.legacy_admin = True
so downstream auth dependencies can grant admin access without a real user row.
"""

import os

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response


class LegacyTokenMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        api_token = os.getenv("CB_API_TOKEN")
        if api_token and request.url.path.startswith("/api/"):
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer ") and auth_header[7:] == api_token:
                request.state.legacy_admin = True
        return await call_next(request)
