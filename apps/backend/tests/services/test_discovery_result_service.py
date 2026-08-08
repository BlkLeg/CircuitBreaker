"""The one row-building and hardware-classification path for a discovery result (§5, D-9).

`_scan_import` drives it once per row of a finished batch; Slice 4's agent
ingest drives it once per incremental finding. Everything asserted here is
asserted against the *shared* helper so the agent path cannot grow matching
semantics of its own — the proof that the server path's output is unchanged by
the extraction lives next door in `test_discovery_service.py`, which pins
`_scan_import` end to end.
"""

import datetime
import json

from app.db.models import Hardware, ScanJob, Tenant
from app.services.discovery_result_service import build_and_classify_result


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


def _job(db_session, **kwargs):  # type: ignore[no-untyped-def]
    defaults = {
        "target_cidr": "10.60.0.0/24",
        "status": "running",
        "scan_types_json": '["agent_connect"]',
        "created_at": _now(),
    }
    defaults.update(kwargs)
    job = ScanJob(**defaults)
    db_session.add(job)
    db_session.flush()
    return job


def _tenant(db_session, name: str):  # type: ignore[no-untyped-def]
    """No tenant factory exists and this task does not own `tests/factories.py`."""
    tenant = Tenant(name=name)
    db_session.add(tenant)
    db_session.flush()
    return tenant


# ── The server path, called directly ──────────────────────────────────────────


def test_server_path_classifies_an_unknown_host_as_new(db_session) -> None:  # type: ignore[no-untyped-def]
    job = _job(db_session)

    res, classification = build_and_classify_result(
        db_session, job, {"ip": "10.60.0.5", "mac_address": "AA:BB:CC:10:00:01"}
    )
    db_session.flush()

    assert classification == "new"
    assert (res.state, res.merge_status) == ("new", "pending")
    assert res.scan_job_id == job.id
    assert (res.discovery_agent_id, res.finding_id) == (None, None)


def test_server_path_lookup_is_not_tenant_filtered(db_session, factories) -> None:  # type: ignore[no-untyped-def]
    """The server scanner's matcher has never carried a tenant predicate and
    D-9 keeps it that way: Hardware rows predate tenants, and narrowing the
    server path would silently stop matching every untenanted row."""
    tenant = _tenant(db_session, "result-server-other")
    hw = factories.hardware(
        name="cross-tenant", mac_address="AA:BB:CC:10:00:02", tenant_id=tenant.id
    )
    job = _job(db_session, tenant_id=None)

    res, classification = build_and_classify_result(
        db_session, job, {"ip": "10.60.0.6", "mac_address": "AA:BB:CC:10:00:02"}
    )
    db_session.flush()

    assert classification == "matched"
    assert res.matched_entity_id == hw.id


# ── The agent path ────────────────────────────────────────────────────────────


def test_agent_lowercase_mac_matches_an_uppercase_stored_mac(db_session, factories) -> None:  # type: ignore[no-untyped-def]
    """The neighbour cache reports `net.HardwareAddr.String()`, which is
    lowercase; every Hardware row the nmap scanner ever wrote is uppercase."""
    agent = factories.agent(status="active")
    hw = factories.hardware(name="neigh-host", mac_address="AA:BB:CC:10:00:03")
    job = _job(db_session, scan_agent_id=agent.id)

    res, classification = build_and_classify_result(
        db_session,
        job,
        {"ip": "10.60.0.7", "mac_address": "aa:bb:cc:10:00:03", "hostname": "neigh-host"},
        discovery_agent_id=agent.id,
        finding_id="f-lower",
    )
    db_session.flush()

    assert classification == "matched"
    assert res.matched_entity_id == hw.id
    assert res.mac_address == "AA:BB:CC:10:00:03"


def test_agent_finding_never_matches_another_tenants_hardware(db_session, factories) -> None:  # type: ignore[no-untyped-def]
    """Without the predicate a tenant-A agent's finding matches a tenant-B row
    and auto-merge then writes the discovered hostname and IP into it."""
    tenant_a = _tenant(db_session, "result-agent-a")
    tenant_b = _tenant(db_session, "result-agent-b")
    agent = factories.agent(status="active", tenant_id=tenant_a.id)
    factories.hardware(name="b-owned", mac_address="AA:BB:CC:10:00:04", tenant_id=tenant_b.id)
    job = _job(db_session, scan_agent_id=agent.id, tenant_id=tenant_a.id)

    res, classification = build_and_classify_result(
        db_session,
        job,
        {"ip": "10.60.0.8", "mac_address": "aa:bb:cc:10:00:04"},
        discovery_agent_id=agent.id,
        finding_id="f-tenant-b",
    )
    db_session.flush()

    assert classification == "new"
    assert (res.matched_entity_type, res.matched_entity_id) == (None, None)


def test_agent_finding_matches_hardware_in_its_own_tenant(db_session, factories) -> None:  # type: ignore[no-untyped-def]
    tenant_a = _tenant(db_session, "result-agent-own")
    agent = factories.agent(status="active", tenant_id=tenant_a.id)
    hw = factories.hardware(name="a-owned", mac_address="AA:BB:CC:10:00:05", tenant_id=tenant_a.id)
    job = _job(db_session, scan_agent_id=agent.id, tenant_id=tenant_a.id)

    _res, classification = build_and_classify_result(
        db_session,
        job,
        {"ip": "10.60.0.9", "mac_address": "aa:bb:cc:10:00:05", "hostname": "a-owned"},
        discovery_agent_id=agent.id,
        finding_id="f-tenant-a",
    )
    db_session.flush()

    assert classification == "matched"
    assert _res.matched_entity_id == hw.id


def test_agent_finding_matches_an_untenanted_row_from_an_untenanted_job(  # type: ignore[no-untyped-def]
    db_session, factories
) -> None:
    """Both-sides-NULL is the single-tenant default install, so `IS NULL` has to
    be spelled out — SQL's `NULL = NULL` is NULL and would classify every
    finding `new` for every deployment that never created a tenant."""
    agent = factories.agent(status="active", tenant_id=None)
    hw = factories.hardware(name="untenanted", mac_address="AA:BB:CC:10:00:06", tenant_id=None)
    job = _job(db_session, scan_agent_id=agent.id, tenant_id=None)

    res, classification = build_and_classify_result(
        db_session,
        job,
        {"ip": "10.60.0.10", "mac_address": "aa:bb:cc:10:00:06", "hostname": "untenanted"},
        discovery_agent_id=agent.id,
        finding_id="f-untenanted",
    )
    db_session.flush()

    assert classification == "matched"
    assert res.matched_entity_id == hw.id


def test_agent_ip_fallback_is_tenant_filtered_too(db_session, factories) -> None:  # type: ignore[no-untyped-def]
    """The MAC lookup is not the only way into a Hardware row; a MAC-less
    finding falls through to IP, and that lookup needs the same predicate."""
    tenant_a = _tenant(db_session, "result-ip-a")
    tenant_b = _tenant(db_session, "result-ip-b")
    agent = factories.agent(status="active", tenant_id=tenant_a.id)
    factories.hardware(name="b-by-ip", ip_address="10.60.0.11", tenant_id=tenant_b.id)
    job = _job(db_session, scan_agent_id=agent.id, tenant_id=tenant_a.id)

    _res, classification = build_and_classify_result(
        db_session,
        job,
        {"ip": "10.60.0.11"},
        discovery_agent_id=agent.id,
        finding_id="f-ip-b",
    )
    db_session.flush()

    assert classification == "new"


def test_agent_provenance_is_persisted(db_session, factories) -> None:  # type: ignore[no-untyped-def]
    tenant = _tenant(db_session, "result-provenance")
    agent = factories.agent(status="active", tenant_id=tenant.id)
    job = _job(db_session, scan_agent_id=agent.id, tenant_id=tenant.id)

    res, _classification = build_and_classify_result(
        db_session,
        job,
        {"ip": "10.60.0.12", "mac_address": "aa:bb:cc:10:00:07", "source": "agent"},
        discovery_agent_id=agent.id,
        finding_id="f-provenance",
    )
    db_session.flush()
    db_session.expire(res)

    assert res.discovery_agent_id == agent.id
    assert res.finding_id == "f-provenance"
    assert res.tenant_id == tenant.id
    assert res.source_type == "agent"


def test_agent_conflict_is_classified_and_recorded(db_session, factories) -> None:  # type: ignore[no-untyped-def]
    agent = factories.agent(status="active")
    factories.hardware(name="stored-name", mac_address="AA:BB:CC:10:00:08")
    job = _job(db_session, scan_agent_id=agent.id)

    res, classification = build_and_classify_result(
        db_session,
        job,
        {"ip": "10.60.0.13", "mac_address": "aa:bb:cc:10:00:08", "hostname": "reported-name"},
        discovery_agent_id=agent.id,
        finding_id="f-conflict",
    )
    db_session.flush()

    assert classification == "conflict"
    assert res.state == "conflict"
    # Double-encoded on purpose-by-history: `_scan_import` has always written
    # `json.dumps(...)` into this JSONB column and the review UI parses it back.
    assert json.loads(res.conflicts_json) == [
        {"field": "hostname", "stored": "stored-name", "discovered": "reported-name"}
    ]


def test_agent_row_imports_idempotently_through_the_review_queue(db_session, factories) -> None:  # type: ignore[no-untyped-def]
    """An agent-provenance row is an ordinary review-queue row: accepting it
    twice must upsert one Hardware, not two (plan §5.7)."""
    from app.schemas.discovery import BatchImportItem, BatchImportRequest
    from app.services.discovery_import_service import batch_import

    agent = factories.agent(status="active")
    job = _job(db_session, scan_agent_id=agent.id)

    res, _classification = build_and_classify_result(
        db_session,
        job,
        {"ip": "10.60.0.14", "mac_address": "aa:bb:cc:10:00:09", "hostname": "agent-host"},
        discovery_agent_id=agent.id,
        finding_id="f-import",
    )
    db_session.flush()

    req = BatchImportRequest(items=[BatchImportItem(scan_result_id=res.id, overrides={})])
    batch_import(db_session, job.id, req, actor="reviewer")
    batch_import(db_session, job.id, req, actor="reviewer")
    db_session.expire_all()

    matches = db_session.query(Hardware).filter(Hardware.mac_address == "AA:BB:CC:10:00:09").all()
    assert len(matches) == 1
