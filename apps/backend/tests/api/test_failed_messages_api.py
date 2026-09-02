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
async def test_requeue_marks_the_row(client, auth_headers, db_session) -> None:
    parked = _park(db_session)

    resp = await client.post(f"/api/v1/failed-messages/{parked.id}/requeue", headers=auth_headers)

    assert resp.status_code == 200, resp.text
    assert resp.json()["requeued_at"] is not None


@pytest.mark.asyncio
async def test_acting_twice_on_one_row_is_refused(client, auth_headers, db_session) -> None:
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
