"""Slice 4.1: the TLS trust rotation state machine."""

from datetime import timedelta

from app.core.time import utcnow
from app.services import agent_tls_pin


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
