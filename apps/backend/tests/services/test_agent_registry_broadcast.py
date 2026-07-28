import json
from unittest.mock import AsyncMock

import pytest

from app.services import agent_registry as svc


@pytest.mark.asyncio
async def test_broadcast_presence_publishes_to_redis_ws_and_nats(monkeypatch):
    redis_client = AsyncMock()
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=redis_client))
    nats_publish = AsyncMock()
    monkeypatch.setattr("app.core.nats_client.nats_client.publish", nats_publish)
    ws_broadcast = AsyncMock()
    monkeypatch.setattr("app.core.ws_manager.ws_manager.broadcast", ws_broadcast)

    await svc.broadcast_presence(5, "connected", detail={"worker": "w1"})

    redis_client.publish.assert_called_once()
    channel, payload = redis_client.publish.call_args[0]
    assert channel == "cb:agents:events"
    body = json.loads(payload)
    assert body == {"agent_id": 5, "event_type": "connected", "detail": {"worker": "w1"}}

    nats_publish.assert_called_once()
    ws_broadcast.assert_called_once()
    assert ws_broadcast.call_args[0][0] == {
        "agent_id": 5,
        "event_type": "connected",
        "detail": {"worker": "w1"},
    }


@pytest.mark.asyncio
async def test_broadcast_presence_falls_back_to_ws_manager_when_redis_unavailable(monkeypatch):
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=None))
    nats_publish = AsyncMock()
    monkeypatch.setattr("app.core.nats_client.nats_client.publish", nats_publish)
    ws_broadcast = AsyncMock()
    monkeypatch.setattr("app.core.ws_manager.ws_manager.broadcast", ws_broadcast)

    await svc.broadcast_presence(5, "disconnected")

    ws_broadcast.assert_called_once()
    body = ws_broadcast.call_args[0][0]
    assert body["agent_id"] == 5
    assert body["event_type"] == "disconnected"


@pytest.mark.asyncio
async def test_broadcast_presence_never_raises_when_all_transports_fail(monkeypatch):
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(side_effect=RuntimeError("boom")))
    monkeypatch.setattr(
        "app.core.ws_manager.ws_manager.broadcast", AsyncMock(side_effect=RuntimeError("boom"))
    )
    monkeypatch.setattr(
        "app.core.nats_client.nats_client.publish", AsyncMock(side_effect=RuntimeError("boom"))
    )

    await svc.broadcast_presence(5, "connected")
