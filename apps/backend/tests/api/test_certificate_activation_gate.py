"""Slice 4.1: activating a certificate no agent has converged on is what
strands the fleet, so it is refused unless the operator forces it.

Certificates are created through the API rather than from the shared
`self_signed_certificate` fixture: activation decrypts `key_pem` through the
credential vault, and only the create route writes a key the vault can read.
This mirrors `tests/api/test_certificates_activate.py`.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def activation_env(monkeypatch, tmp_path):
    """Point activation at a scratch data dir and stub the nginx reload, so
    these tests exercise the gate rather than the host's TLS plumbing."""
    from app.services import certificate_activation as act

    monkeypatch.setenv("CB_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(act, "_reload_tls", lambda: (True, "nginx reloaded"))
    return tmp_path


async def _make_certificate(client, auth_headers, domain: str) -> int:
    resp = await client.post(
        "/api/v1/certificates",
        json={"domain": domain, "type": "selfsigned", "auto_renew": True},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    return int(resp.json()["id"])


async def _rotate(client, auth_headers, cert_id: int) -> None:
    resp = await client.post(
        "/api/v1/agents/tls-pin/rotate",
        json={"certificate_id": cert_id},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text


async def _serve_baseline_certificate(client, auth_headers, domain: str) -> int:
    """Activate one certificate so the install is actually serving something.

    Load-bearing for every test below. The gate's first question is whether
    this activation *changes* the trust policy agents verify against, and
    with nothing on disk for nginx to present there is no policy to change
    and nothing to strand — so a test that skips this step exercises the
    early return, not the gate.
    """
    cert_id = await _make_certificate(client, auth_headers, domain)
    resp = await client.post(f"/api/v1/certificates/{cert_id}/activate", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    return cert_id


@pytest.mark.asyncio
async def test_activation_is_refused_while_agents_are_unconverged(
    client, auth_headers, db_session, factories, activation_env
):
    factories.agent(status="active", hostname="lagging")
    db_session.commit()
    await _serve_baseline_certificate(client, auth_headers, "base-refuse.example.com")
    cert_id = await _make_certificate(client, auth_headers, "gate-refuse.example.com")
    await _rotate(client, auth_headers, cert_id)

    resp = await client.post(f"/api/v1/certificates/{cert_id}/activate", headers=auth_headers)

    assert resp.status_code == 409
    assert "1" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_activation_succeeds_once_every_agent_has_converged(
    client, auth_headers, db_session, factories, activation_env
):
    from app.services import agent_registry

    agent = factories.agent(status="active")
    db_session.commit()
    await _serve_baseline_certificate(client, auth_headers, "base-converged.example.com")
    cert_id = await _make_certificate(client, auth_headers, "gate-converged.example.com")
    await _rotate(client, auth_headers, cert_id)
    agent_registry.record_tls_pin(db_session, agent, "current", successor_ready=True)
    db_session.commit()

    resp = await client.post(f"/api/v1/certificates/{cert_id}/activate", headers=auth_headers)

    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_activation_clears_the_rotation_on_success(
    client, auth_headers, db_session, factories, activation_env
):
    from app.services import agent_registry, agent_tls_pin

    agent = factories.agent(status="active")
    db_session.commit()
    await _serve_baseline_certificate(client, auth_headers, "base-clears.example.com")
    cert_id = await _make_certificate(client, auth_headers, "gate-clears.example.com")
    await _rotate(client, auth_headers, cert_id)
    agent_registry.record_tls_pin(db_session, agent, "current", successor_ready=True)
    db_session.commit()

    resp = await client.post(f"/api/v1/certificates/{cert_id}/activate", headers=auth_headers)
    assert resp.status_code == 200

    db_session.expire_all()
    assert agent_tls_pin.load_tls_pin_rotation_state(db_session).rotation_active is False


@pytest.mark.asyncio
async def test_force_overrides_the_gate(
    client, auth_headers, db_session, factories, activation_env
):
    factories.agent(status="active", hostname="lagging")
    db_session.commit()
    await _serve_baseline_certificate(client, auth_headers, "base-force.example.com")
    cert_id = await _make_certificate(client, auth_headers, "gate-force.example.com")
    await _rotate(client, auth_headers, cert_id)

    resp = await client.post(
        f"/api/v1/certificates/{cert_id}/activate?force=true", headers=auth_headers
    )

    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_force_audits_the_agents_it_strands(
    client, auth_headers, db_session, factories, activation_env
):
    """Stranding must be a decision someone signed for, so the override
    writes an audit entry naming what it is about to break."""
    from app.db.models import Log

    factories.agent(status="active", hostname="lagging")
    db_session.commit()
    await _serve_baseline_certificate(client, auth_headers, "base-audit.example.com")
    cert_id = await _make_certificate(client, auth_headers, "gate-audit.example.com")
    await _rotate(client, auth_headers, cert_id)

    resp = await client.post(
        f"/api/v1/certificates/{cert_id}/activate?force=true", headers=auth_headers
    )
    assert resp.status_code == 200

    db_session.expire_all()
    entries = db_session.query(Log).filter(Log.action == "certificate_activated_forced").all()
    assert entries, "a forced activation must be audited"


@pytest.mark.asyncio
async def test_an_install_with_no_agents_is_never_blocked(client, auth_headers, activation_env):
    """The overwhelming majority of installs. There is nobody to strand, so
    the gate must be invisible — swapping certificates freely is the normal
    case and this mechanism must not tax it."""
    await _serve_baseline_certificate(client, auth_headers, "base-noagents.example.com")
    cert_id = await _make_certificate(client, auth_headers, "gate-noagents.example.com")

    resp = await client.post(f"/api/v1/certificates/{cert_id}/activate", headers=auth_headers)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_a_trust_change_with_no_rotation_at_all_is_refused(
    client, auth_headers, db_session, factories, activation_env
):
    """The likeliest way to hit F4: swap the certificate without knowing this
    mechanism exists. A gate keyed only on the convergence counts would wave
    this through, because those are meaningless while no rotation runs."""
    factories.agent(status="active", hostname="unaware")
    db_session.commit()

    # Activate one certificate so the install is actually serving something
    # an agent could have pinned. There is nothing on disk before this, and
    # nothing on disk means nothing to strand.
    first = await _make_certificate(client, auth_headers, "served.example.com")
    assert (
        await client.post(f"/api/v1/certificates/{first}/activate", headers=auth_headers)
    ).status_code == 200

    second = await _make_certificate(client, auth_headers, "swapped.example.com")
    resp = await client.post(f"/api/v1/certificates/{second}/activate", headers=auth_headers)

    assert resp.status_code == 409
    assert "no rotation has advertised" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_a_rotation_for_a_different_certificate_does_not_open_the_gate(
    client, auth_headers, db_session, factories, activation_env
):
    """Rotating to certificate A and then activating certificate B strands
    the fleet just as thoroughly, and passes a count-only check."""
    from app.services import agent_registry

    agent = factories.agent(status="active")
    db_session.commit()

    first = await _make_certificate(client, auth_headers, "served-b.example.com")
    assert (
        await client.post(f"/api/v1/certificates/{first}/activate", headers=auth_headers)
    ).status_code == 200

    advertised = await _make_certificate(client, auth_headers, "advertised.example.com")
    other = await _make_certificate(client, auth_headers, "other.example.com")
    await _rotate(client, auth_headers, advertised)
    agent_registry.record_tls_pin(db_session, agent, "current", successor_ready=True)
    db_session.commit()

    resp = await client.post(f"/api/v1/certificates/{other}/activate", headers=auth_headers)

    assert resp.status_code == 409
    assert "no rotation has advertised" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_reactivating_the_served_certificate_is_never_blocked(
    client, auth_headers, db_session, factories, activation_env
):
    """Its policy is what agents already trust, so nothing changes for them."""
    factories.agent(status="active")
    db_session.commit()

    cert_id = await _make_certificate(client, auth_headers, "stable.example.com")
    assert (
        await client.post(f"/api/v1/certificates/{cert_id}/activate", headers=auth_headers)
    ).status_code == 200

    again = await client.post(f"/api/v1/certificates/{cert_id}/activate", headers=auth_headers)
    assert again.status_code == 200
