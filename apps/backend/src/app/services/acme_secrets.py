"""DNS-01 provider credential handling (INC-07).

A Cloudflare API token or an RFC2136 TSIG key authorizes publishing records in the zone the
certificate is issued against. That makes it a bearer credential of the same class as the
webhook URLs ``notification_secrets.py`` handles, and this module is deliberately the same
shape: an ``<key>_enc`` sibling holding Fernet ciphertext, a ``<key>_set`` flag on the way
out, and carry-forward so editing one field cannot destroy another.

Three directions, one per caller:

- ``encrypt_config`` — settings write path. Plaintext in, ciphertext stored.
- ``decrypt_config`` — issuance path. Ciphertext out, plaintext in hand for the seconds
  certbot needs it.
- ``redact_config``  — settings read path. Never returns a usable credential.

The mask is bare, unlike the sink one. A webhook URL keeps its host so an operator can tell
four Slack sinks apart; there is exactly one DNS provider configured per install, and an API
token has no non-secret half worth previewing.

Anything encrypted here must also be re-encrypted by ``vault_service.rotate_vault_key`` —
otherwise rotating the key silently orphans the credential, and the install discovers it at
the next renewal rather than at the rotation.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.services.credential_vault import get_vault

# Which config keys are credentials, per DNS provider. Two providers and no more: an
# untested provider is worse than an absent one, which is the finding (INC-16) this batch
# closes alongside.
SECRET_KEYS: dict[str, tuple[str, ...]] = {
    "cloudflare": ("api_token",),
    "rfc2136": ("tsig_secret",),
}

# Fail closed: a provider added later is assumed to carry a secret rather than assumed to
# carry none. Both known secret names are covered, since a new provider will use one of them.
_DEFAULT_SECRET_KEYS: tuple[str, ...] = ("api_token", "tsig_secret")

MASK = "•••"

_VAULT_UNAVAILABLE = (
    "Vault is not initialized. Complete the first-run setup so the DNS provider "
    "credential can be stored securely."
)


def secret_keys_for(provider: str) -> tuple[str, ...]:
    return SECRET_KEYS.get(provider, _DEFAULT_SECRET_KEYS)


def _enc_key(key: str) -> str:
    return f"{key}_enc"


def is_masked(value: Any) -> bool:
    """True when *value* is a redacted preview handed back by a client.

    Detection is on the mask character rather than an exact comparison, matching
    ``notification_secrets.is_masked``; no real credential contains U+2022.
    """
    return isinstance(value, str) and "•" in value


def _encrypt(plaintext: str) -> str:
    try:
        return get_vault().encrypt(plaintext)
    except RuntimeError as exc:
        if "not initialized" in str(exc).lower():
            raise HTTPException(status_code=503, detail=_VAULT_UNAVAILABLE) from exc
        raise


def encrypt_config(
    provider: str,
    incoming: dict[str, Any],
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return *incoming* with its secret keys encrypted, ready to store.

    *existing* is the currently stored config. A secret the client did not send, or sent
    back as its own mask, is carried forward from there — so correcting the RFC2136 server
    address does not silently blank the TSIG key.
    """
    stored = dict(incoming)
    previous = existing or {}

    for key in secret_keys_for(provider):
        enc_key = _enc_key(key)
        value = stored.pop(key, None)
        stored.pop(enc_key, None)
        stored.pop(f"{key}_set", None)

        if value is not None and not is_masked(value) and str(value) != "":
            stored[enc_key] = _encrypt(str(value))
            continue

        carried = previous.get(enc_key)
        if carried:
            stored[enc_key] = carried
        elif previous.get(key):
            # Written before this module existed, or by hand. Upgrade it in place.
            stored[enc_key] = _encrypt(str(previous[key]))

    return stored


def decrypt_config(config: dict[str, Any]) -> dict[str, Any]:
    """Return *config* with secrets in plaintext, for the certbot credentials file.

    Decryption failure propagates: an issuance that cannot read its credential must fail
    loudly rather than write a file with an empty token and let certbot report a confusing
    authorization error instead.
    """
    plain = dict(config)
    vault = get_vault()

    for enc_key in [k for k in plain if k.endswith("_enc")]:
        key = enc_key[: -len("_enc")]
        ciphertext = plain.pop(enc_key)
        if ciphertext:
            plain[key] = vault.decrypt(str(ciphertext))

    return plain


def redact_config(provider: str, config: dict[str, Any]) -> dict[str, Any]:
    """Return *config* with every secret replaced by a bare mask plus a set-flag.

    Unlike the sink equivalent this never decrypts: the mask carries no part of the value,
    so there is nothing to build it from, and a read path that does not touch the vault
    cannot be turned into a 500 by a key problem.
    """
    redacted = {k: v for k, v in config.items() if not k.endswith("_enc")}

    for key in secret_keys_for(provider):
        has_secret = bool(config.get(_enc_key(key))) or bool(config.get(key))
        redacted[f"{key}_set"] = has_secret
        if has_secret:
            redacted[key] = MASK
        else:
            redacted.pop(key, None)

    return redacted


def load_dns_credentials(db: Session | None = None) -> dict[str, Any] | None:
    """Return the decrypted DNS-01 credentials plus ``_provider``, or None.

    None means *not configured*, and preflight turns that into a refusal naming the
    settings page. A provider chosen with no credential stored is also None — a half-filled
    form must not read as ready, because the only other place that would surface is a
    certbot authorization failure the operator cannot interpret.

    The session is optional because both callers differ: the settings API has one, and
    issuance runs from a scheduled job that does not.
    """
    if db is not None:
        return _load(db)

    from app.db.session import SessionLocal

    with SessionLocal() as session:
        return _load(session)


def _load(db: Session) -> dict[str, Any] | None:
    from app.db.models import AppSettings

    cfg = db.get(AppSettings, 1)
    if cfg is None:
        return None

    provider = (cfg.acme_dns_provider or "").strip()
    stored: object = cfg.acme_dns_config
    if not provider or not isinstance(stored, dict) or not stored:
        return None

    creds = decrypt_config(stored)
    if not any(creds.get(key) for key in secret_keys_for(provider)):
        return None

    creds["_provider"] = provider
    return creds
