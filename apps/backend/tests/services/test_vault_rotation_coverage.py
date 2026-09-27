"""Vault key rotation must carry every vault-encrypted value with it.

``rotate_vault_key`` re-encrypts an explicit list of locations. Anything stored
with the vault but missing from that list survives the rotation as ciphertext
the new key cannot read. The agent server keys were such a location: the first
rotation (automatic every 90 days) left the server unable to decrypt its own
Noise static key, and every agent /link handshake failed with InvalidToken
(issue #168). OPNsense, S3 backup, OAuth/OIDC, integration, certificate, user
token and telemetry secrets were missing in the same way.

The last test here fails when a module that encrypts with the vault is added,
so a new location cannot be introduced without deciding how it rotates.
"""

import json
import os
import re
from datetime import timedelta
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.core.agent_crypto import _generate_keypair, load_server_key_rotation_state
from app.core.time import utcnow
from app.db.models import AppSettings, Certificate
from app.services.credential_vault import get_vault

SRC_APP = Path(__file__).resolve().parents[2] / "src" / "app"


@pytest.fixture
def restore_vault():
    """Undo everything a rotation mutates outside the DB transaction."""
    from app.services import vault_service

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


@pytest.fixture
def rotate(db_session, app_cfg, monkeypatch, restore_vault):
    """Rotate the vault key without writing /data/.env, which does not exist here."""
    from app.services import vault_service

    monkeypatch.setattr(vault_service, "write_vault_key_to_env", lambda _key: None)
    return lambda: vault_service.rotate_vault_key(db_session)


def _settings(db_session) -> AppSettings:
    cfg = db_session.get(AppSettings, 1)
    assert cfg is not None
    return cfg


def _decrypt(ciphertext: object) -> str:
    return get_vault().decrypt(str(ciphertext))


def _throwaway_key_pem() -> str:
    """A private key generated for this test only; key material never lives in the repo."""
    return (
        Ed25519PrivateKey.generate()
        .private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        .decode()
    )


def test_agent_links_survive_a_vault_rotation(db_session, rotate) -> None:
    """Issue #168: the server keys an agent handshakes against are unchanged."""
    vault = get_vault()
    current_priv, _ = _generate_keypair()
    successor_priv, _ = _generate_keypair()
    cfg = _settings(db_session)
    cfg.agent_server_private_key = vault.encrypt(current_priv.hex())
    cfg.agent_server_key_pending_private_key = vault.encrypt(successor_priv.hex())
    cfg.agent_server_key_rotation_overlap_expires_at = utcnow() + timedelta(hours=1)
    db_session.commit()
    before = load_server_key_rotation_state(db_session, now=utcnow())

    rotate()

    after = load_server_key_rotation_state(db_session, now=utcnow())
    assert after.current_pub == before.current_pub
    assert after.successor_pub == before.successor_pub
    assert after.rotation_active


def test_every_vault_location_survives_a_rotation(db_session, factories, rotate) -> None:
    vault = get_vault()
    cfg = _settings(db_session)
    plain = {
        "opnsense_api_key_enc": "opn-key",
        "opnsense_api_secret_enc": "opn-secret",
        "backup_s3_secret_key_enc": "s3-secret",
    }
    for attr, value in plain.items():
        setattr(cfg, attr, vault.encrypt(value))
    cfg.oauth_providers = {"github": {"client_id": "id", "client_secret_enc": vault.encrypt("gh")}}
    cfg.oidc_providers = [{"slug": "kc", "client_secret_enc": vault.encrypt("kc")}]
    integ = factories.integration(api_key=vault.encrypt("kuma-token"))
    user = factories.user(oauth_tokens=vault.encrypt(json.dumps({"refresh": "r"})))
    hw = factories.hardware(telemetry_config={"protocol": "ipmi", "password": vault.encrypt("bmc")})
    key_pem = _throwaway_key_pem()
    cert = Certificate(
        domain="rotation.test",
        cert_pem="-----BEGIN CERTIFICATE-----\n-----END CERTIFICATE-----\n",
        key_pem=vault.encrypt(key_pem),
        expires_at=utcnow() + timedelta(days=30),
    )
    db_session.add(cert)
    db_session.commit()
    old_integration_key = integ.api_key

    rotate()

    for obj in (cfg, integ, user, hw, cert):
        db_session.refresh(obj)
    for attr, value in plain.items():
        assert _decrypt(getattr(cfg, attr)) == value, attr
    assert _decrypt(cfg.oauth_providers["github"]["client_secret_enc"]) == "gh"
    assert cfg.oauth_providers["github"]["client_id"] == "id"
    assert _decrypt(cfg.oidc_providers[0]["client_secret_enc"]) == "kc"
    assert integ.api_key != old_integration_key
    assert _decrypt(integ.api_key) == "kuma-token"
    assert json.loads(_decrypt(user.oauth_tokens)) == {"refresh": "r"}
    assert _decrypt(hw.telemetry_config["password"]) == "bmc"
    assert hw.telemetry_config["protocol"] == "ipmi"
    assert _decrypt(cert.key_pem) == key_pem


def test_legacy_plaintext_values_are_left_alone(db_session, factories, rotate) -> None:
    """Rows written before encryption hold plaintext; rotation must not mangle them."""
    pem = _throwaway_key_pem()
    tokens = json.dumps({"refresh": "legacy"})
    cert = Certificate(
        domain="legacy.test",
        cert_pem="-----BEGIN CERTIFICATE-----\n-----END CERTIFICATE-----\n",
        key_pem=pem,
        expires_at=utcnow() + timedelta(days=30),
    )
    db_session.add(cert)
    user = factories.user(oauth_tokens=tokens)
    db_session.commit()

    rotate()

    db_session.refresh(cert)
    db_session.refresh(user)
    assert cert.key_pem == pem
    assert user.oauth_tokens == tokens


# Every module that stores a value with the vault, and where rotate_vault_key
# carries it. A module added to the codebase that encrypts with the vault fails
# the test below until it is placed here — after rotate_vault_key covers it.
ROTATED_BY_MODULE = {
    "api/admin_db.py": "AppSettings.backup_s3_secret_key_enc",
    "api/auth_oauth.py": "User.oauth_tokens",
    "api/integrations.py": "Integration.api_key",
    "api/settings.py": "AppSettings.oauth_providers / oidc_providers client_secret_enc",
    "api/telemetry.py": "Hardware.telemetry_config password",
    "api/vault.py": "none: encrypts a throwaway sentinel to test the key",
    "core/agent_crypto.py": "AppSettings.agent_server_private_key / pending key",
    "services/acme_secrets.py": "AppSettings.acme_dns_config *_enc",
    "services/certificate_service.py": "Certificate.key_pem",
    "services/discovery_dispatch.py": "DiscoveryProfile.snmp_community_encrypted",
    "services/discovery_profiles_service.py": "DiscoveryProfile.snmp_community_encrypted",
    "services/integration_provider_service.py": "Credential.encrypted_value",
    "services/notification_secrets.py": "NotificationSink.provider_config *_enc",
    "services/proxmox_service.py": "Credential.encrypted_value",
    "services/settings_service.py": "AppSettings smtp/dhcp/opnsense *_enc",
}

_VAULT_ENCRYPT = re.compile(r"(?:vault|get_vault\(\))\.encrypt\(")


def test_every_module_that_encrypts_with_the_vault_is_rotated() -> None:
    encrypting = {
        str(path.relative_to(SRC_APP))
        for path in SRC_APP.rglob("*.py")
        if path.name not in {"credential_vault.py", "vault_service.py"}
        and _VAULT_ENCRYPT.search(path.read_text(encoding="utf-8"))
    }
    unplaced = sorted(encrypting - set(ROTATED_BY_MODULE))
    assert not unplaced, (
        f"{unplaced} encrypt with the vault but are not in ROTATED_BY_MODULE. Make "
        "rotate_vault_key re-encrypt what they store (issue #168 is what happens "
        "otherwise), then add them here."
    )
    stale = sorted(set(ROTATED_BY_MODULE) - encrypting)
    assert not stale, (
        f"{stale} no longer encrypt with the vault; remove them from ROTATED_BY_MODULE"
    )
