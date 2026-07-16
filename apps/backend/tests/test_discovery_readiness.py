from datetime import UTC, datetime, timedelta
from unittest.mock import patch


async def test_readiness_endpoint_returns_capabilities(client, auth_headers):
    resp = await client.get("/api/v1/discovery/readiness", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    keys = [c["key"] for c in body["capabilities"]]
    assert keys == ["nmap_present", "nmap_raw", "arp_l2", "lan_adjacency"]
    for c in body["capabilities"]:
        assert c["state"] in {
            "ready",
            "auto-fixable",
            "needs-helper-action",
            "unavailable-on-platform",
        }
        assert c["explanation"]


def test_nmap_binary_present_true_when_on_path():
    from app.services.discovery_probes import nmap_binary_present

    with patch("shutil.which", return_value="/usr/bin/nmap"):
        assert nmap_binary_present() is True


def test_nmap_binary_present_false_when_missing():
    from app.services.discovery_probes import nmap_binary_present

    with patch("shutil.which", return_value=None):
        assert nmap_binary_present() is False


def _mock_open_text(text):
    from unittest.mock import mock_open

    return mock_open(read_data=text)


def test_nmap_os_capable_true_with_ambient_net_raw():
    from app.services.discovery_probes import _has_ambient_net_raw

    # CapAmb with bit 13 set → 0x0000000000002000
    proc_status = "Name:\tpython\nCapAmb:\t0000000000002000\n"
    with patch("builtins.open", _mock_open_text(proc_status)):
        assert _has_ambient_net_raw() is True


def test_nmap_os_capable_false_without_ambient_net_raw():
    from app.services.discovery_probes import _has_ambient_net_raw

    proc_status = "Name:\tpython\nCapAmb:\t0000000000000000\n"
    with patch("builtins.open", _mock_open_text(proc_status)):
        assert _has_ambient_net_raw() is False


def test_readiness_all_ready_when_capable():
    import app.services.discovery_readiness as r

    with (
        patch.object(r, "nmap_binary_present", return_value=True),
        patch.object(r, "_nmap_os_capable", return_value=True),
        patch.object(r, "_arp_available", return_value=True),
        patch.object(r, "detect_lan_adjacency", return_value=True),
    ):
        caps = {c.key: c for c in r.get_discovery_readiness()}

    assert list(caps) == ["nmap_present", "nmap_raw", "arp_l2", "lan_adjacency"]
    assert caps["nmap_present"].state == r.CapState.READY
    assert caps["nmap_raw"].state == r.CapState.READY
    assert caps["arp_l2"].state == r.CapState.READY
    assert caps["lan_adjacency"].state == r.CapState.READY


def test_readiness_nmap_missing_is_auto_fixable():
    import app.services.discovery_readiness as r

    with (
        patch.object(r, "nmap_binary_present", return_value=False),
        patch.object(r, "_nmap_os_capable", return_value=False),
        patch.object(r, "_arp_available", return_value=False),
        patch.object(r, "detect_lan_adjacency", return_value=True),
    ):
        caps = {c.key: c for c in r.get_discovery_readiness()}

    assert caps["nmap_present"].state == r.CapState.AUTO_FIXABLE
    assert caps["nmap_present"].explanation  # non-empty human text


def test_readiness_arp_needs_helper_when_no_adjacency():
    import app.services.discovery_readiness as r

    with (
        patch.object(r, "nmap_binary_present", return_value=True),
        patch.object(r, "_nmap_os_capable", return_value=True),
        patch.object(r, "_arp_available", return_value=False),
        patch.object(r, "detect_lan_adjacency", return_value=False),
    ):
        caps = {c.key: c for c in r.get_discovery_readiness()}

    assert caps["arp_l2"].state == r.CapState.NEEDS_HELPER_ACTION
    assert caps["lan_adjacency"].state == r.CapState.NEEDS_HELPER_ACTION


def test_startup_logging_warns_on_degraded(caplog):
    import logging

    import app.services.discovery_readiness as r

    with (
        patch.object(r, "nmap_binary_present", return_value=False),
        patch.object(r, "_nmap_os_capable", return_value=False),
        patch.object(r, "_arp_available", return_value=False),
        patch.object(r, "detect_lan_adjacency", return_value=True),
        caplog.at_level(logging.WARNING),
    ):
        r.log_discovery_readiness_at_startup()

    assert any("nmap" in rec.message.lower() for rec in caplog.records)


# ── get_capability_heal_metadata (read-time join against the worker audit log) ──


def _seed_heal_log(db_session, *, action, entity_name, details, timestamp):
    """Insert a worker-audit Log row shaped like discovery_reconciler's
    _attempt_heal writes, with an explicit timestamp so ordering between
    rows is deterministic (no wall-clock sleeps needed)."""
    from app.db.models import Log

    log = Log(
        timestamp=timestamp,
        level="info",
        category="worker",
        action=action,
        actor="system",
        actor_name="discovery_reconciler",
        entity_type="discovery_capability",
        entity_name=entity_name,
        details=details,
    )
    db_session.add(log)
    db_session.flush()
    return log


def test_heal_metadata_no_history_returns_none(db_session):
    from app.services.discovery_readiness import get_capability_heal_metadata

    result = get_capability_heal_metadata(db_session, "nmap_present")

    assert result == {"last_healed_at": None, "last_error": None}


def test_heal_metadata_success_only(db_session):
    from app.services.discovery_readiness import get_capability_heal_metadata

    ts = datetime.now(UTC)
    _seed_heal_log(
        db_session,
        action="discovery_auto_heal_ensure_nmap",
        entity_name="nmap_present",
        details="capability=nmap_present",
        timestamp=ts,
    )

    result = get_capability_heal_metadata(db_session, "nmap_present")

    assert result["last_healed_at"] == ts.isoformat()
    assert result["last_error"] is None


def test_heal_metadata_failure_only(db_session):
    from app.services.discovery_readiness import get_capability_heal_metadata

    ts = datetime.now(UTC)
    _seed_heal_log(
        db_session,
        action="discovery_auto_heal_ensure_nmap_failed",
        entity_name="nmap_present",
        details="capability=nmap_present error=binary not found",
        timestamp=ts,
    )

    result = get_capability_heal_metadata(db_session, "nmap_present")

    assert result["last_healed_at"] is None
    assert result["last_error"] == "binary not found"


def test_heal_metadata_success_after_failure_clears_last_error(db_session):
    """A failure followed by a later success should report the success and
    clear last_error — ordering is driven by an explicit later timestamp,
    not a real-time sleep, so it can't flake under load."""
    from app.services.discovery_readiness import get_capability_heal_metadata

    base = datetime.now(UTC)
    _seed_heal_log(
        db_session,
        action="discovery_auto_heal_ensure_nmap_failed",
        entity_name="nmap_present",
        details="capability=nmap_present error=binary not found",
        timestamp=base,
    )
    _seed_heal_log(
        db_session,
        action="discovery_auto_heal_ensure_nmap",
        entity_name="nmap_present",
        details="capability=nmap_present",
        timestamp=base + timedelta(seconds=1),
    )

    result = get_capability_heal_metadata(db_session, "nmap_present")

    assert result["last_healed_at"] == (base + timedelta(seconds=1)).isoformat()
    assert result["last_error"] is None


def test_heal_metadata_failure_after_success_sets_last_error(db_session):
    """The mirror case: a failure newer than the last success should still
    surface last_error even though a prior success exists."""
    from app.services.discovery_readiness import get_capability_heal_metadata

    base = datetime.now(UTC)
    _seed_heal_log(
        db_session,
        action="discovery_auto_heal_ensure_nmap",
        entity_name="nmap_present",
        details="capability=nmap_present",
        timestamp=base,
    )
    _seed_heal_log(
        db_session,
        action="discovery_auto_heal_ensure_nmap_failed",
        entity_name="nmap_present",
        details="capability=nmap_present error=binary not found",
        timestamp=base + timedelta(seconds=1),
    )

    result = get_capability_heal_metadata(db_session, "nmap_present")

    assert result["last_healed_at"] == base.isoformat()
    assert result["last_error"] == "binary not found"


def test_heal_metadata_arp_l2_and_lan_adjacency_share_lan_discovery_entity(db_session):
    from app.services.discovery_readiness import get_capability_heal_metadata

    ts = datetime.now(UTC)
    _seed_heal_log(
        db_session,
        action="discovery_auto_heal_enable_lan_discovery",
        entity_name="lan_discovery",
        details="capability=lan_discovery",
        timestamp=ts,
    )

    arp_result = get_capability_heal_metadata(db_session, "arp_l2")
    lan_result = get_capability_heal_metadata(db_session, "lan_adjacency")

    assert arp_result == lan_result
    assert arp_result["last_healed_at"] == ts.isoformat()
    assert arp_result["last_error"] is None


def test_heal_metadata_unknown_capability_key_returns_none(db_session):
    from app.services.discovery_readiness import get_capability_heal_metadata

    result = get_capability_heal_metadata(db_session, "not_a_real_capability")

    assert result == {"last_healed_at": None, "last_error": None}


# ── GET /api/v1/discovery/readiness extended with helper_installed + per-capability metadata ──


async def test_readiness_endpoint_includes_helper_installed_boolean(client, auth_headers):
    resp = await client.get("/api/v1/discovery/readiness", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "helper_installed" in body
    assert isinstance(body["helper_installed"], bool)


async def test_readiness_endpoint_includes_heal_metadata_per_capability(client, auth_headers):
    resp = await client.get("/api/v1/discovery/readiness", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    for c in body["capabilities"]:
        assert "last_healed_at" in c
        assert "last_error" in c


async def test_readiness_endpoint_heal_metadata_scoped_to_capability(
    client, auth_headers, db_session
):
    """A heal logged for nmap_present should appear only on nmap_present,
    not on nmap_raw or other capabilities."""
    from datetime import UTC, datetime

    # Seed a heal log for nmap_present only
    ts = datetime.now(UTC)
    from app.db.models import Log

    log = Log(
        timestamp=ts,
        level="info",
        category="worker",
        action="discovery_auto_heal_ensure_nmap",
        actor="system",
        actor_name="discovery_reconciler",
        entity_type="discovery_capability",
        entity_name="nmap_present",
        details="capability=nmap_present",
    )
    db_session.add(log)
    db_session.commit()

    resp = await client.get("/api/v1/discovery/readiness", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()

    # Find nmap_present and nmap_raw capabilities
    nmap_present_cap = next((c for c in body["capabilities"] if c["key"] == "nmap_present"), None)
    nmap_raw_cap = next((c for c in body["capabilities"] if c["key"] == "nmap_raw"), None)

    assert nmap_present_cap is not None
    assert nmap_raw_cap is not None

    # nmap_present should have the heal logged
    assert nmap_present_cap["last_healed_at"] == ts.isoformat()
    assert nmap_present_cap["last_error"] is None

    # nmap_raw should have no heal (None)
    assert nmap_raw_cap["last_healed_at"] is None
    assert nmap_raw_cap["last_error"] is None
