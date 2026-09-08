"""Tests for the retention purge against agent-sourced discovery history.

Split out of the former tests/test_discovery.py.
"""

from tests.discovery.helpers import _AGENT_SUBNET, _eligible_agent

# ---------------------------------------------------------------------------
# The retention purge against agent-sourced history (Task 26)
# ---------------------------------------------------------------------------
#
# Slice 4 hangs three new foreign keys off the rows this daily cron deletes:
# `scan_jobs.scan_agent_id`, `scan_results.discovery_agent_id` and
# `scan_results.tenant_id`. None of them points *out* of the purge's blast
# radius, so they are not what breaks it. Three that were already there are, and
# all three were NO ACTION.
#
# `scan_results.scan_job_id` and `scan_logs.scan_job_id`: the purge deleted
# results and jobs by their *own* `created_at`, so an old job that still owned a
# newer child could not be deleted — and an agent job owns exactly that, because
# a finding spooled across an outage is written when it finally arrives, long
# after its dispatch was created.
#
# `hardware.source_scan_result_id` (Fix A1): an inbound edge from outside
# discovery altogether, written by every approval path, which the Task 26 audit
# of the three *new* FKs never enumerated. One merged device is enough to block
# the DELETE outright.
#
# In every case the resulting `IntegrityError` is swallowed by the body's own
# `except Exception`, so the whole purge silently does nothing and retention
# stops happening fleet-wide. The full inbound-FK enumeration — and the
# assertion that a new edge cannot be added to these tables unexamined — lives
# in `tests/unit/test_migration_0101_discovery_retention_and_global_pause.py`.


class _KeepOpenSession:
    """`db_session` handed to code that owns its own session and closes it.

    `_purge_old_scan_results_impl` opens `SessionLocal()` and closes it in a
    `finally`, which would end this test's outer transaction; everything else is
    delegated so the purge runs its real statements against the test's data.
    """

    def __init__(self, session):
        self._session = session

    def __getattr__(self, name):
        return getattr(self._session, name)

    def close(self) -> None:
        return None


def _aged(days: int) -> str:
    from datetime import timedelta

    from app.core.time import utcnow

    return (utcnow() - timedelta(days=days)).isoformat()


def _purge_fixture_rows(db_session, agent):
    """One expired agent job with a *late* finding, plus a fresh one to keep.

    The late finding is the point: `created_at` on the result is inside the
    retention window while the job that owns it is outside it, which is the
    ordinary shape of a spooled agent finding and the one the purge cannot
    express as two independent date filters.
    """
    from types import SimpleNamespace

    from app.db.models import ScanJob, ScanLog, ScanResult

    def _job(created_at: str, **kwargs) -> ScanJob:
        job = ScanJob(
            scan_agent_id=agent.id,
            target_cidr=_AGENT_SUBNET,
            scan_types_json='["agent_connect"]',
            source_type="agent",
            status="completed",
            created_at=created_at,
            **kwargs,
        )
        db_session.add(job)
        db_session.flush()
        return job

    def _result(job, created_at: str, ip: str, finding: str) -> ScanResult:
        row = ScanResult(
            scan_job_id=job.id,
            discovery_agent_id=agent.id,
            finding_id=finding,
            ip_address=ip,
            source_type="agent",
            state="new",
            merge_status="pending",
            created_at=created_at,
        )
        db_session.add(row)
        db_session.flush()
        return row

    expired = _job(_aged(60))
    expired_result = _result(expired, _aged(60), "10.20.30.41", "f-old")
    late_result = _result(expired, _aged(1), "10.20.30.42", "f-late")
    db_session.add(
        ScanLog(
            scan_job_id=expired.id,
            level="INFO",
            phase="agent_connect",
            message="dispatched",
            created_at=_aged(60),
        )
    )
    kept = _job(_aged(1))
    kept_result = _result(kept, _aged(1), "10.20.30.43", "f-new")
    db_session.flush()
    # Ids, not instances: the purge deletes rows out from under the identity map
    # and every later attribute read on a survivor would be an ObjectDeletedError
    # rather than the assertion the test means to make.
    return SimpleNamespace(
        expired_job=expired.id,
        expired_result=expired_result.id,
        late_result=late_result.id,
        kept_job=kept.id,
        kept_result=kept_result.id,
    )


def _run_purge(monkeypatch, db_session):
    from app.services import discovery_scheduler

    monkeypatch.setattr(discovery_scheduler, "SessionLocal", lambda: _KeepOpenSession(db_session))
    discovery_scheduler._purge_old_scan_results_impl()
    db_session.expunge_all()


def _row_count(db_session, model, row_id) -> int:
    return db_session.query(model).filter(model.id == row_id).count()


def test_the_purge_retires_an_expired_agent_job_with_all_of_its_children(
    db_session, factories, monkeypatch
):
    """Retention has to actually happen for agent history.

    Everything hanging off an expired job goes with it — the finding that
    arrived late included — because a job cannot be deleted while any child row
    still references it and there is nothing else that would ever clean them up.
    """
    from app.db.models import ScanJob, ScanLog, ScanResult

    agent = _eligible_agent(factories)
    rows = _purge_fixture_rows(db_session, agent)

    _run_purge(monkeypatch, db_session)

    assert _row_count(db_session, ScanJob, rows.expired_job) == 0
    assert _row_count(db_session, ScanResult, rows.expired_result) == 0
    assert _row_count(db_session, ScanResult, rows.late_result) == 0
    assert db_session.query(ScanLog).filter(ScanLog.scan_job_id == rows.expired_job).count() == 0
    # And only the expired job: a purge that took the whole table would satisfy
    # every assertion above.
    assert _row_count(db_session, ScanJob, rows.kept_job) == 1
    assert _row_count(db_session, ScanResult, rows.kept_result) == 1


def test_the_purge_never_touches_the_agent_that_produced_the_history(
    db_session, factories, monkeypatch
):
    """D-1: only an explicit, 409-guarded operator delete removes an agent.

    `scan_jobs.scan_agent_id` and `scan_results.discovery_agent_id` are CASCADE
    *from* the agent, so nothing here should reach it — but the purge is the one
    scheduled job that deletes discovery rows unattended, and an agent silently
    disappearing from the fleet at 30 days would be indistinguishable from a
    revocation until its next enrolment.
    """
    from app.db.models import Agent, AgentCapabilityGrant, DiscoveryProfile

    agent = _eligible_agent(factories)
    agent_id = agent.id
    # Constructed directly: `factories.discovery_profile` still spells the column
    # `scan_types_json`, which `DiscoveryProfile` has never had.
    profile = DiscoveryProfile(
        name="system-managed",
        cidr=_AGENT_SUBNET,
        normalized_cidr=_AGENT_SUBNET,
        scan_types='["agent_connect"]',
        scan_agent_id=agent.id,
        managed_by="system",
        enabled=1,
        created_at=_aged(60),
        updated_at=_aged(60),
    )
    db_session.add(profile)
    db_session.flush()
    profile_id = profile.id
    _purge_fixture_rows(db_session, agent)

    _run_purge(monkeypatch, db_session)

    assert _row_count(db_session, Agent, agent_id) == 1
    assert (
        db_session.query(AgentCapabilityGrant)
        .filter(AgentCapabilityGrant.agent_id == agent_id)
        .count()
        == 1
    )
    # The profile outlives its jobs: it is the subnet's identity and its cadence,
    # not history.
    assert _row_count(db_session, DiscoveryProfile, profile_id) == 1


def test_the_purge_ages_out_a_result_a_device_was_merged_from(db_session, factories, monkeypatch):
    """A device merged out of discovery must not pin discovery history forever.

    `hardware.source_scan_result_id` is the provenance pointer every approval
    path writes (`discovery_merge.py`, `discovery_import_service.py`), and it
    was a bare `ForeignKey("scan_results.id")` — no `ondelete`, i.e. NO ACTION.
    So the widened DELETE below raised `ForeignKeyViolation` the moment any
    expiring result had been merged into inventory, the body's own `except`
    swallowed it and rolled back, and results, logs *and* jobs all survived:
    retention never happened at all for any installation that had ever approved
    a discovered device. The other purge tests cannot see this, because a
    spooled finding is never a merged one.

    Fix A1 makes the constraint `ON DELETE SET NULL`. The pointer is
    *provenance*; losing it when the result ages out is precisely what retention
    means, and the alternative — exempting merged results from the purge — would
    make the rows most worth ageing out the only ones that never age out. The
    device is inventory and stays.
    """
    from app.db.models import Hardware, ScanJob, ScanResult

    agent = _eligible_agent(factories)
    rows = _purge_fixture_rows(db_session, agent)
    device = factories.hardware(
        name="merged-from-discovery",
        ip_address="10.20.30.41",
        source="discovery",
        source_scan_result_id=rows.expired_result,
    )
    device_id = device.id
    db_session.flush()

    _run_purge(monkeypatch, db_session)

    assert _row_count(db_session, ScanResult, rows.expired_result) == 0, (
        "the merged result is the row most worth ageing out, not the one exempt from it"
    )
    assert _row_count(db_session, ScanJob, rows.expired_job) == 0, (
        "one blocked child rolls the whole purge back — jobs included"
    )
    survivor = db_session.get(Hardware, device_id)
    assert survivor is not None, "retention ages out discovery history, never inventory"
    assert survivor.source_scan_result_id is None, (
        "the provenance pointer goes with the result it points at"
    )
