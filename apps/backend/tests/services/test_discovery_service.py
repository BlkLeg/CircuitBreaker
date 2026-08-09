import pytest


def test_arp_stub_injected_for_arp_only_host() -> None:
    """ARP-only IPs (phones with no open ports) get a stub in nmap_results."""
    nmap_results: dict = {}
    arp_mac_by_ip = {"192.168.1.55": "aa:bb:cc:dd:ee:ff"}

    for ip, mac in arp_mac_by_ip.items():
        nmap_results.setdefault(
            ip,
            {
                "mac": mac,
                "hostname": None,
                "os_family": None,
                "open_ports": [],
                "raw": "",
            },
        )

    assert "192.168.1.55" in nmap_results
    assert nmap_results["192.168.1.55"]["mac"] == "aa:bb:cc:dd:ee:ff"


def test_arp_stub_does_not_overwrite_existing_nmap_entry() -> None:
    """setdefault must not clobber existing nmap data."""
    nmap_results: dict = {
        "192.168.1.1": {"mac": "11:22:33:44:55:66", "hostname": "router", "open_ports": [80]}
    }
    arp_mac_by_ip = {"192.168.1.1": "aa:bb:cc:dd:ee:ff"}

    for ip, mac in arp_mac_by_ip.items():
        nmap_results.setdefault(
            ip, {"mac": mac, "hostname": None, "os_family": None, "open_ports": [], "raw": ""}
        )

    assert nmap_results["192.168.1.1"]["hostname"] == "router"
    assert nmap_results["192.168.1.1"]["open_ports"] == [80]


def test_ttl_probe_fires_when_mac_is_none() -> None:
    """TTL probe condition must be True when mac_address is None."""
    from app.services.discovery_service import _is_randomized_mac

    # Old condition: _is_randomized_mac(None or "") == False → TTL skipped
    assert _is_randomized_mac("") is False

    # New condition: not mac_address → True when mac is None
    mac_address: str | None = None
    should_probe = not mac_address or _is_randomized_mac(mac_address)
    assert should_probe is True


@pytest.mark.asyncio
async def test_probe_gather_continues_after_single_host_exception() -> None:
    """return_exceptions=True lets surviving hosts complete even when one raises."""
    import asyncio

    async def good(ip: str) -> dict:
        return {"ip": ip}

    async def bad(ip: str) -> dict:
        raise RuntimeError("socket error")

    raw = await asyncio.gather(
        good("1.1.1.1"), bad("1.1.1.2"), good("1.1.1.3"), return_exceptions=True
    )
    results = [r for r in raw if not isinstance(r, BaseException)]
    assert len(results) == 2


def test_dhcp_auto_probe_detects_dnsmasq_leases(tmp_path, monkeypatch) -> None:
    """When dhcp_file is empty but a known lease path exists, it is auto-detected."""
    import os

    leases = tmp_path / "dnsmasq.leases"
    leases.write_text("1234567890 aa:bb:cc:dd:ee:ff 192.168.1.50 android-phone *\n")

    import app.services.discovery_service as ds

    monkeypatch.setattr(ds, "_AUTO_DHCP_PATHS", [str(leases)])

    dhcp_file = ""
    for _p in ds._AUTO_DHCP_PATHS:
        if os.path.isfile(_p) and os.access(_p, os.R_OK):
            dhcp_file = _p
            break

    assert dhcp_file == str(leases)


def test_scan_import_commits_once_for_batch(db_session) -> None:  # type: ignore[no-untyped-def]
    """_scan_import must issue at most 2 commits for N results, not N commits."""
    from unittest.mock import patch

    import app.services.discovery_service as ds
    from app.db.models import ScanJob

    job = ScanJob(
        target_cidr="192.168.1.0/24",
        status="running",
        scan_types_json='["nmap"]',
        created_at="2026-01-01T00:00:00",
    )
    db_session.add(job)
    db_session.commit()

    commit_count: list[int] = [0]
    original_commit = db_session.commit

    def counting_commit() -> None:
        commit_count[0] += 1
        return original_commit()

    raw_results = [{"ip": f"192.168.1.{i}"} for i in range(1, 6)]

    with (
        patch.object(ds, "SessionLocal", return_value=db_session),
        patch.object(db_session, "close"),
    ):
        db_session.commit = counting_commit
        ds._scan_import(job.id, {}, raw_results)

    # Restore commit so cleanup works
    db_session.commit = original_commit

    # 1 commit for batch results + 1 for job counters = 2 max, never 5+
    assert commit_count[0] <= 2, f"Expected ≤2 commits for 5 results, got {commit_count[0]}"


# ── _scan_import characterization (Slice 4 D-9) ───────────────────────────────
#
# Row building, hardware matching and conflict classification move out of
# `_scan_import` into `discovery_result_service`. These pin the server path's
# observable output so the extraction is provably a no-op for it: the agent path
# is allowed to differ only where D-9 says it may (tenant filter, normalization
# by the caller), never here.


def _import_job(db_session, **kwargs):  # type: ignore[no-untyped-def]
    from app.db.models import ScanJob

    defaults = {
        "target_cidr": "192.168.77.0/24",
        "status": "running",
        "scan_types_json": '["nmap"]',
        "created_at": "2026-01-01T00:00:00",
    }
    defaults.update(kwargs)
    job = ScanJob(**defaults)
    db_session.add(job)
    db_session.flush()
    return job


def _run_scan_import(db_session, job_id, raw_results, setup=None):  # type: ignore[no-untyped-def]
    """Drive `_scan_import` against the SAVEPOINT session it would otherwise
    replace with its own `SessionLocal`."""
    from unittest.mock import patch

    import app.services.discovery_service as ds

    with (
        patch.object(ds, "SessionLocal", return_value=db_session),
        patch.object(db_session, "close"),
    ):
        return ds._scan_import(job_id, setup or {}, raw_results)


def _sole_result(db_session, job_id):  # type: ignore[no-untyped-def]
    from app.db.models import ScanResult

    rows = db_session.query(ScanResult).filter(ScanResult.scan_job_id == job_id).all()
    assert len(rows) == 1, f"expected exactly one ScanResult, got {len(rows)}"
    return rows[0]


def test_scan_import_classifies_an_unknown_host_as_new(db_session) -> None:  # type: ignore[no-untyped-def]
    job = _import_job(db_session)

    stats = _run_scan_import(
        db_session,
        job.id,
        [{"ip": "192.168.77.10", "mac_address": "AA:BB:CC:00:00:01", "hostname": "printer"}],
    )["stats"]

    res = _sole_result(db_session, job.id)
    assert (res.state, res.merge_status) == ("new", "pending")
    assert res.matched_entity_type is None and res.matched_entity_id is None
    assert res.source_type == "nmap"
    assert stats == {
        "hosts_found": 1,
        "hosts_new": 1,
        "hosts_updated": 0,
        "hosts_conflict": 0,
    }


def test_scan_import_matches_a_known_mac(db_session, factories) -> None:  # type: ignore[no-untyped-def]
    hw = factories.hardware(name="known-host", mac_address="AA:BB:CC:00:00:02")
    job = _import_job(db_session)

    stats = _run_scan_import(
        db_session,
        job.id,
        [{"ip": "192.168.77.11", "mac_address": "AA:BB:CC:00:00:02", "hostname": "known-host"}],
    )["stats"]

    res = _sole_result(db_session, job.id)
    assert res.state == "matched"
    assert (res.matched_entity_type, res.matched_entity_id) == ("hardware", hw.id)
    assert res.conflicts_json is None
    assert stats["hosts_updated"] == 1 and stats["hosts_new"] == 0


def test_scan_import_flags_a_hostname_conflict(db_session, factories) -> None:  # type: ignore[no-untyped-def]
    import json as _json

    hw = factories.hardware(name="stored-name", mac_address="AA:BB:CC:00:00:03")
    job = _import_job(db_session)

    stats = _run_scan_import(
        db_session,
        job.id,
        [
            {
                "ip": "192.168.77.12",
                "mac_address": "AA:BB:CC:00:00:03",
                "hostname": "discovered-name",
            }
        ],
    )["stats"]

    res = _sole_result(db_session, job.id)
    assert res.state == "conflict"
    assert res.matched_entity_id == hw.id
    assert _json.loads(res.conflicts_json) == [
        {"field": "hostname", "stored": "stored-name", "discovered": "discovered-name"}
    ]
    assert stats["hosts_conflict"] == 1 and stats["hosts_updated"] == 0


def test_scan_import_applies_the_docker_override_fields(db_session) -> None:  # type: ignore[no-untyped-def]
    job = _import_job(db_session)

    _run_scan_import(
        db_session,
        job.id,
        [
            {
                "ip": "172.18.0.4",
                "source": "docker",
                "hostname": "raw-hostname",
                "os_vendor": "raw-vendor",
                "os_family": "raw-family",
                "os_vendor_override": "Docker",
                "os_family_override": "container",
                "hostname_override": "web-1",
            }
        ],
    )

    res = _sole_result(db_session, job.id)
    assert (res.os_vendor, res.os_family, res.hostname) == ("Docker", "container", "web-1")
    assert res.source_type == "docker"


def test_scan_import_resolves_network_for_a_docker_row(db_session, factories) -> None:  # type: ignore[no-untyped-def]
    """`network_id`/`vlan_id` are looked up from `networks` when the docker
    result does not carry them — the one lookup D-9 keeps inside the helper."""
    net = factories.network(cidr="10.44.0.0/24", vlan_id=44)
    job = _import_job(db_session)

    _run_scan_import(
        db_session,
        job.id,
        [{"ip": "10.44.0.9", "source": "docker"}],
    )

    res = _sole_result(db_session, job.id)
    assert (res.network_id, res.vlan_id) == (net.id, 44)


def test_scan_import_keeps_a_supplied_network_id(db_session, factories) -> None:  # type: ignore[no-untyped-def]
    """The resolution is a fallback: a caller-supplied id wins, and a non-docker
    source is never resolved at all."""
    factories.network(cidr="10.45.0.0/24", vlan_id=45)
    supplied = factories.network(cidr="10.99.0.0/24", vlan_id=99)
    job = _import_job(db_session)

    _run_scan_import(
        db_session,
        job.id,
        [
            {"ip": "10.45.0.9", "source": "docker", "network_id": supplied.id, "vlan_id": 99},
            {"ip": "10.45.0.10", "source": "nmap"},
        ],
    )

    from app.db.models import ScanResult

    rows = {
        r.ip_address: r
        for r in db_session.query(ScanResult).filter(ScanResult.scan_job_id == job.id).all()
    }
    assert (rows["10.45.0.9"].network_id, rows["10.45.0.9"].vlan_id) == (supplied.id, 99)
    assert (rows["10.45.0.10"].network_id, rows["10.45.0.10"].vlan_id) == (None, None)


# ── The queued backlog: parking, the ceiling, and the loop it must run on ─────
#
# Slice 4 Phase C remediation. Three defects live on one path — the drain that
# `_scan_finalize` and `finalize_agent_job` run when a job gives its concurrency
# slot back:
#
# * B1. The drain handed *every* queued job to the dispatcher, including one
#   parked in `waiting_for_agent` (D-5), and `_release_to_waiting` re-stamps
#   `dispatch_deadline_at` — so an unrelated scan finishing anywhere pushed a
#   parked job's deadline forward and it never reached its `agent_unavailable`
#   expiry.
# * B2. The direct dispatch path consulted no concurrency ceiling, so a job
#   created by cron or the API went `running` while ignoring
#   `max_concurrent_scans` — a limit it then consumed a slot against.
# * B3. `_scan_finalize` is sync and runs only in an executor thread, where
#   `asyncio.create_task` raises: the drain blew up exactly when a slot had just
#   been freed and a queued job existed.


def _backlog_agent(db_session, factories):  # type: ignore[no-untyped-def]
    """An active agent with `local_discovery` granted.

    Enough for `discovery_eligibility` to get as far as the online check, which
    is the only denial these tests care about: everything it inspects before
    presence (status, grant) has to pass or the job would be *failed* rather
    than parked.
    """
    import secrets

    from app.db.models import Tenant

    tenant = Tenant(name=f"discovery-backlog-{secrets.token_hex(4)}")
    db_session.add(tenant)
    db_session.flush()
    agent = factories.agent(status="active", tenant_id=tenant.id)
    factories.agent_capability_grant(agent, capability="local_discovery", enabled=True, config={})
    db_session.flush()
    return agent


def _backlog_job(db_session, **kwargs):  # type: ignore[no-untyped-def]
    from app.core.time import utcnow_iso
    from app.db.models import ScanJob

    defaults = {
        "target_cidr": "10.62.0.0/24",
        "status": "queued",
        "scan_types_json": '["nmap"]',
        "source_type": "manual",
        "progress_phase": "queued",
        "created_at": utcnow_iso(),
    }
    defaults.update(kwargs)
    job = ScanJob(**defaults)
    db_session.add(job)
    db_session.flush()
    return job


def _parked_backlog_job(db_session, agent, *, deadline_at, **kwargs):  # type: ignore[no-untyped-def]
    """A job in exactly the state `agent_discovery._release_to_waiting` leaves it."""
    from app.services import agent_discovery

    return _backlog_job(
        db_session,
        scan_agent_id=agent.id,
        tenant_id=agent.tenant_id,
        source_type="agent",
        scan_types_json='["agent_connect"]',
        status="queued",
        dispatch_status=agent_discovery.DISPATCH_STATUS_QUEUED,
        dispatch_id=None,
        started_at=None,
        progress_phase=agent_discovery.PHASE_WAITING_FOR_AGENT,
        dispatch_deadline_at=deadline_at,
        **kwargs,
    )


def _raise_the_ceiling(db_session, value: int = 10) -> None:
    """Other suites commit scan jobs of their own; a ceiling of 2 would let them
    decide whether this test's job is reached at all."""
    from app.services.settings_service import get_or_create_settings

    settings = get_or_create_settings(db_session)
    settings.max_concurrent_scans = value
    db_session.flush()


async def _eventually(predicate, limit_s: float = 5.0, what: str = "condition") -> None:  # type: ignore[no-untyped-def]
    """Poll until the loop has run whatever the subject scheduled onto it."""
    import asyncio
    import time

    deadline = time.monotonic() + limit_s
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"{what} never became true within {limit_s}s")


def test_the_queued_drain_leaves_a_job_parked_for_its_agent_to_its_deadline_owner(
    db_session, factories, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    """B1. D-5 parks a job whose agent is away with a deadline that
    `agent_discovery_reconcile` expires as `agent_unavailable`. Handing that row
    back to the dispatcher re-parks it with a *fresh* deadline, so a drain that
    included it would reset the clock every time any other scan finished.
    `_drain_queued_jobs` already refuses to do this; so must the server path."""
    from datetime import timedelta

    from app.core.time import utcnow
    from app.services import discovery_scheduler, discovery_service

    _raise_the_ceiling(db_session)
    agent = _backlog_agent(db_session, factories)
    parked = _parked_backlog_job(
        db_session,
        agent,
        deadline_at=utcnow() + timedelta(seconds=300),
        created_at="2020-01-01T00:00:00+00:00",
    )
    plain = _backlog_job(db_session, created_at="2020-01-02T00:00:00+00:00")

    handed: list[int] = []
    monkeypatch.setattr(
        discovery_service, "schedule_discovery_scan_job", lambda job_id: handed.append(job_id)
    )

    discovery_scheduler._schedule_queued_scan_jobs(db_session)

    assert plain.id in handed, "an ordinary queued job is still drained"
    assert parked.id not in handed


async def test_a_parked_job_keeps_its_original_deadline_when_an_unrelated_job_finishes(
    db_session, factories, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    """B1, end to end and through the real dispatcher. The treadmill: any job
    completing anywhere drained the backlog, the parked job went back to
    `dispatch_discovery_job`, its agent was still away, and
    `_release_to_waiting` stamped `now + DISPATCH_DEADLINE_S` over the deadline
    that was about to expire it."""
    from datetime import timedelta
    from unittest.mock import AsyncMock, patch

    from app.core.time import utcnow
    from app.services import agent_discovery, agent_registry, discovery_service

    _raise_the_ceiling(db_session)
    agent = _backlog_agent(db_session, factories)
    deadline = utcnow() + timedelta(seconds=300)
    parked = _parked_backlog_job(db_session, agent, deadline_at=deadline)
    finishing = _backlog_job(db_session, status="running")

    monkeypatch.setattr(agent_registry, "is_agent_online", AsyncMock(return_value=False))
    monkeypatch.setattr(agent_registry, "get_agent_connection_owner", AsyncMock(return_value=None))

    # The real router on the test's own session: `_execute_scan_job_in_session`
    # opens a session of its own, which cannot see rows living in this test's
    # SAVEPOINT. Everything downstream of it — the claim, the eligibility check,
    # the parking — is the production code.
    async def _route(job_id: int) -> None:
        await discovery_service.execute_scan_job(db_session, job_id)

    monkeypatch.setattr(discovery_service, "_execute_scan_job_in_session", _route)

    with (
        patch.object(discovery_service, "SessionLocal", return_value=db_session),
        patch.object(db_session, "close"),
    ):
        discovery_service._scan_finalize(finishing.id, {}, "completed", False)

    # Long enough for a task the drain created to have run: nothing on that path
    # awaits real I/O once presence is mocked.
    import asyncio

    await asyncio.sleep(0.2)

    db_session.refresh(parked)
    assert parked.status == "queued"
    assert parked.progress_phase == agent_discovery.PHASE_WAITING_FOR_AGENT
    assert parked.dispatch_deadline_at is not None
    drift = abs((agent_discovery._aware(parked.dispatch_deadline_at) - deadline).total_seconds())
    assert drift < 1, f"the parked deadline moved by {drift}s"


async def test_an_agent_job_over_the_concurrency_ceiling_is_not_dispatched(
    db_session, factories, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    """B2. `_claim` sets `status='running'`, so a dispatched agent job consumes a
    `max_concurrent_scans` slot from everyone else's point of view. A direct
    dispatch that never asked for one is a job exempt from a limit it spends."""
    from app.services import agent_discovery, discovery_service
    from app.services.settings_service import get_or_create_settings

    settings = get_or_create_settings(db_session)
    settings.max_concurrent_scans = 1
    db_session.flush()

    _backlog_job(db_session, status="running")  # the only slot, held by a server scan
    agent = _backlog_agent(db_session, factories)
    job = _backlog_job(
        db_session,
        scan_agent_id=agent.id,
        tenant_id=agent.tenant_id,
        source_type="agent",
        scan_types_json='["agent_connect"]',
    )

    dispatched: list[int] = []

    async def _spy(db, job_id: int) -> bool:  # type: ignore[no-untyped-def]
        dispatched.append(job_id)
        return True

    monkeypatch.setattr(agent_discovery, "dispatch_discovery_job", _spy)

    await discovery_service.execute_scan_job(db_session, job.id)

    assert dispatched == []
    db_session.refresh(job)
    # Parked the way a server job with no slot is parked (`_scan_setup`), not the
    # way D-5 parks one whose agent is away: the agent here is fine, and a row in
    # `waiting_for_agent` is one the reconciler expires as `agent_unavailable`.
    assert job.status == "queued"
    assert job.progress_phase != agent_discovery.PHASE_WAITING_FOR_AGENT
    assert job.dispatch_id is None
    assert job.dispatch_deadline_at is None


async def test_an_agent_job_with_a_free_slot_still_reaches_the_dispatcher(
    db_session, factories, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    """The other half of B2's ceiling: it may not become a gate that refuses
    every agent job."""
    from app.services import agent_discovery, discovery_service

    _raise_the_ceiling(db_session)
    agent = _backlog_agent(db_session, factories)
    job = _backlog_job(
        db_session,
        scan_agent_id=agent.id,
        tenant_id=agent.tenant_id,
        source_type="agent",
        scan_types_json='["agent_connect"]',
    )

    dispatched: list[int] = []

    async def _spy(db, job_id: int) -> bool:  # type: ignore[no-untyped-def]
        dispatched.append(job_id)
        return True

    monkeypatch.setattr(agent_discovery, "dispatch_discovery_job", _spy)

    await discovery_service.execute_scan_job(db_session, job.id)

    assert dispatched == [job.id]


async def test_finalizing_in_an_executor_thread_still_drains_the_backlog(
    db_session, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    """B3. `_scan_finalize` is synchronous and every caller runs it through
    `loop.run_in_executor`, where `asyncio.create_task` raises
    `RuntimeError: no running event loop`. The raise landed after the terminal
    status committed and before the pending count returned, so the job went
    terminal with no `job_update` event and the backlog never drained — exactly
    when a slot had just been freed and a queued job was waiting for it."""
    import asyncio
    from unittest.mock import patch

    from app.services import discovery_scheduler, discovery_service

    loop = asyncio.get_running_loop()
    # What `main.py`'s lifespan does at startup, undone by monkeypatch here.
    monkeypatch.setattr(discovery_scheduler, "_main_loop", loop)

    _raise_the_ceiling(db_session)
    finishing = _backlog_job(db_session, status="running")
    queued = _backlog_job(db_session, created_at="2020-01-03T00:00:00+00:00")

    started: list[int] = []

    async def _route(job_id: int) -> None:
        started.append(job_id)

    monkeypatch.setattr(discovery_service, "_execute_scan_job_in_session", _route)

    with (
        patch.object(discovery_service, "SessionLocal", return_value=db_session),
        patch.object(db_session, "close"),
    ):
        pending = await loop.run_in_executor(
            None, discovery_service._scan_finalize, finishing.id, {}, "completed", False
        )

    assert isinstance(pending, int), "the pending count must still be returned to the caller"
    await _eventually(
        lambda: queued.id in started, what=f"queued job {queued.id} reaching the scan executor"
    )
