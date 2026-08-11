from __future__ import annotations

import threading
from datetime import timedelta

import pytest
from fastapi import HTTPException

from app.core.time import utcnow
from app.db.models import AppSettings, User, UserSession
from app.services import auth_service

_SETUP_TOKEN = "sec4-setup-token-at-least-16-chars"


def _bootstrap_payload(setup_token: str = _SETUP_TOKEN, email: str = "first@example.com") -> dict:
    return {
        "setup_token": setup_token,
        "email": email,
        "password": "TestPassword123!",
        "theme_preset": "gruvbox-dark",
    }


def _prepare_bootstrap_state(db_session, setup_token: str = _SETUP_TOKEN) -> AppSettings:
    db_session.query(UserSession).delete()
    db_session.query(User).delete()
    cfg = db_session.get(AppSettings, 1)
    if cfg is None:
        cfg = AppSettings(id=1)
        db_session.add(cfg)
        db_session.flush()
    cfg.auth_enabled = False
    cfg.bootstrap_token_hash = auth_service._hash_bootstrap_token(setup_token)
    cfg.bootstrap_token_expires_at = utcnow() + timedelta(hours=1)
    cfg.bootstrap_token_used_at = None
    db_session.commit()
    db_session.refresh(cfg)
    return cfg


@pytest.mark.asyncio
async def test_bootstrap_initialize_requires_setup_token(client, db_session):
    _prepare_bootstrap_state(db_session)

    payload = _bootstrap_payload()
    payload.pop("setup_token")
    resp = await client.post("/api/v1/bootstrap/initialize", json=payload)

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_bootstrap_initialize_rejects_wrong_setup_token(client, db_session):
    cfg = _prepare_bootstrap_state(db_session)
    original_hash = cfg.bootstrap_token_hash

    resp = await client.post(
        "/api/v1/bootstrap/initialize",
        json=_bootstrap_payload(setup_token="wrong-token-at-least-16-chars"),
    )

    assert resp.status_code == 403
    assert db_session.query(User).count() == 0
    db_session.refresh(cfg)
    assert cfg.bootstrap_token_hash == original_hash
    assert cfg.bootstrap_token_used_at is None

    retry = await client.post("/api/v1/bootstrap/initialize", json=_bootstrap_payload())
    assert retry.status_code == 200
    assert db_session.query(User).count() == 1


@pytest.mark.asyncio
async def test_bootstrap_initialize_rejects_expired_token_and_rotates_recovery_token(
    client, db_session, monkeypatch, tmp_path
):
    cfg = _prepare_bootstrap_state(db_session)
    cfg.bootstrap_token_expires_at = utcnow() - timedelta(minutes=1)
    db_session.flush()
    monkeypatch.delenv("CB_SETUP_TOKEN", raising=False)
    monkeypatch.setenv("CB_DATA_DIR", str(tmp_path))

    resp = await client.post("/api/v1/bootstrap/initialize", json=_bootstrap_payload())

    assert resp.status_code == 403
    assert db_session.query(User).count() == 0
    token_file = tmp_path / "bootstrap-setup-token"
    assert token_file.exists()
    replacement_token = token_file.read_text(encoding="utf-8").strip()
    assert replacement_token
    assert replacement_token != _SETUP_TOKEN
    db_session.refresh(cfg)
    assert cfg.bootstrap_token_hash == auth_service._hash_bootstrap_token(replacement_token)
    assert cfg.bootstrap_token_expires_at > utcnow()
    assert cfg.bootstrap_token_used_at is None


@pytest.mark.asyncio
async def test_bootstrap_initialize_consumes_setup_token_once(client, db_session):
    cfg = _prepare_bootstrap_state(db_session)

    first = await client.post("/api/v1/bootstrap/initialize", json=_bootstrap_payload())
    client.cookies.clear()
    replay = await client.post(
        "/api/v1/bootstrap/initialize",
        json=_bootstrap_payload(email="second@example.com"),
    )

    assert first.status_code == 200
    assert replay.status_code == 409
    assert db_session.query(User).count() == 1
    db_session.refresh(cfg)
    assert cfg.auth_enabled is True
    assert cfg.bootstrap_token_hash is None
    assert cfg.bootstrap_token_expires_at is None
    assert cfg.bootstrap_token_used_at is not None


@pytest.mark.asyncio
async def test_bootstrap_status_generates_private_setup_token_file(
    client, db_session, monkeypatch, tmp_path
):
    cfg = _prepare_bootstrap_state(db_session)
    cfg.bootstrap_token_hash = None
    cfg.bootstrap_token_expires_at = None
    cfg.bootstrap_token_used_at = None
    monkeypatch.delenv("CB_SETUP_TOKEN", raising=False)
    monkeypatch.setenv("CB_DATA_DIR", str(tmp_path))

    resp = await client.get("/api/v1/bootstrap/status")

    assert resp.status_code == 200
    body = resp.json()
    assert body["needs_bootstrap"] is True
    assert body["setup_token_required"] is True
    assert body["setup_token_expires_at"]
    token_file = tmp_path / "bootstrap-setup-token"
    assert token_file.exists()
    assert token_file.stat().st_mode & 0o777 == 0o600
    db_session.refresh(cfg)
    assert cfg.bootstrap_token_hash == auth_service._hash_bootstrap_token(
        token_file.read_text(encoding="utf-8").strip()
    )


@pytest.mark.asyncio
async def test_bootstrap_status_uses_operator_token_without_disclosing_it(
    client, db_session, monkeypatch, tmp_path
):
    cfg = _prepare_bootstrap_state(db_session)
    cfg.bootstrap_token_hash = None
    cfg.bootstrap_token_expires_at = None
    cfg.bootstrap_token_used_at = None
    operator_token = "operator-provided-bootstrap-token"
    monkeypatch.setenv("CB_SETUP_TOKEN", operator_token)
    monkeypatch.setenv("CB_DATA_DIR", str(tmp_path))

    resp = await client.get("/api/v1/bootstrap/status")

    assert resp.status_code == 200
    assert operator_token not in resp.text
    assert not (tmp_path / "bootstrap-setup-token").exists()
    db_session.refresh(cfg)
    assert cfg.bootstrap_token_hash == auth_service._hash_bootstrap_token(operator_token)
    assert cfg.bootstrap_token_expires_at is not None
    assert cfg.bootstrap_token_used_at is None

    init = await client.post(
        "/api/v1/bootstrap/initialize",
        json=_bootstrap_payload(setup_token=operator_token),
    )
    assert init.status_code == 200
    assert db_session.query(User).count() == 1


@pytest.mark.asyncio
async def test_bootstrap_status_fails_closed_for_invalid_operator_token(
    client, db_session, monkeypatch
):
    cfg = _prepare_bootstrap_state(db_session)
    cfg.bootstrap_token_hash = None
    cfg.bootstrap_token_expires_at = None
    cfg.bootstrap_token_used_at = None
    monkeypatch.setenv("CB_SETUP_TOKEN", "too-short")

    resp = await client.get("/api/v1/bootstrap/status")

    assert resp.status_code == 503
    assert "CB_SETUP_TOKEN must be at least" in resp.json()["detail"]
    assert db_session.query(User).count() == 0


def test_concurrent_bootstrap_requests_create_exactly_one_first_admin(setup_db):
    from app.db.session import SessionLocal

    def reset_committed_state() -> None:
        with SessionLocal() as session:
            session.query(UserSession).delete()
            session.query(User).delete()
            cfg = session.get(AppSettings, 1)
            if cfg is None:
                cfg = AppSettings(id=1)
                session.add(cfg)
                session.flush()
            cfg.auth_enabled = False
            cfg.bootstrap_token_hash = auth_service._hash_bootstrap_token(_SETUP_TOKEN)
            cfg.bootstrap_token_expires_at = utcnow() + timedelta(hours=1)
            cfg.bootstrap_token_used_at = None
            session.commit()

    reset_committed_state()
    barrier = threading.Barrier(2)
    results: list[int] = []
    lock = threading.Lock()

    def worker(index: int) -> None:
        with SessionLocal() as session:
            cfg = session.get(AppSettings, 1)
            assert cfg is not None
            barrier.wait(timeout=10)
            try:
                auth_service.bootstrap_initialize(
                    db=session,
                    cfg=cfg,
                    setup_token=_SETUP_TOKEN,
                    email=f"sec4-race-{index}@example.com",
                    password_or_hash="TestPassword123!",
                    theme_preset="gruvbox-dark",
                )
                status = 200
            except HTTPException as exc:
                status = exc.status_code
            with lock:
                results.append(status)

    threads = [threading.Thread(target=worker, args=(index,)) for index in (1, 2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    assert sorted(results) == [200, 409]
    with SessionLocal() as session:
        users = session.query(User).all()
        cfg = session.get(AppSettings, 1)
        assert len(users) == 1
        assert users[0].is_admin is True
        assert users[0].role == "admin"
        assert cfg is not None
        assert cfg.auth_enabled is True
        assert cfg.bootstrap_token_hash is None
        assert cfg.bootstrap_token_used_at is not None

        session.query(UserSession).delete()
        session.query(User).delete()
        cfg.auth_enabled = True
        session.commit()
