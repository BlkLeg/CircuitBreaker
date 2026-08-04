"""Python-side Noise IK *initiator*, used only by tests to simulate the Go
agent's handshake and transport behavior against the real ws_agents.py
responder — see app.core.agent_crypto.NoiseIKResponder for the server-side
half, and apps/agent/internal/link/link.go for the Go behavior this mirrors.

The rekey helpers below deliberately reuse the production ``_spec_rekey``
rather than reimplementing REKEY, so a test passing here means the real
derivation ran. That the derivation matches the Go agent's is proven
separately, against a shared fixture, in test_noise_rekey_conformance.py."""

from __future__ import annotations

from dissononce.cipher.chachapoly import ChaChaPolyCipher
from dissononce.dh.x25519.public import PublicKey as X25519PublicKey
from dissononce.dh.x25519.x25519 import X25519DH
from dissononce.hash.sha256 import SHA256Hash
from dissononce.processing.handshakepatterns.interactive.IK import IKHandshakePattern
from dissononce.processing.impl.cipherstate import CipherState
from dissononce.processing.impl.handshakestate import HandshakeState
from dissononce.processing.impl.symmetricstate import SymmetricState

from app.core.agent_crypto import _keypair_from_private, _spec_rekey


class TestNoiseInitiator:
    __test__ = False  # not a pytest test class despite the name

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
        self.send_generation = 0
        self.recv_generation = 0

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

    def rekey_send(self) -> None:
        """Rotate the agent->server cipher. Callers must have already sent the
        `transport.rekey` announcement under the old key."""
        send_cipher, _ = self._ciphers
        _spec_rekey(send_cipher)
        self.send_generation += 1

    def rekey_recv(self) -> None:
        """Rotate the server->agent cipher, immediately after decrypting the
        server's `transport.rekey` announcement."""
        _, recv_cipher = self._ciphers
        _spec_rekey(recv_cipher)
        self.recv_generation += 1
