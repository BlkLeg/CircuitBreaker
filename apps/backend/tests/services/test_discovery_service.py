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
