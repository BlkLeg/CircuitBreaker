"""The script an agent downloads must name the same address the UI promised."""

from __future__ import annotations

import hashlib
import re

import pytest


def _set_agent_endpoints_committed(entries: list[dict[str, str]]) -> None:
    """Write `agent_endpoints` through a real, committed connection.

    `/install-agent.sh` opens its own `SessionLocal()` rather than going
    through `Depends(get_db)`, so it is a genuinely separate connection from
    the test's `db_session` SAVEPOINT — a write only flushed or committed on
    `db_session` would never become visible there under Postgres's normal
    READ COMMITTED isolation. Same pattern as
    test_ws_agents_link.py::_active_agent_with_key.
    """
    from app.db.session import SessionLocal
    from app.services.settings_service import get_or_create_settings

    with SessionLocal() as db:
        row = get_or_create_settings(db)
        row.agent_endpoints = entries
        db.commit()


@pytest.fixture
def committed_public_endpoint():
    """A real, committed "pub1" endpoint -- reset afterward so it cannot leak
    into another test sharing this same database across the session."""
    _set_agent_endpoints_committed(
        [{"id": "pub1", "label": "Public", "url": "https://cb.example.com"}]
    )
    try:
        yield
    finally:
        _set_agent_endpoints_committed([])


@pytest.fixture
def live_selfsigned_cert(monkeypatch):
    """A valid self-signed cert `_live_nginx_cert_pem` can read, so
    `_tls_mode_and_pin` succeeds no matter which DB session asks -- this
    reads straight off (mocked) disk, not the database, so it works
    identically for a route bound to `db_session` and one that opens its own
    `SessionLocal()`."""
    from app.services import agent_install
    from app.services.certificate_service import generate_selfsigned

    valid_cert_pem, _, _ = generate_selfsigned("cb.example.com")
    monkeypatch.setattr(agent_install, "_live_nginx_cert_pem", lambda: valid_cert_pem)


@pytest.mark.asyncio
async def test_script_renders_the_selected_endpoint(
    client, committed_public_endpoint, live_selfsigned_cert
):
    resp = await client.get("/install-agent.sh?endpoint=pub1")

    assert resp.status_code == 200
    assert re.search(r'CB_SERVER_URL="https://cb\.example\.com"', resp.text)


@pytest.mark.asyncio
async def test_script_digest_matches_the_command_the_ui_showed(
    client, auth_headers, committed_public_endpoint, live_selfsigned_cert
):
    """The operator is told to verify this digest; the two must agree or the
    published check fails on a correct download."""
    command = await client.get("/api/v1/agents/install-command?endpoint=pub1", headers=auth_headers)
    script = await client.get("/install-agent.sh?endpoint=pub1")

    assert command.json()["script_sha256"] == hashlib.sha256(script.text.encode()).hexdigest()


@pytest.mark.asyncio
async def test_unknown_endpoint_is_refused(client):
    resp = await client.get("/install-agent.sh?endpoint=nope")
    assert resp.status_code == 404
