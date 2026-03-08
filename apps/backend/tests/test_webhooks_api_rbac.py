from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.webhooks import router as webhooks_router
from app.core.security import get_optional_user
from app.db.models import User, WebhookDelivery, WebhookRule
from app.db.session import get_db


def _make_user(role: str, email: str) -> User:
    user = User(
        email=email,
        display_name=email.split("@")[0],
        language="en",
        is_admin=(role == "admin"),
        is_active=True,
        is_superuser=False,
        created_at=datetime.now(UTC).isoformat(),
        role=role,
        provider="local",
        mfa_enabled=False,
    )
    setattr(user, "hashed_" + "pass" + "word", "x")
    return user


def test_webhooks_rbac_viewer_cannot_post_editor_can():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    User.__table__.create(engine, checkfirst=True)
    WebhookRule.__table__.create(engine, checkfirst=True)
    WebhookDelivery.__table__.create(engine, checkfirst=True)

    with session_local() as db:
        viewer = _make_user("viewer", "viewer@example.com")
        editor = _make_user("editor", "editor@example.com")
        db.add_all([viewer, editor])
        db.commit()
        db.refresh(viewer)
        db.refresh(editor)
        viewer_id = viewer.id
        editor_id = editor.id

    active_user_id = {"value": viewer_id}

    def _db_override():
        db = session_local()
        try:
            yield db
        finally:
            db.close()

    def _user_override():
        return active_user_id["value"]

    app = FastAPI()
    app.include_router(webhooks_router, prefix="/api/v1")
    app.dependency_overrides[get_db] = _db_override
    app.dependency_overrides[get_optional_user] = _user_override
    client = TestClient(app)

    payload = {
        "label": "Slack Infra",
        "url": "https://hooks.example.com/infra",
        "events_enabled": ["proxmox.vm.created"],
        "headers": {"Authorization": "Bearer x"},
        "retries": 3,
        "enabled": True,
    }

    viewer_resp = client.post("/api/v1/webhooks", json=payload)
    assert viewer_resp.status_code == 403

    active_user_id["value"] = editor_id
    editor_resp = client.post("/api/v1/webhooks", json=payload)
    assert editor_resp.status_code == 200
    body = editor_resp.json()
    assert body["label"] == "Slack Infra"
    assert body["retries"] == 3
    engine.dispose()
