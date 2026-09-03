"""H6: the two fleet-wide trust rotations must leave a record.

`POST /agents/server-key/rotate` rotates the key every agent authenticates the
*server* with. `POST /agents/tls-pin/rotate` rotates the policy every agent
validates the TLS leaf against. Either is the move an attacker with admin
access makes to interpose on the whole fleet, and neither wrote an audit row,
a chained log entry, or anything else.

The middleware backstop does not reach them: it returns early when no rule
matches, and its nested fallback requires a numeric path segment that neither
route has. Slice 4.3 chained ten events covering the *agent's* device key and
left the *server's* two out — worse than unchained, since nothing recorded them
at all.
"""

import pytest

from app.services import log_service


@pytest.fixture
def captured_audit(monkeypatch):
    """`log_audit` writes through `write_log` on its own session, so a real row
    would roll back with this test's transaction. Asserting on the call is the
    established pattern here."""
    written: list[dict] = []
    monkeypatch.setattr(log_service, "write_log", lambda **kw: written.append(kw))
    return written


@pytest.mark.asyncio
async def test_a_server_key_rotation_is_recorded(client, auth_headers, captured_audit):
    resp = await client.post("/api/v1/agents/server-key/rotate", headers=auth_headers)

    assert resp.status_code == 201
    entry = next(e for e in captured_audit if e["action"] == "agent_server_key_rotated")
    assert entry["severity"] == "warn"


@pytest.mark.asyncio
async def test_a_tls_pin_rotation_is_recorded(
    client, auth_headers, captured_audit, self_signed_certificate
):
    resp = await client.post(
        "/api/v1/agents/tls-pin/rotate",
        json={"certificate_id": self_signed_certificate.id},
        headers=auth_headers,
    )

    assert resp.status_code == 201
    entry = next(e for e in captured_audit if e["action"] == "agent_tls_pin_rotated")
    assert entry["severity"] == "warn"
    assert self_signed_certificate.domain in entry["details"]
