import pytest

from app.core.audit import log_audit
from app.db.models import Log


@pytest.mark.asyncio
async def test_log_audit_system_actor(db_session):
    """log_audit with no request and no user_id should log as 'system'."""
    log_audit(db_session, None, action="test_system_action")

    entry = db_session.query(Log).filter(Log.action == "test_system_action").first()
    assert entry is not None
    assert entry.actor == "system"
    assert entry.actor_name == "system"


@pytest.mark.asyncio
async def test_log_audit_anonymous_actor(db_session, client):
    """log_audit with a request but no user_id should log as 'anonymous'."""
    # We need a mock request or just call it with something that looks like a request
    # In reality, log_audit is called from within a route
    from fastapi import Request

    # Minimal mock request
    request = Request(scope={"type": "http", "headers": [], "client": ("127.0.0.1", 12345)})

    log_audit(db_session, request, action="test_anon_action")

    entry = db_session.query(Log).filter(Log.action == "test_anon_action").first()
    assert entry is not None
    assert entry.actor == "anonymous"
    assert entry.actor_name == "anonymous"


@pytest.mark.asyncio
async def test_middleware_extracts_actor_from_cookie(client, db_session, auth_headers):
    """Middleware should extract actor from cb_session cookie if Authorization header is missing."""
    # First, get the token from auth_headers
    token = auth_headers["Authorization"].split(" ")[1]

    # Clear Authorization header and set cookie instead
    client.cookies.set("cb_session", token)

    # Perform an action that triggers LoggingMiddleware (e.g. GET /api/v1/hardware)
    # We need an action that modifies something to be sure it logs?
    # Actually LoggingMiddleware logs almost everything.
    resp = await client.get("/api/v1/hardware", headers={})  # No Auth header
    assert resp.status_code == 200

    # Wait a bit for the background task to finish
    import asyncio

    await asyncio.sleep(0.5)

    # Check logs
    # The middleware logs with action like "list_hardware" or similar
    # Let's find the latest log entry
    entry = db_session.query(Log).order_by(Log.id.desc()).first()
    assert entry is not None
    # It should not be anonymous
    assert entry.actor != "anonymous"
    # It should match the user from auth_headers (usually the first admin user)
    assert "@" in entry.actor or entry.actor_name != "anonymous"
