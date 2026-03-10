"""Minimal API tests for status pages, groups, and dashboard."""

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.status import router as status_router
from app.db.models import Base, Hardware, StatusGroup, StatusHistory, StatusPage
from app.db.session import get_db


def test_status_pages_list_and_dashboard():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        bind=engine,
        tables=[
            StatusPage.__table__,
            StatusGroup.__table__,
            StatusHistory.__table__,
            Hardware.__table__,
        ],
    )
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    def _db_override():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app = FastAPI()
    app.include_router(status_router, prefix="/api/v1/status")
    app.dependency_overrides[get_db] = _db_override

    with session_factory() as db:
        db.add(StatusPage(slug="default", name="Default", config=None))
        db.commit()

    client = TestClient(app)
    r = client.get("/api/v1/status/pages")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    assert any(p.get("slug") == "default" for p in data)

    r2 = client.get("/api/v1/status/dashboard")
    assert r2.status_code == 200
    dash = r2.json()
    assert "pages" in dash
    assert "groups" in dash
    assert "history_sample" in dash


def test_available_entities_and_bulk_group():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        bind=engine,
        tables=[
            StatusPage.__table__,
            StatusGroup.__table__,
            StatusHistory.__table__,
            Hardware.__table__,
        ],
    )
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    def _db_override():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app = FastAPI()
    app.include_router(status_router, prefix="/api/v1/status")
    app.dependency_overrides[get_db] = _db_override

    # Mock require_write_auth
    from app.core.security import require_write_auth

    app.dependency_overrides[require_write_auth] = lambda: {"sub": 1}

    with session_factory() as db:
        page = StatusPage(slug="test-page", name="Test Page", config=None)
        db.add(page)
        hw = Hardware(name="Test Server", role="server", status="up", source="manual")
        db.add(hw)
        db.commit()

    client = TestClient(app)

    # 1. Fetch available entities
    r = client.get("/api/v1/status/available-entities")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["total"] == 1
    assert len(data["entities"]) == 1
    entity = data["entities"][0]
    assert entity["name"] == "Test Server"
    assert entity["type"] == "hardware"

    # 2. Bulk assign to group
    r2 = client.post(
        "/api/v1/status/groups/bulk",
        json={
            "name": "My New Group",
            "page_id": 1,
            "entity_ids": [entity["id"]],
            "entity_type": "hardware",
        },
    )
    assert r2.status_code == 200, r2.text
    resp = r2.json()
    assert resp["added"] == 1

    # 3. Fetch again, should be empty (already grouped)
    r3 = client.get("/api/v1/status/available-entities")
    assert r3.status_code == 200
    assert r3.json()["total"] == 0
