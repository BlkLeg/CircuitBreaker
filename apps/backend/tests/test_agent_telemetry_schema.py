"""Schema-level guarantees for the agent host telemetry tables (Task 8, D-3).

Two independent things are pinned here:

1. `AgentHostSample.projection_attempts` and `ix_agent_host_samples_projection`
   are **gone**. Projection runs in the same transaction as the sample insert,
   so a persisted-but-unprojected row cannot exist and nothing ever counts
   attempts; the index supported a scan no query performs. `projected_at`
   stays — `api/agents.py::_sample_json` reports it.
2. Migration `0095_agent_host_telemetry` emits **no** TimescaleDB-only DDL
   unless the extension is actually available (and, for the
   `ALTER TABLE ... SET (timescaledb.compress ...)` pair, unless the target is
   actually a hypertable). The deployment stack in `docker-compose.deps.yml`
   is plain `postgres:16-alpine`, where an unguarded statement aborts the
   whole upgrade.
"""

from __future__ import annotations

import ast
import importlib.util
import io
import tokenize
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext

from app.api.agents import _sample_json
from app.db.models import AgentHostSample

_VERSIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "versions"
_GUARD_NAMES = ("_has_timescaledb", "_is_hypertable")


def _load_migration(name: str):
    """Import a migration module by file path — `migrations/versions` is not a
    package, so a normal import will not find it."""
    path = _VERSIONS_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_migration_{name}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _StubResult:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value


class _StubConnection:
    """Minimal `execute(...).scalar()` stand-in for the guard helpers."""

    def __init__(self, value):
        self._value = value
        self.statements: list[str] = []

    def execute(self, statement, params=None):
        self.statements.append(str(statement))
        return _StubResult(self._value)


# ── 1. The dead column and index are gone; projected_at survives ─────────────


def test_agent_host_sample_has_no_projection_attempts_column():
    assert "projection_attempts" not in AgentHostSample.__table__.c


def test_agent_host_samples_has_no_dead_projection_index(db_session):
    model_indexes = {index.name for index in AgentHostSample.__table__.indexes}
    assert "ix_agent_host_samples_projection" not in model_indexes
    assert "ix_agent_host_samples_agent_time" in model_indexes

    db_indexes = {
        index["name"]
        for index in sa.inspect(db_session.get_bind()).get_indexes("agent_host_samples")
    }
    assert "ix_agent_host_samples_projection" not in db_indexes


def test_projected_at_still_present_and_reported(db_session, factories):
    """The drop did not overreach: `projected_at` is live and still surfaces."""
    assert "projected_at" in AgentHostSample.__table__.c

    agent = factories.agent()
    unprojected = factories.agent_host_sample(agent)
    assert _sample_json(unprojected)["projected"] is False

    from app.core.time import utcnow

    projected = factories.agent_host_sample(agent, projected_at=utcnow())
    assert _sample_json(projected)["projected"] is True


# ── 2. Migration 0095 guards every TimescaleDB-only statement ────────────────


def test_migration_0095_skips_hypertable_without_timescaledb():
    module = _load_migration("0095_agent_host_telemetry")
    assert module._has_timescaledb(_StubConnection(None)) is False


def test_has_timescaledb_true_when_extension_available():
    module = _load_migration("0095_agent_host_telemetry")
    assert module._has_timescaledb(_StubConnection(1)) is True


def test_is_hypertable_false_for_a_plain_table(db_session):
    module = _load_migration("0095_agent_host_telemetry")
    bind = db_session.get_bind()
    assert module._has_timescaledb(bind) is True
    assert module._is_hypertable(bind, "agent_host_samples") is False


def _timescale_token_lines(source: str) -> list[tuple[int, str]]:
    """`(lineno, token)` for every non-comment token naming TimescaleDB DDL.

    Comments are excluded on purpose — a comment explaining the guard is not
    a statement PostgreSQL will choke on.
    """
    hits: list[tuple[int, str]] = []
    reader = io.StringIO(source).readline
    for token in tokenize.generate_tokens(reader):
        if token.type in (tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE):
            continue
        if "timescaledb." in token.string or "create_hypertable" in token.string:
            hits.append((token.start[0], token.string.strip()))
    return hits


def _guard_aliases(tree: ast.AST, source: str) -> dict[str, str]:
    """Local names bound to an expression that calls a guard helper.

    `compression_managed = is_postgres and _has_timescaledb(conn) and ...`
    makes `if compression_managed:` a guarded block just as much as spelling
    the call out inline, and keeps a disable/re-enable pair provably gated on
    the identical predicate.
    """
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        value_src = ast.get_source_segment(source, node.value) or ""
        if any(name in value_src for name in _GUARD_NAMES):
            aliases[target.id] = value_src
    return aliases


def _resolve_guard(test_src: str, aliases: dict[str, str]) -> str:
    """Inline any guard alias referenced by an `if` test."""
    resolved = test_src
    for name, expansion in aliases.items():
        if name in resolved:
            resolved = f"{resolved} {expansion}"
    return resolved


def _guarded_line_ranges(tree: ast.AST, source: str) -> list[range]:
    """Line ranges of `if <guard>:` bodies, where <guard> reaches a guard helper."""
    aliases = _guard_aliases(tree, source)
    ranges: list[range] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test_src = _resolve_guard(ast.get_source_segment(source, node.test) or "", aliases)
        if not any(name in test_src for name in _GUARD_NAMES):
            continue
        for stmt in node.body:
            ranges.append(range(stmt.lineno, (stmt.end_lineno or stmt.lineno) + 1))
    return ranges


def test_migration_0095_emits_no_timescaledb_ddl_without_the_extension():
    """Every `timescaledb.` / `create_hypertable` statement sits inside a block
    guarded by `_has_timescaledb` (and `_is_hypertable` where required)."""
    path = _VERSIONS_DIR / "0095_agent_host_telemetry.py"
    source = path.read_text()
    tree = ast.parse(source)

    helper_ranges = [
        range(node.lineno, (node.end_lineno or node.lineno) + 1)
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name in _GUARD_NAMES
    ]
    guarded = _guarded_line_ranges(tree, source)
    assert guarded, "0095 declares no TimescaleDB guard blocks at all"

    offenders = []
    for lineno, text in _timescale_token_lines(source):
        if any(lineno in rng for rng in helper_ranges):
            continue  # the guard helpers' own SQL
        if not any(lineno in rng for rng in guarded):
            offenders.append((lineno, text))

    assert offenders == [], f"unguarded TimescaleDB DDL in 0095: {offenders}"


def test_migration_0095_compression_statements_also_check_is_hypertable():
    """`ALTER TABLE ... SET (timescaledb.compress ...)` fails on a non-hypertable
    even when the extension is installed, so availability alone is not enough."""
    path = _VERSIONS_DIR / "0095_agent_host_telemetry.py"
    source = path.read_text()
    lines = source.splitlines()
    tree = ast.parse(source)

    aliases = _guard_aliases(tree, source)
    compress_blocks = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        body_src = "\n".join(
            "\n".join(lines[stmt.lineno - 1 : (stmt.end_lineno or stmt.lineno)])
            for stmt in node.body
        )
        if "timescaledb.compress" not in body_src:
            continue
        compress_blocks += 1
        test_src = _resolve_guard(ast.get_source_segment(source, node.test) or "", aliases)
        assert "_has_timescaledb" in test_src, (
            f"compression block at line {node.lineno} is not gated on _has_timescaledb"
        )
        assert "_is_hypertable" in test_src, (
            f"compression block at line {node.lineno} is not gated on _is_hypertable"
        )
    # upgrade() disable + re-enable, downgrade() disable + re-enable
    assert compress_blocks == 4


# ── 3. Migration 0096 drops the column idempotently ─────────────────────────


@pytest.mark.parametrize("run", [1, 2])
def test_migration_0096_is_idempotent(db_session, run):
    """The column/index are already absent (schema is built from the models),
    so both passes must be clean no-ops."""
    module = _load_migration("0096_drop_agent_projection_attempts")
    assert module.down_revision == "0095_agent_host_telemetry"

    connection = db_session.get_bind()
    for _ in range(run):
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            module.upgrade()

    columns = {c["name"] for c in sa.inspect(connection).get_columns("agent_host_samples")}
    assert "projection_attempts" not in columns
    assert "projected_at" in columns
