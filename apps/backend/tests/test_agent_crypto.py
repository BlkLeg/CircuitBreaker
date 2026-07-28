from app.core.agent_crypto import get_server_static_keypair, server_fingerprint


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
