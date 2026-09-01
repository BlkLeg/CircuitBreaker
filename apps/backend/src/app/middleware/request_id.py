"""Per-request correlation ID.

Mints or validates an `X-Request-ID` for every HTTP request, publishes it on a
contextvar so any module can read it without threading it through call
signatures, and attaches it to log records. This is the server half of
correlating a browser navigation to the backend work it caused — the frontend
mints its own ID and sends it inbound; this module is what makes that ID show
up in server logs and the response.

Deliberately separate from `LoggingMiddleware` (`middleware/logging_middleware.py`),
which is the mutating-request audit-log writer, not a request tracer.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Iterable
from contextvars import ContextVar, Token
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from starlette.types import ASGIApp, Message, Receive, Scope, Send

#: The current request's correlation ID, or `None` outside a request. Exported
#: so loggers, DB listeners (see `db/session.py`'s slow-query listener), and
#: any other module can read the current request's ID without it being passed
#: down through every call signature.
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

#: The header this middleware reads from an inbound request and sets on every
#: outgoing response.
REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID_HEADER_BYTES = b"x-request-id"  # ASGI scope/response headers are lower-cased

#: An inbound value is echoed back only when it satisfies this: at most 64
#: characters from a safe charset. Anything else (a newline, a control
#: character, an over-long value) is discarded and replaced with a minted
#: UUID4 rather than reflected — echoing it into a response header or a log
#: line would let a client inject content into both.
_MAX_REQUEST_ID_LENGTH = 64
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")


def is_valid_request_id(value: str) -> bool:
    """True when `value` is safe to accept and echo back as a request ID."""
    return (
        bool(value)
        and len(value) <= _MAX_REQUEST_ID_LENGTH
        and bool(_REQUEST_ID_PATTERN.match(value))
    )


def _extract_inbound_request_id(scope: Scope) -> str | None:
    """Read the raw `X-Request-ID` header value out of an ASGI scope, if present."""
    for name, value in scope.get("headers", ()):
        if name == _REQUEST_ID_HEADER_BYTES:
            return bytes(value).decode("latin-1")
    return None


class RequestIdMiddleware:
    """Establish a correlation ID for every HTTP request.

    Reads the inbound `X-Request-ID` header when present and syntactically
    valid, otherwise mints a UUID4. Sets `request_id_var` for the life of the
    request and resets it in a `finally` so nothing leaks between requests
    (or, under a worker that reuses its context, into the next one), and sets
    `X-Request-ID` on the outgoing response.

    Registered in `main.py` as the outermost middleware — the last
    `add_middleware` call — so the request ID is established before every
    other layer runs, including `HttpMetricsMiddleware`: a request ID minted
    inside the metrics layer could never appear in the metrics layer's own
    log lines.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        inbound = _extract_inbound_request_id(scope)
        request_id = inbound if inbound and is_valid_request_id(inbound) else str(uuid.uuid4())

        token: Token[str | None] = request_id_var.set(request_id)

        async def _send(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((_REQUEST_ID_HEADER_BYTES, request_id.encode("latin-1")))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, _send)
        finally:
            request_id_var.reset(token)


class RequestIdLogFilter(logging.Filter):
    """Attach the current request's correlation ID to every log record.

    Sets `record.request_id` from `request_id_var`, using the literal `"-"`
    when there is none (e.g. a log line emitted outside a request, or during
    startup/shutdown), so a format string referencing `%(request_id)s` never
    raises for lack of the attribute.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get() or "-"
        return True


_INSTALL_MARKER = "_cb_request_id_filter_installed"


def install_request_id_log_filter(logger_names: Iterable[str] | None = None) -> None:
    """Install the request-ID filter on root and selected named loggers, exactly once.

    A parallel installer to `app.core.log_redaction.install_global_log_redaction`
    rather than a change to it, so the redaction filter keeps running
    unmodified — this adds a filter, it does not replace one. Call from the
    same place `install_global_log_redaction()` is called (`main.py`) so both
    are attached to the same logger set.
    """
    filter_instance = RequestIdLogFilter()
    root = logging.getLogger()
    if not getattr(root, _INSTALL_MARKER, False):
        root.addFilter(filter_instance)
        setattr(root, _INSTALL_MARKER, True)

    target_names = tuple(logger_names or ("uvicorn", "uvicorn.error", "uvicorn.access", "app"))
    for logger_name in target_names:
        logger = logging.getLogger(logger_name)
        if getattr(logger, _INSTALL_MARKER, False):
            continue
        logger.addFilter(filter_instance)
        setattr(logger, _INSTALL_MARKER, True)
