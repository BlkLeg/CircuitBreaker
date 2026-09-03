"""The operator surface over parked JetStream work.

Route F14 asks for more than a table: "every JetStream max-deliver exhaustion
produces an operator-visible record". Visible means reachable — a row nobody can
list is the same silent failure with a nicer schema.

These routes expose the payloads of messages that failed, which can carry
whatever the producing system put in them, so admin-only is a security property
and not a nicety. That is asserted here rather than assumed from the router's
declaration, because a `dependencies=[...]` line is easy to drop in a refactor
and nothing else would notice.
"""

from __future__ import annotations

import pytest

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
    row = svc.park_message(db, **kwargs)
    db.commit()
    return row


@pytest.mark.asyncio
async def test_listing_requires_an_admin(client, viewer_headers, db_session) -> None:
    _park(db_session)

    resp = await client.get("/api/v1/failed-messages", headers=viewer_headers)

    assert resp.status_code == 403, (
        f"a viewer reached parked payloads (got {resp.status_code}) — these rows "
        "carry whatever the producing system sent, so the admin gate is a "
        "security boundary"
    )


@pytest.mark.asyncio
async def test_listing_is_unavailable_without_authentication(client, db_session) -> None:
    _park(db_session)

    resp = await client.get("/api/v1/failed-messages")

    assert resp.status_code in (401, 403), resp.text


@pytest.mark.asyncio
async def test_an_admin_sees_the_parked_record(client, auth_headers, db_session) -> None:
    parked = _park(db_session)

    resp = await client.get("/api/v1/failed-messages", headers=auth_headers)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [row["id"] for row in body] == [parked.id]
    row = body[0]
    assert row["stream"] == "MONITOR_POLL"
    assert row["subject"] == "mon.poll.item"
    assert row["consumer"] == "monitor_poll"
    assert row["delivered_count"] == 5
    assert "unparseable" in row["error"]
    assert row["requeued_at"] is None
    assert row["discarded_at"] is None


@pytest.fixture
def published(monkeypatch):
    """A connected bus that records what it was handed.

    The requeue route now refuses when NATS is disconnected, which it is
    throughout this suite. That refusal is the fix: `nats_client.publish`
    buffers instead of raising, so every requeue used to return 200 and stamp
    `requeued_at` while the message went nowhere — and a test asserting only on
    `requeued_at` could not tell the two apart.
    """
    from app.core.nats_client import NATSClient, nats_client

    monkeypatch.setattr(NATSClient, "is_connected", property(lambda self: True))
    sent: list[str] = []

    async def _publish(subject: str, payload: bytes) -> None:
        sent.append(subject)

    monkeypatch.setattr(nats_client, "publish", _publish)
    return sent


@pytest.mark.asyncio
async def test_discard_marks_the_row_and_removes_it_from_the_listing(
    client, auth_headers, db_session
) -> None:
    parked = _park(db_session)

    resp = await client.post(f"/api/v1/failed-messages/{parked.id}/discard", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["discarded_at"] is not None

    listing = await client.get("/api/v1/failed-messages", headers=auth_headers)
    assert listing.json() == []


@pytest.mark.asyncio
async def test_requeue_marks_the_row(client, auth_headers, db_session, published) -> None:
    parked = _park(db_session)

    resp = await client.post(f"/api/v1/failed-messages/{parked.id}/requeue", headers=auth_headers)

    assert resp.status_code == 200, resp.text
    assert resp.json()["requeued_at"] is not None
    assert published == [parked.subject], "the row is only marked if it actually republished"


@pytest.mark.asyncio
async def test_acting_twice_on_one_row_is_refused(
    client, auth_headers, db_session, published
) -> None:
    """A double-click must not republish the same work twice.

    409 rather than 200: the operator needs to know the second action did not
    happen, and a silent duplicate is the worst outcome for a recovery tool.
    """
    parked = _park(db_session)

    first = await client.post(f"/api/v1/failed-messages/{parked.id}/requeue", headers=auth_headers)
    assert first.status_code == 200, first.text

    second = await client.post(f"/api/v1/failed-messages/{parked.id}/requeue", headers=auth_headers)
    assert second.status_code == 409, second.text
    assert "detail" in second.json()


@pytest.mark.asyncio
async def test_an_unknown_id_is_a_404_with_a_detail(client, auth_headers) -> None:
    resp = await client.post("/api/v1/failed-messages/9999999/requeue", headers=auth_headers)

    assert resp.status_code == 404, resp.text
    assert "detail" in resp.json()


# --- M14: a requeue that reports success must have reached a stream ----------


@pytest.mark.asyncio
async def test_requeue_is_refused_while_the_bus_is_disconnected(db_session) -> None:
    """`nats_client.publish` catches everything and buffers into a bounded
    deque on a disconnect, dropping silently on overflow — so every requeue
    returned 200 and stamped `requeued_at` whether or not the message reached a
    stream. Requeue 250 rows with NATS down: 200 buffer, 50 vanish, all 250 read
    as requeued.

    The existing test asserted only that `requeued_at` was set, and was green on
    a requeue that provably republished nothing.
    """
    from app.services import failed_message_service as svc

    row = svc.park_message(
        db_session,
        stream="MONITOR_POLL",
        subject="mon.poll.item",
        consumer="monitor_poll",
        payload=b'{"monitor_id": 1}',
        error="boom",
        delivered_count=5,
    )
    db_session.commit()

    published: list[str] = []

    async def _publish(subject: str, payload: bytes) -> None:
        published.append(subject)

    with pytest.raises(svc.RepublishFailed):
        await svc.requeue_and_publish(db_session, row.id, _publish, is_connected=lambda: False)

    db_session.rollback()
    db_session.refresh(row)
    assert published == [], "nothing may be published while the bus is down"
    assert row.requeued_at is None, "the row must stay parked, not claim a requeue"


def test_resolved_rows_are_pruned_but_parked_ones_are_not(db_session) -> None:
    """`discard` keeps the row by design, so without retention the operator
    action that clears a flood left every payload behind for ever. Unfinished
    work is never pruned by age."""
    from datetime import timedelta

    from app.core.time import utcnow
    from app.services import failed_message_service as svc

    old_parked = svc.park_message(
        db_session,
        stream="MONITOR_POLL",
        subject="mon.poll.old-parked",
        consumer="monitor_poll",
        payload=b"{}",
        error="still failing",
        delivered_count=5,
    )
    old_discarded = svc.park_message(
        db_session,
        stream="MONITOR_POLL",
        subject="mon.poll.old-discarded",
        consumer="monitor_poll",
        payload=b"{}",
        error="dealt with",
        delivered_count=5,
    )
    long_ago = utcnow() - timedelta(days=90)
    old_parked.parked_at = long_ago
    old_discarded.parked_at = long_ago
    old_discarded.discarded_at = long_ago
    db_session.commit()

    parked_id, discarded_id = old_parked.id, old_discarded.id
    model = type(old_parked)

    deleted = svc.prune_resolved(db_session, older_than_days=30)

    # The deleted instance is still in the identity map; drop it so these read
    # the table rather than a stale object.
    db_session.expunge_all()

    assert deleted == 1
    assert db_session.query(model).filter_by(id=parked_id).first() is not None
    assert db_session.query(model).filter_by(id=discarded_id).first() is None
