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


def _restore_bootstrapped_state(db_session) -> None:
    """Put `auth_enabled` back so a bootstrap test cannot disarm later ones.

    `AppSettings` is seeded once per session by the `app_cfg` fixture and is not
    covered by the per-test rollback, so a test that turns auth off has to turn
    it back on itself.
    """
    cfg = db_session.get(AppSettings, 1)
    if cfg is not None:
        cfg.auth_enabled = True
        db_session.commit()


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
    # bootstrap_initialize generates a vault key and commits its hash to
    # app_settings (auth_service._generate_and_persist_vault_key). This test
    # drives it on committed sessions rather than the rolled-back db_session
    # fixture, so that hash outlives the test unless it is put back — and
    # tests/test_config_validate.py then reports the process CB_VAULT_KEY as
    # stale against it and fails, from the other side of the suite.
    with SessionLocal() as session:
        _cfg = session.get(AppSettings, 1)
        vault_state_before = {
            "vault_key": _cfg.vault_key,
            "vault_key_hash": _cfg.vault_key_hash,
            "vault_key_rotated_at": _cfg.vault_key_rotated_at,
        }
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
        for _name, _value in vault_state_before.items():
            setattr(cfg, _name, _value)
        session.commit()


# ── SEC-09 / P0-4: the setup window is not an open admin session ─────────────
# Before the first admin exists there is nobody to authenticate, so first-run
# runs as the admin sentinel. It used to do that on every route, which let
# anyone who could reach the port during the window rewrite settings and OAuth
# providers — and so capture the operator's account as it was created.


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/v1/hardware"),
        ("get", "/api/v1/monitors"),
        ("get", "/api/v1/agents"),
        ("get", "/api/v1/logs"),
        ("post", "/api/v1/admin/clear-lab"),
    ],
)
async def test_unbootstrapped_app_does_not_hand_out_admin_off_the_setup_surface(
    client, db_session, method, path
):
    _prepare_bootstrap_state(db_session)
    try:
        resp = await getattr(client, method)(path)
        assert resp.status_code in (401, 403), f"{method.upper()} {path} -> {resp.status_code}"
    finally:
        _restore_bootstrapped_state(db_session)


@pytest.mark.asyncio
async def test_unbootstrapped_app_cannot_rewrite_settings_before_an_admin_exists(
    client, db_session
):
    _prepare_bootstrap_state(db_session)
    try:
        resp = await client.put("/api/v1/settings", json={"site_name": "attacker"})
        assert resp.status_code in (401, 403)
    finally:
        _restore_bootstrapped_state(db_session)


@pytest.mark.asyncio
async def test_first_run_surface_still_reachable_while_unbootstrapped(client, db_session):
    """The wizard's own calls must keep working, or OOBE cannot complete."""
    _prepare_bootstrap_state(db_session)
    try:
        assert (await client.get("/api/v1/bootstrap/status")).status_code == 200
        assert (await client.get("/api/v1/settings")).status_code == 200
        # The OAuth provider step runs before an account can exist.
        oauth = await client.patch("/api/v1/settings/oauth", json={"oidc_providers": []})
        assert oauth.status_code not in (401, 403)
    finally:
        _restore_bootstrapped_state(db_session)


# ── Pointing the operator at the token ───────────────────────────────────────
# OOBE used to say "find this in your server data directory", which is not a
# place — CB_DATA_DIR is /var/lib/circuitbreaker on a native install and /data
# in the container. The status response carries the resolved path so the wizard
# can print a command that works, without ever carrying the token itself.


@pytest.mark.asyncio
async def test_bootstrap_status_points_at_the_token_file(client, db_session, monkeypatch, tmp_path):
    cfg = _prepare_bootstrap_state(db_session)
    cfg.bootstrap_token_hash = None
    cfg.bootstrap_token_expires_at = None
    cfg.bootstrap_token_used_at = None
    monkeypatch.delenv("CB_SETUP_TOKEN", raising=False)
    monkeypatch.setenv("CB_DATA_DIR", str(tmp_path))

    resp = await client.get("/api/v1/bootstrap/status")

    assert resp.status_code == 200
    body = resp.json()
    token_file = tmp_path / "bootstrap-setup-token"
    assert body["setup_token_path"] == str(token_file)
    # The path is a signpost; the token behind it stays on the server (SEC-09).
    assert token_file.read_text(encoding="utf-8").strip() not in resp.text


@pytest.mark.asyncio
async def test_bootstrap_status_omits_the_path_when_the_operator_supplied_the_token(
    client, db_session, monkeypatch, tmp_path
):
    """CB_SETUP_TOKEN writes no file, so there is no path to point at."""
    cfg = _prepare_bootstrap_state(db_session)
    cfg.bootstrap_token_hash = None
    cfg.bootstrap_token_expires_at = None
    cfg.bootstrap_token_used_at = None
    operator_token = "operator-provided-bootstrap-token"
    monkeypatch.setenv("CB_SETUP_TOKEN", operator_token)
    monkeypatch.setenv("CB_DATA_DIR", str(tmp_path))

    resp = await client.get("/api/v1/bootstrap/status")

    assert resp.status_code == 200
    assert resp.json()["setup_token_path"] is None
    assert operator_token not in resp.text


@pytest.mark.asyncio
async def test_bootstrap_status_stops_pointing_at_the_token_once_bootstrapped(
    client, db_session, monkeypatch, tmp_path
):
    """A completed install has no reason to hand out filesystem paths pre-auth."""
    monkeypatch.delenv("CB_SETUP_TOKEN", raising=False)
    monkeypatch.setenv("CB_DATA_DIR", str(tmp_path))
    _restore_bootstrapped_state(db_session)

    resp = await client.get("/api/v1/bootstrap/status")

    assert resp.status_code == 200
    body = resp.json()
    assert body["needs_bootstrap"] is False
    assert body["setup_token_path"] is None
