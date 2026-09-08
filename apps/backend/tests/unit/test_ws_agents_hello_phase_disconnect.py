"""A client that vanishes mid-hello must end the /link connection quietly.

`link_stream`'s receive loop already treats `WebSocketDisconnect`/`RuntimeError`
on a send as an ordinary disconnect and leaves the loop. Its *hello phase* — the
`hello.ack`, `capabilities.set` and the two rotation resends that go out before
the loop starts — did not: an agent that dropped in the window between its hello
and the server's answer produced an unhandled ASGI exception and a ~40-line
traceback in the API log, once per occurrence, from any client that cared to
disconnect at the right moment.

That is not hypothetical. It is what `cb-agent uninstall` did on every single
run: it wrote its `uninstall` frame and closed immediately, uvicorn completed
the close handshake while the server was still committing the hello, and the
traceback at the `hello.ack` send was the only trace the whole feature left.
"""

import logging

import pytest
from starlette.websockets import WebSocketDisconnect

from app.api import ws_agents


class _RecordingWebSocket:
    """Sends succeed and are recorded."""

    def __init__(self) -> None:
        self.sent: list[bytes] = []

    async def send_bytes(self, data: bytes) -> None:
        self.sent.append(data)


class _VanishedWebSocket:
    """Sends fail the way a peer that already closed makes them fail."""

    def __init__(self, exc: BaseException) -> None:
        self.exc = exc

    async def send_bytes(self, data: bytes) -> None:
        raise self.exc


@pytest.mark.asyncio
async def test_hello_phase_send_reports_success_and_delivers():
    ws = _RecordingWebSocket()

    delivered = await ws_agents._send_hello_phase_frame(
        ws, b"payload", agent_id=7, phase="hello.ack"
    )

    assert delivered is True
    assert ws.sent == [b"payload"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exc",
    [
        WebSocketDisconnect(code=1006),
        # Starlette surfaces a send on an already-closed socket this way, which
        # is why the receive loop's own handlers catch both.
        RuntimeError('Cannot call "send" once a close message has been sent.'),
    ],
    ids=["disconnect", "closed"],
)
async def test_hello_phase_send_reports_a_vanished_peer_without_raising(exc, caplog):
    ws = _VanishedWebSocket(exc)

    with caplog.at_level(logging.INFO, logger=ws_agents._logger.name):
        delivered = await ws_agents._send_hello_phase_frame(
            ws, b"payload", agent_id=7, phase="hello.ack"
        )

    assert delivered is False
    # Named agent and named phase: enough to tell "agents keep dropping during
    # the hello" from "one agent dropped once" without a traceback per event.
    messages = [r.getMessage() for r in caplog.records]
    assert any("7" in m and "hello.ack" in m for m in messages), messages


@pytest.mark.asyncio
async def test_hello_phase_send_does_not_swallow_unrelated_failures():
    """Only the two disconnect shapes are ordinary. Anything else is a bug and
    must keep behaving like one — a silently dropped connection with no
    traceback is exactly how the uninstall defect stayed invisible."""
    ws = _VanishedWebSocket(ValueError("cipher state is broken"))

    with pytest.raises(ValueError):
        await ws_agents._send_hello_phase_frame(ws, b"payload", agent_id=7, phase="hello.ack")
