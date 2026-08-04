"""One-time backfill: convert enabled HardwareMonitor rows into MonitorItems.

This module is invoked from Alembic migration 0083 while replaying the full
migration history against a fresh database. At that point in the chain, the
`hardware`, `hardware_monitors`, and `monitor_items` tables only have the
columns added by migrations up to and including 0083 -- later migrations
(e.g. 5ed182a77737, which adds `hardware.privacy_score`/`threat_profile`)
haven't run yet.

Importing the live ORM models here would be wrong: they reflect the
*current* schema, including columns added by migrations that come after
0083. An ORM `SELECT`/`INSERT` against those models pulls in every mapped
column, which breaks as soon as the model gains a column that didn't exist
yet at this point in history. Instead we describe only the columns this
backfill actually needs, as a migration-local snapshot.
"""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

_metadata = sa.MetaData()

_hardware = sa.Table(
    "hardware",
    _metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("ip_address", sa.String),
)

_hardware_monitors = sa.Table(
    "hardware_monitors",
    _metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("hardware_id", sa.Integer),
    sa.Column("enabled", sa.Boolean),
    sa.Column("interval_secs", sa.Integer),
    sa.Column("probe_methods", JSONB),
)

_monitor_items = sa.Table(
    "monitor_items",
    _metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("target_type", sa.String),
    sa.Column("target_id", sa.Integer),
    sa.Column("host", sa.String),
    sa.Column("check_type", sa.String),
    sa.Column("params", JSONB),
    sa.Column("interval_secs", sa.Integer),
    sa.Column("enabled", sa.Boolean),
    sa.Column("next_due_at", sa.DateTime(timezone=True)),
    sa.Column("consecutive_failures", sa.Integer),
    sa.Column("created_at", sa.DateTime(timezone=True)),
    sa.Column("updated_at", sa.DateTime(timezone=True)),
)


def backfill_monitor_items(db: Session) -> int:
    created = 0
    monitors = (
        db.execute(sa.select(_hardware_monitors).where(_hardware_monitors.c.enabled.is_(True)))
        .mappings()
        .all()
    )
    for mon in monitors:
        hw = (
            db.execute(sa.select(_hardware).where(_hardware.c.id == mon["hardware_id"]))
            .mappings()
            .first()
        )
        if not hw or not hw["ip_address"]:
            continue
        methods = mon["probe_methods"] or ["icmp"]
        now = datetime.now(UTC)
        for method in methods:
            if method not in ("icmp", "tcp", "http"):
                continue
            exists = db.execute(
                sa.select(_monitor_items.c.id).where(
                    _monitor_items.c.target_type == "hardware",
                    _monitor_items.c.target_id == hw["id"],
                    _monitor_items.c.check_type == method,
                )
            ).first()
            if exists:
                continue
            db.execute(
                sa.insert(_monitor_items).values(
                    target_type="hardware",
                    target_id=hw["id"],
                    host=hw["ip_address"],
                    check_type=method,
                    params={"packet_count": 5} if method == "icmp" else {},
                    interval_secs=mon["interval_secs"] or 60,
                    enabled=True,
                    next_due_at=now,
                    consecutive_failures=0,
                    created_at=now,
                    updated_at=now,
                )
            )
            created += 1
    return created
