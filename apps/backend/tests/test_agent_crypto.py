from datetime import UTC, datetime, timedelta

import pytest

from app.core.agent_crypto import (
    ClockSkewError,
    check_clock_skew,
    get_server_static_keypair,
    server_fingerprint,
)


def test_server_static_keypair_is_stable_across_calls(db_session, app_cfg):
    # app_cfg initializes the credential vault (get_server_static_keypair
    # encrypts/decrypts the private key through it); db_session ensures the
    # schema exists. Neither is strictly needed after the first call in this
    # process, since the keypair is cached for the process lifetime, but the
    # first call to touch the DB/vault needs both available.
    priv1, pub1 = get_server_static_keypair()
    priv2, pub2 = get_server_static_keypair()

    assert priv1 == priv2
    assert pub1 == pub2
    assert len(priv1) == 32
    assert len(pub1) == 32


def test_server_fingerprint_is_derived_from_the_public_key():
    import hashlib

    _, pub = get_server_static_keypair()
    expected = hashlib.sha256(pub).hexdigest()[:32]

    assert server_fingerprint() == expected
    assert len(server_fingerprint()) == 32


def test_noise_ik_responder_completes_handshake_against_python_initiator():
    from dissononce.cipher.chachapoly import ChaChaPolyCipher
    from dissononce.dh.x25519.x25519 import X25519DH
    from dissononce.hash.sha256 import SHA256Hash
    from dissononce.processing.handshakepatterns.interactive.IK import IKHandshakePattern
    from dissononce.processing.impl.cipherstate import CipherState as CS
    from dissononce.processing.impl.handshakestate import HandshakeState as HS
    from dissononce.processing.impl.symmetricstate import SymmetricState as SS

    from app.core.agent_crypto import (
        NoiseIKResponder,
        _generate_keypair,
        _keypair_from_private,
    )

    server_priv, server_pub = _generate_keypair()
    agent_priv, agent_pub = _generate_keypair()

    responder = NoiseIKResponder(server_priv)

    initiator = HS(SS(CS(ChaChaPolyCipher()), SHA256Hash()), X25519DH())
    initiator.initialize(
        IKHandshakePattern(),
        True,
        b"",
        s=_keypair_from_private(agent_priv),
        rs=_keypair_from_private(server_priv).public,
    )
    msg1 = bytearray()
    initiator.write_message(b"", msg1)

    msg2 = responder.read_message(bytes(msg1))

    payload = bytearray()
    initiator_ciphers = initiator.read_message(msg2, payload)

    # Handshake payload is empty in this exchange.
    assert bytes(payload) == b""
    # The responder learned the agent's device public key from the handshake.
    assert responder.remote_static() == agent_pub

    send_cipher, _ = initiator_ciphers
    ct = send_cipher.encrypt_with_ad(b"", b"hello from agent")
    pt = responder.decrypt(ct)
    assert pt == b"hello from agent"

    _, recv_cipher = initiator_ciphers
    ct2 = responder.encrypt(b"hello from server")
    pt2 = recv_cipher.decrypt_with_ad(b"", ct2)
    assert pt2 == b"hello from server"


def test_noise_ik_responder_precondition_guards_raise_before_handshake_completes():
    from app.core.agent_crypto import NoiseIKResponder, _generate_keypair

    server_priv, _ = _generate_keypair()
    responder = NoiseIKResponder(server_priv)

    with pytest.raises(RuntimeError):
        responder.remote_static()
    with pytest.raises(RuntimeError):
        responder.encrypt(b"x")
    with pytest.raises(RuntimeError):
        responder.decrypt(b"x")


# ── check_clock_skew / ClockSkewError ──────────────────────────────────────

_REF = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def test_check_clock_skew_within_window_does_not_raise():
    ts = _REF - timedelta(seconds=30)
    check_clock_skew(ts, now=_REF)  # should not raise


def test_check_clock_skew_past_timestamp_outside_window_raises():
    ts = _REF - timedelta(seconds=90)
    with pytest.raises(ClockSkewError):
        check_clock_skew(ts, now=_REF)


def test_check_clock_skew_future_timestamp_outside_window_raises():
    ts = _REF + timedelta(seconds=90)
    with pytest.raises(ClockSkewError):
        check_clock_skew(ts, now=_REF)


def test_check_clock_skew_raises_specifically_clock_skew_error_not_generic():
    ts = _REF - timedelta(seconds=90)
    try:
        check_clock_skew(ts, now=_REF)
    except ClockSkewError:
        pass
    except Exception as exc:  # pragma: no cover - failure path only
        pytest.fail(f"expected ClockSkewError, got {type(exc).__name__}: {exc}")
    else:
        pytest.fail("expected ClockSkewError, nothing was raised")


def test_check_clock_skew_boundary_exactly_60s_does_not_raise():
    # Implementation uses a strict `>` comparison against the 60s threshold,
    # so a delta of exactly 60.0s is still within the allowed window.
    ts = _REF - timedelta(seconds=60)
    check_clock_skew(ts, now=_REF)  # should not raise


def test_check_clock_skew_boundary_just_over_60s_raises():
    ts = _REF - timedelta(seconds=60, milliseconds=1)
    with pytest.raises(ClockSkewError):
        check_clock_skew(ts, now=_REF)


def test_check_clock_skew_naive_timestamp_is_treated_as_utc_and_does_not_typeerror():
    # A naive ts (no tzinfo) must not blow up comparing against an
    # aware `now` — it should be treated as UTC, matching app.core.time's
    # convention elsewhere in the codebase.
    naive_ts = _REF.replace(tzinfo=None) - timedelta(seconds=30)
    check_clock_skew(naive_ts, now=_REF)  # should not raise, and not TypeError


def test_check_clock_skew_naive_timestamp_outside_window_raises_clock_skew_error():
    naive_ts = _REF.replace(tzinfo=None) - timedelta(seconds=90)
    with pytest.raises(ClockSkewError):
        check_clock_skew(naive_ts, now=_REF)


def test_check_clock_skew_defaults_now_to_the_real_current_time():
    # No `now=` passed: a very old timestamp must still raise using the
    # real wall-clock default.
    with pytest.raises(ClockSkewError):
        check_clock_skew(datetime(2000, 1, 1, tzinfo=UTC))
