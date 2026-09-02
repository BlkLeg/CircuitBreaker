"""Slice 4.1: the TLS trust rotation state machine."""

from datetime import timedelta

import pytest

from app.core.time import utcnow
from app.services import agent_tls_pin


def _make_unrelated_cert_pem() -> str:
    """A throwaway leaf, generated at import time rather than committed —
    key material never lives in the repo (CLAUDE.md). Only its public half
    is ever used here, but generating it keeps the rule uniform."""
    from datetime import timedelta

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "served.cb-test.invalid")])
    now = utcnow()
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(hours=1))
        .sign(key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM).decode()


_UNRELATED_CERT_PEM = _make_unrelated_cert_pem()


def test_no_rotation_reads_as_inactive(db_session):
    state = agent_tls_pin.load_tls_pin_rotation_state(db_session)
    assert state.rotation_active is False
    assert state.successor_mode is None
    assert state.successor_pin is None


def test_start_records_a_self_signed_successor(db_session, self_signed_certificate):
    state = agent_tls_pin.start_tls_pin_rotation(db_session, self_signed_certificate)
    assert state is not None
    assert state.rotation_active is True
    assert state.successor_mode == "self_signed"
    assert state.successor_pin  # a real SPKI digest, not empty
    assert state.overlap_expires_at is not None


def test_start_records_a_public_cutover_with_no_pin(db_session, letsencrypt_certificate):
    """A Let's Encrypt successor drops the pin. The rotation is still active —
    an empty pin is a policy, not an absence."""
    state = agent_tls_pin.start_tls_pin_rotation(db_session, letsencrypt_certificate)
    assert state is not None
    assert state.rotation_active is True
    assert state.successor_mode == "public"
    assert state.successor_pin == ""


def test_second_start_while_active_is_refused(db_session, self_signed_certificate):
    assert agent_tls_pin.start_tls_pin_rotation(db_session, self_signed_certificate) is not None
    assert agent_tls_pin.start_tls_pin_rotation(db_session, self_signed_certificate) is None


def test_complete_clears_every_column(db_session, self_signed_certificate):
    agent_tls_pin.start_tls_pin_rotation(db_session, self_signed_certificate)
    agent_tls_pin.complete_tls_pin_rotation(db_session)

    state = agent_tls_pin.load_tls_pin_rotation_state(db_session)
    assert state.rotation_active is False
    assert state.successor_pin is None
    assert state.started_at is None
    assert state.overlap_expires_at is None


def test_overlap_defaults_to_seven_days(db_session, self_signed_certificate):
    now = utcnow()
    state = agent_tls_pin.start_tls_pin_rotation(db_session, self_signed_certificate, now=now)
    assert state is not None
    expected = now + timedelta(seconds=agent_tls_pin.TLS_PIN_OVERLAP_SECONDS)
    assert state.overlap_expires_at == expected


def test_record_tls_pin_marks_the_successor_bucket(db_session, factories):
    from app.services import agent_registry

    agent = factories.agent(status="active")
    agent_registry.record_tls_pin(db_session, agent, "successor")

    assert agent.tls_pin_successor_pinned_at is not None
    assert agent.tls_pin_current_pinned_at is None


def test_record_tls_pin_marks_the_current_bucket(db_session, factories):
    from app.services import agent_registry

    agent = factories.agent(status="active")
    agent_registry.record_tls_pin(db_session, agent, "current")

    assert agent.tls_pin_current_pinned_at is not None
    assert agent.tls_pin_successor_pinned_at is None


def test_record_tls_pin_ignores_an_unreported_kind(db_session, factories):
    """An agent predating this mechanism sends no tls_pin_kind at all. That
    must leave both columns untouched rather than being counted as
    convergence on the current policy — an agent that cannot report is
    exactly the one an operator must not be told has converged."""
    from app.services import agent_registry

    agent = factories.agent(status="active")
    agent_registry.record_tls_pin(db_session, agent, "")

    assert agent.tls_pin_current_pinned_at is None
    assert agent.tls_pin_successor_pinned_at is None


@pytest.mark.asyncio
async def test_broadcast_pushes_only_to_online_active_agents(
    db_session, factories, monkeypatch, self_signed_certificate
):
    from app.services import agent_registry

    online = factories.agent(status="active")
    offline = factories.agent(status="active")
    pushed: list[int] = []

    async def fake_presence(ids):
        return {online.id: {"online": True}, offline.id: {"online": False}}

    async def fake_publish(agent_id, frame):
        assert frame["type"] == "tls.pin.rotate"
        assert frame["payload"]["mode"] == "self_signed"
        pushed.append(agent_id)

    monkeypatch.setattr(agent_registry, "bulk_presence", fake_presence)
    monkeypatch.setattr(agent_registry, "publish_agent_control_frame", fake_publish)

    state = agent_tls_pin.start_tls_pin_rotation(db_session, self_signed_certificate)
    assert state is not None
    count = await agent_registry.broadcast_tls_pin_rotate(db_session, state)

    assert pushed == [online.id]
    assert count == 1


def test_successor_is_the_staged_certificate_not_the_one_nginx_serves(
    db_session, self_signed_certificate, monkeypatch, tmp_path
):
    """The whole point of a successor is that it differs from what is being
    served right now.

    `agent_install._tls_mode_and_pin` deliberately prefers the live nginx
    certificate over the `Certificate` row it is handed — correct for the
    install command, which must hand a new agent the pin its very next
    handshake will see. It is wrong here: on any real install
    `{CB_DATA_DIR}/tls/fullchain.pem` exists, so deriving the successor
    through it would advertise the pin the fleet already trusts, every agent
    would "converge" on a policy nothing changed, and the activation gate
    would wave through the cutover that strands them all.
    """
    from app.services.agent_install import _spki_pin

    served = tmp_path / "tls"
    served.mkdir()
    (served / "fullchain.pem").write_text(_UNRELATED_CERT_PEM)
    monkeypatch.setenv("CB_DATA_DIR", str(tmp_path))

    state = agent_tls_pin.start_tls_pin_rotation(db_session, self_signed_certificate)

    assert state is not None
    assert state.successor_pin == _spki_pin(self_signed_certificate.cert_pem)
    assert state.successor_pin != _spki_pin(_UNRELATED_CERT_PEM)


def test_readiness_alone_marks_the_successor_bucket(db_session, factories):
    """An agent that holds the advertised successor but still matches the
    current policy is exactly the agent the gate must count as converged —
    it will survive the cutover. Before the cutover, that is every reachable
    agent, so this is the normal case rather than an edge one."""
    from app.services import agent_registry

    agent = factories.agent(status="active")
    agent_registry.record_tls_pin(db_session, agent, "current", successor_ready=True)

    assert agent.tls_pin_successor_pinned_at is not None
    assert agent.tls_pin_current_pinned_at is not None


def test_a_reachable_fleet_converges_before_the_cutover(
    db_session, factories, self_signed_certificate
):
    """The deadlock regression.

    Convergence used to be keyed on a successor *match*, which an agent can
    only report after the server serves the successor — i.e. after the very
    activation the gate guards. Every rotation therefore had to be forced,
    which is the stranding the gate exists to prevent.
    """
    from app.services import agent_registry

    agent = factories.agent(status="active")
    state = agent_tls_pin.start_tls_pin_rotation(db_session, self_signed_certificate)
    assert state is not None

    # What the agent reports on its next hello, with the OLD certificate
    # still being served: it matched current, and it holds the successor.
    agent_registry.record_tls_pin(db_session, agent, "current", successor_ready=True)

    converged, unconverged = agent_tls_pin.convergence_counts(db_session, state)
    assert (converged, unconverged) == (1, 0)


def test_an_agent_that_never_heard_the_advertisement_blocks(
    db_session, factories, self_signed_certificate
):
    """The other half: an agent that dialed but does not hold the successor
    — offline during the broadcast, or predating the mechanism — must keep
    the gate shut. It is the agent the cutover would strand."""
    from app.services import agent_registry

    agent = factories.agent(status="active")
    state = agent_tls_pin.start_tls_pin_rotation(db_session, self_signed_certificate)
    assert state is not None

    agent_registry.record_tls_pin(db_session, agent, "current", successor_ready=False)

    converged, unconverged = agent_tls_pin.convergence_counts(db_session, state)
    assert (converged, unconverged) == (0, 1)
