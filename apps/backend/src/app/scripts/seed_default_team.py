"""Seed Default Tenant.

Ensures Default Tenant (id=1) exists and assigns all tenant-capable entities
that have a NULL tenant_id to tenant_id=1.

Idempotent — safe to re-run, but NOT safe to run casually on v1.

Multi-tenancy is deferred for v1 (SEC-2B): the deployment is single-tenant and
the tenant columns exist only to carry upgraded data. The read rule in
``monitor_service.reader_can_access_monitor`` hides a row only when the reader
and the row *both* carry tenant ids and they differ — so while rows stay
tenantless, everything is visible and the rule is inert.

Stamping every row with tenant_id=1 takes that rule out of its inert state. Any
user carrying a different tenant id immediately stops seeing data that was
visible a moment earlier. That is a live authorization change performed by a
script whose name suggests routine setup, in a release whose tenancy story is
"deferred" — so it requires explicit confirmation rather than a bare invocation.

Usage:
    CB_CONFIRM_TENANT_SEED=1 python -m app.scripts.seed_default_team
"""

import logging
import os

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


_CONFIRM_ENV = "CB_CONFIRM_TENANT_SEED"


def seed_default_tenant(*, confirmed: bool | None = None) -> None:
    """Assign tenantless rows to Default Tenant. See the module docstring first.

    Requires explicit confirmation — pass ``confirmed=True`` or set
    ``CB_CONFIRM_TENANT_SEED=1`` — because it changes who can read what.
    """
    if confirmed is None:
        confirmed = os.getenv(_CONFIRM_ENV, "").strip().lower() in {"1", "true", "yes"}
    if not confirmed:
        raise SystemExit(
            "Refusing to seed tenant ids without confirmation.\n"
            "This assigns every tenantless row to tenant_id=1, which activates the "
            "tenant read rule and can hide data from users carrying a different "
            "tenant id. Multi-tenancy is deferred for v1 (SEC-2B).\n"
            f"Re-run with {_CONFIRM_ENV}=1 if that is what you intend."
        )

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
