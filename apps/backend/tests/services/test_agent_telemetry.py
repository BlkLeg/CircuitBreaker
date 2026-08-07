"""`app.services.agent_telemetry` — payload validation, sample ingestion, the
Hardware live projection, and capability readiness.

Note on `AgentHostSample.projection_attempts`: the column and the
`ix_agent_host_samples_projection` index are **gone** (Task 8 / D-3). Projection
happens in the same transaction as the insert, so a persisted-but-unprojected
row cannot exist and nothing ever counted attempts; the index supported a scan
no query performs. `projected_at` stays and is asserted throughout this file.
The schema-level regression tests live in
`tests/test_agent_telemetry_schema.py::test_agent_host_sample_has_no_projection_attempts_column`
and its `..._has_no_dead_projection_index` sibling; the ingest path's own guard
is `test_ingest_still_succeeds_after_column_drop` below.
"""

from __future__ import annotations

import copy
import json
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from app.core.time import utcnow
from app.db.models import (
    AgentCapabilityReadiness,
    AgentEvent,
    AgentHostSample,
    Hardware,
    HardwareLiveMetric,
)
from app.schemas.agent_frame import TYPE_CAPABILITY_READINESS, AgentFrame
from app.services import agent_link, agent_telemetry

# The wire corpus is the schema of record for `telemetry.host` (Task 3), so the
# payload every test here builds on is *read from it* rather than hand-rolled —
# a collector-side field rename can then never pass the backend suite silently.
_CORPUS_PATH = Path(__file__).resolve().parents[4] / "fixtures" / "agent_frame_corpus.json"
_FULL_SAMPLE = "telemetry.host — full sample"


def _corpus_payload() -> dict:
    entries = json.loads(_CORPUS_PATH.read_text())
    for entry in entries:
        if entry["description"].startswith(_FULL_SAMPLE):
            return entry["json"]["payload"]
    raise AssertionError(
        f"{_CORPUS_PATH} has no entry described {_FULL_SAMPLE!r} — Task 3 owns that fixture"
    )


def _payload(**overrides) -> dict:
    """The corpus `telemetry.host` full sample with top-level keys overridden.

    Pass ``summary=_summary(...)`` to vary the summary; pass ``key=_ABSENT`` to
    drop a key entirely.
    """
    payload = copy.deepcopy(_corpus_payload())
    for key, value in overrides.items():
        if value is _ABSENT:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


def _summary(**overrides) -> dict:
    summary = copy.deepcopy(_corpus_payload()["summary"])
    for key, value in overrides.items():
        if value is _ABSENT:
            summary.pop(key, None)
        else:
            summary[key] = value
    return summary


class _Absent:
    def __repr__(self) -> str:  # pragma: no cover - debug aid only
        return "<absent>"


_ABSENT = _Absent()


@pytest.fixture(autouse=True)
def telemetry_side_effects(monkeypatch):
    """Intercept the three fan-out calls `agent_telemetry` makes.

    They are module-level *imports* (`from app.core.redis import get_redis`,
    `from app.services.telemetry_cache import cache_telemetry, publish_telemetry`),
    so patching `app.core.redis.get_redis` would not intercept them — the names
    must be patched on `app.services.agent_telemetry` itself.
    """
    published: list[tuple[str, dict]] = []
    redis_client = AsyncMock()

    async def _publish(channel, message):
        published.append((channel, json.loads(message)))
        return 1

    redis_client.publish.side_effect = _publish

    async def _get_redis():
        return redis_client

    cache_telemetry = AsyncMock()
    publish_telemetry = AsyncMock()
    monkeypatch.setattr(agent_telemetry, "get_redis", _get_redis)
    monkeypatch.setattr(agent_telemetry, "cache_telemetry", cache_telemetry)
    monkeypatch.setattr(agent_telemetry, "publish_telemetry", publish_telemetry)
    return SimpleNamespace(
        published=published,
        redis=redis_client,
        cache_telemetry=cache_telemetry,
        publish_telemetry=publish_telemetry,
    )


@pytest.fixture(autouse=True)
def reset_violation_window():
    """`_violations` is process-global; leaking counts across tests would make
    the rate-limit assertions order-dependent."""
    agent_telemetry._violations.clear()
    yield
    agent_telemetry._violations.clear()


def _readiness_rows(db, agent) -> list[AgentCapabilityReadiness]:
    return list(
        db.execute(
            select(AgentCapabilityReadiness)
            .where(AgentCapabilityReadiness.agent_id == agent.id)
            .order_by(AgentCapabilityReadiness.collector)
        ).scalars()
    )


def _samples(db, agent) -> list[AgentHostSample]:
    return list(
        db.execute(
            select(AgentHostSample)
            .where(AgentHostSample.agent_id == agent.id)
            .order_by(AgentHostSample.collected_at)
        ).scalars()
    )


def _count(db, model) -> int:
    return db.execute(select(func.count()).select_from(model)).scalar_one()


def _violations_for(db, agent) -> list[AgentEvent]:
    return list(
        db.execute(
            select(AgentEvent)
            .where(
                AgentEvent.agent_id == agent.id,
                AgentEvent.event_type == "protocol_violation",
            )
            .order_by(AgentEvent.id)
        ).scalars()
    )


# ── D-9: capability.readiness ingestion is all-or-nothing ────────────────────


@pytest.mark.asyncio
async def test_invalid_readiness_state_persists_nothing(db_session, factories):
    """A readiness report whose *second* entry is invalid must persist neither.

    Before the pre-validation pass, `ingest_readiness` mutated and `db.add`-ed
    each item as it iterated, so the first collector's row was already pending
    when the second raised — and the follow-up SELECT below flushes it
    (`tests/conftest.py` builds the session with SQLAlchemy's default
    `autoflush=True`).
    """
    agent = factories.agent(status="active")
    payload = {
        "readiness": [
            {"collector": "host.core", "state": "ready"},
            {"collector": "host.docker", "state": "bogus"},
        ]
    }

    with pytest.raises(agent_telemetry.InvalidHostTelemetry, match="invalid readiness state"):
        await agent_telemetry.ingest_readiness(db_session, agent, payload)

    assert _readiness_rows(db_session, agent) == []


@pytest.mark.asyncio
async def test_invalid_readiness_state_through_dispatch_frame_persists_nothing(
    db_session, factories
):
    """Same payload through the real caller, whose `except` branch commits."""
    agent = factories.agent(status="active")
    frame = AgentFrame(
        type=TYPE_CAPABILITY_READINESS,
        ts=utcnow(),
        payload={
            "readiness": [
                {"collector": "host.core", "state": "ready"},
                {"collector": "host.docker", "state": "bogus"},
            ]
        },
    )

    await agent_link.dispatch_frame(db_session, agent, frame)

    assert _readiness_rows(db_session, agent) == []
    events = list(
        db_session.execute(
            select(AgentEvent).where(
                AgentEvent.agent_id == agent.id,
                AgentEvent.event_type == "protocol_violation",
            )
        ).scalars()
    )
    assert len(events) == 1
    assert events[0].detail["reason"] == "invalid readiness state"


@pytest.mark.asyncio
async def test_ingest_readiness_accepts_disabled_state_without_grant(db_session, factories):
    """`capability.readiness` is deliberately absent from
    `agent_link.CAPABILITY_FOR_TYPE`, so an agent whose `host_telemetry` grant
    was just revoked can still report its own shutdown. Task 11 depends on
    exactly this: on disable it publishes one `disabled` row per collector."""
    agent = factories.agent(status="active")
    factories.agent_capability_grant(agent, capability="host_telemetry", enabled=False)
    factories.agent_capability_readiness(agent, collector="host.core", state="ready")
    db_session.commit()

    frame = AgentFrame(
        type=TYPE_CAPABILITY_READINESS,
        ts=utcnow(),
        payload={"readiness": [{"collector": "host.core", "state": "disabled"}]},
    )
    await agent_link.dispatch_frame(db_session, agent, frame)

    rows = _readiness_rows(db_session, agent)
    assert [(r.collector, r.state) for r in rows] == [("host.core", "disabled")]
    assert (
        db_session.execute(
            select(AgentEvent).where(
                AgentEvent.agent_id == agent.id,
                AgentEvent.event_type == "capability_violation",
            )
        ).first()
        is None
    )


# ── capability.readiness — normal operation ──────────────────────────────────


@pytest.mark.asyncio
async def test_first_readiness_report_inserts_one_row_per_collector(db_session, factories):
    agent = factories.agent(status="active")

    changed = await agent_telemetry.ingest_readiness(
        db_session,
        agent,
        {
            "readiness": [
                {"collector": "host.docker", "state": "unavailable", "reason": "no socket"},
                {"collector": "host.core", "state": "ready"},
            ]
        },
    )

    assert changed is True
    rows = _readiness_rows(db_session, agent)
    assert [(r.collector, r.state) for r in rows] == [
        ("host.core", "ready"),
        ("host.docker", "unavailable"),
    ]
    assert rows[1].reason == "no socket"


@pytest.mark.asyncio
async def test_identical_readiness_replay_reports_unchanged_and_publishes_nothing(
    db_session, factories, telemetry_side_effects
):
    agent = factories.agent(status="active")
    payload = {"readiness": [{"collector": "host.core", "state": "ready"}]}

    assert await agent_telemetry.ingest_readiness(db_session, agent, payload) is True
    telemetry_side_effects.published.clear()

    assert await agent_telemetry.ingest_readiness(db_session, agent, payload) is False
    assert telemetry_side_effects.published == []


@pytest.mark.asyncio
async def test_readiness_reason_change_alone_reports_changed(db_session, factories):
    agent = factories.agent(status="active")
    await agent_telemetry.ingest_readiness(
        db_session, agent, {"readiness": [{"collector": "host.hwmon", "state": "degraded"}]}
    )

    changed = await agent_telemetry.ingest_readiness(
        db_session,
        agent,
        {"readiness": [{"collector": "host.hwmon", "state": "degraded", "reason": "no sensors"}]},
    )

    assert changed is True
    assert _readiness_rows(db_session, agent)[0].reason == "no sensors"


@pytest.mark.asyncio
async def test_readiness_updated_at_advances_even_on_an_unchanged_report(db_session, factories):
    """Freshness is what the UI shows; an unchanged report is still a report."""
    agent = factories.agent(status="active")
    payload = {"readiness": [{"collector": "host.core", "state": "ready"}]}

    await agent_telemetry.ingest_readiness(db_session, agent, payload)
    first = _readiness_rows(db_session, agent)[0].updated_at

    assert await agent_telemetry.ingest_readiness(db_session, agent, payload) is False
    second = _readiness_rows(db_session, agent)[0].updated_at

    assert second > first


@pytest.mark.asyncio
async def test_malformed_readiness_payload_records_a_protocol_violation(db_session, factories):
    agent = factories.agent(status="active")
    frame = AgentFrame(type=TYPE_CAPABILITY_READINESS, ts=utcnow(), payload={"readiness": "nope"})

    await agent_link.dispatch_frame(db_session, agent, frame)

    events = list(
        db_session.execute(
            select(AgentEvent).where(
                AgentEvent.agent_id == agent.id,
                AgentEvent.event_type == "protocol_violation",
            )
        ).scalars()
    )
    assert [e.detail["reason"] for e in events] == ["invalid readiness payload"]
    assert _readiness_rows(db_session, agent) == []


# ── validate_host_payload — rejection matrix ─────────────────────────────────


def test_payload_over_256_kib_is_rejected():
    payload = _payload(padding="x" * (256 << 10))

    with pytest.raises(agent_telemetry.InvalidHostTelemetry, match="payload exceeds 256 KiB"):
        agent_telemetry.validate_host_payload(payload, utcnow())


@pytest.mark.parametrize("missing", ["sample_id", "status", "summary"])
def test_missing_required_field_is_rejected(missing):
    payload = _payload(**{missing: _ABSENT})

    with pytest.raises(agent_telemetry.InvalidHostTelemetry, match="payload schema is invalid"):
        agent_telemetry.validate_host_payload(payload, utcnow())


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"schema": 2}, id="schema-2"),
        pytest.param({"status": "unknown"}, id="status-unknown"),
    ],
)
def test_unsupported_schema_or_status_is_rejected(overrides):
    with pytest.raises(agent_telemetry.InvalidHostTelemetry, match="unsupported schema or status"):
        agent_telemetry.validate_host_payload(_payload(**overrides), utcnow())


@pytest.mark.parametrize(
    "sample_id",
    [
        pytest.param("a" * 31, id="31-chars"),
        pytest.param("a" * 33, id="33-chars"),
        pytest.param("A" * 32, id="uppercase-hex"),
        pytest.param("z" * 32, id="non-hex"),
    ],
)
def test_malformed_sample_id_is_rejected(sample_id):
    with pytest.raises(
        agent_telemetry.InvalidHostTelemetry, match="sample_id must be 128-bit lowercase hex"
    ):
        agent_telemetry.validate_host_payload(_payload(sample_id=sample_id), utcnow())


@pytest.mark.parametrize(
    ("field", "limit"),
    [("filesystems", 128), ("disks", 128), ("interfaces", 128), ("temperatures", 256)],
)
def test_oversized_list_is_rejected(field, limit):
    entry = _corpus_payload()[field][0]
    payload = _payload(**{field: [copy.deepcopy(entry) for _ in range(limit + 1)]})

    with pytest.raises(
        agent_telemetry.InvalidHostTelemetry, match=f"{field} exceeds {limit} entries"
    ):
        agent_telemetry.validate_host_payload(payload, utcnow())


@pytest.mark.parametrize("field", sorted(agent_telemetry._PERCENT_FIELDS))
@pytest.mark.parametrize("value", [100.1, -0.1])
def test_percent_field_outside_range_is_rejected(field, value):
    payload = _payload(summary=_summary(**{field: value}))

    with pytest.raises(
        agent_telemetry.InvalidHostTelemetry, match=f"summary.{field} is outside 0..100"
    ):
        agent_telemetry.validate_host_payload(payload, utcnow())


@pytest.mark.parametrize("value", [0, 100])
def test_percent_field_boundaries_are_accepted(value):
    payload = _payload(summary=_summary(**dict.fromkeys(agent_telemetry._PERCENT_FIELDS, value)))

    sample = agent_telemetry.validate_host_payload(payload, utcnow())

    assert sample.summary["cpu_pct"] == value


def test_negative_non_percent_field_is_rejected():
    payload = _payload(summary=_summary(uptime_s=-1))

    with pytest.raises(agent_telemetry.InvalidHostTelemetry, match="summary.uptime_s is negative"):
        agent_telemetry.validate_host_payload(payload, utcnow())


@pytest.mark.parametrize("value", ["high", None], ids=["string", "null"])
def test_non_numeric_summary_value_fails_schema_validation(value):
    """`summary: dict[str, int | float]` rejects these *before* the numeric
    loop runs, so the message is the schema one — not "is not numeric"."""
    payload = _payload(summary=_summary(cpu_pct=value))

    with pytest.raises(agent_telemetry.InvalidHostTelemetry, match="payload schema is invalid"):
        agent_telemetry.validate_host_payload(payload, utcnow())


def test_boolean_summary_value_is_coerced_to_one_and_accepted():
    """Pins current behavior, not desired behavior.

    pydantic coerces JSON `true` to int 1 for `dict[str, int | float]`, so the
    `isinstance(value, bool)` guard in `validate_host_payload` is unreachable
    dead code and a boolean lands as 1. Rejecting it needs a `field_validator`
    on `summary`; this test exists so the dead branch is visible rather than
    mistaken for coverage.
    """
    payload = _payload(summary=_summary(cpu_pct=True))

    sample = agent_telemetry.validate_host_payload(payload, utcnow())

    assert sample.summary["cpu_pct"] == 1
    assert not isinstance(sample.summary["cpu_pct"], bool)


# ── validate_host_payload — collection timestamp window ──────────────────────


def test_timestamp_more_than_60s_in_the_future_is_rejected():
    with pytest.raises(
        agent_telemetry.InvalidHostTelemetry, match="collection timestamp is in the future"
    ):
        agent_telemetry.validate_host_payload(_payload(), utcnow() + timedelta(seconds=61))


def test_timestamp_59s_in_the_future_is_accepted():
    sample = agent_telemetry.validate_host_payload(_payload(), utcnow() + timedelta(seconds=59))

    assert sample.status == "healthy"


def test_timestamp_older_than_30d_is_rejected():
    stale = utcnow() - timedelta(days=30, minutes=1)

    with pytest.raises(
        agent_telemetry.InvalidHostTelemetry, match="collection timestamp is outside retention"
    ):
        agent_telemetry.validate_host_payload(_payload(), stale)


def test_timestamp_29d_old_is_accepted():
    sample = agent_telemetry.validate_host_payload(_payload(), utcnow() - timedelta(days=29))

    assert sample.status == "healthy"


def test_naive_collection_timestamp_is_treated_as_utc():
    """A naive timestamp must not raise on the tz-aware comparison — it is
    interpreted as UTC, so "now, without a tzinfo" is inside the window."""
    naive = utcnow().replace(tzinfo=None)

    sample = agent_telemetry.validate_host_payload(_payload(), naive)

    assert sample.sample_id == _corpus_payload()["sample_id"]


# ── ingest_host_sample — agent state and capability grants ───────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["pending", "revoked", "rejected"])
async def test_non_active_agent_is_rejected_and_persists_nothing(db_session, factories, status):
    agent = factories.agent(status=status)

    with pytest.raises(agent_telemetry.InvalidHostTelemetry, match="agent is not active"):
        await agent_telemetry.ingest_host_sample(db_session, agent, _payload(), utcnow())

    assert _samples(db_session, agent) == []


@pytest.mark.asyncio
async def test_ungranted_valid_telemetry_persists_nothing(db_session, factories):
    """The capability gate must reject a *valid* payload, not just a malformed
    one — the pre-existing agent_link tests only ever sent `{"cpu": 0.5}`,
    which never survives validation, so they could not tell the gate apart
    from the validator."""
    agent = factories.agent(status="active")
    factories.agent_capability_grant(agent, capability="host_telemetry", enabled=False)
    frame = AgentFrame(type="telemetry.host", ts=utcnow(), payload=_payload())

    await agent_link.dispatch_frame(db_session, agent, frame)

    assert _samples(db_session, agent) == []
    events = list(
        db_session.execute(
            select(AgentEvent).where(
                AgentEvent.agent_id == agent.id,
                AgentEvent.event_type == "capability_violation",
            )
        ).scalars()
    )
    assert len(events) == 1
    assert events[0].detail == {"frame_type": "telemetry.host"}


@pytest.mark.asyncio
async def test_granted_valid_telemetry_persists_exactly_one_row(db_session, factories):
    agent = factories.agent(status="active")
    factories.agent_capability_grant(agent, capability="host_telemetry", enabled=True)
    frame = AgentFrame(type="telemetry.host", ts=utcnow(), payload=_payload())

    await agent_link.dispatch_frame(db_session, agent, frame)

    rows = _samples(db_session, agent)
    assert len(rows) == 1
    assert rows[0].sample_id == _corpus_payload()["sample_id"]


@pytest.mark.asyncio
async def test_missing_grant_row_behaves_as_denied(db_session, factories):
    """No `agent_capability_grants` row is a denial everywhere — never a
    fallback to the capability's `default_enabled`."""
    agent = factories.agent(status="active")
    frame = AgentFrame(type="telemetry.host", ts=utcnow(), payload=_payload())

    await agent_link.dispatch_frame(db_session, agent, frame)

    assert _samples(db_session, agent) == []
    assert (
        db_session.execute(
            select(AgentEvent).where(
                AgentEvent.agent_id == agent.id,
                AgentEvent.event_type == "capability_violation",
            )
        ).first()
        is not None
    )


# ── protocol-violation rate limiting ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_repeated_invalid_payloads_record_one_violation_per_minute(
    db_session, factories, monkeypatch
):
    agent = factories.agent(status="active")
    factories.agent_capability_grant(agent, capability="host_telemetry", enabled=True)
    clock = {"now": 1000.0}
    # Replace only agent_telemetry's `time` reference; patching stdlib
    # `time.monotonic` globally would also move asyncio's own clock.
    monkeypatch.setattr(agent_telemetry, "time", SimpleNamespace(monotonic=lambda: clock["now"]))

    async def send_invalid():
        await agent_link.dispatch_frame(
            db_session,
            agent,
            AgentFrame(type="telemetry.host", ts=utcnow(), payload={"cpu": 0.5}),
        )

    for _ in range(5):
        await send_invalid()

    events = _violations_for(db_session, agent)
    assert len(events) == 1, "five rejections inside one minute must collapse to one audit event"
    assert events[0].detail["reason"] == "payload schema is invalid"
    assert events[0].detail["repeated"] == 1

    clock["now"] += 61
    await send_invalid()

    events = _violations_for(db_session, agent)
    assert len(events) == 2
    # The second event carries the count accumulated while suppressed.
    assert events[1].detail["repeated"] == 5


# ── idempotency and the concurrent-writer path ───────────────────────────────


@pytest.mark.asyncio
async def test_identical_sample_replay_is_idempotent(db_session, factories):
    hardware = factories.hardware()
    agent = factories.agent(status="active", hardware_id=hardware.id)
    collected_at = utcnow()
    payload = _payload()

    first = await agent_telemetry.ingest_host_sample(db_session, agent, payload, collected_at)
    first_id = first.id

    # A sentinel the replay must not overwrite: reaching the projection block
    # again would reset telemetry_status to the payload's "healthy".
    refreshed = db_session.get(Hardware, hardware.id)
    refreshed.telemetry_status = "sentinel"
    db_session.commit()

    second = await agent_telemetry.ingest_host_sample(db_session, agent, payload, collected_at)

    assert second.id == first_id
    assert _count(db_session, AgentHostSample) == 1
    assert _count(db_session, HardwareLiveMetric) == 1
    refreshed = db_session.get(Hardware, hardware.id)
    assert refreshed.telemetry_status == "sentinel"
    assert refreshed.telemetry_last_polled == collected_at


@pytest.mark.asyncio
async def test_flush_integrity_error_returns_existing_row(db_session, factories):
    """The concurrent-writer path: another worker committed this exact
    (agent_id, sample_id, collected_at) between our SELECT and our INSERT, so
    the flush violates `uq_agent_host_sample`. Never executed in production
    today — this is the only test that reaches it."""
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm import Session as OrmSession

    hardware = factories.hardware()
    agent = factories.agent(status="active", hardware_id=hardware.id)
    db_session.commit()
    collected_at = utcnow()
    payload = _payload()

    original_flush = OrmSession.flush
    fired = {"value": False}

    def fake_flush(self, *args, **kwargs):
        if not fired["value"] and any(isinstance(o, AgentHostSample) for o in self.new):
            fired["value"] = True
            # Make the row durable (the concurrent winner's write), then fail
            # our INSERT the way the unique constraint would.
            original_flush(self, *args, **kwargs)
            self.commit()
            raise IntegrityError("INSERT INTO agent_host_samples", {}, Exception("duplicate key"))
        return original_flush(self, *args, **kwargs)

    OrmSession.flush = fake_flush
    try:
        row = await agent_telemetry.ingest_host_sample(db_session, agent, payload, collected_at)
    finally:
        OrmSession.flush = original_flush

    assert fired["value"] is True
    assert row.sample_id == payload["sample_id"]
    assert _count(db_session, AgentHostSample) == 1
    # The early return happens before the projection block — the winner owns it.
    assert _count(db_session, HardwareLiveMetric) == 0


@pytest.mark.asyncio
async def test_flush_integrity_error_that_is_not_the_dedupe_propagates(db_session, factories):
    """An integrity failure the dedupe cannot explain must surface as itself.

    The handler above exists for one recoverable case: `uq_agent_host_sample`
    already holds this (agent_id, sample_id, collected_at). A blanket
    `except IntegrityError` swallowed *every* integrity failure and then died
    inside the re-SELECT with an unrelated `NoResultFound`, which is what a
    fresh install hit while `agent_host_samples.id` was being created without
    its sequence (see
    `tests/test_agent_telemetry_schema.py::test_bootstrap_metadata_preserves_autoincrement`):
    the real NotNullViolation never reached the logs and the /link socket
    dropped on a misleading error instead.
    """
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm import Session as OrmSession

    agent = factories.agent(status="active")
    db_session.commit()

    original_flush = OrmSession.flush
    not_null = Exception('null value in column "id" violates not-null constraint')

    def fake_flush(self, *args, **kwargs):
        if any(isinstance(o, AgentHostSample) for o in self.new):
            raise IntegrityError("INSERT INTO agent_host_samples", {}, not_null)
        return original_flush(self, *args, **kwargs)

    OrmSession.flush = fake_flush
    try:
        with pytest.raises(IntegrityError) as excinfo:
            await agent_telemetry.ingest_host_sample(db_session, agent, _payload(), utcnow())
    finally:
        OrmSession.flush = original_flush

    assert excinfo.value.orig is not_null
    assert _count(db_session, AgentHostSample) == 0


@pytest.mark.asyncio
async def test_different_sample_id_at_same_timestamp_persists_a_second_row(db_session, factories):
    agent = factories.agent(status="active")
    collected_at = utcnow()

    await agent_telemetry.ingest_host_sample(
        db_session, agent, _payload(sample_id="1" * 32), collected_at
    )
    await agent_telemetry.ingest_host_sample(
        db_session, agent, _payload(sample_id="2" * 32), collected_at
    )

    assert sorted(r.sample_id for r in _samples(db_session, agent)) == ["1" * 32, "2" * 32]


# ── unlinked vs linked agents ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unlinked_agent_sample_persists_without_projection(
    db_session, factories, telemetry_side_effects
):
    agent = factories.agent(status="active")
    collected_at = utcnow()

    row = await agent_telemetry.ingest_host_sample(db_session, agent, _payload(), collected_at)

    assert row.hardware_id is None
    assert row.projected_at is None
    assert _count(db_session, HardwareLiveMetric) == 0
    channels = [channel for channel, _ in telemetry_side_effects.published]
    assert channels == [f"telemetry:agent:{agent.id}"]
    telemetry_side_effects.cache_telemetry.assert_not_awaited()
    telemetry_side_effects.publish_telemetry.assert_not_awaited()


@pytest.mark.asyncio
async def test_pre_link_sample_is_not_backfilled_after_linking(db_session, factories):
    """Linking is not retroactive: the projection is a write-time side effect,
    so a sample collected before the link stays unattributed."""
    agent = factories.agent(status="active")
    early = await agent_telemetry.ingest_host_sample(
        db_session, agent, _payload(sample_id="1" * 32), utcnow() - timedelta(minutes=5)
    )
    early_id = early.id

    hardware = factories.hardware()
    agent.hardware_id = hardware.id
    db_session.commit()
    await agent_telemetry.ingest_host_sample(
        db_session, agent, _payload(sample_id="2" * 32), utcnow()
    )

    db_session.expire_all()
    stale = db_session.execute(
        select(AgentHostSample).where(AgentHostSample.id == early_id)
    ).scalar_one()
    assert stale.hardware_id is None
    assert stale.projected_at is None
    metrics = list(db_session.execute(select(HardwareLiveMetric)).scalars())
    assert [m.agent_sample_id for m in metrics] == ["2" * 32]


@pytest.mark.asyncio
async def test_older_sample_from_second_agent_does_not_move_hardware_last_polled(
    db_session, factories
):
    """Two agents on one host: a spool catch-up burst from B must not rewind
    the live view A already advanced past."""
    hardware = factories.hardware()
    agent_a = factories.agent(status="active", hardware_id=hardware.id)
    agent_b = factories.agent(status="active", hardware_id=hardware.id)
    base = utcnow() - timedelta(minutes=5)
    newer, older = base + timedelta(seconds=10), base + timedelta(seconds=5)

    await agent_telemetry.ingest_host_sample(
        db_session, agent_a, _payload(sample_id="a" * 32, summary=_summary(cpu_pct=11.0)), newer
    )
    await agent_telemetry.ingest_host_sample(
        db_session, agent_b, _payload(sample_id="b" * 32, summary=_summary(cpu_pct=22.0)), older
    )

    refreshed = db_session.get(Hardware, hardware.id)
    assert refreshed.telemetry_last_polled == newer
    assert refreshed.telemetry_data["cpu_pct"] == 11.0

    samples = {
        r.sample_id: r.agent_id for r in db_session.execute(select(AgentHostSample)).scalars()
    }
    assert samples == {"a" * 32: agent_a.id, "b" * 32: agent_b.id}
    metrics = {
        m.agent_sample_id: (m.agent_id, m.cpu_pct)
        for m in db_session.execute(select(HardwareLiveMetric)).scalars()
    }
    assert metrics == {"a" * 32: (agent_a.id, 11.0), "b" * 32: (agent_b.id, 22.0)}


@pytest.mark.asyncio
async def test_uptime_float_persists_into_bigint_column(db_session, factories):
    """The Go collector genuinely emits a float uptime; both destination
    columns are BigInteger, so the value must round rather than blow up."""
    hardware = factories.hardware()
    agent = factories.agent(status="active", hardware_id=hardware.id)

    await agent_telemetry.ingest_host_sample(
        db_session, agent, _payload(summary=_summary(uptime_s=123456.78)), utcnow()
    )

    db_session.expire_all()
    sample = db_session.execute(select(AgentHostSample)).scalar_one()
    metric = db_session.execute(select(HardwareLiveMetric)).scalar_one()
    assert sample.uptime_s == 123457
    assert metric.uptime_s == 123457


@pytest.mark.asyncio
async def test_ingest_still_succeeds_after_column_drop(db_session, factories):
    """`projection_attempts` is gone from the model *and* nothing on the ingest
    path still tries to write it (D-3, Task 8)."""
    assert "projection_attempts" not in AgentHostSample.__table__.c

    hardware = factories.hardware()
    agent = factories.agent(status="active", hardware_id=hardware.id)

    row = await agent_telemetry.ingest_host_sample(db_session, agent, _payload(), utcnow())

    db_session.expire_all()
    sample = db_session.execute(select(AgentHostSample)).scalar_one()
    assert sample.id == row.id
    assert sample.projected_at is not None
    assert db_session.execute(select(HardwareLiveMetric)).scalar_one().agent_id == agent.id


# ── Task 5: the live projection speaks platform key names ────────────────────
#
# `agent_summary_to_platform` + `live_metric_fields` (app/services/
# telemetry_normalize.py) are the single mapping from a normalized platform
# telemetry dict onto `hardware_live_metrics`. Everything below pins the
# consumer-visible half of that: the *Hardware* surfaces (telemetry_data, the
# live-metric row, the Redis cache/WebSocket envelope) carry platform names,
# while the *Agent-detail* surfaces keep the agent's own names.


_PLATFORM_KEYS = (
    "cpu_pct",
    "mem_pct",
    "mem_used",
    "mem_total",
    "mem_used_mb",
    "mem_total_mb",
    "mem_used_gb",
    "mem_total_gb",
    "disk_pct",
    "rootfs_used",
    "rootfs_total",
    "disk_used_gb",
    "disk_total_gb",
    "temp_c",
    "cpu_temp",
    "uptime_s",
)


@pytest.mark.asyncio
async def test_linked_agent_hardware_telemetry_data_uses_platform_keys(db_session, factories):
    """`hardware.telemetry_data` is spread into the entity response the map
    reads, so it must not carry `root_disk_pct`/`max_temp_c`/`mem_used_bytes`."""
    hardware = factories.hardware()
    agent = factories.agent(status="active", hardware_id=hardware.id)

    await agent_telemetry.ingest_host_sample(db_session, agent, _payload(), utcnow())

    data = db_session.get(Hardware, hardware.id).telemetry_data
    assert set(_PLATFORM_KEYS) <= set(data)
    assert "root_disk_pct" not in data
    assert "max_temp_c" not in data
    assert "mem_used_bytes" not in data
    assert data["disk_pct"] == 41.8
    assert data["temp_c"] == 48.0
    assert data["cpu_temp"] == 48.0
    assert data["mem_used_gb"] == 5.0
    assert data["mem_total_gb"] == 15.5
    assert data["disk_used_gb"] == 194.7
    assert data["disk_total_gb"] == 465.8
    # Agent-detail parity fields ride along unchanged.
    assert data["load_1"] == 0.42
    assert data["logical_cpus"] == 8
    # No power probe exists on the Linux collector.
    assert "power_w" not in data


@pytest.mark.asyncio
async def test_agent_live_metric_raw_round_trips_through_row_to_payload(db_session, factories):
    """`GET /api/v1/hardware/{id}/telemetry`'s DB-fallback branch serves
    `HardwareLiveMetric.raw` verbatim, so storing the agent frame payload there
    leaked agent key names straight into the hardware telemetry API."""
    from app.services.telemetry_service import _row_to_payload

    hardware = factories.hardware()
    agent = factories.agent(status="active", hardware_id=hardware.id)

    await agent_telemetry.ingest_host_sample(db_session, agent, _payload(), utcnow())

    db_session.expire_all()
    metric = db_session.execute(select(HardwareLiveMetric)).scalar_one()
    payload = _row_to_payload(metric)
    assert payload["disk_pct"] == 41.8
    assert payload["temp_c"] == 48.0
    assert "summary" not in payload
    assert "schema" not in payload


@pytest.mark.asyncio
async def test_agent_projection_matches_ingest_worker_normalization(db_session, factories):
    """One normalizer: the agent path and the poller ingest worker must produce
    identical `hardware_live_metrics` columns for the same platform dict."""
    from app.services.telemetry_normalize import agent_summary_to_platform
    from app.workers.telemetry_ingest_worker import _build_metric_row

    hardware = factories.hardware()
    agent = factories.agent(status="active", hardware_id=hardware.id)
    # A non-integral MiB value: the pre-refactor projection divided by 1024**2
    # without rounding, while `_bytes_to_mb` rounds to 2 dp.
    summary = _summary(mem_used_bytes=5368709632)
    collected_at = utcnow()

    await agent_telemetry.ingest_host_sample(
        db_session, agent, _payload(summary=summary), collected_at
    )

    db_session.expire_all()
    metric = db_session.execute(select(HardwareLiveMetric)).scalar_one()
    platform = agent_summary_to_platform(summary, _payload()["filesystems"])
    expected = _build_metric_row(hardware.id, "agent", platform, "healthy", None, collected_at)
    for column in ("cpu_pct", "mem_pct", "mem_used_mb", "mem_total_mb", "disk_pct", "temp_c"):
        assert getattr(metric, column) == expected[column], column
    assert metric.uptime_s == expected["uptime_s"]
    assert metric.power_w is expected["power_w"] is None
    assert metric.raw == expected["raw"]
    assert metric.mem_used_mb == 5120.0


@pytest.mark.asyncio
async def test_agent_cache_and_publish_envelope_uses_platform_keys(
    db_session, factories, telemetry_side_effects
):
    hardware = factories.hardware()
    agent = factories.agent(status="active", hardware_id=hardware.id)

    await agent_telemetry.ingest_host_sample(db_session, agent, _payload(), utcnow())

    cache_args = telemetry_side_effects.cache_telemetry.await_args
    publish_args = telemetry_side_effects.publish_telemetry.await_args
    assert cache_args.args[0] == hardware.id
    cached = cache_args.args[1]
    published = publish_args.args[1]
    for envelope in (cached, published):
        assert envelope["source"] == "agent"
        assert envelope["agent_id"] == agent.id
        assert envelope["sample_id"] == _payload()["sample_id"]
        data = envelope["data"]
        assert data["disk_pct"] == 41.8
        assert data["temp_c"] == 48.0
        assert data["mem_used_gb"] == 5.0
        assert "root_disk_pct" not in data
        assert "max_temp_c" not in data
        assert "mem_used_bytes" not in data
    assert published["entity_type"] == "hardware"
    assert published["hardware_id"] == hardware.id


@pytest.mark.asyncio
async def test_non_live_status_withholds_hardware_last_seen(db_session, factories, monkeypatch):
    """Latent-divergence guard. Today `validate_host_payload` admits only
    `healthy`/`degraded`, neither of which is in `_NON_LIVE_STATUSES`, so the
    gate is unobservable in production — but the poller paths
    (`telemetry_service.write_telemetry`, `telemetry_ingest_worker`) all gate
    `last_seen` on it and the agent path must not be the odd one out when the
    agent's status vocabulary grows."""
    monkeypatch.setattr(agent_telemetry, "_NON_LIVE_STATUSES", frozenset({"degraded"}))
    hardware = factories.hardware()
    agent = factories.agent(status="active", hardware_id=hardware.id)
    collected_at = utcnow()

    await agent_telemetry.ingest_host_sample(
        db_session, agent, _payload(status="degraded"), collected_at
    )

    refreshed = db_session.get(Hardware, hardware.id)
    assert refreshed.last_seen is None
    assert refreshed.telemetry_status == "degraded"
    assert refreshed.telemetry_last_polled == collected_at


@pytest.mark.asyncio
async def test_live_status_still_stamps_hardware_last_seen(db_session, factories):
    hardware = factories.hardware()
    agent = factories.agent(status="active", hardware_id=hardware.id)
    collected_at = utcnow()

    await agent_telemetry.ingest_host_sample(db_session, agent, _payload(), collected_at)

    assert db_session.get(Hardware, hardware.id).last_seen == collected_at.isoformat()


@pytest.mark.asyncio
async def test_agent_detail_sample_json_still_uses_agent_keys(db_session, factories):
    """The Agent-detail page is keyed on the agent's own names; the platform
    normalizer must not reach `agent_host_samples` or `_sample_json`."""
    from app.api.agents import _sample_json

    hardware = factories.hardware()
    agent = factories.agent(status="active", hardware_id=hardware.id)
    payload = _payload()

    row = await agent_telemetry.ingest_host_sample(db_session, agent, payload, utcnow())

    rendered = _sample_json(row)
    assert set(rendered["summary"]) == {
        "cpu_pct",
        "mem_pct",
        "root_disk_pct",
        "net_rx_bps",
        "net_tx_bps",
        "max_temp_c",
        "load_1",
        "uptime_s",
    }
    assert rendered["summary"]["root_disk_pct"] == 41.8
    assert rendered["summary"]["max_temp_c"] == 48.0
    assert rendered["payload"] == payload
