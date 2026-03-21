"""Legacy CB_API_TOKEN middleware.

Rejects Bearer tokens that match the deprecated CB_API_TOKEN environment
variable.  If CB_LEGACY_AUTH=true is set, falls back to the old god-mode
behaviour (grants request.state.legacy_admin = True) as a rollback toggle.
"""

import hmac
import logging
import os

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

_logger = logging.getLogger(__name__)


class LegacyTokenMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        api_token = os.getenv("CB_API_TOKEN")
        if api_token and request.url.path.startswith("/api/"):
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                bearer = auth_header[7:]
                if bearer and hmac.compare_digest(bearer, api_token):
                    # CB_LEGACY_AUTH=true is the rollback feature flag
                    if os.getenv("CB_LEGACY_AUTH", "").lower() == "true":
                        _logger.warning(
                            "CB_LEGACY_AUTH rollback active — granting legacy admin. "
                            "Remove CB_LEGACY_AUTH and migrate to service accounts."
                        )
                        request.state.legacy_admin = True
                        return await call_next(request)
                    return JSONResponse(
                        status_code=401,
                        content={
                            "detail": (
                                "CB_API_TOKEN is deprecated. Migrate to service accounts "
                                "(POST /api/v1/auth/service-account). Set CB_LEGACY_AUTH=true "
                                "to temporarily restore old behaviour."
                            )
                        },
                    )

        return await call_next(request)
