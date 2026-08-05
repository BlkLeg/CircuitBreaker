"""Server-side X25519 identity and Noise IK responder for the agent link.

The server holds one static X25519 keypair as its stable long-term identity,
generated on first use and persisted (encrypted) via the existing credential
vault. Every enrolling/linking agent verifies against this same public key —
except during a Task 28 server-key rotation's overlap window, when a
successor keypair is also valid (see `ServerKeyRotationState` /
`complete_ik_handshake` below).

A link session is established by one Noise IK handshake per connection, and
its two transport ciphers are then rekeyed in place every REKEY_INTERVAL_SECONDS
— independently per direction — via `transport.rekey` control frames (see
`NoiseIKResponder.rekey_send`/`rekey_recv` and ws_agents.py's link_stream).
Long-term key rotation (`key.rotate`) is mostly a separate mechanism, owned by
`services/agent_registry.py`'s pending-key state machine (Task 27) — but
`device_identity_matches` below lives here rather than there because it's the
one piece of that mechanism that's actually about the Noise layer: Noise IK's
responder never validates the initiator's static key against a known set at
the crypto layer (unlike the *responder's own* static key, which Task 28's
server-key rotation genuinely does have to try two of). Any key the initiator
holds a matching private key for completes the handshake; `remote_static()`
below just reports back whatever key that was. Deciding whether that reported
key is one this server currently recognizes for a given agent — its current
key, or an unexpired pending successor during a device-key rotation's
transition window — is a post-handshake identity check, not a handshake
mechanic, which is exactly what `device_identity_matches` is.

SECURITY: this module handles the server's static private key. Never log key
material (private key bytes/hex, shared secrets, or raw handshake payloads).
"""

from __future__ import annotations

import dataclasses
import hashlib
import logging
from datetime import UTC, datetime, timedelta
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
from sqlalchemy import update as sa_update
from sqlalchemy.orm import Session

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


# ── Task 28: server-key rotation with an overlap window ────────────────────

# Global Constraints: "Server-key overlap defaults to 7 days." Mirrors
# agent_registry.DEVICE_KEY_ROTATION_WINDOW_SECONDS's monkeypatch-by-tests
# convention, but for the server's own identity key rather than one device's.
SERVER_KEY_OVERLAP_SECONDS = 7 * 24 * 60 * 60


@dataclasses.dataclass(frozen=True)
class ServerKeyRotationState:
    """The server's current identity keypair, plus (Task 28) an in-progress
    rotation's successor keypair and overlap-expiry, as of one
    `load_server_key_rotation_state` call. `successor_priv`/`successor_pub`
    are `None` whenever no rotation is in progress."""

    current_priv: bytes
    current_pub: bytes
    successor_priv: bytes | None
    successor_pub: bytes | None
    started_at: datetime | None
    overlap_expires_at: datetime | None

    @property
    def rotation_active(self) -> bool:
        return self.successor_priv is not None


def _settle_expired_server_key_rotation(row: object, *, now: datetime) -> bool:
    """If `row` (an `AppSettings` instance) has an in-progress server-key
    rotation whose overlap window has elapsed as of `now`, promote the
    pending successor into `agent_server_private_key` and clear the rotation
    fields, in place — Task 28's "retire the previous key ... after the
    configured overlap elapses". Never touches the vault: both columns
    already hold vault ciphertext, so promotion is a plain string copy, not a
    decrypt/re-encrypt round trip.

    Returns True if it settled a rotation (caller must commit), False
    (no-op) otherwise — no rotation in progress, or one still inside its
    window. `row` is typed `object` rather than `AppSettings` to avoid this
    core crypto module importing the ORM models module at all; every
    attribute access below is exactly the three columns Task 28 added to
    that model.
    """
    pending = row.agent_server_key_pending_private_key  # type: ignore[attr-defined]
    if pending is None:
        return False
    expiry = row.agent_server_key_rotation_overlap_expires_at  # type: ignore[attr-defined]
    if expiry is None:  # pragma: no cover - defensive; the two are always set together
        return False
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=UTC)
    if now < expiry:
        return False
    row.agent_server_private_key = pending  # type: ignore[attr-defined]
    row.agent_server_key_pending_private_key = None  # type: ignore[attr-defined]
    row.agent_server_key_rotation_started_at = None  # type: ignore[attr-defined]
    row.agent_server_key_rotation_overlap_expires_at = None  # type: ignore[attr-defined]
    return True


def load_server_key_rotation_state(
    db: Session, *, now: datetime | None = None
) -> ServerKeyRotationState:
    """The server's current + (if a Task 28 rotation is in progress) successor
    identity keypairs, read fresh from `db` on every call.

    Deliberately NOT cached the way `get_server_static_keypair`'s
    process-lifetime `_load_or_create_keypair` is: rotation state can change
    underneath a running process — a rotation starting, or its overlap
    window lapsing — in a way the single stable identity
    `get_server_static_keypair` models never has to account for. Settles a
    lapsed rotation lazily, on whichever call happens to notice (the same
    "next access notices and clears it" convention as
    `agent_registry.settle_device_key_rotation`'s expired-pending-rotation
    branch) — there is no scheduled sweep for this either.

    Reuses the exact same `agent_server_private_key` column
    `get_server_static_keypair` reads, and creates it identically
    (generate-and-persist on first use) if it's still unset — so whichever
    of the two code paths happens to run first in a process is the one that
    generates it, and the two never diverge for the "no rotation ever
    happened" common case every existing caller of `get_server_static_keypair`
    still exercises.
    """
    from app.services.credential_vault import get_vault
    from app.services.settings_service import get_or_create_settings

    reference = now if now is not None else utcnow()
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)

    vault = get_vault()
    row = get_or_create_settings(db)

    if not row.agent_server_private_key:
        priv_bytes, _ = _generate_keypair()
        row.agent_server_private_key = vault.encrypt(priv_bytes.hex())
        db.commit()

    if _settle_expired_server_key_rotation(row, now=reference):
        db.commit()

    current_priv = bytes.fromhex(vault.decrypt(row.agent_server_private_key))
    current_pub = _public_from_private(current_priv)

    successor_priv: bytes | None = None
    successor_pub: bytes | None = None
    if row.agent_server_key_pending_private_key:
        successor_priv = bytes.fromhex(vault.decrypt(row.agent_server_key_pending_private_key))
        successor_pub = _public_from_private(successor_priv)

    return ServerKeyRotationState(
        current_priv=current_priv,
        current_pub=current_pub,
        successor_priv=successor_priv,
        successor_pub=successor_pub,
        started_at=row.agent_server_key_rotation_started_at,
        overlap_expires_at=row.agent_server_key_rotation_overlap_expires_at,
    )


def start_server_key_rotation(
    db: Session, *, overlap_seconds: int | None = None, now: datetime | None = None
) -> ServerKeyRotationState | None:
    """Begin a Task 28 server-key rotation: generate a fresh successor X25519
    keypair, persist its private key (vault-encrypted, alongside the current
    one) on the same singleton `AppSettings` row `get_server_static_keypair`
    already uses, and set an overlap-expiry `overlap_seconds` (default
    `SERVER_KEY_OVERLAP_SECONDS`, 7 days per Global Constraints) from `now`.

    Returns `None` — rejecting, doing nothing — if a rotation is already
    active (its overlap window hasn't elapsed yet): `api/agents.py`'s admin
    endpoint turns that into a 409. Unlike Task 27's
    `agent_registry.start_device_key_rotation`, which lets a second call
    simply supersede an in-progress device-key rotation, the brief requires
    this one to refuse outright while a prior rotation's overlap is still in
    progress — the server has exactly one rotation in flight at a time.

    Genuinely serializes two concurrent callers (fix round 1 — the
    `state.rotation_active` check above this function's docstring once
    described is a plain SELECT with no lock, so two callers racing past it
    before either commits would otherwise both "win", the second silently
    overwriting the first's successor keypair): the actual write is a
    conditional `UPDATE ... WHERE agent_server_key_pending_private_key IS
    NULL`, whose `WHERE` clause Postgres re-evaluates against the
    just-committed row for any caller that had to wait on the first's
    row-level write lock. A caller whose `UPDATE` therefore affects zero
    rows lost that race and returns `None` exactly as if it had seen
    `state.rotation_active` true to begin with — its freshly generated (and
    now-orphaned) successor keypair is simply discarded, never written.
    """
    from app.db.models import AppSettings
    from app.services.credential_vault import get_vault

    reference = now if now is not None else utcnow()
    state = load_server_key_rotation_state(db, now=reference)
    if state.rotation_active:
        return None

    vault = get_vault()
    window = overlap_seconds if overlap_seconds is not None else SERVER_KEY_OVERLAP_SECONDS
    priv_bytes, _ = _generate_keypair()
    encrypted = vault.encrypt(priv_bytes.hex())
    expiry = reference + timedelta(seconds=window)

    result = db.execute(
        sa_update(AppSettings)
        .where(
            AppSettings.id == 1,
            AppSettings.agent_server_key_pending_private_key.is_(None),
        )
        .values(
            agent_server_key_pending_private_key=encrypted,
            agent_server_key_rotation_started_at=reference,
            agent_server_key_rotation_overlap_expires_at=expiry,
        )
    )
    if result.rowcount == 0:  # type: ignore[attr-defined]
        # Lost the race — some other caller's rotation committed first (or,
        # far less likely, the row was deleted out from under us). Nothing
        # was written on this session's behalf, but roll back regardless so
        # this session doesn't carry a stale view of the row forward into
        # whatever its caller does next — same defensive stance
        # settings_service.get_or_create_settings already takes on its own
        # concurrent-first-request IntegrityError race.
        db.rollback()
        return None
    db.commit()

    return load_server_key_rotation_state(db, now=reference)


def complete_ik_handshake(
    handshake_msg: bytes, db: Session, *, now: datetime | None = None
) -> tuple[NoiseIKResponder, bytes, str] | None:
    """Responder side of one Noise IK handshake message, tried against every
    currently-valid server private key: the current key, and — only for as
    long as an in-progress Task 28 rotation's overlap window hasn't elapsed —
    its successor. Tries the current key first, so the overwhelmingly common
    no-rotation-in-progress case never pays for a second attempt.

    Returns `(responder, response_bytes, key_kind)` for whichever key's
    `HandshakeState` actually processed `handshake_msg` — `key_kind` is
    `"current"` or `"successor"`, letting the caller record which of the
    server's two keys this handshake authenticated against (see
    `agent_registry.record_server_key_pin`) — or `None` if `handshake_msg`
    doesn't validate against any currently-valid key. Never raises: failing
    against every candidate key is an ordinary "reject this connection"
    outcome for `ws_agents.py`'s callers, not an exceptional one.
    """
    state = load_server_key_rotation_state(db, now=now)
    candidates: list[tuple[str, bytes]] = [("current", state.current_priv)]
    if state.successor_priv is not None:
        candidates.append(("successor", state.successor_priv))

    for key_kind, priv in candidates:
        responder = NoiseIKResponder(priv)
        try:
            response = responder.read_message(handshake_msg)
        except Exception:
            continue
        return responder, response, key_kind
    return None


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


def device_identity_matches(
    remote_static_hex: str,
    *,
    current_pk: str,
    pending_pk: str | None,
    pending_expiry: datetime | None,
    now: datetime | None = None,
) -> bool:
    """True if `remote_static_hex` — a completed Noise IK handshake's
    initiator static key, as returned by `NoiseIKResponder.remote_static().hex()`
    — is a currently-valid identity given one Agent row's current device key
    and (Task 27) its in-progress device-key rotation state, if any.

    Called from `agent_registry.resolve_agent_for_handshake`, which is where
    this replaces the old exact-match-only `device_pk` lookup for `/link`.
    Two cases accept:
      - `remote_static_hex == current_pk` — the ordinary, no-rotation-in-
        progress case (and also the *first* case checked during an active
        rotation, so an agent that hasn't switched to its successor key yet
        keeps working throughout the window).
      - `remote_static_hex == pending_pk`, provided `pending_expiry` hasn't
        passed — the device-key transition window (15 minutes by default,
        Global Constraints). A pending key presented after its expiry is
        rejected exactly like a key this server has never seen: the caller
        gets `False` back and treats it as an unrecognized handshake.
    Naive datetimes (`pending_expiry` or `now`) are treated as UTC, matching
    `check_clock_skew`'s convention.
    """
    if remote_static_hex == current_pk:
        return True
    if pending_pk is None or remote_static_hex != pending_pk or pending_expiry is None:
        return False

    reference = now if now is not None else utcnow()
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)
    expiry = pending_expiry
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=UTC)
    return reference <= expiry


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
