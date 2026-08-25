"""DNS-01 provider credentials are secrets, and follow notification_secrets.py exactly.

A Cloudflare API token or an RFC2136 TSIG key is a bearer credential for the zone: whoever
holds it can publish records for the domain this install's certificate is issued against.
So it travels the same three directions a webhook URL does — encrypted on write, decrypted
only at the moment certbot needs it, masked on read — and for the same reason.

INC-06 recorded the failure mode the rotation test below exists for: a secret that
``rotate_vault_key`` does not re-encrypt is silently orphaned at the next key rotation, and
nothing notices until an issuance fails months later.
"""

from __future__ import annotations

import os

import pytest

from app.services import acme_secrets

_CF_TOKEN = "cf-tok-SECRETVALUE"
_TSIG = "dHNpZy1TRUNSRVQ="


@pytest.fixture(autouse=True)
def _vault_ready():
    """Load the in-memory vault with the suite's test key."""
    from app.services.credential_vault import get_vault

    get_vault().reinitialize(os.environ["CB_VAULT_KEY"])


@pytest.fixture
def restore_vault():
    """Undo everything a rotation mutates outside the DB transaction."""
    from app.services import vault_service
    from app.services.credential_vault import get_vault

    saved_key = os.environ.get("CB_VAULT_KEY")
    saved_fernet = get_vault()._fernet
    saved_source = vault_service._key_source
    saved_active = vault_service._active_key
    yield
    if saved_key is not None:
        os.environ["CB_VAULT_KEY"] = saved_key
    get_vault()._fernet = saved_fernet
    vault_service._key_source = saved_source
    vault_service._active_key = saved_active


# ---------------------------------------------------------------------------
# The three directions
# ---------------------------------------------------------------------------


def test_cloudflare_token_is_stored_encrypted() -> None:
    stored = acme_secrets.encrypt_config("cloudflare", {"api_token": _CF_TOKEN})

    assert "api_token" not in stored
    assert _CF_TOKEN not in str(stored)
    assert stored["api_token_enc"] != _CF_TOKEN


def test_decrypt_returns_the_token_for_use() -> None:
    stored = acme_secrets.encrypt_config("cloudflare", {"api_token": _CF_TOKEN})

    assert acme_secrets.decrypt_config(stored)["api_token"] == _CF_TOKEN


def test_read_path_never_returns_a_usable_credential() -> None:
    stored = acme_secrets.encrypt_config("cloudflare", {"api_token": _CF_TOKEN})

    redacted = acme_secrets.redact_config("cloudflare", stored)

    assert redacted["api_token_set"] is True
    assert _CF_TOKEN not in str(redacted)
    assert redacted["api_token"] == acme_secrets.MASK


def test_read_path_says_so_when_nothing_is_configured() -> None:
    redacted = acme_secrets.redact_config("cloudflare", {})

    assert redacted["api_token_set"] is False
    assert "api_token" not in redacted


def test_read_path_keeps_the_non_secret_fields() -> None:
    """An operator has to be able to see which server and key name are configured."""
    stored = acme_secrets.encrypt_config(
        "rfc2136", {"server": "ns1.example.com", "tsig_name": "cb-key", "tsig_secret": _TSIG}
    )

    redacted = acme_secrets.redact_config("rfc2136", stored)

    assert redacted["server"] == "ns1.example.com"
    assert redacted["tsig_name"] == "cb-key"
    assert _TSIG not in str(redacted)


def test_editing_another_field_carries_the_secret_forward() -> None:
    existing = acme_secrets.encrypt_config(
        "rfc2136", {"tsig_secret": _TSIG, "server": "ns1.example.com"}
    )

    updated = acme_secrets.encrypt_config(
        "rfc2136", {"server": "ns2.example.com"}, existing=existing
    )

    assert acme_secrets.decrypt_config(updated)["tsig_secret"] == _TSIG
    assert updated["server"] == "ns2.example.com"


def test_sending_the_mask_back_does_not_destroy_the_secret() -> None:
    """The read path hands out a mask; a form that round-trips it must be a no-op."""
    existing = acme_secrets.encrypt_config("cloudflare", {"api_token": _CF_TOKEN})
    redacted = acme_secrets.redact_config("cloudflare", existing)

    updated = acme_secrets.encrypt_config("cloudflare", dict(redacted), existing=existing)

    assert acme_secrets.decrypt_config(updated)["api_token"] == _CF_TOKEN


def test_an_unknown_provider_is_assumed_to_carry_a_secret() -> None:
    """Fail closed: a provider added later must not leak by defaulting to 'no secrets'."""
    stored = acme_secrets.encrypt_config("someday-dns", {"api_token": _CF_TOKEN})

    assert _CF_TOKEN not in str(stored)


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


def test_load_dns_credentials_is_none_when_unconfigured(db_session, app_cfg) -> None:
    from app.db.models import AppSettings

    cfg = db_session.get(AppSettings, 1)
    cfg.acme_dns_provider = None
    cfg.acme_dns_config = None
    db_session.commit()

    assert acme_secrets.load_dns_credentials(db_session) is None


def test_load_dns_credentials_returns_plaintext_and_the_provider(db_session, app_cfg) -> None:
    from app.db.models import AppSettings

    cfg = db_session.get(AppSettings, 1)
    cfg.acme_dns_provider = "cloudflare"
    cfg.acme_dns_config = acme_secrets.encrypt_config("cloudflare", {"api_token": _CF_TOKEN})
    db_session.commit()

    creds = acme_secrets.load_dns_credentials(db_session)

    assert creds is not None
    assert creds["_provider"] == "cloudflare"
    assert creds["api_token"] == _CF_TOKEN


def test_a_provider_with_no_stored_config_is_not_configured(db_session, app_cfg) -> None:
    """Choosing a provider and never entering a credential must not read as ready —
    preflight decides whether to refuse from this answer."""
    from app.db.models import AppSettings

    cfg = db_session.get(AppSettings, 1)
    cfg.acme_dns_provider = "cloudflare"
    cfg.acme_dns_config = None
    db_session.commit()

    assert acme_secrets.load_dns_credentials(db_session) is None


# ---------------------------------------------------------------------------
# Rotation — the INC-06 lesson
# ---------------------------------------------------------------------------


def test_rotate_vault_key_reencrypts_acme_secrets(
    db_session, app_cfg, monkeypatch, restore_vault
) -> None:
    """Omitting this is how the next key rotation silently orphans the credentials."""
    from app.db.models import AppSettings
    from app.services import vault_service

    cfg = db_session.get(AppSettings, 1)
    cfg.acme_dns_provider = "cloudflare"
    cfg.acme_dns_config = acme_secrets.encrypt_config("cloudflare", {"api_token": _CF_TOKEN})
    db_session.commit()
    before = cfg.acme_dns_config["api_token_enc"]
    monkeypatch.setattr(vault_service, "write_vault_key_to_env", lambda _key: None)

    vault_service.rotate_vault_key(db_session)

    db_session.refresh(cfg)
    assert cfg.acme_dns_config["api_token_enc"] != before
    assert acme_secrets.decrypt_config(cfg.acme_dns_config)["api_token"] == _CF_TOKEN


def test_a_stored_dns_credential_counts_as_an_encrypted_secret(db_session, app_cfg) -> None:
    """Startup refuses to mint a fresh key while readable secrets exist."""
    from app.db.models import AppSettings
    from app.services.vault_service import _count_encrypted_secrets

    cfg = db_session.get(AppSettings, 1)
    cfg.acme_dns_config = None
    db_session.commit()
    before = _count_encrypted_secrets(db_session)

    cfg.acme_dns_config = acme_secrets.encrypt_config("cloudflare", {"api_token": _CF_TOKEN})
    db_session.commit()

    assert _count_encrypted_secrets(db_session) == before + 1
