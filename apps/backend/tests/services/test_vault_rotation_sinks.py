"""Vault key rotation must carry notification sink secrets with it (INC-06).

``rotate_vault_key`` re-encrypts an explicit list of locations. A secret stored
somewhere not on that list survives rotation as ciphertext nobody can read
again — so encrypting sink webhook URLs without extending rotation would turn
every configured sink into silent, permanent breakage on the next rotation.
"""

import os

import pytest

from app.db.models import NotificationSink
from app.services.notification_secrets import decrypt_config, encrypt_config

_SLACK_URL = "https://hooks.slack.com/services/T00000000/B00000000/xoxbSECRETTOKEN"


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


def _encrypted_sink(db_session, name: str = "Ops Slack") -> NotificationSink:
    sink = NotificationSink(
        name=name,
        provider_type="slack",
        provider_config=encrypt_config("slack", {"webhook_url": _SLACK_URL}),
        enabled=True,
    )
    db_session.add(sink)
    db_session.commit()
    return sink


def test_rotation_keeps_sink_secrets_decryptable(
    db_session, app_cfg, monkeypatch, restore_vault
) -> None:
    from app.services import vault_service

    sink = _encrypted_sink(db_session)
    before = sink.provider_config["webhook_url_enc"]
    # Persisting the new key writes /data/.env, which does not exist here.
    monkeypatch.setattr(vault_service, "write_vault_key_to_env", lambda _key: None)

    vault_service.rotate_vault_key(db_session)

    db_session.refresh(sink)
    assert sink.provider_config["webhook_url_enc"] != before
    assert decrypt_config(sink.provider_config)["webhook_url"] == _SLACK_URL


def test_rotation_leaves_a_legacy_plaintext_sink_alone(
    db_session, app_cfg, monkeypatch, restore_vault
) -> None:
    from app.services import vault_service

    sink = NotificationSink(
        name="Legacy",
        provider_type="slack",
        provider_config={"webhook_url": _SLACK_URL},
        enabled=True,
    )
    db_session.add(sink)
    db_session.commit()
    monkeypatch.setattr(vault_service, "write_vault_key_to_env", lambda _key: None)

    vault_service.rotate_vault_key(db_session)

    db_session.refresh(sink)
    assert sink.provider_config["webhook_url"] == _SLACK_URL


def test_encrypted_sinks_count_as_encrypted_secrets(db_session, app_cfg) -> None:
    """Startup refuses to mint a fresh key while readable secrets exist."""
    from app.services.vault_service import _count_encrypted_secrets

    before = _count_encrypted_secrets(db_session)
    _encrypted_sink(db_session)

    assert _count_encrypted_secrets(db_session) == before + 1


def test_a_plaintext_sink_does_not_count_as_an_encrypted_secret(db_session, app_cfg) -> None:
    from app.services.vault_service import _count_encrypted_secrets

    before = _count_encrypted_secrets(db_session)
    db_session.add(
        NotificationSink(
            name="Legacy",
            provider_type="slack",
            provider_config={"webhook_url": _SLACK_URL},
            enabled=True,
        )
    )
    db_session.commit()

    assert _count_encrypted_secrets(db_session) == before
