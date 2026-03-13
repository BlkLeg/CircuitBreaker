"""Minimal API tests for status pages, groups, and dashboard."""

from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.status import router as status_router
from app.core.security import require_write_auth
from app.db.models import Hardware, StatusGroup, StatusHistory, StatusPage
from app.db.session import SessionLocal, get_db


def _require_postgres() -> None:
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.skip(f"PostgreSQL unavailable for status integration tests: {exc}")


def test_status_pages_list_and_dashboard():
    _require_postgres()
    created_page_id = None
    test_slug = f"default-{uuid4().hex[:8]}"

    def _db_override():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app = FastAPI()
    app.include_router(status_router, prefix="/api/v1/status")
    app.dependency_overrides[get_db] = _db_override

    with SessionLocal() as db:
        page = StatusPage(slug=test_slug, name="Default", config=None)
        db.add(page)
        db.commit()
        db.refresh(page)
        created_page_id = page.id

    try:
        client = TestClient(app)
        r = client.get("/api/v1/status/pages")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        assert any(p.get("slug") == test_slug for p in data)

        r2 = client.get("/api/v1/status/dashboard")
        assert r2.status_code == 200
        dash = r2.json()
        assert "pages" in dash
        assert "groups" in dash
        assert "history_sample" in dash
    finally:
        if created_page_id is not None:
            with SessionLocal() as db:
                db.query(StatusPage).filter(StatusPage.id == created_page_id).delete()
                db.commit()


def test_available_entities_and_bulk_group():
    _require_postgres()
    created_page_id = None
    created_hw_id = None
    created_group_ids: list[int] = []
    test_name = f"Test Server {uuid4().hex[:8]}"

    def _db_override():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app = FastAPI()
    app.include_router(status_router, prefix="/api/v1/status")
    app.dependency_overrides[get_db] = _db_override
    app.dependency_overrides[require_write_auth] = lambda: {"sub": 1}

    with SessionLocal() as db:
        page = StatusPage(slug="test-page", name="Test Page", config=None)
        db.add(page)
        hw = Hardware(name=test_name, role="server", status="up", source="manual")
        db.add(hw)
        db.commit()
        db.refresh(page)
        db.refresh(hw)
        created_page_id = page.id
        created_hw_id = hw.id

    try:
        client = TestClient(app)

        r = client.get("/api/v1/status/available-entities")
        assert r.status_code == 200, r.text
        data = r.json()
        assert isinstance(data.get("entities"), list)

        entity = next((item for item in data["entities"] if item.get("name") == test_name), None)
        assert entity is not None
        assert entity["type"] == "hardware"

        r2 = client.post(
            "/api/v1/status/groups/bulk",
            json={
                "name": "My New Group",
                "page_id": created_page_id,
                "entity_ids": [entity["id"]],
                "entity_type": "hardware",
            },
        )
        assert r2.status_code == 200, r2.text
        resp = r2.json()
        assert resp["added"] >= 1

        with SessionLocal() as db:
            created_group_ids = [
                row.id
                for row in db.query(StatusGroup)
                .filter(
                    StatusGroup.status_page_id == created_page_id,
                    StatusGroup.name == "My New Group",
                )
                .all()
            ]

        r3 = client.get("/api/v1/status/available-entities")
        assert r3.status_code == 200
        post_entities = r3.json().get("entities", [])
        assert all(item.get("id") != entity["id"] for item in post_entities)
    finally:
        with SessionLocal() as db:
            if created_group_ids:
                db.query(StatusHistory).filter(
                    StatusHistory.group_id.in_(created_group_ids)
                ).delete(synchronize_session=False)
                db.query(StatusGroup).filter(StatusGroup.id.in_(created_group_ids)).delete(
                    synchronize_session=False
                )
            if created_hw_id is not None:
                db.query(Hardware).filter(Hardware.id == created_hw_id).delete()
            if created_page_id is not None:
                db.query(StatusPage).filter(StatusPage.id == created_page_id).delete()
            db.commit()
