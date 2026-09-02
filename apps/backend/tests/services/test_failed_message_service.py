"""Parking, listing, requeueing and discarding poisoned JetStream work.

The behaviour worth pinning is not "a row can be written" — it is that an
operator can tell the three states apart afterwards. A parked message that has
been requeued is not the same as one nobody has looked at, and neither is the
same as one deliberately thrown away. Route F14's whole point is that the
operator can see and act on the failure, so the states have to survive.
"""

from __future__ import annotations

import pytest

from app.db.models_failed_message import FailedMessage
from app.services import failed_message_service as svc


def _park(db, **overrides):
    kwargs = {
        "stream": "MONITOR_POLL",
        "subject": "mon.poll.item",
        "consumer": "monitor_poll",
        "payload": b'{"monitor_id": 1}',
        "error": "ValueError: unparseable",
        "delivered_count": 5,
    }
    kwargs.update(overrides)
    return svc.park_message(db, **kwargs)


def test_a_parked_message_is_listed_with_its_evidence(db_session) -> None:
    parked = _park(db_session)

    listed = svc.list_parked(db_session)
    assert [row.id for row in listed] == [parked.id]
    row = listed[0]
    assert row.stream == "MONITOR_POLL"
    assert row.subject == "mon.poll.item"
    assert row.delivered_count == 5
    assert row.payload == b'{"monitor_id": 1}', (
        "the payload must survive verbatim — a message that failed to parse is "
        "exactly the kind that parks, and re-encoding it destroys the evidence"
    )
    assert row.error == "ValueError: unparseable"
    assert row.parked_at is not None
    assert not row.is_resolved


def test_discard_resolves_the_row_without_deleting_it(db_session) -> None:
    parked = _park(db_session)

    svc.discard(db_session, parked.id)

    assert svc.list_parked(db_session) == [], "a discarded row leaves the default listing"
    everything = svc.list_parked(db_session, include_resolved=True)
    assert [row.id for row in everything] == [parked.id], (
        "the row is kept: 'this failed and was thrown away' is a different fact "
        "from 'this never happened'"
    )
    assert everything[0].discarded_at is not None
    assert everything[0].is_resolved


def test_requeue_marks_the_row_and_returns_what_to_republish(db_session) -> None:
    parked = _park(db_session)

    republish = svc.requeue(db_session, parked.id)

    assert republish.subject == "mon.poll.item"
    assert republish.payload == b'{"monitor_id": 1}'
    refreshed = db_session.get(FailedMessage, parked.id)
    assert refreshed.requeued_at is not None
    assert svc.list_parked(db_session) == []


def test_requeue_refuses_a_row_that_was_already_resolved(db_session) -> None:
    """Otherwise a double-click on the operator page republishes twice.

    The failure is silent and duplicative, which is the worst combination for a
    recovery tool: the operator sees success both times and the stream gets the
    work twice.
    """
    parked = _park(db_session)
    svc.requeue(db_session, parked.id)

    with pytest.raises(svc.MessageAlreadyResolved):
        svc.requeue(db_session, parked.id)


def test_discard_refuses_a_row_that_was_already_resolved(db_session) -> None:
    parked = _park(db_session)
    svc.discard(db_session, parked.id)

    with pytest.raises(svc.MessageAlreadyResolved):
        svc.discard(db_session, parked.id)


def test_acting_on_an_unknown_id_raises_not_found(db_session) -> None:
    with pytest.raises(svc.MessageNotFound):
        svc.requeue(db_session, 9_999_999)
    with pytest.raises(svc.MessageNotFound):
        svc.discard(db_session, 9_999_999)


def test_listing_is_newest_first(db_session) -> None:
    """An operator triaging a flood needs the most recent failures at the top."""
    first = _park(db_session, error="first")
    second = _park(db_session, error="second")

    listed = svc.list_parked(db_session)
    assert [row.id for row in listed] == [second.id, first.id]


@pytest.mark.asyncio
async def test_requeue_and_publish_sends_the_payload_to_its_original_subject(
    db_session,
) -> None:
    parked = _park(db_session)
    db_session.commit()
    sent: list[tuple[str, bytes]] = []

    async def _publish(subject: str, payload: bytes) -> None:
        sent.append((subject, payload))

    row = await svc.requeue_and_publish(db_session, parked.id, _publish)

    assert sent == [("mon.poll.item", b'{"monitor_id": 1}')]
    assert row.requeued_at is not None


@pytest.mark.asyncio
async def test_a_publisher_that_raises_leaves_the_message_parked(db_session) -> None:
    """The mark and the send must not disagree.

    A row marked requeued whose message never reached a stream is the worst
    state to be in: the operator believes the work was recovered and it silently
    was not, and the listing no longer shows it as needing attention.
    """
    parked = _park(db_session)
    db_session.commit()

    async def _explode(subject: str, payload: bytes) -> None:
        raise RuntimeError("broker unreachable")

    with pytest.raises(svc.RepublishFailed):
        await svc.requeue_and_publish(db_session, parked.id, _explode)

    still_parked = svc.list_parked(db_session)
    assert [r.id for r in still_parked] == [parked.id]
    assert still_parked[0].requeued_at is None
