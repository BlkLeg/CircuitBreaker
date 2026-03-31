"""Model-level unit tests."""


def test_arp_prober_defaults_to_disabled(db_session):
    """New AppSettings rows must have arp_enabled=False."""
    from app.db.models import AppSettings

    settings = AppSettings(id=9999)
    db_session.add(settings)
    db_session.flush()
    assert settings.arp_enabled is False, (
        f"arp_enabled defaults to {settings.arp_enabled!r}; expected False"
    )
