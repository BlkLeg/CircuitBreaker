"""Server-side X25519 identity and Noise IK responder for the agent link.

The server holds one static X25519 keypair for its whole lifetime, generated on
first use and persisted (encrypted) via the existing credential vault. Every
enrolling/linking agent verifies against this same public key.

Rekeying is out of scope for this slice: a link session is re-established
(fresh Noise IK handshake) on every reconnect, so a single-handshake
responder per connection is correct and complete here. In-session rekey is
deferred to a later slice.

SECURITY: this module handles the server's static private key. Never log key
material (private key bytes/hex, shared secrets, or raw handshake payloads).
"""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime
from functools import lru_cache

from cryptography.hazmat.primitives.asymmetric import x25519
from dissononce.cipher.chachapoly import ChaChaPolyCipher
from dissononce.dh.x25519.keypair import KeyPair as X25519KeyPair
from dissononce.dh.x25519.private import PrivateKey as X25519PrivateKey
from dissononce.dh.x25519.public import PublicKey as X25519PublicKey
from dissononce.dh.x25519.x25519 import X25519DH
from dissononce.hash.sha256 import SHA256Hash
from dissononce.processing.handshakepatterns.interactive.IK import IKHandshakePattern
from dissononce.processing.impl.cipherstate import CipherState
from dissononce.processing.impl.handshakestate import HandshakeState
from dissononce.processing.impl.symmetricstate import SymmetricState

from app.core.time import utcnow

_logger = logging.getLogger(__name__)

_CLOCK_SKEW_SECONDS = 60


class ClockSkewError(Exception):
    """Raised when a handshake timestamp falls outside the allowed skew window."""


def _generate_keypair() -> tuple[bytes, bytes]:
    """Generate a fresh raw X25519 keypair: (private_bytes, public_bytes), 32 bytes each."""
    priv = x25519.X25519PrivateKey.generate()
    priv_bytes = priv.private_bytes_raw()
    pub_bytes = priv.public_key().public_bytes_raw()
    return priv_bytes, pub_bytes


@lru_cache(maxsize=1)
def _load_or_create_keypair() -> tuple[bytes, bytes]:
    """Load the server's static keypair from the DB (vault-decrypting it), or
    generate and persist one on first use. Cached for the process lifetime —
    this is a single stable identity for the server's whole lifetime, not a
    per-request value.
    """
    from app.db.session import SessionLocal
    from app.services.credential_vault import get_vault
    from app.services.settings_service import get_or_create_settings

    vault = get_vault()
    with SessionLocal() as db:
        row = get_or_create_settings(db)
        if row.agent_server_private_key:
            priv_hex = vault.decrypt(row.agent_server_private_key)
            priv_bytes = bytes.fromhex(priv_hex)
            pub_bytes = (
                x25519.X25519PrivateKey.from_private_bytes(priv_bytes)
                .public_key()
                .public_bytes_raw()
            )
            return priv_bytes, pub_bytes

        priv_bytes, pub_bytes = _generate_keypair()
        row.agent_server_private_key = vault.encrypt(priv_bytes.hex())
        db.commit()
        _logger.info("agent_crypto: generated new server static X25519 identity")
        return priv_bytes, pub_bytes


def get_server_static_keypair() -> tuple[bytes, bytes]:
    """Return (private_bytes, public_bytes), 32 bytes each, generating once on first call."""
    return _load_or_create_keypair()


def server_fingerprint() -> str:
    """32 lowercase hex chars over the server static public key. Grouping into
    XXXX-XXXX-... groups is a display concern handled by callers."""
    _, pub = get_server_static_keypair()
    return hashlib.sha256(pub).hexdigest()[:32]


def check_clock_skew(ts: datetime, *, now: datetime | None = None) -> None:
    """Raise ClockSkewError if *ts* is more than 60s away from *now* (default:
    the real current time). Naive datetimes are treated as UTC."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    reference = now if now is not None else utcnow()
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)

    delta = abs((reference - ts).total_seconds())
    if delta > _CLOCK_SKEW_SECONDS:
        raise ClockSkewError(
            f"handshake timestamp skew {delta:.1f}s exceeds {_CLOCK_SKEW_SECONDS}s"
        )


def _keypair_from_private(priv_bytes: bytes) -> X25519KeyPair:
    """Build a dissononce X25519KeyPair from raw 32-byte private key material."""
    pub_bytes = (
        x25519.X25519PrivateKey.from_private_bytes(priv_bytes).public_key().public_bytes_raw()
    )
    return X25519KeyPair(X25519PublicKey(pub_bytes), X25519PrivateKey(priv_bytes))


class NoiseIKResponder:
    """Server-side (responder) half of a single Noise_IK_25519_ChaChaPoly_SHA256
    handshake. One instance is good for exactly one handshake/session — a new
    link session (e.g. on reconnect) gets a fresh instance. Rekeying within a
    session is out of scope for this slice.
    """

    def __init__(self, server_private: bytes) -> None:
        self._state = HandshakeState(
            SymmetricState(CipherState(ChaChaPolyCipher()), SHA256Hash()),
            X25519DH(),
        )
        self._state.initialize(
            IKHandshakePattern(),
            False,
            b"",
            s=_keypair_from_private(server_private),
        )
        # (c1, c2): c1 encrypts/decrypts initiator->responder traffic, c2 the
        # reverse direction (Noise spec 5.2 Split()). As the responder we
        # decrypt with c1 and encrypt with c2.
        self._cipher_pair: tuple[CipherState, CipherState] | None = None

    def read_message(self, data: bytes) -> bytes:
        """Process the initiator's single IK message, return our response message."""
        payload_buf = bytearray()
        self._state.read_message(data, payload_buf)
        response = bytearray()
        self._cipher_pair = self._state.write_message(b"", response)
        return bytes(response)

    def remote_static(self) -> bytes:
        """The agent's device public key, known once the IK handshake's single
        inbound message has been processed by read_message()."""
        return self._state.rs.data if self._state.rs is not None else b""

    def encrypt(self, plaintext: bytes) -> bytes:
        if self._cipher_pair is None:
            raise RuntimeError("handshake not complete: call read_message() first")
        _, send_cipher = self._cipher_pair
        return send_cipher.encrypt_with_ad(b"", plaintext)

    def decrypt(self, ciphertext: bytes) -> bytes:
        if self._cipher_pair is None:
            raise RuntimeError("handshake not complete: call read_message() first")
        recv_cipher, _ = self._cipher_pair
        return recv_cipher.decrypt_with_ad(b"", ciphertext)
