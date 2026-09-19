"""Unit tests for `services/discovery_enrich.py`.

The three rules the module exists to keep — never create, never overwrite, never
rename — each get their own case, because each one is what makes running this
without an operator's review defensible in the first place.
"""

from datetime import UTC, datetime

import pytest

from app.db.models import Hardware, Log, ScanJob, ScanResult, Tenant
from app.services.discovery_enrich import (
    AUDIT_ACTION,
    ENRICHED_MERGE_STATUS,
    backfill_pending_matched,
    enrich_matched_result,
    log_enrichment,
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _make_job(db, tenant_id=None) -> ScanJob:
    job = ScanJob(
        status="completed",
        triggered_by="test",
        target_cidr="10.0.0.0/24",
        scan_types_json='["nmap"]',
        tenant_id=tenant_id,
        created_at=_now(),
    )
    db.add(job)
    db.flush()
    return job


def _make_hw(db, *, name="dev", ip="10.0.0.5", mac=None, **kw) -> Hardware:
    hw = Hardware(
        name=name,
        ip_address=ip,
        mac_address=mac,
        role="server",
        source="discovery",
        discovered_at=_now(),
        last_seen=_now(),
        **kw,
    )
    db.add(hw)
    db.flush()
    return hw


def _make_result(
    db,
    job,
    *,
    hw=None,
    ip="10.0.0.5",
    mac=None,
    hostname=None,
    state="matched",
    merge_status="pending",
    source_type="nmap",
    agent_id=None,
    **kw,
) -> ScanResult:
    sr = ScanResult(
        scan_job_id=job.id,
        ip_address=ip,
        mac_address=mac,
        hostname=hostname,
        state=state,
        merge_status=merge_status,
        source_type=source_type,
        discovery_agent_id=agent_id,
        tenant_id=job.tenant_id,
        matched_entity_type="hardware" if hw is not None else None,
        matched_entity_id=hw.id if hw is not None else None,
        created_at=_now(),
        **kw,
    )
    db.add(sr)
    db.flush()
    return sr


# ── The point of the feature ─────────────────────────────────────────────────


def test_fills_an_empty_mac_and_drops_the_row_out_of_the_queue(db_session):
    job = _make_job(db_session)
    hw = _make_hw(db_session, mac=None)
    sr = _make_result(db_session, job, hw=hw, mac="bc:24:11:3b:f4:bb")

    outcome = enrich_matched_result(db_session, sr)

    assert outcome.enriched is True
    assert hw.mac_address == "BC:24:11:3B:F4:BB"  # canonicalised on the way in
    assert sr.merge_status == ENRICHED_MERGE_STATUS
    assert {f["field"] for f in outcome.fields} >= {"mac_address"}
    assert sr.enriched_at is not None


def test_records_which_fields_it_filled(db_session):
    job = _make_job(db_session)
    hw = _make_hw(db_session, mac=None, vendor=None)
    sr = _make_result(db_session, job, hw=hw, mac="AA:BB:CC:DD:EE:FF", os_vendor="Acme")

    enrich_matched_result(db_session, sr)

    filled = {f["field"]: f["value"] for f in sr.enriched_fields_json}
    assert filled["mac_address"] == "AA:BB:CC:DD:EE:FF"
    assert filled["vendor"] == "Acme"


def test_nothing_to_fill_still_refreshes_liveness_and_records_an_empty_list(db_session):
    job = _make_job(db_session)
    hw = _make_hw(
        db_session,
        mac="AA:BB:CC:DD:EE:FF",
        vendor="Acme",
        os_version="Linux",
        hostname="known",
        vendor_icon_slug="acme",
        status="offline",
    )
    hw.discovered_at = _now()
    sr = _make_result(db_session, job, hw=hw, mac="AA:BB:CC:DD:EE:FF")

    outcome = enrich_matched_result(db_session, sr)

    assert outcome.enriched is True
    assert outcome.fields == []
    assert sr.enriched_fields_json == []
    assert hw.status == "online"
    assert sr.merge_status == ENRICHED_MERGE_STATUS


# ── Rule 1: never create ─────────────────────────────────────────────────────


def test_a_new_result_is_left_alone_and_creates_no_hardware(db_session):
    job = _make_job(db_session)
    before = db_session.query(Hardware).count()
    sr = _make_result(db_session, job, state="new", ip="10.0.0.99", mac="11:22:33:44:55:66")

    outcome = enrich_matched_result(db_session, sr)

    assert outcome.enriched is False
    assert db_session.query(Hardware).count() == before
    assert sr.merge_status == "pending"


def test_a_deleted_match_target_leaves_the_row_pending(db_session):
    job = _make_job(db_session)
    hw = _make_hw(db_session)
    sr = _make_result(db_session, job, hw=hw)
    sr.matched_entity_id = hw.id + 10_000  # the device was deleted underneath us

    outcome = enrich_matched_result(db_session, sr)

    assert outcome.enriched is False
    assert sr.merge_status == "pending"


# ── Rule 2: never overwrite ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("attr", "stored", "hw_kwargs", "result_kwargs"),
    [
        (
            "mac_address",
            "99:99:99:99:99:99",
            {"mac": "99:99:99:99:99:99"},
            {"mac": "AA:BB:CC:DD:EE:FF"},
        ),
        (
            "vendor",
            "Operator's answer",
            {"vendor": "Operator's answer"},
            {"os_vendor": "Scanner guess"},
        ),
        (
            "os_version",
            "Operator's answer",
            {"os_version": "Operator's answer"},
            {"os_family": "Scanner guess"},
        ),
    ],
)
def test_never_overwrites_a_value_that_is_already_set(
    db_session, attr, stored, hw_kwargs, result_kwargs
):
    job = _make_job(db_session)
    hw = _make_hw(db_session, **hw_kwargs)
    sr = _make_result(db_session, job, hw=hw, **result_kwargs)

    enrich_matched_result(db_session, sr)

    assert getattr(hw, attr) == stored
    assert all(f["field"] != attr for f in sr.enriched_fields_json)


def test_a_mac_another_device_already_claims_is_not_filled(db_session):
    """A row matched by IP must not be able to install a MAC that belongs to
    someone else — that is the identity every future MAC-tier lookup follows."""
    job = _make_job(db_session)
    _make_hw(db_session, name="incumbent", ip="10.0.0.1", mac="AA:BB:CC:DD:EE:FF")
    hw = _make_hw(db_session, name="claimant", ip="10.0.0.5", mac=None)
    sr = _make_result(db_session, job, hw=hw, ip="10.0.0.5", mac="aa:bb:cc:dd:ee:ff")

    enrich_matched_result(db_session, sr)

    assert hw.mac_address is None
    assert all(f["field"] != "mac_address" for f in sr.enriched_fields_json)


# ── Rule 3: never rename ─────────────────────────────────────────────────────


def test_the_device_name_is_never_written(db_session):
    job = _make_job(db_session)
    hw = _make_hw(db_session, name="my-nas", mac=None)
    sr = _make_result(db_session, job, hw=hw, mac="AA:BB:CC:DD:EE:FF", hostname="dhcp-guess")

    enrich_matched_result(db_session, sr)

    assert hw.name == "my-nas"


def test_an_agent_finding_may_not_name_a_device_the_inventory_left_unnamed(db_session, factories):
    job = _make_job(db_session)
    agent = factories.agent(status="approved")
    hw = _make_hw(db_session, hostname=None, mac=None)
    sr = _make_result(
        db_session,
        job,
        hw=hw,
        mac="AA:BB:CC:DD:EE:FF",
        hostname="agent-saw-this",
        agent_id=agent.id,
    )

    enrich_matched_result(db_session, sr)

    assert hw.hostname is None
    assert hw.mac_address == "AA:BB:CC:DD:EE:FF"  # the rest of the row still enriches


def test_a_server_finding_may_fill_an_empty_hostname(db_session):
    job = _make_job(db_session)
    hw = _make_hw(db_session, hostname=None)
    sr = _make_result(db_session, job, hw=hw, hostname="server-resolved-this")

    enrich_matched_result(db_session, sr)

    assert hw.hostname == "server-resolved-this"


# ── Guards ───────────────────────────────────────────────────────────────────


def test_a_conflict_stays_pending_for_the_operator(db_session):
    job = _make_job(db_session)
    hw = _make_hw(db_session, mac=None)
    sr = _make_result(db_session, job, hw=hw, state="conflict", mac="AA:BB:CC:DD:EE:FF")

    outcome = enrich_matched_result(db_session, sr)

    assert outcome.enriched is False
    assert sr.merge_status == "pending"
    assert hw.mac_address is None


@pytest.mark.parametrize("source_type", ["proxmox", "docker"])
def test_out_of_scope_sources_are_skipped(db_session, source_type):
    job = _make_job(db_session)
    hw = _make_hw(db_session, mac=None)
    sr = _make_result(db_session, job, hw=hw, source_type=source_type, mac="AA:BB:CC:DD:EE:FF")

    assert enrich_matched_result(db_session, sr).enriched is False
    assert sr.merge_status == "pending"


def test_an_already_processed_row_is_never_enriched_twice(db_session):
    job = _make_job(db_session)
    hw = _make_hw(db_session, mac=None)
    sr = _make_result(db_session, job, hw=hw, mac="AA:BB:CC:DD:EE:FF")

    assert enrich_matched_result(db_session, sr).enriched is True
    hw.vendor = None  # pretend something else cleared it between calls
    assert enrich_matched_result(db_session, sr).enriched is False
    assert hw.vendor is None


def test_an_agent_finding_does_not_cross_a_tenant(db_session, factories):
    """The job is tenant-less, so its findings must not touch a tenant's device."""
    tenant = Tenant(name="other-tenant", slug="other")
    db_session.add(tenant)
    db_session.flush()
    job = _make_job(db_session, tenant_id=None)
    agent = factories.agent(status="approved")
    hw = _make_hw(db_session, mac=None, tenant_id=tenant.id)
    sr = _make_result(db_session, job, hw=hw, mac="AA:BB:CC:DD:EE:FF", agent_id=agent.id)

    assert enrich_matched_result(db_session, sr).enriched is False
    assert hw.mac_address is None


# ── Audit ────────────────────────────────────────────────────────────────────


def _audit_count(db) -> int:
    return db.query(Log).filter(Log.action == AUDIT_ACTION).count()


def test_an_enrichment_that_filled_something_is_audited(db_session):
    job = _make_job(db_session)
    hw = _make_hw(db_session, mac=None)
    sr = _make_result(db_session, job, hw=hw, mac="AA:BB:CC:DD:EE:FF")
    before = _audit_count(db_session)

    log_enrichment(db_session, sr, enrich_matched_result(db_session, sr))

    assert _audit_count(db_session) == before + 1


def test_a_bare_liveness_refresh_is_not_audited(db_session):
    """Otherwise a six-hourly sweep of a /24 writes 254 rows a pass saying nothing."""
    job = _make_job(db_session)
    hw = _make_hw(
        db_session,
        mac="AA:BB:CC:DD:EE:FF",
        vendor="Acme",
        os_version="Linux",
        hostname="known",
        vendor_icon_slug="acme",
    )
    hw.discovered_at = _now()
    sr = _make_result(db_session, job, hw=hw, mac="AA:BB:CC:DD:EE:FF")
    before = _audit_count(db_session)

    log_enrichment(db_session, sr, enrich_matched_result(db_session, sr))

    assert _audit_count(db_session) == before


# ── The upgrade backfill ─────────────────────────────────────────────────────


def test_backfill_drains_the_queue_and_is_idempotent(db_session):
    job = _make_job(db_session)
    for i in range(3):
        hw = _make_hw(db_session, name=f"dev{i}", ip=f"10.0.0.{i + 10}", mac=None)
        _make_result(db_session, job, hw=hw, ip=f"10.0.0.{i + 10}", mac=f"AA:BB:CC:DD:EE:{i:02X}")
    _make_result(db_session, job, state="new", ip="10.0.0.200")

    assert backfill_pending_matched(db_session) == 3
    assert backfill_pending_matched(db_session) == 0

    still_pending = (
        db_session.query(ScanResult)
        .filter(ScanResult.merge_status == "pending", ScanResult.scan_job_id == job.id)
        .all()
    )
    assert [r.state for r in still_pending] == ["new"]
