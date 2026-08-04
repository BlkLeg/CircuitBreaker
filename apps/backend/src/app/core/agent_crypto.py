"""Server-side X25519 identity and Noise IK responder for the agent link.

The server holds one static X25519 keypair for its whole lifetime, generated on
first use and persisted (encrypted) via the existing credential vault. Every
enrolling/linking agent verifies against this same public key.

A link session is established by one Noise IK handshake per connection, and
its two transport ciphers are then rekeyed in place every REKEY_INTERVAL_SECONDS
— independently per direction — via `transport.rekey` control frames (see
`NoiseIKResponder.rekey_send`/`rekey_recv` and ws_agents.py's link_stream).
Long-term key rotation (`key.rotate`) is a separate mechanism and is not
handled here.

SECURITY: this module handles the server's static private key. Never log key
material (private key bytes/hex, shared secrets, or raw handshake payloads).
"""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime
from functools import lru_cache
from typing import cast

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

# How often each side rotates its *own* outbound transport cipher. The agent
# times its agent->server cipher in internal/link/link.go's `rekeyInterval`;
# this is the server->agent counterpart. The two are independent — neither
# side waits on the other. Tests monkeypatch this module attribute (which is
# why ws_agents.py reads it through the module rather than importing the value).
REKEY_INTERVAL_SECONDS = 15 * 60

# The only `transport.rekey` direction either side ever sends: `direction` is
# sender-relative, so "outbound" means "the cipher I encrypt with", which the
# receiver matches against its own receive cipher.
REKEY_DIRECTION_OUTBOUND = "outbound"


class ClockSkewError(Exception):
    """Raised when a handshake timestamp falls outside the allowed skew window."""


class RekeyError(Exception):
    """Raised when an inbound `transport.rekey` announcement can't be applied —
    a wrong direction or an out-of-step generation. Both mean our view of the
    peer's send cipher has diverged from the peer's own, which the
    authenticated, ordered Noise transport otherwise makes impossible, so the
    caller should tear the connection down and let a fresh handshake
    resynchronize it."""


def _spec_rekey(state: CipherState) -> None:
    """Apply the Noise spec §11.3 REKEY operation to *state* in place.

    REKEY(k) is defined as the first 32 bytes of ENCRYPT(k, 2^64-1, zerolen,
    zeros[32]), and Rekey() must leave the nonce counter n untouched ("it
    doesn't reset n" — spec §11.3), so both peers' counters stay in lockstep
    across a rekey.

    dissononce 0.34.3's own ``CipherState.rekey()`` cannot be used directly:
    it applies the correct derivation but then (a) omits the spec's truncation
    to 32 bytes, storing the full 48-byte ChaChaPoly output as the key — which
    makes the very next encrypt raise ``ValueError: ChaCha20Poly1305 key must
    be 32 bytes`` — and (b) resets n to 0 via ``initialize_key``. The
    derivation itself (``Cipher.rekey``) is spec-correct and is what we call
    here, so this is the standard REKEY, not a custom one: it reproduces
    github.com/flynn/noise's ``CipherState.Rekey()`` byte-for-byte, which
    fixtures/noise_rekey_vectors.json pins from both languages.

    Reaching into ``_key``/``_nonce`` is unavoidable — dissononce exposes no
    public getters, and ``SymmetricState.split()`` hardcodes its ``CipherState``
    construction so a subclass can't be injected. Both attributes are pinned by
    tests in tests/test_agent_crypto.py so a dissononce upgrade that renames or
    fixes them fails loudly instead of silently desynchronizing the link.
    """
    nonce = state._nonce
    key = state._key
    if key is None:  # pragma: no cover - only reachable pre-handshake
        raise RekeyError("cannot rekey a cipher state with no key")
    state.initialize_key(state.cipher.rekey(key)[:32])
    state.set_nonce(nonce)


def _public_from_private(priv_bytes: bytes) -> bytes:
    """Derive the raw 32-byte X25519 public key for raw 32-byte private key material."""
    return x25519.X25519PrivateKey.from_private_bytes(priv_bytes).public_key().public_bytes_raw()


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
            return priv_bytes, _public_from_private(priv_bytes)

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
    pub_bytes = _public_from_private(priv_bytes)
    return X25519KeyPair(X25519PublicKey(pub_bytes), X25519PrivateKey(priv_bytes))


class NoiseIKResponder:
    """Server-side (responder) half of a single Noise_IK_25519_ChaChaPoly_SHA256
    handshake. One instance is good for exactly one handshake/session — a new
    link session (e.g. on reconnect) gets a fresh instance.

    Within a session each transport cipher is rekeyed in place on its own
    schedule: `rekey_send` rotates the server->agent cipher (announced by a
    `transport.rekey` frame this side sends), `rekey_recv` rotates the
    agent->server cipher (in response to one the agent sends). The two
    directions carry independent generation counters and never rekey together.
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
        # Per-direction rekey counters for this session, both starting at 0
        # (no rekey yet). They reset with the instance, i.e. on every
        # reconnect, because a fresh handshake gives both sides fresh split
        # keys. The agent keeps the mirror-image pair in link.go.
        self._send_generation = 0
        self._recv_generation = 0

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
        if self._state.rs is None:
            raise RuntimeError("handshake not complete: call read_message() first")
        return cast(bytes, self._state.rs.data)

    def encrypt(self, plaintext: bytes) -> bytes:
        if self._cipher_pair is None:
            raise RuntimeError("handshake not complete: call read_message() first")
        _, send_cipher = self._cipher_pair
        return cast(bytes, send_cipher.encrypt_with_ad(b"", plaintext))

    def decrypt(self, ciphertext: bytes) -> bytes:
        if self._cipher_pair is None:
            raise RuntimeError("handshake not complete: call read_message() first")
        recv_cipher, _ = self._cipher_pair
        return cast(bytes, recv_cipher.decrypt_with_ad(b"", ciphertext))

    @property
    def next_send_generation(self) -> int:
        """The generation number the next server->agent `transport.rekey`
        announcement must carry. Read it when building the frame, then call
        `rekey_send` once the frame is on the wire."""
        return self._send_generation + 1

    def rekey_send(self) -> None:
        """Rotate the server->agent cipher.

        Call this strictly *after* the `transport.rekey` announcement has been
        encrypted and sent: that frame has to go out under the old key, or the
        agent cannot decrypt the message telling it to rekey.
        """
        if self._cipher_pair is None:
            raise RuntimeError("handshake not complete: call read_message() first")
        _, send_cipher = self._cipher_pair
        _spec_rekey(send_cipher)
        self._send_generation += 1

    def rekey_recv(self, generation: int) -> None:
        """Rotate the agent->server cipher in response to the agent's
        `transport.rekey`.

        Call this immediately after decrypting that frame and before
        decrypting anything else — every subsequent frame from the agent is
        sealed under the new key. Generations are strictly sequential from 1;
        anything else raises RekeyError.
        """
        if self._cipher_pair is None:
            raise RuntimeError("handshake not complete: call read_message() first")
        expected = self._recv_generation + 1
        if generation != expected:
            raise RekeyError(f"transport.rekey generation {generation}, want {expected}")
        recv_cipher, _ = self._cipher_pair
        _spec_rekey(recv_cipher)
        self._recv_generation = generation
