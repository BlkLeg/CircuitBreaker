# apps/backend/tests/services/test_monitor_backfill.py
from app.db.models import Hardware, HardwareMonitor, MonitorItem
from app.services.monitoring.backfill import backfill_monitor_items


def test_backfill_creates_icmp_item_per_enabled_monitor(db_session):
    hw = Hardware(name="router", ip_address="10.0.0.1")
    db_session.add(hw)
    db_session.commit()
    db_session.add(
        HardwareMonitor(
            hardware_id=hw.id,
            enabled=True,
            interval_secs=30,
            probe_methods=["icmp", "tcp"],
            last_status="up",
            created_at="2026-07-14T00:00:00Z",
            updated_at="2026-07-14T00:00:00Z",
        )
    )
    db_session.commit()

    created = backfill_monitor_items(db_session)
    db_session.commit()
    assert created >= 1

    items = db_session.query(MonitorItem).filter(MonitorItem.target_id == hw.id).all()
    kinds = {i.check_type for i in items}
    assert "icmp" in kinds
    assert all(i.host == "10.0.0.1" and i.interval_secs == 30 for i in items)
