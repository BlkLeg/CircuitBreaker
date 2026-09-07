"""Database-schema guards that run before the application serves traffic.

Alembic, the required-table assertion, the TimescaleDB requirement check and
the row-level-security diagnostic.  Split out of ``app.main`` so that the
startup contract can be read — and tested — without loading the router graph.

Every function here is called from ``main.lifespan`` and from nowhere else,
except ``run_alembic_upgrade`` which ``cb migrate`` and ``start.py`` also call.
"""

import logging
import os

import sqlalchemy as sa

from app.db.session import engine
from app.startup.paths import alembic_ini_candidates, resolve_existing_path

_logger = logging.getLogger(__name__)

#: Tables whose absence means the schema never migrated at all.  Deliberately
#: minimal: this is a "did Alembic run" tripwire, not a schema validator.
REQUIRED_SCHEMA_TABLES = frozenset({"app_settings"})


def run_alembic_upgrade() -> None:
    """Bring the database to Alembic head, stamping legacy schemas first."""
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect

    alembic_ini_path = resolve_existing_path(*alembic_ini_candidates())
    if alembic_ini_path is None:
        raise FileNotFoundError("Could not locate alembic.ini for migrations")
    _alembic_ini = str(alembic_ini_path)

    try:
        insp = inspect(engine)
        table_names = set(insp.get_table_names())

        if "users" in table_names and "alembic_version" not in table_names:
            if os.environ.get("CB_DISABLE_LEGACY_ALEMBIC_STAMP", "").lower() in (
                "1",
                "true",
                "yes",
            ):
                raise RuntimeError(
                    "Legacy database detected (table users exists, alembic_version missing) "
                    "and CB_DISABLE_LEGACY_ALEMBIC_STAMP is set. "
                    "Stamp the correct base revision manually (often: alembic stamp "
                    "a3b4c5d6e7fc), then retry."
                )
            # Old DB with no alembic tracking: stamp to the revision just before
            # 0017 (webhooks/oauth) so upgrade() will run 0017+ and add any
            # missing columns (e.g. registration_open). Stamping to "head" would
            # make upgrade a no-op and leave the schema outdated.
            _logger.warning(
                "Legacy PostgreSQL schema: Alembic will stamp a3b4c5d6e7fc (0015_proxmox_storage) "
                "because users exists but alembic_version is missing. "
                "For imported or hand-built databases set CB_DISABLE_LEGACY_ALEMBIC_STAMP=true "
                "and stamp manually."
            )
            alembic_cfg = Config(_alembic_ini)
            command.stamp(alembic_cfg, "a3b4c5d6e7fc")  # 0015_proxmox_storage
    except Exception as e:
        logging.exception("Migration pre-check failed: %s", e)
        raise

    alembic_cfg = Config(_alembic_ini)
    command.upgrade(alembic_cfg, "head")


def require_timescale_if_configured() -> None:
    """Exit when CB_REQUIRE_TIMESCALE is set but the extension is not available."""
    if os.environ.get("CB_REQUIRE_TIMESCALE", "").lower() not in ("1", "true", "yes"):
        return
    try:
        with engine.connect() as conn:
            row = conn.execute(
                sa.text("SELECT 1 FROM pg_available_extensions WHERE name = 'timescaledb' LIMIT 1")
            ).scalar()
        if not row:
            _logger.critical(
                "CB_REQUIRE_TIMESCALE is set but TimescaleDB is not available on this "
                "PostgreSQL instance. Install the extension or unset CB_REQUIRE_TIMESCALE."
            )
            raise SystemExit(1)
    except SystemExit:
        raise
    except Exception as exc:
        _logger.critical("TimescaleDB requirement check failed: %s", exc, exc_info=True)
        raise SystemExit(1) from exc


def get_existing_schema_tables() -> set[str]:
    """Every real table in the public schema, as PostgreSQL currently sees it."""
    from sqlalchemy.exc import SQLAlchemyError

    query = sa.text(
        "SELECT c.relname "
        "FROM pg_class c "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'public' AND c.relkind = 'r'"
    )
    try:
        with engine.connect() as conn:
            rows = conn.execute(query).fetchall()
            return {row[0] for row in rows}
    except SQLAlchemyError as exc:
        _logger.critical("Database schema inspection failed before startup: %s", exc, exc_info=True)
        raise


RLS_TENANT_TABLES = (
    "hardware",
    "services",
    "networks",
    "compute_units",
    "storage",
    "hardware_clusters",
    "external_nodes",
    "ip_addresses",
    "vlans",
    "sites",
    "node_relations",
    "scan_jobs",
    "integration_configs",
    "topologies",
)


def rls_bypass_warning(
    bind: sa.engine.Engine, tables: tuple[str, ...] = RLS_TENANT_TABLES
) -> str | None:
    """The message to warn with, or None when the role can read its tenant tables.

    Three ways a role is unaffected by RLS, and this used to check only the first:

    * ``rolbypassrls`` on the role;
    * owning the table -- PostgreSQL does not apply policies to a table's owner;
    * unless the table is ``FORCE ROW LEVEL SECURITY``, which binds the owner too.

    Checking only rolbypassrls warned every packaged install that its database
    was misconfigured when it was not: the packaged role owns the database it
    migrated, so it owns those tables and reads them normally.
    (0040_rls_policies ENABLEs RLS and does not FORCE it.)

    That is worth more than log tidiness, because the remedy the message implies
    is ``ALTER ROLE ... BYPASSRLS`` -- a cluster-wide, unconditional, permanent
    exemption on every table, where ownership bypass is scoped to owned tables
    and can be tightened later by adding FORCE. A misleading warning pointing at
    a privilege escalation is worse than no warning.

    Returned rather than logged so it can be tested against a real database
    without asserting on log plumbing. Development and CI run as a role that has
    BYPASSRLS, which is precisely why nothing here was exercised before.
    """
    with bind.connect() as conn:
        if (
            conn.execute(
                sa.text("SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user")
            ).scalar()
            is True
        ):
            return None

        for tbl in tables:
            row = conn.execute(
                sa.text(
                    "SELECT c.relrowsecurity, c.relforcerowsecurity, "
                    "       pg_get_userbyid(c.relowner) = current_user AS is_owner "
                    "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = 'public' AND c.relname = :t AND c.relkind = 'r'"
                ),
                {"t": tbl},
            ).fetchone()
            if not row:
                continue
            enabled, forced, is_owner = row
            if not enabled:
                continue
            if is_owner and not forced:
                continue  # owner bypass applies; policies do not restrict this role
            role = conn.execute(sa.text("SELECT current_user")).scalar()
            reason = (
                "the table is FORCE ROW LEVEL SECURITY, so owning it does not help"
                if forced
                else "the role neither owns the table nor has BYPASSRLS"
            )
            return (
                f"Row-level security is enabled on public.{tbl} and {reason} "
                f"(role {role!r}). Tenant-scoped queries may return no rows unless "
                f"session variables (e.g. app.current_tenant) match policies."
            )
    return None


def warn_if_rls_without_bypass() -> None:
    """Warn once when RLS would actually hide rows from this role."""
    try:
        message = rls_bypass_warning(engine)
        if message:
            _logger.warning("%s", message)
    except Exception:
        _logger.debug("RLS/BYPASSRLS diagnostic skipped", exc_info=True)


def assert_required_schema() -> None:
    try:
        existing_tables = get_existing_schema_tables()
    except Exception as exc:
        _logger.critical("Database schema check failed before startup: %s", exc, exc_info=True)
        raise SystemExit(1) from exc

    missing_tables = sorted(REQUIRED_SCHEMA_TABLES - existing_tables)
    if missing_tables:
        _logger.warning(
            "Database schema is missing required tables (%s) after the initial migration pass; "
            "retrying Alembic once.",
            ", ".join(missing_tables),
        )
        try:
            run_alembic_upgrade()
            existing_tables = get_existing_schema_tables()
        except Exception as exc:
            _logger.critical(
                "Database schema repair failed before startup: %s",
                exc,
                exc_info=True,
            )
            raise SystemExit(1) from exc

        missing_tables = sorted(REQUIRED_SCHEMA_TABLES - existing_tables)
        if missing_tables:
            _logger.critical(
                "Database schema is still missing required tables (%s). "
                "Run Alembic against the correct PostgreSQL database with "
                "'make migrate' or 'alembic upgrade head', then restart.",
                ", ".join(missing_tables),
            )
            raise SystemExit(1)
