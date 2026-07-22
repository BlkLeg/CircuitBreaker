from app.schemas.settings import AppSettingsUpdate
from app.services.settings_service import get_or_create_settings, update_settings


def test_fqdn_defaults_none(db_session):
    settings = get_or_create_settings(db_session)
    assert settings.fqdn is None


def test_fqdn_can_be_set_directly(db_session):
    settings = get_or_create_settings(db_session)
    settings.fqdn = "circuitbreaker.example.com"
    db_session.flush()
    reloaded = get_or_create_settings(db_session)
    assert reloaded.fqdn == "circuitbreaker.example.com"


def test_fqdn_can_be_toggled_via_update_settings(db_session):
    update_settings(db_session, AppSettingsUpdate(fqdn="cb.example.com"))
    settings = get_or_create_settings(db_session)
    assert settings.fqdn == "cb.example.com"
