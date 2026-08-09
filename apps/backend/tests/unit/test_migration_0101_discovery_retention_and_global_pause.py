"""Schema-level guarantees for Slice 4's Phase D remediation (Fixes A1 and A2).

Two defects that both survived behind green gates, and both are schema-shaped:

**A1.** `hardware.source_scan_result_id` was a bare `ForeignKey("scan_results.id")`
— NO ACTION — and every discovery approval path writes it. The retention purge
(`discovery_scheduler._purge_old_scan_results_impl`) therefore raised
`ForeignKeyViolation` on the first expiring result that had been merged into
inventory, its own `except` swallowed it, and results, logs *and* jobs all
survived. Retention had never happened for any installation that ever approved a
discovered device. `tests/test_discovery.py` proves the behaviour against real
rows; this module pins the constraint that makes it possible, in both the
migrated and the fresh-install schema, and audits the whole inbound FK graph so
the next edge added to these tables cannot re-break it unnoticed.

**A2.** `app_settings.agent_discovery_paused` did not exist. The fleet-wide hold
read `False` forever and only a test writing an *unmapped* attribute could see
it as anything else.

Mirrors `tests/unit/test_migration_0100_discovery_agent_execution.py`.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext

_VERSIONS_DIR = Path(__file__).resolve().parents[2] / "migrations" / "versions"
_MIGRATION = "0101_discovery_retention_and_global_pause"
_PARENT = "0100_discovery_agent_execution"

_PAUSE_COLUMN = "agent_discovery_paused"
_PROVENANCE_COLUMN = "source_scan_result_id"

#: PostgreSQL's `pg_constraint.confdeltype` codes, spelled out so a failure
#: reads as the referential action an operator would recognise.
_ON_DELETE = {
    "a": "NO ACTION",
    "r": "RESTRICT",
    "c": "CASCADE",
    "n": "SET NULL",
    "d": "SET DEFAULT",
}

#: Every foreign key that points *at* a table the retention purge deletes from,
#: with the referential action each one must carry. This is the audit A1 exists
#: because nobody had done: the Task 26 review checked the three FKs Slice 4
#: *added* and never enumerated the ones already there.
#:
#: * `hardware.source_scan_result_id` — SET NULL. Inventory outlives discovery
#:   history; the provenance pointer does not. NO ACTION here blocked the purge
#:   outright.
#: * `scan_results.scan_job_id` / `scan_logs.scan_job_id` — NO ACTION is correct
#:   *because the purge deletes both children explicitly, in the same
#:   transaction, before the job*. They are NOT NULL, so SET NULL is impossible
#:   and CASCADE would hide a bug rather than fix one: a job may only ever be
#:   deleted by something that meant to take its children too.
#: * `scan_jobs.profile_id` — NO ACTION, and unreachable by the purge, which
#:   deletes no `discovery_profiles` row at all. A profile is the subnet's
#:   identity and cadence, not history (D-1).
_INBOUND_FKS_TO_PURGED_TABLES = {
    ("hardware", "source_scan_result_id", "scan_results"): "SET NULL",
    ("scan_results", "scan_job_id", "scan_jobs"): "NO ACTION",
    ("scan_logs", "scan_job_id", "scan_jobs"): "NO ACTION",
    ("scan_jobs", "profile_id", "discovery_profiles"): "NO ACTION",
}


def _load_migration(name: str):
    """`migrations/versions` is not a package, so import by file path."""
    path = _VERSIONS_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_migration_{name}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(connection, migration_step) -> None:
    context = MigrationContext.configure(connection)
    with Operations.context(context):
        migration_step()


def _replay(connection, module) -> None:
    """Downgrade then upgrade, so every assertion reads the migration's own DDL
    rather than the `Base.metadata.create_all` schema the fixture starts from."""
    _run(connection, module.downgrade)
    _run(connection, module.upgrade)


def _ondelete(connection, table: str, column: str) -> str | None:
    """The referential action on *table.column*'s foreign key, as PostgreSQL
    holds it. Read from `pg_constraint` rather than the inspector because
    reflection reports NO ACTION by *omitting* `ondelete`, which is
    indistinguishable from "there is no constraint at all"."""
    row = connection.execute(
        sa.text(
            "SELECT c.confdeltype FROM pg_constraint c "
            "JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1] "
            "WHERE c.contype = 'f' AND c.conrelid = cast(:t AS regclass) "
            "AND array_length(c.conkey, 1) = 1 AND a.attname = :c"
        ),
        {"t": table, "c": column},
    ).scalar()
    return None if row is None else _ON_DELETE[row]


def test_revision_chains_onto_0100():
    module = _load_migration(_MIGRATION)

    assert module.revision == _MIGRATION
    assert module.down_revision == _PARENT


def test_migration_0101_is_the_only_child_of_0100():
    """A second migration claiming the same parent gives alembic two heads and
    breaks `upgrade head` on every deployment — the exact check CI runs."""
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


def test_the_provenance_pointer_is_set_null_after_the_migration(db_session):
    """The constraint that lets retention run at all."""
    module = _load_migration(_MIGRATION)
    connection = db_session.get_bind()

    _replay(connection, module)

    assert _ondelete(connection, "hardware", _PROVENANCE_COLUMN) == "SET NULL", (
        "NO ACTION here makes every merged device pin its scan result forever, "
        "and one such row rolls the whole day's purge back"
    )


def test_the_downgrade_really_restores_no_action(db_session):
    """A downgrade that left SET NULL behind would make this revision
    irreversible in the one direction an operator rolls back for."""
    module = _load_migration(_MIGRATION)
    connection = db_session.get_bind()

    _run(connection, module.downgrade)
    assert _ondelete(connection, "hardware", _PROVENANCE_COLUMN) == "NO ACTION"
    assert _PAUSE_COLUMN not in {
        c["name"] for c in sa.inspect(connection).get_columns("app_settings")
    }

    _run(connection, module.upgrade)
    assert _ondelete(connection, "hardware", _PROVENANCE_COLUMN) == "SET NULL"


def test_every_foreign_key_into_the_purged_tables_is_accounted_for(db_session):
    """The enumeration A1 exists because nobody had done.

    Fails on a *new* inbound edge as loudly as on a changed one: an FK pointing
    at `scan_results`, `scan_jobs` or `discovery_profiles` that nobody thought
    about is exactly how retention broke, and it broke silently for the lifetime
    of the feature.
    """
    module = _load_migration(_MIGRATION)
    connection = db_session.get_bind()

    _replay(connection, module)

    rows = connection.execute(
        sa.text(
            "SELECT c.conrelid::regclass::text, a.attname, c.confrelid::regclass::text, "
            "       c.confdeltype "
            "FROM pg_constraint c "
            "JOIN unnest(c.conkey) AS k(attnum) ON true "
            "JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum "
            "WHERE c.contype = 'f' "
            "AND c.confrelid::regclass::text IN "
            "    ('scan_results', 'scan_jobs', 'discovery_profiles')"
        )
    ).all()

    actual = {(src, column, target): _ON_DELETE[code] for src, column, target, code in rows}
    assert actual == _INBOUND_FKS_TO_PURGED_TABLES


def test_the_global_pause_column_exists_and_holds_nobody_by_default(db_session):
    """A2: the storage `discovery_service.global_agent_discovery_paused` reads.

    NOT NULL with a `false` server default, because the column lands on a table
    that already has its singleton row and "not paused" is the only backfill
    that preserves the behaviour of every install upgrading into it.
    """
    module = _load_migration(_MIGRATION)
    connection = db_session.get_bind()

    _replay(connection, module)

    column = {c["name"]: c for c in sa.inspect(connection).get_columns("app_settings")}[
        _PAUSE_COLUMN
    ]
    assert column["nullable"] is False
    assert "false" in str(column["default"]).lower()


def test_upgrading_twice_is_a_no_op(db_session):
    """Both steps are guarded, and that guard is what lets the fresh-install path
    work: `0001_init` creates the column and the SET NULL constraint from
    `Base.metadata`, and this revision then runs against a schema that already
    has both. An unguarded `op.add_column` would raise `DuplicateColumn` there —
    which is why every earlier `app_settings` column had to be excluded from the
    bootstrap instead (`0002_discovery_engine.py:74-84`).
    """
    module = _load_migration(_MIGRATION)
    connection = db_session.get_bind()

    _replay(connection, module)
    _run(connection, module.upgrade)

    assert _ondelete(connection, "hardware", _PROVENANCE_COLUMN) == "SET NULL"
    assert _PAUSE_COLUMN in {c["name"] for c in sa.inspect(connection).get_columns("app_settings")}


def test_a_fresh_bootstrap_carries_the_provenance_ondelete(db_session):
    """D-2: `0001_init` rebuilds from `Base.metadata`, so what it copies *badly*
    is the only definition a fresh install ever gets.

    This edge is copied faithfully — `scan_results` is not an excluded table and
    `id` is not an excluded column, so `_should_copy_fk` keeps the constraint and
    `_copy_column` passes `ondelete=fk.ondelete` through — which is why no
    `_EXCLUDED_COLUMNS` entry is needed for it, unlike every FK `0100` adds.
    Asserted rather than assumed: a fresh install silently getting NO ACTION
    would reproduce the original bug on every new deployment.
    """
    bootstrap = _load_migration("0001_init")._build_bootstrap_metadata()

    foreign_keys = list(bootstrap.tables["hardware"].c[_PROVENANCE_COLUMN].foreign_keys)
    assert [fk.target_fullname for fk in foreign_keys] == ["scan_results.id"]
    assert foreign_keys[0].ondelete == "SET NULL"


def test_a_fresh_bootstrap_creates_the_global_pause_column(db_session):
    """The other half of the fresh-install path: a plain `Boolean NOT NULL
    DEFAULT '0'` with no FK and no index is reproduced exactly by `_copy_column`,
    so it stays out of `_EXCLUDED_COLUMNS` and the guarded `upgrade()` above
    simply finds it already there."""
    bootstrap = _load_migration("0001_init")._build_bootstrap_metadata()

    column = bootstrap.tables["app_settings"].c[_PAUSE_COLUMN]
    assert column.nullable is False
    assert column.server_default is not None
