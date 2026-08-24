"""Notification sink secret handling (INC-06).

A Slack/Discord/Teams incoming-webhook URL is a bearer credential: whoever
holds it can post into the channel. These tests pin the three directions the
value travels — encrypted on write, decrypted for delivery, masked on read —
and the carry-forward rule that stops a masked round-trip from destroying the
stored secret.
"""

import os

import pytest

from app.services.notification_secrets import (
    decrypt_config,
    encrypt_config,
    redact_config,
)

_SLACK_URL = "https://hooks.slack.com/services/T00000000/B00000000/xoxbSECRETTOKEN"
_SECRET_PART = "xoxbSECRETTOKEN"


@pytest.fixture(autouse=True)
def _vault_ready():
    """Load the in-memory vault with the suite's test key."""
    from app.services.credential_vault import get_vault

    get_vault().reinitialize(os.environ["CB_VAULT_KEY"])


def test_encrypt_config_stores_the_webhook_url_as_ciphertext() -> None:
    stored = encrypt_config("slack", {"webhook_url": _SLACK_URL})

    assert "webhook_url" not in stored
    assert _SECRET_PART not in str(stored)
    assert stored["webhook_url_enc"] != _SLACK_URL


def test_decrypt_config_round_trips_the_webhook_url() -> None:
    stored = encrypt_config("slack", {"webhook_url": _SLACK_URL})

    assert decrypt_config(stored)["webhook_url"] == _SLACK_URL


def test_decrypt_config_passes_through_a_legacy_plaintext_row() -> None:
    """Rows written before this change hold a plaintext URL; delivery must not break."""
    assert decrypt_config({"webhook_url": _SLACK_URL})["webhook_url"] == _SLACK_URL


def test_encrypt_config_preserves_non_secret_keys() -> None:
    stored = encrypt_config("slack", {"webhook_url": _SLACK_URL, "channel": "#ops"})

    assert stored["channel"] == "#ops"


def test_encrypt_config_leaves_an_email_config_untouched() -> None:
    """Email sinks carry routing only — nothing to encrypt (INC-02 depends on this)."""
    config = {"to": "ops@example.com", "subject_prefix": "[CB]"}

    assert encrypt_config("email", config) == config


def test_redact_config_masks_the_bearer_part_of_the_webhook_url() -> None:
    stored = encrypt_config("slack", {"webhook_url": _SLACK_URL})

    redacted = redact_config("slack", stored)

    assert _SECRET_PART not in str(redacted)
    assert redacted["webhook_url"] == "https://hooks.slack.com/services/•••"
    assert redacted["webhook_url_set"] is True
    assert "webhook_url_enc" not in redacted


def test_redact_config_masks_a_legacy_plaintext_row() -> None:
    """The leak closes on read for existing installs, before any rewrite happens."""
    redacted = redact_config("slack", {"webhook_url": _SLACK_URL})

    assert _SECRET_PART not in str(redacted)
    assert redacted["webhook_url_set"] is True


def test_redact_config_reports_an_absent_secret_as_unset() -> None:
    redacted = redact_config("slack", {})

    assert redacted["webhook_url_set"] is False
    assert "webhook_url" not in redacted


def test_encrypt_config_keeps_the_stored_secret_when_handed_the_mask() -> None:
    """A client that PATCHes the redacted value back must not clobber the secret."""
    stored = encrypt_config("slack", {"webhook_url": _SLACK_URL})
    masked = redact_config("slack", stored)["webhook_url"]

    updated = encrypt_config("slack", {"webhook_url": masked}, existing=stored)

    assert decrypt_config(updated)["webhook_url"] == _SLACK_URL


def test_encrypt_config_keeps_the_stored_secret_when_the_key_is_absent() -> None:
    stored = encrypt_config("slack", {"webhook_url": _SLACK_URL})

    updated = encrypt_config("slack", {"channel": "#ops"}, existing=stored)

    assert decrypt_config(updated)["webhook_url"] == _SLACK_URL


def test_encrypt_config_replaces_the_secret_when_handed_a_new_url() -> None:
    stored = encrypt_config("slack", {"webhook_url": _SLACK_URL})
    replacement = "https://hooks.slack.com/services/T11111111/B11111111/newSECRET"

    updated = encrypt_config("slack", {"webhook_url": replacement}, existing=stored)

    assert decrypt_config(updated)["webhook_url"] == replacement


def test_an_unknown_provider_type_still_treats_the_webhook_url_as_secret() -> None:
    """Fail closed: a provider added later must not leak by default."""
    stored = encrypt_config("pagerduty", {"webhook_url": _SLACK_URL})

    assert _SECRET_PART not in str(stored)
    assert _SECRET_PART not in str(redact_config("pagerduty", stored))


def test_encrypt_config_rejects_a_write_when_the_vault_is_unavailable() -> None:
    from fastapi import HTTPException

    from app.services.credential_vault import CredentialVault, get_vault

    vault = get_vault()
    saved = vault._fernet
    try:
        CredentialVault.__init__(vault)  # de-initialize without touching the singleton
        with pytest.raises(HTTPException) as exc:
            encrypt_config("slack", {"webhook_url": _SLACK_URL})
        assert exc.value.status_code == 503
    finally:
        vault._fernet = saved
