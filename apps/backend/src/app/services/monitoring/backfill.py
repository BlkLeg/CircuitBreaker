"""One-time backfill: convert enabled HardwareMonitor rows into MonitorItems."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.db.models import Hardware, HardwareMonitor, MonitorItem


def backfill_monitor_items(db: Session) -> int:
    created = 0
    monitors = db.query(HardwareMonitor).filter(HardwareMonitor.enabled.is_(True)).all()
    for mon in monitors:
        hw = db.get(Hardware, mon.hardware_id)
        if not hw or not hw.ip_address:
            continue
        methods = mon.probe_methods or ["icmp"]
        now = datetime.now(UTC)
        for method in methods:
            if method not in ("icmp", "tcp", "http"):
                continue
            exists = (
                db.query(MonitorItem)
                .filter(
                    MonitorItem.target_type == "hardware",
                    MonitorItem.target_id == hw.id,
                    MonitorItem.check_type == method,
                )
                .first()
            )
            if exists:
                continue
            db.add(
                MonitorItem(
                    target_type="hardware",
                    target_id=hw.id,
                    host=hw.ip_address,
                    check_type=method,
                    params={"packet_count": 5} if method == "icmp" else {},
                    interval_secs=mon.interval_secs or 60,
                    enabled=True,
                    next_due_at=now,
                )
            )
            created += 1
    return created
