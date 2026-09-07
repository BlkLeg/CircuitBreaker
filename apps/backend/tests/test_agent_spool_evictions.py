"""When the agent destroys history, the server has to say so (plan Phase 3).

The agent's disk spool is capped and drops its oldest buffered observations to
make room. The policy stays. What is pinned here is that it is no longer
*silent* on the server side:

1. Migration `0110_agent_spool_evictions` chains onto `0109`, adds every column
   as nullable, replays idempotently, and its `downgrade` really drops them.
2. `agent_registry.record_spool_evictions` is change-gated like
   `record_spool_stats`, writes a `spool_evicted` audit event when the reported
   loss *increases*, and a `spool_eviction_counter_reset` event when it
   *decreases* — never a silent `max()`, which would hide a state-directory
   reset.
3. `agent_registry.record_refused_frame` counts frames this server destroyed on
   ingest, and is deliberately **not** rate-limited, unlike the audit row that
   accompanies it.
4. Backward compatibility in both directions: an agent that omits the wire keys
   leaves the columns NULL ("never reported"), and one that sends explicit
   zeros writes 0 ("reported, nothing destroyed").
"""

from __future__ import annotations

import ast
import importlib.util
from datetime import UTC, datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext

from app.db.models import Agent, AgentEvent
from app.schemas.agent_frame import HeartbeatPayload, HelloPayload
from app.services import agent_registry

_VERSIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "versions"
_MIGRATION = "0110_agent_spool_evictions"
_PARENT = "0109_discovery_enrichment"
_COLUMNS = (
    "spool_evicted_frames",
    "spool_evicted_bytes",
    "spool_evicted_oldest_at",
    "spool_evicted_newest_at",
    "spool_evicted_reported_at",
    "refused_frames",
    "refused_frames_last_at",
    "refused_frames_last_reason",
    "data_ack_negotiated",
)

_OLDEST = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)
_NEWEST = datetime(2026, 9, 3, 18, 30, tzinfo=UTC)


def _load_migration(name: str):
    """`migrations/versions` is not a package, so import by file path."""
    path = _VERSIONS_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_migration_{name}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _events(db, agent_id: int, event_type: str) -> list[AgentEvent]:
    return (
        db.query(AgentEvent)
        .filter(AgentEvent.agent_id == agent_id, AgentEvent.event_type == event_type)
        .all()
    )


# ── Migration ───────────────────────────────────────────────────────────────


def test_migration_0110_chains_onto_0109():
    module = _load_migration(_MIGRATION)

    assert module.revision == _MIGRATION
    assert module.down_revision == _PARENT


def test_migration_0110_is_the_only_child_of_0109():
    """A second migration claiming the same parent would give alembic two
    heads and break `upgrade head` on every deployment."""
    children = []
    for path in _VERSIONS_DIR.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            targets = getattr(node, "targets", [])
            annotated = isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
            names = [t.id for t in targets if isinstance(t, ast.Name)]
            if annotated:
                names = [node.target.id]
            if "down_revision" not in names:
                continue
            value = getattr(node, "value", None)
            if isinstance(value, ast.Constant) and value.value == _PARENT:
                children.append(path.name)

    assert children == [f"{_MIGRATION}.py"]


def test_agent_model_declares_every_new_column_as_nullable():
    for name in _COLUMNS:
        column = Agent.__table__.columns[name]
        assert column.nullable is True, f"{name} must be nullable — NULL means 'never reported'"


@pytest.mark.parametrize("run", [1, 2])
def test_migration_0110_upgrade_is_idempotent(db_session, run):
    """The columns already exist (the test schema is built from the models),
    so every pass must be a clean no-op rather than a duplicate-column error."""
    module = _load_migration(_MIGRATION)
    connection = db_session.get_bind()

    for _ in range(run):
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            module.upgrade()

    columns = {c["name"] for c in sa.inspect(connection).get_columns("agents")}
    assert set(_COLUMNS) <= columns


def test_migration_0110_replays_upgrade_downgrade_upgrade(db_session):
    module = _load_migration(_MIGRATION)
    connection = db_session.get_bind()

    context = MigrationContext.configure(connection)
    with Operations.context(context):
        module.downgrade()
    columns = {c["name"] for c in sa.inspect(connection).get_columns("agents")}
    assert not (set(_COLUMNS) & columns)

    context = MigrationContext.configure(connection)
    with Operations.context(context):
        module.upgrade()
    restored = {c["name"]: c for c in sa.inspect(connection).get_columns("agents")}
    assert set(_COLUMNS) <= set(restored)
    for name in _COLUMNS:
        assert restored[name]["nullable"] is True


def test_migration_0110_backfills_nothing(db_session, factories):
    """A fabricated 0 would claim an agent had confirmed it destroyed nothing.
    NULL is the truth for an agent that has never reported."""
    source = (_VERSIONS_DIR / f"{_MIGRATION}.py").read_text().lower()
    assert "update " not in source
    assert "insert " not in source

    agent = factories.agent(status="active")
    module = _load_migration(_MIGRATION)
    connection = db_session.get_bind()
    context = MigrationContext.configure(connection)
    with Operations.context(context):
        module.upgrade()

    db_session.expire_all()
    refreshed = db_session.get(Agent, agent.id)
    for name in _COLUMNS:
        assert getattr(refreshed, name) is None


# ── record_spool_evictions ──────────────────────────────────────────────────


def test_first_eviction_report_writes_the_columns_and_audits_the_loss(db_session, factories):
    """The event is the point of the task: a permanent, timestamped record
    that history was destroyed, which survives the counters being overwritten
    by a later report."""
    agent = factories.agent(status="active")
    assert agent.spool_evicted_frames is None

    wrote = agent_registry.record_spool_evictions(
        db_session, agent, 9412, 33554432, _OLDEST, _NEWEST
    )
    db_session.commit()

    assert wrote is True
    assert agent.spool_evicted_frames == 9412
    assert agent.spool_evicted_bytes == 33554432
    assert agent.spool_evicted_oldest_at == _OLDEST
    assert agent.spool_evicted_newest_at == _NEWEST
    assert agent.spool_evicted_reported_at is not None

    events = _events(db_session, agent.id, agent_registry.EVENT_SPOOL_EVICTED)
    assert len(events) == 1
    assert events[0].detail["frames"] == 9412
    assert events[0].detail["new_frames"] == 9412
    assert events[0].detail["oldest_dropped_at"] == _OLDEST.isoformat()
    assert events[0].detail["newest_dropped_at"] == _NEWEST.isoformat()


def test_an_explicit_zero_eviction_report_writes_no_event(db_session, factories):
    """A current agent that has destroyed nothing still sends the keys. That is
    a report worth persisting (it distinguishes "confirmed clean" from "never
    said") but it is not an audit-worthy event."""
    agent = factories.agent(status="active")

    wrote = agent_registry.record_spool_evictions(db_session, agent, 0, 0, None, None)
    db_session.commit()

    assert wrote is True
    assert agent.spool_evicted_frames == 0
    assert _events(db_session, agent.id, agent_registry.EVENT_SPOOL_EVICTED) == []


def test_unchanged_eviction_report_does_not_rewrite_the_row(db_session, factories):
    """Heartbeats arrive every 20s per agent and the steady state is
    "unchanged". Re-stamping on every one would be a fleet-wide UPDATE storm
    carrying no new information — and would spam the audit trail besides."""
    agent = factories.agent(status="active")
    assert (
        agent_registry.record_spool_evictions(db_session, agent, 9412, 33554432, _OLDEST, _NEWEST)
        is True
    )
    db_session.commit()
    first_reported_at = agent.spool_evicted_reported_at

    wrote = agent_registry.record_spool_evictions(
        db_session, agent, 9412, 33554432, _OLDEST, _NEWEST
    )
    db_session.commit()

    assert wrote is False
    assert agent.spool_evicted_reported_at == first_reported_at
    assert len(_events(db_session, agent.id, agent_registry.EVENT_SPOOL_EVICTED)) == 1


def test_an_increase_audits_only_the_newly_destroyed_frames(db_session, factories):
    agent = factories.agent(status="active")
    agent_registry.record_spool_evictions(db_session, agent, 100, 1000, _OLDEST, _OLDEST)
    db_session.commit()

    agent_registry.record_spool_evictions(db_session, agent, 150, 1500, _OLDEST, _NEWEST)
    db_session.commit()

    events = _events(db_session, agent.id, agent_registry.EVENT_SPOOL_EVICTED)
    assert len(events) == 2
    assert events[-1].detail["frames"] == 150
    assert events[-1].detail["new_frames"] == 50


def test_a_decrease_is_recorded_as_a_counter_reset_not_silently_ignored(db_session, factories):
    """The agent never resets this counter, so a decrease means its state
    directory was recreated. Taking `max()` would look conservative and would
    in fact hide that — and the reset is itself worth knowing, because an
    eviction record was thrown away with it."""
    agent = factories.agent(status="active")
    agent_registry.record_spool_evictions(db_session, agent, 9412, 33554432, _OLDEST, _NEWEST)
    db_session.commit()

    wrote = agent_registry.record_spool_evictions(db_session, agent, 3, 512, None, None)
    db_session.commit()

    assert wrote is True
    # Overwritten, not max()'d.
    assert agent.spool_evicted_frames == 3
    assert agent.spool_evicted_bytes == 512
    assert agent.spool_evicted_oldest_at is None
    resets = _events(db_session, agent.id, agent_registry.EVENT_SPOOL_EVICTION_COUNTER_RESET)
    assert len(resets) == 1
    assert resets[0].detail["previous_frames"] == 9412
    assert resets[0].detail["reported_frames"] == 3
    # And it is not also audited as a fresh eviction.
    assert len(_events(db_session, agent.id, agent_registry.EVENT_SPOOL_EVICTED)) == 1


# ── record_refused_frame ────────────────────────────────────────────────────


def test_record_refused_frame_counts_every_refusal(db_session, factories):
    """Explicitly not rate-limited. The matching `agent_events` row is
    throttled to one a minute, so the audit trail undercounts by design; an
    operator must still be able to see the true volume."""
    agent = factories.agent(status="active")
    assert agent.refused_frames is None

    for _ in range(500):
        agent_registry.record_refused_frame(agent, agent_registry.REFUSAL_INVALID_HOST_TELEMETRY)
    db_session.commit()

    assert agent.refused_frames == 500
    assert agent.refused_frames_last_reason == agent_registry.REFUSAL_INVALID_HOST_TELEMETRY
    assert agent.refused_frames_last_at is not None


def test_record_refused_frame_bounds_the_stored_reason(db_session, factories):
    """The column is `String(64)`; a longer reason is truncated rather than
    raising a DataError mid-ingest."""
    agent = factories.agent(status="active")

    agent_registry.record_refused_frame(agent, "x" * 500)
    db_session.commit()

    assert len(agent.refused_frames_last_reason) == 64


# ── Backward compatibility, both directions ─────────────────────────────────


def test_old_agent_hello_leaves_the_eviction_columns_null(db_session, factories):
    """Old agent -> new server. A build predating the fields omits the keys
    entirely, and must not have a 0 invented for it — that would claim it had
    confirmed no data loss."""
    agent = factories.agent(status="active")

    agent_registry.update_hello_metadata(
        db_session, agent, HelloPayload.model_validate({"spool_depth": 3})
    )
    db_session.commit()

    assert agent.spool_evicted_frames is None
    assert agent.spool_evicted_bytes is None
    assert agent.spool_evicted_reported_at is None


def test_new_agent_hello_persists_the_at_connect_eviction_snapshot(db_session, factories):
    """Eviction happens while the agent is disconnected, so the reconnect is
    the first moment this server can learn of it."""
    agent = factories.agent(status="active")

    agent_registry.update_hello_metadata(
        db_session,
        agent,
        HelloPayload.model_validate(
            {
                "spool_depth": 4096,
                "spool_evicted_frames": 9412,
                "spool_evicted_bytes": 33554432,
                "spool_evicted_oldest_ts": _OLDEST.isoformat(),
                "spool_evicted_newest_ts": _NEWEST.isoformat(),
            }
        ),
    )
    db_session.commit()

    assert agent.spool_evicted_frames == 9412
    assert agent.spool_evicted_oldest_at == _OLDEST
    assert len(_events(db_session, agent.id, agent_registry.EVENT_SPOOL_EVICTED)) == 1


def test_wire_payloads_distinguish_absent_from_explicit_zero():
    """New agent -> old server is the other direction, and it holds because
    the extra keys are simply unknown to an older pydantic model, which drops
    them (`extra="ignore"`). What has to hold *here* is the mirror of that: a
    payload that omits the group and one that sends explicit zeros must stay
    distinguishable, which is the whole reason the Go side carries no
    `omitempty` and this side gates on `model_fields_set`."""
    old = HeartbeatPayload.model_validate({"spool_depth": 0, "spool_bytes": 0})
    assert old.spool_evicted_frames == 0
    assert "spool_evicted_frames" not in old.model_fields_set

    current = HeartbeatPayload.model_validate(
        {
            "spool_depth": 0,
            "spool_bytes": 0,
            "spool_evicted_frames": 0,
            "spool_evicted_bytes": 0,
            "spool_evicted_oldest_ts": None,
            "spool_evicted_newest_ts": None,
        }
    )
    assert "spool_evicted_frames" in current.model_fields_set
    assert current.spool_evicted_oldest_ts is None

    lossy = HeartbeatPayload.model_validate(
        {
            "spool_depth": 4096,
            "spool_bytes": 67108864,
            "spool_evicted_frames": 9412,
            "spool_evicted_bytes": 33554432,
            "spool_evicted_oldest_ts": "2026-09-01T00:00:00Z",
            "spool_evicted_newest_ts": "2026-09-03T18:30:00Z",
        }
    )
    assert lossy.spool_evicted_frames == 9412
    assert lossy.spool_evicted_oldest_ts == _OLDEST


def test_an_unknown_extra_key_is_ignored_rather_than_rejected():
    """New agent -> old server, simulated: an older `HeartbeatPayload` sees the
    eviction keys as unknown. Pydantic's default `extra="ignore"` must drop
    them rather than raise, or a current agent would tear down its link to
    every server that predates this phase."""
    payload = HeartbeatPayload.model_validate(
        {"spool_depth": 0, "spool_bytes": 0, "a_field_from_a_later_phase": {"nested": True}}
    )

    assert payload.spool_depth == 0
    assert not hasattr(payload, "a_field_from_a_later_phase")
