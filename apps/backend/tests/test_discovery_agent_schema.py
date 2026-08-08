"""Bootstrap fidelity for the discovery execution-location schema
(Slice 4 Task 4, plan §2).

`0001_init` does not replay later revisions — it rebuilds the whole current
`Base.metadata` up front and every later `create_table` then short-circuits — so
anything it copies *badly* is the only definition a fresh install ever gets.
Slice 4 adds two kinds of object it copies badly, which is why every one of them
is excluded from the bootstrap and created by `0100` on fresh installs and
upgrades alike:

1. Every new FK points at `agents`, which is in `_EXCLUDED_TABLES`, so
   `_should_copy_fk` drops the constraint and the bootstrap would emit a bare
   `INTEGER`. That voids the RESTRICT lifecycle plan §2 requires — and with it
   the 409 that stops an operator deleting an agent a discovery profile still
   names — on every new deployment, silently.
2. The bootstrap's index-copy loop rebuilds indexes as
   `sa.Index(name, *cols, unique=...)`, dropping `postgresql_where`. Copying
   `uq_scan_results_job_finding` would turn it into a *full* unique index, and
   since every server-scanner row has a NULL `finding_id`, a fresh install would
   accept exactly one result per job and fail on the second.

Patterned on `tests/test_monitor_probe_schema.py`.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext

from app.db.models import DiscoveryProfile, ScanJob, ScanResult

_VERSIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "versions"

_NEW_COLUMNS = {
    "discovery_profiles": ("scan_agent_id", "normalized_cidr", "managed_by", "paused_at"),
    "scan_jobs": (
        "scan_agent_id",
        "dispatch_id",
        "dispatch_status",
        "dispatch_deadline_at",
        "last_finding_at",
        "finding_count",
        "scope_version",
    ),
    "scan_results": ("discovery_agent_id", "finding_id", "tenant_id"),
}


def _load_migration(name: str):
    """Import a migration module by file path — `migrations/versions` is not a
    package, so a normal import will not find it."""
    path = _VERSIONS_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_migration_{name}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_bootstrap_does_not_create_the_discovery_agent_columns():
    bootstrap = _load_migration("0001_init")._build_bootstrap_metadata()

    for table_name, columns in _NEW_COLUMNS.items():
        table = bootstrap.tables[table_name]
        present = [name for name in columns if name in table.c]
        assert present == [], (
            f"0001_init would emit {table_name}.{present} without their agents FK "
            "(agents is an excluded table), voiding the delete lifecycle on fresh installs"
        )


def test_bootstrap_does_not_copy_the_partial_indexes():
    """Every partial index Slice 4 adds references an excluded column, so the
    copy loop's own filter drops it. That is what makes `_EXCLUDED_COLUMNS` the
    whole fix — there is no separate index exclusion list to maintain."""
    bootstrap = _load_migration("0001_init")._build_bootstrap_metadata()

    for table_name, banned in (
        ("scan_results", "uq_scan_results_job_finding"),
        ("discovery_profiles", "uq_discovery_profiles_system_agent_cidr"),
        ("scan_jobs", "uq_scan_jobs_dispatch_id"),
        ("scan_jobs", "ix_scan_jobs_agent_status_created"),
    ):
        names = {index.name for index in bootstrap.tables[table_name].indexes}
        assert banned not in names, (
            f"0001_init would copy {banned} without its WHERE clause, turning a partial "
            "index into a full one"
        )


def test_the_models_really_declare_predicates_the_copy_loop_cannot_carry():
    """The reason the exclusion is load-bearing rather than defensive."""
    partial = {
        index.name
        for model in (DiscoveryProfile, ScanJob, ScanResult)
        for index in model.__table__.indexes
        if index.dialect_options["postgresql"]["where"] is not None
    }
    assert {
        "uq_scan_results_job_finding",
        "uq_discovery_profiles_system_agent_cidr",
        "uq_scan_jobs_dispatch_id",
    } <= partial, f"expected partial indexes are not declared on the models: {partial}"


def test_scan_agent_foreign_keys_survive_a_real_alembic_round_trip(db_session):
    """Drive `0100` the way alembic does, over discovery tables that have no
    agent columns — i.e. exactly the shape the bootstrap leaves behind."""
    module = _load_migration("0100_discovery_agent_execution")
    connection = db_session.get_bind()

    context = MigrationContext.configure(connection)
    with Operations.context(context):
        module.downgrade()
    for table, columns in _NEW_COLUMNS.items():
        present = {c["name"] for c in sa.inspect(connection).get_columns(table)}
        assert not (set(columns) & present), f"{table} did not downgrade cleanly"

    context = MigrationContext.configure(connection)
    with Operations.context(context):
        module.upgrade()

    inspector = sa.inspect(connection)
    profile_fks = {
        (tuple(fk["constrained_columns"]), fk["referred_table"], fk["options"].get("ondelete"))
        for fk in inspector.get_foreign_keys("discovery_profiles")
    }
    assert (("scan_agent_id",), "agents", "RESTRICT") in profile_fks, (
        f"scan_agent_id must be a RESTRICT FK to agents, got {profile_fks}"
    )

    # And the partial predicate survived the round trip, which is the half a
    # bare "the index exists" assertion would miss.
    definition = connection.execute(
        sa.text("SELECT indexdef FROM pg_indexes WHERE indexname = 'uq_scan_results_job_finding'")
    ).scalar()
    assert definition is not None and "WHERE" in definition


def test_scan_results_gets_its_row_level_security_policy_from_0100(db_session):
    """`scan_jobs` was already RLS-managed and `scan_results` was not, so a
    result-level tenant column with no policy behind it would be decoration.

    The policy is created by `0100`, **not** by adding `scan_results` to
    `0040_rls_policies._RLS_TABLES`. That list would be a no-op either way:
    `0040` skips any table with no `tenant_id` column, and on a fresh install
    the column does not exist when `0040` runs (it is in `_EXCLUDED_COLUMNS`),
    while on an upgrade `0040` has long since been applied.
    """
    module = _load_migration("0100_discovery_agent_execution")
    connection = db_session.get_bind()

    context = MigrationContext.configure(connection)
    with Operations.context(context):
        module.downgrade()
    context = MigrationContext.configure(connection)
    with Operations.context(context):
        module.upgrade()

    policy = connection.execute(
        sa.text(
            "SELECT qual FROM pg_policies "
            "WHERE tablename = 'scan_results' AND policyname = 'tenant_isolation_scan_results'"
        )
    ).scalar()
    assert policy is not None, "scan_results carries a tenant_id with no isolation policy"
    assert "app.current_tenant" in policy
