"""M2: one poison message must not take the batch down with it.

`monitor_poll_worker` fetches up to 50 messages and calls `process_batch` once.
The comment on its failure path claimed handling was "per message, not per
batch", but only the *delivery budget* was per message: one exception naked all
50 together, marched all 50 to `max_deliver`, then parked and terminated them.
49 healthy monitor checks, deleted from a work queue and filed as failures under
someone else's exception.

Separately, a message whose payload would not parse was logged and acked —
deleted outright, with no record — despite `db/models_failed_message.py` naming
a parse failure as exactly what `failed_messages` is for.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from app.workers import monitor_poll_worker as worker


@dataclass
class _Metadata:
    num_delivered: int


@dataclass
class _FakeMsg:
    subject: str
    data: bytes
    num_delivered: int = 1
    actions: list[str] = field(default_factory=list)

    @property
    def metadata(self) -> _Metadata:
        return _Metadata(num_delivered=self.num_delivered)

    async def nak(self) -> None:
        self.actions.append("nak")

    async def ack(self) -> None:
        self.actions.append("ack")

    async def term(self) -> None:
        self.actions.append("term")


@pytest.mark.asyncio
async def test_a_poison_message_does_not_discard_the_batch_beside_it(monkeypatch) -> None:
    good_a = _FakeMsg(subject="mon.poll.item", data=b'{"id": 1}')
    poison = _FakeMsg(subject="mon.poll.item", data=b'{"id": 2}')
    good_b = _FakeMsg(subject="mon.poll.item", data=b'{"id": 3}')

    async def _process(items: list[dict], _factory: Any) -> int:
        if any(item["id"] == 2 for item in items):
            raise RuntimeError("poison")
        return len(items)

    monkeypatch.setattr(worker, "process_batch", _process)

    parked: list[Any] = []

    async def _handle(msg: Any, **kwargs: Any) -> bool:
        parked.append(msg)
        return True

    monkeypatch.setattr(worker, "handle_failed_delivery", _handle)

    await worker._process_individually(
        [(good_a, {"id": 1}), (poison, {"id": 2}), (good_b, {"id": 3})]
    )

    assert good_a.actions == ["ack"], "a healthy message must be acknowledged, not discarded"
    assert good_b.actions == ["ack"]
    assert parked == [poison], "only the message that actually failed goes to the dead letter"


@pytest.mark.asyncio
async def test_each_failure_carries_its_own_error(monkeypatch) -> None:
    """Attribution matters: parking 50 messages under whichever exception
    surfaced first makes the operator surface actively misleading."""
    first = _FakeMsg(subject="mon.poll.item", data=b'{"id": 1}')
    second = _FakeMsg(subject="mon.poll.item", data=b'{"id": 2}')

    async def _process(items: list[dict], _factory: Any) -> int:
        raise RuntimeError(f"failure-for-{items[0]['id']}")

    monkeypatch.setattr(worker, "process_batch", _process)

    errors: list[str] = []

    async def _handle(msg: Any, **kwargs: Any) -> bool:
        errors.append(kwargs["error"])
        return True

    monkeypatch.setattr(worker, "handle_failed_delivery", _handle)

    await worker._process_individually([(first, {"id": 1}), (second, {"id": 2})])

    assert "failure-for-1" in errors[0]
    assert "failure-for-2" in errors[1]
