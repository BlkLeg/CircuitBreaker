"""Task 1a/1b: the request-ID middleware and its logging filter.

Unit-level: drives `RequestIdMiddleware` directly as a raw ASGI callable
rather than through the full app, so these tests need no database — matching
the convention in `apps/backend/tests/core/`. Header edge cases (a newline, a
control character) are driven through a hand-built ASGI scope rather than an
httpx client, since a well-behaved HTTP client refuses to transmit those
bytes in a header itself; the point of this middleware is to defend against a
peer — proxy or otherwise — that does not.
"""

from __future__ import annotations

import logging
import re

import pytest

from app.core.log_redaction import LogRedactionFilter
from app.middleware.request_id import (
    RequestIdLogFilter,
    RequestIdMiddleware,
    install_request_id_log_filter,
    is_valid_request_id,
    request_id_var,
)

_UUID4_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", re.IGNORECASE
)


async def _ok_app(scope: dict, receive: object, send: object) -> None:
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


async def _dispatch(
    asgi_app: object, headers: list[tuple[bytes, bytes]]
) -> tuple[int, dict[bytes, bytes]]:
    """Drive an ASGI app directly with a minimal HTTP scope and collect its response."""
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "query_string": b"",
        "headers": headers,
    }
    sent: list[dict] = []

    async def receive() -> dict:
        return {"type": "http.disconnect"}

    async def send(message: dict) -> None:
        sent.append(message)

    await asgi_app(scope, receive, send)  # type: ignore[operator]
    start = next(m for m in sent if m["type"] == "http.response.start")
    return start["status"], dict(start["headers"])


@pytest.fixture(autouse=True)
def _reset_contextvar():
    """Nothing should leak in from a previous test regardless of ordering."""
    token = request_id_var.set(None)
    yield
    request_id_var.reset(token)


async def test_missing_header_mints_a_uuid4_and_returns_it():
    status, headers = await _dispatch(RequestIdMiddleware(_ok_app), headers=[])
    assert status == 200
    value = headers[b"x-request-id"].decode()
    assert _UUID4_RE.match(value), value


async def test_valid_inbound_header_is_echoed_back_unchanged():
    inbound = "abc-123_DEF.456"  # deliberately includes every allowed char class
    _, headers = await _dispatch(
        RequestIdMiddleware(_ok_app), headers=[(b"x-request-id", inbound.encode())]
    )
    assert headers[b"x-request-id"].decode() == inbound


async def test_a_36_char_crypto_randomuuid_value_is_accepted_unchanged():
    """Task 2 (frontend) mints crypto.randomUUID() and sends it inbound — this
    is the exact shape that must round-trip unchanged."""
    inbound = "3fa85f64-5717-4562-b3fc-2c963f66afa6"
    assert len(inbound) == 36
    _, headers = await _dispatch(
        RequestIdMiddleware(_ok_app), headers=[(b"x-request-id", inbound.encode())]
    )
    assert headers[b"x-request-id"].decode() == inbound


@pytest.mark.parametrize(
    "bad_value",
    [
        pytest.param(b"abc\ndef", id="embedded-newline"),
        pytest.param(b"abc\x07def", id="control-character"),
        pytest.param(b"a" * 65, id="over-64-chars"),
        pytest.param(b"has spaces", id="disallowed-charset"),
    ],
)
async def test_invalid_inbound_header_is_discarded_and_replaced(bad_value: bytes):
    _, headers = await _dispatch(
        RequestIdMiddleware(_ok_app), headers=[(b"x-request-id", bad_value)]
    )
    returned = headers[b"x-request-id"]
    # Never echoed: the response carries a freshly minted UUID4, not the
    # injected content, and in particular no raw newline byte.
    assert b"\n" not in returned
    assert _UUID4_RE.match(returned.decode("latin-1")), returned


def test_is_valid_request_id_rejects_the_same_shapes_directly():
    assert is_valid_request_id("3fa85f64-5717-4562-b3fc-2c963f66afa6")
    assert is_valid_request_id("a" * 64)
    assert not is_valid_request_id("a" * 65)
    assert not is_valid_request_id("abc\ndef")
    assert not is_valid_request_id("abc\x07def")
    assert not is_valid_request_id("has spaces")
    assert not is_valid_request_id("")


async def test_contextvar_is_none_after_the_request_completes():
    assert request_id_var.get() is None
    await _dispatch(RequestIdMiddleware(_ok_app), headers=[])
    assert request_id_var.get() is None


async def test_contextvar_resets_even_when_the_inner_app_raises():
    async def _boom(scope: dict, receive: object, send: object) -> None:
        raise RuntimeError("inner app blew up")

    with pytest.raises(RuntimeError):
        await _dispatch(RequestIdMiddleware(_boom), headers=[])
    assert request_id_var.get() is None


async def test_non_http_scope_passes_through_untouched():
    """A lifespan/websocket scope must not be given a request ID or headers."""
    calls: list[str] = []

    async def _lifespan_app(scope: dict, receive: object, send: object) -> None:
        calls.append(scope["type"])

    scope = {"type": "lifespan"}

    async def receive() -> dict:
        return {}

    async def send(message: dict) -> None:
        pass

    await RequestIdMiddleware(_lifespan_app)(scope, receive, send)
    assert calls == ["lifespan"]
    assert request_id_var.get() is None


async def test_log_record_emitted_during_a_request_carries_that_requests_id():
    logger = logging.getLogger("app.test_request_id.during")
    logger.setLevel(logging.DEBUG)
    id_filter = RequestIdLogFilter()
    logger.addFilter(id_filter)
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append  # type: ignore[method-assign]
    logger.addHandler(handler)

    seen: dict[str, str | None] = {}

    async def _logging_app(scope: dict, receive: object, send: object) -> None:
        seen["request_id"] = request_id_var.get()
        logger.warning("inside a request")
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    try:
        _, headers = await _dispatch(RequestIdMiddleware(_logging_app), headers=[])
        assert len(records) == 1
        assert records[0].request_id == seen["request_id"]
        assert records[0].request_id == headers[b"x-request-id"].decode()
        assert records[0].request_id != "-"
    finally:
        logger.removeHandler(handler)
        logger.removeFilter(id_filter)


def test_log_record_emitted_outside_a_request_carries_the_placeholder():
    logger = logging.getLogger("app.test_request_id.outside")
    logger.setLevel(logging.DEBUG)
    id_filter = RequestIdLogFilter()
    logger.addFilter(id_filter)
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append  # type: ignore[method-assign]
    logger.addHandler(handler)
    try:
        assert request_id_var.get() is None
        logger.warning("no request in flight")
        assert len(records) == 1
        assert records[0].request_id == "-"
    finally:
        logger.removeHandler(handler)
        logger.removeFilter(id_filter)


def test_redaction_still_runs_after_the_request_id_filter_is_installed():
    """1b requires this filter to be *added*, never to replace redaction."""
    logger = logging.getLogger("app.test_request_id.redaction")
    logger.setLevel(logging.DEBUG)
    redaction_filter = LogRedactionFilter()
    id_filter = RequestIdLogFilter()
    logger.addFilter(redaction_filter)
    logger.addFilter(id_filter)
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append  # type: ignore[method-assign]
    logger.addHandler(handler)
    try:
        logger.warning("Authorization: Bearer sekret-token-value")
        assert len(records) == 1
        rendered = records[0].getMessage()
        assert "sekret-token-value" not in rendered
        assert "[REDACTED]" in rendered
        # Both filters ran: redaction masked the message and the ID filter
        # still attached its (here, placeholder) attribute.
        assert records[0].request_id == "-"
    finally:
        logger.removeHandler(handler)
        logger.removeFilter(redaction_filter)
        logger.removeFilter(id_filter)


def test_install_is_idempotent_and_does_not_duplicate_filters():
    logger_name = "app.test_request_id.install_once"
    logger = logging.getLogger(logger_name)
    before = len(logger.filters)
    install_request_id_log_filter((logger_name,))
    install_request_id_log_filter((logger_name,))
    assert len(logger.filters) == before + 1
