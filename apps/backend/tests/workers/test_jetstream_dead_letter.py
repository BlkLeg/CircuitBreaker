"""A message that can never succeed must stop being redelivered — and be kept.

Route F14. Both JetStream consumers `nak()` every failure with no `max_deliver`,
so a poison message is redelivered forever and its consumer makes no progress.
Worse in `monitor_poll_worker`, which naks the *whole batch* on one failure: a
single bad message blocks every good message beside it, indefinitely.

Setting `max_deliver` alone would swap the infinite loop for a silent drop —
still nothing for the operator, and now the data is gone too. So the rule under
test is the pair: while the budget remains, nak and let NATS retry; once it is
spent, park the payload and `term()` so the consumer moves on with a record left
behind.

The fake below follows the convention `tests/services/test_telemetry_ingest_stream_update.py`
sets, and for the same reason: this suite has no live NATS on purpose
(`nats-server` is in no Fedora repository, see
`tests/test_nats_initial_connect_is_bounded.py`). It models the two semantics the
helper actually depends on — `metadata.num_delivered`, and that `term()` and
`nak()` are different outcomes — because a fake that merely recorded calls would
let a worker that never terminates anything pass.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

import pytest

from app.db.models_failed_message import FailedMessage
from app.workers.dead_letter import handle_failed_delivery


@dataclass
class _Metadata:
    num_delivered: int


@dataclass
class _FakeMsg:
    """A JetStream message that records which terminal action it received.

    `nak`, `ack` and `term` are distinct on the wire and mean different things to
    the server: nak asks for redelivery, term says never again. Collapsing them
    in the fake would hide the entire defect this test exists for.
    """

    subject: str
    data: bytes
    num_delivered: int
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


def _factory(db_session):
    @contextmanager
    def _session_factory():
        yield db_session

    return _session_factory


@pytest.mark.asyncio
async def test_a_message_with_budget_left_is_naked_and_not_parked(db_session) -> None:
    msg = _FakeMsg(subject="mon.poll.item", data=b"{}", num_delivered=2)

    parked = await handle_failed_delivery(
        msg,
        stream="MONITOR_POLL",
        consumer="monitor_poll",
        error="boom",
        max_deliver=5,
        session_factory=_factory(db_session),
    )

    assert parked is False
    assert msg.actions == ["nak"], "a retryable failure must ask for redelivery"
    assert db_session.query(FailedMessage).count() == 0, (
        "parking a message that still has attempts left would discard work that "
        "may well succeed on the next try"
    )


@pytest.mark.asyncio
async def test_a_message_that_exhausted_its_budget_is_parked_and_terminated(
    db_session,
) -> None:
    msg = _FakeMsg(subject="mon.poll.item", data=b'{"monitor_id": 7}', num_delivered=5)

    parked = await handle_failed_delivery(
        msg,
        stream="MONITOR_POLL",
        consumer="monitor_poll",
        error="ValueError: unparseable",
        max_deliver=5,
        session_factory=_factory(db_session),
    )

    assert parked is True
    assert msg.actions == ["term"], (
        "term, not nak: the point is that the consumer stops being blocked by "
        "this message. A nak here is the infinite loop F14 describes"
    )
    row = db_session.query(FailedMessage).one()
    assert row.subject == "mon.poll.item"
    assert row.stream == "MONITOR_POLL"
    assert row.consumer == "monitor_poll"
    assert row.payload == b'{"monitor_id": 7}'
    assert row.delivered_count == 5
    assert "unparseable" in row.error


@pytest.mark.asyncio
async def test_the_park_is_committed_before_term_is_sent(db_session) -> None:
    """The row must be durable before `term()` gives up the only other copy.

    `term()` tells the server never to redeliver. If the park were still
    uncommitted at that moment, a crash in between would destroy the message
    and its record together — which is the silent drop this whole task exists
    to avoid.

    This asserts the *ordering of the calls*, not that the row is visible. The
    previous version queried the same `db_session` from inside `term()` and
    checked the row was there — but that fixture runs in a savepoint and never
    commits, and `park_message` already flushes, so the row was visible whether
    or not anything committed. Deleting the `db.commit()` this test names left
    it green. Recording the calls is the only version that fails.
    """
    events: list[str] = []

    class _RecordingSession:
        """Records commits without ending the test's transaction."""

        def __init__(self, inner: Any) -> None:
            self._inner = inner

        def __getattr__(self, name: str) -> Any:
            return getattr(self._inner, name)

        def commit(self) -> None:
            events.append("commit")
            self._inner.flush()

    @contextmanager
    def _recording_factory():
        yield _RecordingSession(db_session)

    class _WatchingMsg(_FakeMsg):
        async def term(self) -> None:
            events.append("term")
            await super().term()

    msg = _WatchingMsg(subject="telemetry.host.1", data=b"x", num_delivered=9)
    await handle_failed_delivery(
        msg,
        stream="TELEMETRY",
        consumer="telemetry_ingest",
        error="bad",
        max_deliver=9,
        session_factory=_recording_factory,
    )

    assert events == ["commit", "term"], (
        "the park must be committed before term() is sent; got "
        f"{events}. A missing 'commit' means the durability step this module "
        "documents is not happening"
    )


@pytest.mark.asyncio
async def test_a_failure_to_park_does_not_terminate_the_message(db_session) -> None:
    """If the record cannot be written, redelivery is the safer outcome.

    Terminating anyway would be the silent drop with extra steps.
    """

    @contextmanager
    def _exploding_factory():
        raise RuntimeError("database unavailable")
        yield  # pragma: no cover - unreachable, satisfies the contextmanager shape

    msg = _FakeMsg(subject="mon.poll.item", data=b"{}", num_delivered=5)

    parked = await handle_failed_delivery(
        msg,
        stream="MONITOR_POLL",
        consumer="monitor_poll",
        error="boom",
        max_deliver=5,
        session_factory=_exploding_factory,
    )

    assert parked is False
    assert msg.actions == ["nak"], (
        "when the park fails, ask for redelivery rather than terminating — "
        "losing the message is worse than retrying it"
    )
