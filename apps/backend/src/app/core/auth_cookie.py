"""HttpOnly session cookie for auth (zero token leakage to JS)."""

import os
import secrets
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse, Response

COOKIE_NAME = "cb_session"
CSRF_COOKIE_NAME = "cb_csrf"  # Readable by JS — used for double-submit CSRF defense


def _cookie_params(request: Request, session_timeout_hours: int | None) -> dict[str, Any]:
    max_age = (session_timeout_hours or 24) * 3600
    secure = request.url.scheme == "https" if request.url else True
    return dict(
        max_age=max_age,
        httponly=True,
        secure=secure,
        samesite="strict",
        path="/",
    )


def set_auth_cookie_on_response(
    request: Request, response: Response, token: str, session_timeout_hours: int | None
) -> None:
    """Set the session cookie on an existing response (e.g. RedirectResponse)."""
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        **_cookie_params(request, session_timeout_hours),
    )


def auth_response_with_cookie(
    request: Request,
    token: str,
    body: dict,
    session_timeout_hours: int | None,
) -> Response:
    """Return a JSONResponse with the given body and Set-Cookie for the session token.

    Also sets a readable (non-httpOnly) CSRF token cookie for double-submit defense.
    """
    csrf_token = secrets.token_hex(32)
    response = JSONResponse(content=body)
    set_auth_cookie_on_response(request, response, token, session_timeout_hours)
    max_age = (session_timeout_hours or 24) * 3600
    secure = request.url.scheme == "https" if request.url else True
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=csrf_token,
        max_age=max_age,
        httponly=False,  # Must be readable by JS for double-submit CSRF pattern
        secure=secure,
        samesite="strict",
        path="/",
    )
    return response


def clear_auth_cookie_response(status_code: int = 204) -> Response:
    """Return a response that clears the session cookie (e.g. logout)."""
    response = Response(status_code=status_code)
    response.delete_cookie(key=COOKIE_NAME, path="/")
    return response


def token_from_websocket_scope(scope: dict) -> str | None:
    """Extract cb_session token from WebSocket handshake Cookie header."""
    for name, value in scope.get("headers", []):
        if name == b"cookie":
            cookie = value.decode("latin-1")
            for part in cookie.split(";"):
                part = part.strip()
                if part.startswith(COOKIE_NAME + "="):
                    return str(part[len(COOKIE_NAME) + 1 :].strip())
            return None
    return None


def is_websocket_secure(scope: dict) -> bool:
    """True if the WebSocket handshake is considered secure (e.g. X-Forwarded-Proto: https)."""
    for name, value in scope.get("headers", []):
        if name == b"x-forwarded-proto":
            return bool(value.decode("latin-1").strip().lower() == "https")
    return bool(scope.get("type") == "websocket" and (scope.get("scheme") or "ws") == "wss")


def ws_require_wss() -> bool:
    """True when CB_WS_REQUIRE_WSS is set so non-WSS connections must be rejected."""
    return os.environ.get("CB_WS_REQUIRE_WSS", "").strip().lower() in ("1", "true", "yes")
