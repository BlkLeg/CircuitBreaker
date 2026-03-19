from fastapi import Request

from app.core.audit import log_audit
from app.db.models import Log, User


def test_log_audit_with_user(db_session, factories):
    """log_audit with a user_id should log the user's details."""
    user = factories.user(display_name="Test User Name", email="test@example.com")
    db_session.flush()

    # Verify user is in the session correctly
    fetched_user = db_session.get(User, user.id)
    assert fetched_user.display_name == "Test User Name"

    request = Request(scope={"type": "http", "headers": [], "client": ("127.0.0.1", 12345)})
    log_audit(
        db_session,
        request,
        user_id=user.id,
        action="test_user_action",
        resource="test_resource",
        status="ok",
        details="some details",
        severity="info",
    )

    entry = db_session.query(Log).filter(Log.action == "test_user_action").first()
    assert entry is not None
    assert entry.actor == user.email
    assert entry.actor_name == user.display_name
    assert entry.actor_id == user.id
    assert entry.details == "status=ok | some details"
    assert entry.ip_address == "127.0.0.1"
