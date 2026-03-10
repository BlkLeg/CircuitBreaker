"""Seed Default Team.

Ensures Default Team (id=1) exists and assigns all tenant-capable entities
that have a NULL team_id to team_id=1.

Idempotent — safe to run multiple times.

Usage:
    python -m app.scripts.seed_default_team
    # or via make:
    make db-seed-default-team
"""

import logging

from app.db.models import (
    ExternalNode,
    Hardware,
    HardwareCluster,
    IntegrationConfig,
    LiveMetric,
    Network,
    ScanJob,
    Service,
    Team,
)
from app.db.session import SessionLocal

_logger = logging.getLogger(__name__)


def seed_default_team() -> None:
    db = SessionLocal()
    try:
        # Ensure Default Team exists with id=1
        team = db.query(Team).filter(Team.id == 1).first()
        if team is None:
            team = Team(id=1, name="Default Team")
            db.add(team)
            db.flush()
            _logger.info("Created Default Team (id=1)")
        else:
            _logger.info("Default Team already exists (id=%d, name=%s)", team.id, team.name)

        # Entity tables to back-fill
        entity_models = [
            Hardware,
            Service,
            Network,
            HardwareCluster,
            ExternalNode,
            ScanJob,
            LiveMetric,
            IntegrationConfig,
        ]

        total = 0
        for model in entity_models:
            updated = (
                db.query(model)
                .filter(model.team_id.is_(None))
                .update({model.team_id: 1}, synchronize_session="fetch")
            )
            if updated:
                _logger.info("  %s: assigned %d rows → team_id=1", model.__tablename__, updated)
                total += updated

        db.commit()
        _logger.info("Seed complete. %d total rows assigned to Default Team.", total)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    seed_default_team()
