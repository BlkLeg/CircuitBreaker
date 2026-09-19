#!/usr/bin/env python3
"""Seed and safely remove a Phase-2 workload tier.

Every row this creates is named `loadgen-<tier>-…`, and cleanup deletes by that
prefix and nothing else. The prefix is the safety property: a cleanup run can
never take a row it did not create, even against a database that also holds real
inventory.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from urllib.parse import urlparse

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "apps", "backend", "src"))
sys.path.insert(0, ROOT)

# Imported after the `sys.path` bootstrap above, which is what makes
# `scripts.loadgen` importable when this file is run directly as a script.
from scripts.loadgen.config import TIERS

if TYPE_CHECKING:  # pragma: no cover - typing only
    from sqlalchemy.orm import Session

PREFIX = "loadgen-"

#: Substrings that mark a database as safe to write synthetic load into. The
#: check is a name convention rather than a connection probe on purpose: it
#: reads the same in a workflow file as it does on a workstation, and it fails
#: closed on anything it does not recognise.
SAFE_DATABASE_MARKERS = ("test", "bench", "loadgen")


def assert_safe_database(url: str, override: bool = False) -> None:
    """Refuse an ambiguous production-looking target unless explicitly allowed."""
    database = urlparse(url).path.lstrip("/").lower()
    if not override and not any(marker in database for marker in SAFE_DATABASE_MARKERS):
        raise SystemExit("refusing non-test database; pass --i-know-what-im-doing to override")


def seed(db: Session, tier: str) -> None:
    """Create one tier's hardware and monitor rows, replacing any earlier run's."""
    from app.db.models import Hardware, MonitorItem

    cfg = TIERS[tier]
    cleanup(db, tier)
    hardware: list[Hardware] = []
    for index in range(cfg["topology_entities"]):
        row = Hardware(
            name=f"{PREFIX}{tier}-hw-{index:04d}",
            ip_address=f"10.254.{index // 254}.{index % 254 + 1}",
            role="server",
            status="up",
            tenant_id=1,
        )
        db.add(row)
        hardware.append(row)
    db.flush()

    now = datetime.now(UTC)
    for index in range(cfg["monitors"]):
        target = hardware[index % len(hardware)]
        db.add(
            MonitorItem(
                name=f"{PREFIX}{tier}-monitor-{index:04d}",
                target_type="hardware",
                target_id=target.id,
                host=target.ip_address,
                check_type="tcp",
                params={"port": 9},
                interval_secs=cfg["interval_seconds"],
                enabled=True,
                # Due immediately, so the scheduler has a full backlog to work
                # through from the first second of the measurement window —
                # otherwise monitor lag reads as zero simply because nothing was
                # due yet.
                next_due_at=now,
            )
        )
    db.commit()


def cleanup(db: Session, tier: str) -> None:
    """Delete only the rows `seed` created for *tier*."""
    from app.db.models import Hardware, MonitorItem

    pattern = f"{PREFIX}{tier}-%"
    db.query(MonitorItem).filter(MonitorItem.name.like(pattern)).delete(synchronize_session=False)
    db.query(Hardware).filter(Hardware.name.like(pattern)).delete(synchronize_session=False)
    db.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("seed", "cleanup"))
    parser.add_argument("--tier", choices=sorted(TIERS), required=True)
    parser.add_argument("--db-url", default=os.getenv("CB_DB_URL", ""))
    parser.add_argument("--i-know-what-im-doing", action="store_true")
    args = parser.parse_args()

    if not args.db_url:
        raise SystemExit("--db-url or CB_DB_URL is required")
    assert_safe_database(args.db_url, args.i_know_what_im_doing)
    os.environ["CB_DB_URL"] = args.db_url

    from app.db.session import SessionLocal

    with SessionLocal() as db:
        if args.action == "seed":
            seed(db, args.tier)
        else:
            cleanup(db, args.tier)


if __name__ == "__main__":
    main()
