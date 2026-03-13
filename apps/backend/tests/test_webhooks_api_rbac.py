from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.webhooks import router as webhooks_router
from app.core.security import get_optional_user
from app.db.models import User, WebhookDelivery, WebhookRule
from app.db.session import SessionLocal, get_db


def _require_postgres() -> None:
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.skip(f"PostgreSQL unavailable for webhooks integration test: {exc}")


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
    _require_postgres()
    created_user_ids: list[int] = []
    created_rule_ids: list[int] = []
    unique = uuid4().hex[:8]

    with SessionLocal() as db:
        viewer = _make_user("viewer", f"viewer-{unique}@example.com")
        editor = _make_user("editor", f"editor-{unique}@example.com")
        db.add_all([viewer, editor])
        db.commit()
        db.refresh(viewer)
        db.refresh(editor)
        viewer_id = viewer.id
        editor_id = editor.id
        created_user_ids.extend([viewer_id, editor_id])

    active_user_id = {"value": viewer_id}

    def _db_override():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    def _user_override():
        return active_user_id["value"]

    app = FastAPI()
    app.include_router(webhooks_router, prefix="/api/v1/webhooks")
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

    try:
        viewer_resp = client.post("/api/v1/webhooks", json=payload)
        assert viewer_resp.status_code == 403

        active_user_id["value"] = editor_id
        editor_resp = client.post("/api/v1/webhooks", json=payload)
        assert editor_resp.status_code == 200
        body = editor_resp.json()
        assert body["label"] == "Slack Infra"
        assert body["retries"] == 3
        if body.get("id") is not None:
            created_rule_ids.append(body["id"])
    finally:
        with SessionLocal() as db:
            if created_rule_ids:
                db.query(WebhookDelivery).filter(
                    WebhookDelivery.rule_id.in_(created_rule_ids)
                ).delete(synchronize_session=False)
                db.query(WebhookRule).filter(WebhookRule.id.in_(created_rule_ids)).delete(
                    synchronize_session=False
                )
            if created_user_ids:
                db.query(User).filter(User.id.in_(created_user_ids)).delete(
                    synchronize_session=False
                )
            db.commit()
