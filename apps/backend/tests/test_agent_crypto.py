from datetime import UTC, datetime, timedelta

import pytest

from app.core.agent_crypto import (
    ClockSkewError,
    check_clock_skew,
    device_identity_matches,
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


# ── in-session transport rekey ─────────────────────────────────────────────


def _handshaken_pair():
    """A completed responder plus the matching test initiator, ready for
    transport traffic in both directions."""
    from app.core.agent_crypto import NoiseIKResponder, _generate_keypair, _public_from_private
    from tests.helpers.agent_noise_client import TestNoiseInitiator

    server_priv, _ = _generate_keypair()
    agent_priv, _ = _generate_keypair()

    responder = NoiseIKResponder(server_priv)
    initiator = TestNoiseInitiator(agent_priv, _public_from_private(server_priv))
    initiator.read_message(responder.read_message(initiator.write_message()))
    return responder, initiator


@pytest.mark.parametrize(
    ("agent_rekeys_per_round", "server_rekeys_per_round"),
    [(1, 1), (3, 1), (1, 2), (1, 0), (0, 1)],
    ids=["even", "agent-faster", "server-faster", "agent-only", "server-only"],
)
def test_rekey_keeps_both_directions_working_across_intervals(
    agent_rekeys_per_round, server_rekeys_per_round
):
    """Several rekey intervals in sequence, with the two directions advancing
    at deliberately different rates — neither side's timer waits on the
    other's, so an implementation that coupled them would break here."""
    responder, initiator = _handshaken_pair()

    for round_no in range(5):
        for i in range(2):
            up = f"agent->server r{round_no} m{i}".encode()
            assert responder.decrypt(initiator.encrypt(up)) == up

            down = f"server->agent r{round_no} m{i}".encode()
            assert initiator.decrypt(responder.encrypt(down)) == down

        for _ in range(agent_rekeys_per_round):
            # The announcement itself would go out under the old key; both
            # halves of that direction then advance one generation.
            initiator.rekey_send()
            responder.rekey_recv(initiator.send_generation)
        for _ in range(server_rekeys_per_round):
            generation = responder.next_send_generation
            responder.rekey_send()
            initiator.rekey_recv()
            assert initiator.recv_generation == generation


def test_rekey_send_generation_advances_one_at_a_time():
    responder, _initiator = _handshaken_pair()

    assert responder.next_send_generation == 1
    responder.rekey_send()
    assert responder.next_send_generation == 2
    responder.rekey_send()
    assert responder.next_send_generation == 3


@pytest.mark.parametrize(
    ("applied", "offered"),
    [(0, 0), (0, 2), (2, 2), (2, 1), (2, 4)],
    ids=["zero", "skips-first", "replay", "decreasing", "gap"],
)
def test_rekey_recv_rejects_out_of_step_generations(applied, offered):
    """Generations are strictly sequential from 1. Anything else means our view
    of the agent's send cipher has diverged from the agent's own, which is
    fatal to the session rather than a droppable frame."""
    from app.core.agent_crypto import RekeyError

    responder, initiator = _handshaken_pair()
    for _ in range(applied):
        initiator.rekey_send()
        responder.rekey_recv(initiator.send_generation)

    with pytest.raises(RekeyError):
        responder.rekey_recv(offered)


def test_rekey_recv_rejection_leaves_the_cipher_untouched():
    """A rejected announcement must not half-apply: traffic encrypted under the
    generation actually in force still decrypts afterwards."""
    from app.core.agent_crypto import RekeyError

    responder, initiator = _handshaken_pair()
    initiator.rekey_send()
    responder.rekey_recv(initiator.send_generation)

    with pytest.raises(RekeyError):
        responder.rekey_recv(99)

    assert responder.decrypt(initiator.encrypt(b"still in step")) == b"still in step"


def test_one_sided_rekey_breaks_only_that_direction():
    """The two ciphers are fully independent: a missed rekey on one direction
    must not disturb the other."""
    from dissononce.exceptions.decrypt import DecryptFailedException

    responder, initiator = _handshaken_pair()

    initiator.rekey_send()  # responder never applies the matching rekey_recv

    with pytest.raises(DecryptFailedException):
        responder.decrypt(initiator.encrypt(b"ping"))

    assert initiator.decrypt(responder.encrypt(b"still fine")) == b"still fine"


def test_rekey_before_handshake_raises():
    from app.core.agent_crypto import NoiseIKResponder, _generate_keypair

    server_priv, _ = _generate_keypair()
    responder = NoiseIKResponder(server_priv)

    with pytest.raises(RuntimeError):
        responder.rekey_send()
    with pytest.raises(RuntimeError):
        responder.rekey_recv(1)


def test_production_rekey_interval_is_fifteen_minutes():
    from app.core.agent_crypto import REKEY_INTERVAL_SECONDS

    assert REKEY_INTERVAL_SECONDS == 15 * 60


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


# ── device_identity_matches (Task 27) ──────────────────────────────────────


def test_device_identity_matches_current_key_with_no_pending_rotation():
    assert device_identity_matches("aa", current_pk="aa", pending_pk=None, pending_expiry=None)


def test_device_identity_matches_rejects_unrecognized_key_with_no_pending_rotation():
    assert not device_identity_matches("bb", current_pk="aa", pending_pk=None, pending_expiry=None)


def test_device_identity_matches_current_key_still_accepted_during_active_rotation():
    # The old key must keep working throughout the transition window — an
    # agent that hasn't switched to its successor yet is not locked out.
    assert device_identity_matches(
        "aa",
        current_pk="aa",
        pending_pk="bb",
        pending_expiry=_REF + timedelta(minutes=10),
        now=_REF,
    )


def test_device_identity_matches_pending_key_accepted_within_window():
    assert device_identity_matches(
        "bb",
        current_pk="aa",
        pending_pk="bb",
        pending_expiry=_REF + timedelta(minutes=10),
        now=_REF,
    )


def test_device_identity_matches_pending_key_accepted_exactly_at_expiry():
    expiry = _REF + timedelta(minutes=15)
    assert device_identity_matches(
        "bb", current_pk="aa", pending_pk="bb", pending_expiry=expiry, now=expiry
    )


def test_device_identity_matches_rejects_pending_key_past_expiry():
    assert not device_identity_matches(
        "bb",
        current_pk="aa",
        pending_pk="bb",
        pending_expiry=_REF - timedelta(seconds=1),
        now=_REF,
    )


def test_device_identity_matches_rejects_unrelated_key_even_with_active_rotation():
    assert not device_identity_matches(
        "cc",
        current_pk="aa",
        pending_pk="bb",
        pending_expiry=_REF + timedelta(minutes=10),
        now=_REF,
    )


def test_device_identity_matches_pending_key_without_expiry_is_never_accepted():
    # Defensive: pending_pk set with no expiry (shouldn't happen given
    # start_device_key_rotation always sets both together) must not match.
    assert not device_identity_matches(
        "bb", current_pk="aa", pending_pk="bb", pending_expiry=None, now=_REF
    )


def test_device_identity_matches_naive_pending_expiry_is_treated_as_utc():
    naive_expiry = (_REF + timedelta(minutes=10)).replace(tzinfo=None)
    assert device_identity_matches(
        "bb", current_pk="aa", pending_pk="bb", pending_expiry=naive_expiry, now=_REF
    )


def test_device_identity_matches_naive_now_is_treated_as_utc():
    naive_now = _REF.replace(tzinfo=None)
    assert device_identity_matches(
        "bb",
        current_pk="aa",
        pending_pk="bb",
        pending_expiry=_REF + timedelta(minutes=10),
        now=naive_now,
    )


def test_device_identity_matches_defaults_now_to_the_real_current_time():
    assert device_identity_matches(
        "bb",
        current_pk="aa",
        pending_pk="bb",
        pending_expiry=datetime.now(UTC) + timedelta(minutes=10),
    )
