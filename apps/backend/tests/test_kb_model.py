def test_kb_oui_model_exists(setup_db):
    """KbOui table is created and basic CRUD works."""
    from app.db.models import KbOui
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        entry = KbOui(prefix="BC2411", vendor="Proxmox Server Solutions GmbH", source="manual")
        db.add(entry)
        db.commit()
        found = db.get(KbOui, "BC2411")
        assert found is not None
        assert found.vendor == "Proxmox Server Solutions GmbH"
        assert found.seen_count == 1
        assert found.source == "manual"
    finally:
        db.rollback()
        db.close()


def test_kb_hostname_model_exists(setup_db):
    """KbHostname table is created and basic CRUD works."""
    from app.db.models import KbHostname
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        entry = KbHostname(
            pattern="pve",
            match_type="prefix",
            vendor="Proxmox Server Solutions GmbH",
            device_type="hypervisor",
            os_family="Linux",
            source="manual",
        )
        db.add(entry)
        db.commit()
        found = db.query(KbHostname).filter(KbHostname.pattern == "pve").first()
        assert found is not None
        assert found.vendor == "Proxmox Server Solutions GmbH"
        assert found.match_type == "prefix"
        assert found.seen_count == 1
        assert found.source == "manual"
    finally:
        db.rollback()
        db.close()
