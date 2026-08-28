"""The initial NATS connect must not block startup when the broker is absent.

Found by Tier 3 (ADR 0005 Phase 2), five layers into a packaged boot. uvicorn
logged "Waiting for application startup." and never finished, so /livez never
answered and the service looked hung rather than failed.

`NatsClient.connect()` passes ``max_reconnect_attempts=-1`` to nats-py, which
means *infinite* retries -- and that governs the initial connection too, not only
reconnection after an established link drops. So ``await nats.connect(...)``
never returns when nothing is listening, and never raises either.

Everything downstream of it was already written to handle an absent broker: the
``except`` clause sets ``_connected = False`` and logs "running in no-op mode",
and the next line of the lifespan calls ``validate_core_dependencies()``, which
is the function that decides whether a missing NATS is fatal or degraded. None of
it could run. Infinite reconnect is correct for a live connection that drops; for
the initial connect it converts a decision the code already knows how to make
into a hang.

This matters beyond the test fleet: nats-server is in no Fedora repository, and
nfpm.yaml lists it under ``recommends``, so a Fedora user installing the rpm gets
exactly this configuration -- no broker, and a service that never becomes live.
"""

from __future__ import annotations

import asyncio
import socket

import pytest

from app.core.nats_client import NATSClient


def _closed_port() -> int:
    """A port with nothing listening: bind, read the number, release it."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


@pytest.mark.asyncio
async def test_connect_returns_when_no_broker_is_listening():
    """Bounded, and reports the truth: not connected, no exception escaping."""
    client = NATSClient()
    client._url = f"nats://127.0.0.1:{_closed_port()}"

    # Generous relative to the intended bound, tight relative to "forever".
    await asyncio.wait_for(client.connect(), timeout=30)

    assert client.is_connected is False, (
        "a client that could not reach a broker must report itself disconnected, "
        "so validate_core_dependencies can decide whether that is fatal"
    )
