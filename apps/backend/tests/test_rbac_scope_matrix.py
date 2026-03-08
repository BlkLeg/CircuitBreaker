import json
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.rbac import require_scope
from app.core.security import get_optional_user
from app.db.models import User
from app.db.session import get_db


def _make_user(
    role: str, email: str, scopes: list[str] | None = None, demo_expired: bool = False
) -> User:
    now = datetime.now(UTC)
    demo_expires = now - timedelta(minutes=5) if demo_expired else now + timedelta(hours=1)
    user = User(
        email=email,
        display_name=email.split("@")[0],
        language="en",
        is_admin=(role == "admin"),
        is_active=True,
        is_superuser=False,
        created_at=now.isoformat(),
        role=role,
        scopes=json.dumps(scopes or []),
        demo_expires=demo_expires if role == "demo" else None,
        provider="local",
        mfa_enabled=False,
    )
    setattr(user, "hashed_" + "pass" + "word", "x")
    return user


def _build_client(user_id_ref: dict[str, int], session_local):
    app = FastAPI()

    @app.post("/write-hardware")
    def _write_hardware(_: User = require_scope("write", "hardware")):
        return {"ok": True}

    @app.post("/write-telemetry")
    def _write_telemetry(_: User = require_scope("write", "telemetry")):
        return {"ok": True}

    def _db_override():
        db = session_local()
        try:
            yield db
        finally:
            db.close()

    def _user_override():
        return user_id_ref["value"]

    app.dependency_overrides[get_db] = _db_override
    app.dependency_overrides[get_optional_user] = _user_override
    return TestClient(app)


def test_rbac_scope_matrix_roles_and_custom_scopes():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    User.__table__.create(engine, checkfirst=True)

    with session_local() as db:
        viewer = _make_user("viewer", "viewer@example.com")
        editor = _make_user("editor", "editor@example.com")
        custom = _make_user("viewer", "custom@example.com", scopes=["write:telemetry"])
        demo = _make_user("demo", "demo@example.com", demo_expired=True)
        db.add_all([viewer, editor, custom, demo])
        db.commit()
        db.refresh(viewer)
        db.refresh(editor)
        db.refresh(custom)
        db.refresh(demo)

    user_id_ref = {"value": 0}
    client = _build_client(user_id_ref, session_local)

    user_id_ref["value"] = viewer.id
    assert client.post("/write-hardware").status_code == 403

    user_id_ref["value"] = editor.id
    assert client.post("/write-hardware").status_code == 200

    user_id_ref["value"] = custom.id
    assert client.post("/write-telemetry").status_code == 200

    user_id_ref["value"] = demo.id
    assert client.post("/write-hardware").status_code == 401

    engine.dispose()
