from app.schemas.settings import AppSettingsUpdate
from app.services.settings_service import get_or_create_settings, update_settings


def test_lan_discovery_desired_defaults_false(db_session):
    settings = get_or_create_settings(db_session)
    assert settings.lan_discovery_desired is False


def test_lan_discovery_desired_can_be_toggled(db_session):
    update_settings(db_session, AppSettingsUpdate(lan_discovery_desired=True))
    settings = get_or_create_settings(db_session)
    assert settings.lan_discovery_desired is True
