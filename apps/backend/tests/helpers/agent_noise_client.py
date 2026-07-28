"""Python-side Noise IK *initiator*, used only by tests to simulate the Go
agent's handshake behavior against the real ws_agents.py responder — see
app.core.agent_crypto.NoiseIKResponder for the server-side half."""

from __future__ import annotations

from dissononce.cipher.chachapoly import ChaChaPolyCipher
from dissononce.dh.x25519.public import PublicKey as X25519PublicKey
from dissononce.dh.x25519.x25519 import X25519DH
from dissononce.hash.sha256 import SHA256Hash
from dissononce.processing.handshakepatterns.interactive.IK import IKHandshakePattern
from dissononce.processing.impl.cipherstate import CipherState
from dissononce.processing.impl.handshakestate import HandshakeState
from dissononce.processing.impl.symmetricstate import SymmetricState

from app.core.agent_crypto import _keypair_from_private


class TestNoiseInitiator:
    def __init__(self, agent_private: bytes, server_public: bytes) -> None:
        self._state = HandshakeState(
            SymmetricState(CipherState(ChaChaPolyCipher()), SHA256Hash()),
            X25519DH(),
        )
        self._state.initialize(
            IKHandshakePattern(),
            True,
            b"",
            s=_keypair_from_private(agent_private),
            rs=X25519PublicKey(server_public),
        )
        self._ciphers: tuple[CipherState, CipherState] | None = None

    def write_message(self) -> bytes:
        buf = bytearray()
        self._state.write_message(b"", buf)
        return bytes(buf)

    def read_message(self, data: bytes) -> None:
        payload = bytearray()
        self._ciphers = self._state.read_message(data, payload)

    def encrypt(self, plaintext: bytes) -> bytes:
        send_cipher, _ = self._ciphers
        return send_cipher.encrypt_with_ad(b"", plaintext)

    def decrypt(self, ciphertext: bytes) -> bytes:
        _, recv_cipher = self._ciphers
        return recv_cipher.decrypt_with_ad(b"", ciphertext)
