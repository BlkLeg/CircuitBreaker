"""Seed Default Tenant.

Ensures Default Tenant (id=1) exists and assigns all tenant-capable entities
that have a NULL tenant_id to tenant_id=1.

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
    Network,
    ScanJob,
    Service,
    Tenant,
)
from app.db.session import SessionLocal

_logger = logging.getLogger(__name__)


def seed_default_tenant() -> None:
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter(Tenant.id == 1).first()
        if tenant is None:
            tenant = Tenant(id=1, name="Default Tenant", slug="default")
            db.add(tenant)
            db.flush()
            _logger.info("Created Default Tenant (id=1)")
        else:
            _logger.info("Default Tenant already exists (id=%d, name=%s)", tenant.id, tenant.name)

        entity_models = [
            Hardware,
            Service,
            Network,
            HardwareCluster,
            ExternalNode,
            ScanJob,
            IntegrationConfig,
        ]

        total = 0
        for model in entity_models:
            if not hasattr(model, "tenant_id"):
                continue
            updated = (
                db.query(model)
                .filter(model.tenant_id.is_(None))
                .update({model.tenant_id: 1}, synchronize_session="fetch")
            )
            if updated:
                _logger.info("  %s: assigned %d rows → tenant_id=1", model.__tablename__, updated)
                total += updated

        db.commit()
        _logger.info("Seed complete. %d total rows assigned to Default Tenant.", total)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# Keep backward-compatible alias
seed_default_team = seed_default_tenant

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    seed_default_tenant()
