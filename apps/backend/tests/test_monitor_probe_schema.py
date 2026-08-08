"""Bootstrap fidelity for the remote-probe schema (Task 6, §1).

`0001_init` does not replay later revisions — it rebuilds the whole current
`Base.metadata` up front and every later `create_table` then short-circuits —
so anything it copies *badly* is the only definition a fresh install ever gets.
Two of Slice 3's objects are copied badly, which is why both are excluded from
the bootstrap and created by `0099` on fresh installs and upgrades alike:

1. `monitor_items.probe_agent_id` points at `agents`, which is in
   `_EXCLUDED_TABLES`, so `_should_copy_fk` drops the constraint and the
   bootstrap would emit a bare `INTEGER` column — voiding the RESTRICT
   lifecycle §1 requires (delete-an-assigned-agent must fail, not orphan).
2. The bootstrap's index-copy loop rebuilds indexes as
   `sa.Index(name, *cols, unique=...)`, dropping `postgresql_where`. Copying
   `monitor_probe_runs` would turn its partial unique index into a full one and
   cap a fresh install at one probe run per monitor, forever.

Patterned on `tests/test_agent_telemetry_schema.py`.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext

from app.db.models import MonitorProbeRun

_VERSIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "versions"
_PROBE_COLUMNS = (
    "probe_agent_id",
    "probe_execution_status",
    "probe_execution_reason",
    "probe_last_dispatched_at",
    "probe_last_result_at",
)


def _load_migration(name: str):
    """Import a migration module by file path — `migrations/versions` is not a
    package, so a normal import will not find it."""
    path = _VERSIONS_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_migration_{name}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_bootstrap_does_not_create_monitor_items_probe_columns():
    bootstrap = _load_migration("0001_init")._build_bootstrap_metadata()
    monitor_items = bootstrap.tables["monitor_items"]

    present = [name for name in _PROBE_COLUMNS if name in monitor_items.c]
    assert present == [], (
        "0001_init would emit these columns without their agents FK "
        f"(agents is an excluded table): {present}"
    )
    assert "ix_monitor_items_probe_due" not in {index.name for index in monitor_items.indexes}


def test_bootstrap_does_not_create_monitor_probe_runs():
    bootstrap = _load_migration("0001_init")._build_bootstrap_metadata()

    assert "monitor_probe_runs" not in bootstrap.tables

    # The reason the exclusion is load-bearing: the model really does rely on a
    # predicate the copy loop has no way to carry across.
    partial = {
        index.name: index.dialect_options["postgresql"]["where"]
        for index in MonitorProbeRun.__table__.indexes
        if index.dialect_options["postgresql"]["where"] is not None
    }
    assert partial, "monitor_probe_runs declares no partial index — exclusion would be pointless"


def test_probe_agent_id_foreign_key_survives_a_real_alembic_upgrade(db_session):
    """Drive `0099` the way alembic does, over a `monitor_items` that has no
    probe columns — i.e. exactly the shape the bootstrap leaves behind."""
    module = _load_migration("0099_monitor_probe_runs")
    connection = db_session.get_bind()

    context = MigrationContext.configure(connection)
    with Operations.context(context):
        module.downgrade()
    columns = {c["name"] for c in sa.inspect(connection).get_columns("monitor_items")}
    assert not (set(_PROBE_COLUMNS) & columns)

    context = MigrationContext.configure(connection)
    with Operations.context(context):
        module.upgrade()

    fks = {
        (tuple(fk["constrained_columns"]), fk["referred_table"], fk["options"].get("ondelete"))
        for fk in sa.inspect(connection).get_foreign_keys("monitor_items")
    }
    assert (("probe_agent_id",), "agents", "RESTRICT") in fks, (
        f"probe_agent_id must be a RESTRICT FK to agents, got {fks}"
    )
