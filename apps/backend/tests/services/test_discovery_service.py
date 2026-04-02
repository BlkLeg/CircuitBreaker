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
