"""Cross-language proof that dissononce's REKEY matches github.com/flynn/noise's.

This is the cipher-state counterpart to test_agent_frame_conformance.py: that
one pins the JSON wire shape against the Go agent, this one pins the *key
schedule*. Both peers rekey their transport ciphers every 15 minutes
(app.core.agent_crypto._spec_rekey on this side,
apps/agent/internal/noiseconn's Session.RekeySend/RekeyRecv on the other), so
if the two libraries' REKEY implementations ever diverge the link silently
stops decrypting mid-session.

The same fixture is asserted from Go in
apps/agent/internal/noiseconn/rekey_conformance_test.go — every ciphertext
here was produced by flynn/noise and is reproduced below by dissononce, and
vice versa. ChaChaPoly is deterministic given (key, nonce, ad), so
byte-equality across the two languages is a genuine interop proof rather than
a self-consistency check.
"""

import json
from pathlib import Path

import pytest
from dissononce.cipher.chachapoly import ChaChaPolyCipher
from dissononce.processing.impl.cipherstate import CipherState

from app.core.agent_crypto import _spec_rekey

_VECTORS_PATH = Path(__file__).resolve().parents[3] / "fixtures" / "noise_rekey_vectors.json"
_VECTORS = json.loads(_VECTORS_PATH.read_text())


def _state_at(generation: int) -> CipherState:
    """A CipherState seeded with the fixture's initial key and rekeyed
    `generation` times using the production rekey helper."""
    state = CipherState(ChaChaPolyCipher())
    state.initialize_key(bytes.fromhex(_VECTORS["initial_key_hex"]))
    for _ in range(generation):
        _spec_rekey(state)
    return state


@pytest.mark.parametrize(
    ("generation", "expected_hex"),
    list(enumerate(_VECTORS["rekeyed_keys_hex"], start=1)),
    ids=lambda v: f"gen{v}" if isinstance(v, int) else None,
)
def test_rekey_chain_matches_cross_language_vectors(generation, expected_hex):
    assert _state_at(generation)._key.hex() == expected_hex


def test_rekey_preserves_the_nonce():
    """Noise spec §11.3: REKEY updates k but must not reset n. dissononce's own
    ``CipherState.rekey()`` resets it (and skips the 32-byte truncation), which
    is exactly why ``_spec_rekey`` exists — a receiver that reset n would fall
    out of step with the Go sender on the very first rekey."""
    for start_nonce in (0, 1, 42):
        state = CipherState(ChaChaPolyCipher())
        state.initialize_key(bytes.fromhex(_VECTORS["initial_key_hex"]))
        state.set_nonce(start_nonce)
        _spec_rekey(state)
        assert state._nonce == start_nonce
        assert len(state._key) == 32


def test_rekeyed_cipher_reproduces_the_go_ciphertext():
    """Encrypt the fixture plaintext under a dissononce-rekeyed cipher and
    assert it equals the ciphertext flynn/noise produced under its own
    independently-rekeyed cipher."""
    message = _VECTORS["transport_message"]
    state = _state_at(len(_VECTORS["rekeyed_keys_hex"]))
    state.set_nonce(message["nonce"])

    ciphertext = state.encrypt_with_ad(
        bytes.fromhex(message["ad_hex"]), bytes.fromhex(message["plaintext_hex"])
    )

    assert ciphertext.hex() == message["ciphertext_hex"]


def test_rekeyed_cipher_decrypts_the_go_ciphertext():
    """The other direction: a dissononce-rekeyed receive cipher opens the
    ciphertext a flynn/noise-rekeyed send cipher sealed."""
    message = _VECTORS["transport_message"]
    state = _state_at(len(_VECTORS["rekeyed_keys_hex"]))
    state.set_nonce(message["nonce"])

    plaintext = state.decrypt_with_ad(
        bytes.fromhex(message["ad_hex"]), bytes.fromhex(message["ciphertext_hex"])
    )

    assert plaintext.hex() == message["plaintext_hex"]


def test_dissononce_native_rekey_is_still_unusable_directly():
    """Regression guard on the deviation ``_spec_rekey`` works around.

    dissononce 0.34.3's ``CipherState.rekey()`` stores the untruncated 48-byte
    ChaChaPoly output as the key (spec §11.3 requires the first 32 bytes) and
    resets the nonce. If a future dissononce fixes this, the assertions below
    fail and ``_spec_rekey`` can be simplified to call it — while its
    ``Cipher.rekey`` derivation, which ``_spec_rekey`` does use, stays correct.
    """
    state = CipherState(ChaChaPolyCipher())
    state.initialize_key(bytes.fromhex(_VECTORS["initial_key_hex"]))
    state.set_nonce(7)

    state.rekey()

    assert len(state._key) == 48, "dissononce now truncates — simplify _spec_rekey"
    assert state._nonce == 0, "dissononce now preserves the nonce — simplify _spec_rekey"
    # The untruncated key is the spec key plus the Poly1305 tag, which is why
    # _spec_rekey's [:32] slice of the same derivation is the correct value.
    assert state._key[:32].hex() == _VECTORS["rekeyed_keys_hex"][0]
