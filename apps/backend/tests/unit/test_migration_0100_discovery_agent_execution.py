"""Schema-level guarantees for the discovery execution-location columns
(Slice 4 Task 4, plan §2).

Three things have to be true before discovery can name an agent at all: every
discovery table carries its new columns with the right FK lifecycle, a job's
dispatch token is unique, and the two idempotency rules — one system profile per
(agent, subnet), one result per (job, finding) — are **partial** indexes rather
than full ones.

The partial-ness is the part that would fail silently. Every `scan_results` row
the server scanner has ever written has a NULL `finding_id`; a *full* unique
index on `(scan_job_id, finding_id)` permits exactly one of them per job, so
every scan after this migration would insert one row and then fail. Likewise a
full unique index on `(scan_agent_id, normalized_cidr)` would stop a
user-created profile from targeting a CIDR a system-managed one already covers,
which plan §3 explicitly requires to be allowed.

All of these columns are in `0001_init`'s `_EXCLUDED_COLUMNS` (see
`tests/test_discovery_agent_schema.py` for why), so this module drives the
migration itself rather than the models-built test schema. Mirrors
`tests/unit/test_migration_0099_monitor_probe_runs.py`.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext

_VERSIONS_DIR = Path(__file__).resolve().parents[2] / "migrations" / "versions"
_MIGRATION = "0100_discovery_agent_execution"
_PARENT = "0099_monitor_probe_runs"

_PROFILE_COLUMNS = ("scan_agent_id", "normalized_cidr", "managed_by", "paused_at")
_JOB_COLUMNS = (
    "scan_agent_id",
    "dispatch_id",
    "dispatch_status",
    "dispatch_deadline_at",
    "last_finding_at",
    "finding_count",
    "scope_version",
)
_RESULT_COLUMNS = ("discovery_agent_id", "finding_id", "tenant_id")


def _load_migration(name: str):
    """`migrations/versions` is not a package, so import by file path."""
    path = _VERSIONS_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_migration_{name}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _replay(connection, module) -> None:
    """Downgrade then upgrade, so the assertions read the migration's own DDL
    and not the `Base.metadata.create_all` schema the fixture starts from."""
    context = MigrationContext.configure(connection)
    with Operations.context(context):
        module.downgrade()

    context = MigrationContext.configure(connection)
    with Operations.context(context):
        module.upgrade()


def _index_definition(connection, table: str, name: str) -> str | None:
    """Read the predicate from `pg_indexes` rather than the inspector: the
    reflected dict reports `unique`, but the WHERE clause is the whole point
    here and only the rendered definition is guaranteed to carry it."""
    return connection.execute(
        sa.text("SELECT indexdef FROM pg_indexes WHERE tablename = :t AND indexname = :n"),
        {"t": table, "n": name},
    ).scalar()


def test_revision_chains_onto_0099():
    module = _load_migration(_MIGRATION)

    assert module.revision == _MIGRATION
    assert module.down_revision == _PARENT


def test_migration_0100_is_the_only_child_of_0099():
    """A second migration claiming the same parent would give alembic two heads
    and break `upgrade head` on every deployment — the exact check CI runs."""
    children = []
    for path in _VERSIONS_DIR.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "down_revision" for t in node.targets)
                and isinstance(node.value, ast.Constant)
                and node.value.value == _PARENT
            ):
                children.append(path.name)

    assert children == [f"{_MIGRATION}.py"]


def test_discovery_tables_gain_their_columns(db_session):
    module = _load_migration(_MIGRATION)
    connection = db_session.get_bind()

    _replay(connection, module)

    inspector = sa.inspect(connection)
    for table, expected in (
        ("discovery_profiles", _PROFILE_COLUMNS),
        ("scan_jobs", _JOB_COLUMNS),
        ("scan_results", _RESULT_COLUMNS),
    ):
        columns = {c["name"]: c for c in inspector.get_columns(table)}
        assert set(expected) <= set(columns), f"{table} is missing {set(expected) - set(columns)}"
        for name in expected:
            # Nothing is backfilled: every existing profile, job and result
            # predates the agent and must stay legal. `finding_count` is the one
            # NOT NULL, and it carries a server default for the same reason.
            if name == "finding_count":
                assert columns[name]["nullable"] is False
                assert columns[name]["default"] is not None
            else:
                assert columns[name]["nullable"] is True, f"{table}.{name} must be optional"


def test_foreign_key_lifecycle_splits_restrict_from_cascade(db_session):
    """RESTRICT on the live assignment, CASCADE on finished history.

    RESTRICT everywhere — the literal reading of plan §2 — would make an agent
    permanently undeletable, because the retention purge is disabled outright
    when `discovery_retention_days <= 0`. Revocation, which is what plan §2's
    "does not erase provenance" is actually about, deletes no row at all.
    """
    module = _load_migration(_MIGRATION)
    connection = db_session.get_bind()

    _replay(connection, module)

    inspector = sa.inspect(connection)

    def fks(table: str) -> set[tuple[tuple[str, ...], str, str | None]]:
        return {
            (tuple(fk["constrained_columns"]), fk["referred_table"], fk["options"].get("ondelete"))
            for fk in inspector.get_foreign_keys(table)
        }

    assert (("scan_agent_id",), "agents", "RESTRICT") in fks("discovery_profiles"), (
        "a profile's agent is a live assignment; deleting it must be refused, not orphaned"
    )
    assert (("scan_agent_id",), "agents", "CASCADE") in fks("scan_jobs")
    assert (("discovery_agent_id",), "agents", "CASCADE") in fks("scan_results")
    assert (("tenant_id",), "tenants", "SET NULL") in fks("scan_results")


def test_result_idempotency_index_is_partial(db_session):
    """A *full* unique index here would permit exactly one NULL-`finding_id` row
    per job — which is every row the server scanner writes."""
    module = _load_migration(_MIGRATION)
    connection = db_session.get_bind()

    _replay(connection, module)

    definition = _index_definition(connection, "scan_results", "uq_scan_results_job_finding")
    assert definition is not None, "the partial unique index is missing entirely"
    assert "UNIQUE INDEX" in definition
    assert "scan_job_id" in definition and "finding_id" in definition
    assert "WHERE" in definition and "finding_id IS NOT NULL" in definition

    # And prove it, rather than trusting the rendered DDL: two server-scanner
    # rows for one job is the case that must keep working.
    # Spelled out because `hosts_*`, `triggered_by` and the progress columns
    # carry Python-side defaults rather than server defaults, so a raw INSERT
    # has to supply them.
    job_id = connection.execute(
        sa.text(
            "INSERT INTO scan_jobs ("
            "  scan_types_json, created_at, status, hosts_found, hosts_new,"
            "  hosts_updated, hosts_conflict, triggered_by, source_type,"
            "  progress_phase, progress_message"
            ") VALUES ("
            "  '[\"nmap\"]', '2026-08-08T00:00:00Z', 'completed', 0, 0,"
            "  0, 0, 'api', 'manual', 'done', ''"
            ") RETURNING id"
        )
    ).scalar()
    for ip in ("10.0.0.1", "10.0.0.2"):
        connection.execute(
            sa.text(
                "INSERT INTO scan_results ("
                "  scan_job_id, ip_address, created_at, source_type, state, merge_status"
                ") VALUES (:j, :ip, '2026-08-08T00:00:00Z', 'nmap', 'new', 'pending')"
            ),
            {"j": job_id, "ip": ip},
        )


def test_system_profile_uniqueness_is_partial(db_session):
    """Scoped to `managed_by = 'system'`, so a user-created profile may target
    the same CIDR — plan §3's "user-created profiles remain separate and are
    never overwritten"."""
    module = _load_migration(_MIGRATION)
    connection = db_session.get_bind()

    _replay(connection, module)

    definition = _index_definition(
        connection, "discovery_profiles", "uq_discovery_profiles_system_agent_cidr"
    )
    assert definition is not None
    assert "UNIQUE INDEX" in definition
    assert "scan_agent_id" in definition and "normalized_cidr" in definition
    assert "WHERE" in definition and "system" in definition


def test_dispatch_token_is_unique_and_job_lookup_indexes_exist(db_session):
    module = _load_migration(_MIGRATION)
    connection = db_session.get_bind()

    _replay(connection, module)

    definition = _index_definition(connection, "scan_jobs", "uq_scan_jobs_dispatch_id")
    assert definition is not None
    assert "UNIQUE INDEX" in definition
    assert "WHERE" in definition and "dispatch_id IS NOT NULL" in definition

    indexes = {
        i["name"]: i["column_names"] for i in sa.inspect(connection).get_indexes("scan_jobs")
    }
    assert indexes.get("ix_scan_jobs_agent_status_created") == [
        "scan_agent_id",
        "status",
        "created_at",
    ]
    # `profile_id` has been an unindexed FK since it was introduced; the
    # per-profile dispatch lookups make that measurable rather than theoretical.
    assert indexes.get("ix_scan_jobs_profile_id") == ["profile_id"]
