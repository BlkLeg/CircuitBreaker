"""Notification sink secret handling.

A Slack/Discord/Teams incoming-webhook URL is a bearer credential — whoever
holds it can post into the channel. ``NotificationSink.provider_config`` is a
plain JSONB blob served by ``GET /notifications/sinks`` to any viewer, so those
URLs are stored encrypted under an ``<key>_enc`` sibling (matching the
``AppSettings.smtp_password_enc`` convention) and masked on the way out.

Three directions, one per caller:

- ``encrypt_config`` — API write path. Plaintext in, ciphertext stored.
- ``decrypt_config`` — worker delivery path. Ciphertext out, plaintext in hand.
- ``redact_config``  — API read path. Never returns a usable credential.

Rows written before this module existed hold a plaintext ``webhook_url``.
``decrypt_config`` passes those through so delivery keeps working, and
``redact_config`` masks them so the leak closes on read immediately; they are
rewritten encrypted the next time the sink is saved. No data migration is
needed, which matters because alembic runs before the vault is initialized.

Anything encrypted here must also be re-encrypted by
``vault_service.rotate_vault_key`` — otherwise rotating the key silently
orphans every webhook URL.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from fastapi import HTTPException

from app.services.credential_vault import get_vault

# Which provider_config keys are credentials, per provider type. Email sinks
# carry routing only (to / from_email / subject_prefix) — none of it secret,
# because connection details come from the global SMTP settings.
SECRET_KEYS: dict[str, tuple[str, ...]] = {
    "slack": ("webhook_url",),
    "discord": ("webhook_url",),
    "teams": ("webhook_url",),
    "email": (),
}

# Fail closed: a provider type added later is assumed to carry a webhook URL
# rather than assumed to carry nothing.
_DEFAULT_SECRET_KEYS: tuple[str, ...] = ("webhook_url",)

MASK = "•••"

_VAULT_UNAVAILABLE = (
    "Vault is not initialized. Complete the first-run setup so the webhook URL "
    "can be stored securely."
)


def secret_keys_for(provider_type: str) -> tuple[str, ...]:
    return SECRET_KEYS.get(provider_type, _DEFAULT_SECRET_KEYS)


def _enc_key(key: str) -> str:
    return f"{key}_enc"


def is_masked(value: Any) -> bool:
    """True when *value* is a redacted preview handed back by a client.

    Detection is on the mask character itself rather than an exact-string
    comparison: the preview keeps the host, so no single sentinel would match
    every sink, and no real webhook URL contains U+2022.
    """
    return isinstance(value, str) and "•" in value


def mask_secret(value: str) -> str:
    """Return a preview that identifies the destination without granting it.

    Keeps scheme, host, and the first path segment so an operator can tell two
    Slack sinks apart; everything after it — the part that authenticates — is
    replaced. A value that does not parse as a URL is masked entirely.
    """
    try:
        parsed = urlparse(value)
    except ValueError:
        return MASK
    if not parsed.scheme or not parsed.netloc:
        return MASK
    first_segment = next((seg for seg in parsed.path.split("/") if seg), "")
    prefix = f"{parsed.scheme}://{parsed.netloc}"
    if first_segment:
        return f"{prefix}/{first_segment}/{MASK}"
    return f"{prefix}/{MASK}"


def _encrypt(plaintext: str) -> str:
    try:
        return get_vault().encrypt(plaintext)
    except RuntimeError as exc:
        if "not initialized" in str(exc).lower():
            raise HTTPException(status_code=503, detail=_VAULT_UNAVAILABLE) from exc
        raise


def encrypt_config(
    provider_type: str,
    incoming: dict[str, Any],
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return *incoming* with its secret keys encrypted, ready to store.

    *existing* is the sink's currently stored config. A secret the client did
    not send, or sent back as its own mask, is carried forward from there — so
    editing a sink's name does not destroy its webhook URL.
    """
    stored = dict(incoming)
    previous = existing or {}

    for key in secret_keys_for(provider_type):
        enc_key = _enc_key(key)
        value = stored.pop(key, None)
        stored.pop(enc_key, None)

        if value is not None and not is_masked(value) and str(value) != "":
            stored[enc_key] = _encrypt(str(value))
            continue

        carried = previous.get(enc_key)
        if carried:
            stored[enc_key] = carried
        elif previous.get(key):
            # Legacy plaintext row being saved for the first time since this
            # module landed — upgrade it in place rather than dropping it.
            stored[enc_key] = _encrypt(str(previous[key]))

    return stored


def decrypt_config(config: dict[str, Any]) -> dict[str, Any]:
    """Return *config* with secrets in plaintext, for delivery.

    Both shapes are accepted: an ``<key>_enc`` ciphertext is decrypted, and a
    legacy plaintext ``<key>`` is passed through untouched. Decryption failure
    propagates — a sink that cannot be decrypted must fail loudly rather than
    silently deliver nowhere.
    """
    plain = dict(config)
    vault = get_vault()

    for enc_key in [k for k in plain if k.endswith("_enc")]:
        key = enc_key[: -len("_enc")]
        ciphertext = plain.pop(enc_key)
        if ciphertext:
            plain[key] = vault.decrypt(str(ciphertext))

    return plain


def redact_config(provider_type: str, config: dict[str, Any]) -> dict[str, Any]:
    """Return *config* with every secret replaced by a mask plus a set-flag.

    The mask keeps the host and first path segment, which means the ciphertext
    has to be decrypted to build it. That is deliberate — a bare ``•••`` on
    every row would leave an operator with four Slack sinks unable to tell
    which is which. Decryption failure degrades to the bare mask rather than
    raising, so a vault-key problem cannot turn a list call into a 500.
    """
    redacted = {k: v for k, v in config.items() if not k.endswith("_enc")}

    for key in secret_keys_for(provider_type):
        enc_key = _enc_key(key)
        ciphertext = config.get(enc_key)
        plaintext = config.get(key)
        has_secret = bool(ciphertext) or bool(plaintext)

        redacted[f"{key}_set"] = has_secret
        if not has_secret:
            redacted.pop(key, None)
            continue

        if not plaintext and ciphertext:
            try:
                plaintext = get_vault().decrypt(str(ciphertext))
            except Exception:  # noqa: BLE001 — never let a bad key break a read
                redacted[key] = MASK
                continue

        redacted[key] = mask_secret(str(plaintext))

    return redacted
