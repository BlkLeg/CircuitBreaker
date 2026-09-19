"""The script an agent downloads must name the same address the UI promised."""

from __future__ import annotations

import hashlib
import re
import shlex
from urllib.parse import urlparse

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


def _ensure_server_key_committed() -> None:
    """Pre-generate `AppSettings.agent_server_private_key` through a real,
    committed connection, so no route needs to write it during the test.

    Both `/api/v1/agents/install-command` (via `db_session`) and
    `/install-agent.sh` (via its own `SessionLocal()`) call
    `agent_crypto.load_server_key_rotation_state`, which generates-and-persists
    the key on its *first* use if the column is still unset. Left unset here,
    whichever of the two connections runs first takes a row lock on
    `app_settings` id=1 inside its own transaction to write it — `db_session`'s
    is a SAVEPOINT that is never really committed until teardown, so the
    *second* connection's identical write blocks on that lock until pytest's
    statement/test timeout: a hang, not a clean failure, and one that only
    shows up when this test runs standalone rather than after a sibling test
    that happened to seed the key first. Pre-seeding it for real means neither
    session ever attempts that write, so there is no lock to contend over.
    Idempotent: a key already committed by an earlier test in this session is
    read, not regenerated. Same pattern as
    test_ws_agents_link.py::_start_server_key_rotation_committed.
    """
    from app.core.agent_crypto import load_server_key_rotation_state
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        load_server_key_rotation_state(db)


@pytest.fixture
def committed_server_key():
    """See `_ensure_server_key_committed` -- nothing to tear down, since an
    already-generated key is exactly the steady-state a real deployment is
    in and other tests already rely on that being idempotent."""
    _ensure_server_key_committed()


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
    client, committed_public_endpoint, live_selfsigned_cert, committed_server_key
):
    resp = await client.get("/install-agent.sh?endpoint=pub1")

    assert resp.status_code == 200
    assert re.search(r'CB_SERVER_URL="https://cb\.example\.com"', resp.text)


def _download_url(command: str) -> str:
    """The `/install-agent.sh` URL an emitted install command downloads.

    Split the way a shell would, so a quoted URL and a bare one both resolve
    to the same string.
    """
    for token in shlex.split(command):
        if "/install-agent.sh" in token:
            return token
    raise AssertionError(f"no install-agent.sh download in command: {command!r}")


@pytest.mark.asyncio
async def test_digest_matches_the_url_the_command_actually_emits(
    client, auth_headers, committed_public_endpoint, live_selfsigned_cert, committed_server_key
):
    """Parity for the URL the product emits, not one the test constructs.

    Hand-appending `?endpoint=pub1` to both requests verifies parity for a URL
    nothing ever downloads. The target machine runs whatever the *command*
    says, so the download here is driven by the command: if the emitted URL
    ever loses the query string, this fetches the `forwarded_base_url`
    fallback variant and its digest stops matching -- exactly the
    `sha256sum -c` failure an operator would read as tampering.
    """
    command = await client.get("/api/v1/agents/install-command?endpoint=pub1", headers=auth_headers)
    assert command.status_code == 200, command.text
    body = command.json()

    # Path and query verbatim from the command; only the host is swapped for
    # the ASGI test client's, since "cb.example.com" is not a host it serves.
    emitted = urlparse(_download_url(body["command"]))
    assert emitted.query == "endpoint=pub1", body["command"]
    script = await client.get(f"{emitted.path}?{emitted.query}")

    assert script.status_code == 200, script.text
    assert 'CB_SERVER_URL="https://cb.example.com"' in script.text
    assert body["script_sha256"] == hashlib.sha256(script.text.encode()).hexdigest()


@pytest.mark.asyncio
async def test_unknown_endpoint_is_refused(client):
    resp = await client.get("/install-agent.sh?endpoint=nope")
    assert resp.status_code == 404
