"""Unit tests for the pure privacy ruleset (no I/O)."""

from app.services import privacy_rules


def _check(check_id: str, status: str) -> dict:
    return {
        "check_id": check_id,
        "status": status,
        "evidence": "test",
        "detected_at": "2026-07-15T00:00:00+00:00",
    }


# ── evaluate_device ───────────────────────────────────────────────────────────


def test_evaluate_device_no_open_ports_yields_no_deductions():
    assert privacy_rules.evaluate_device(1, "server", set()) == []


def test_evaluate_device_telnet_open_is_critical():
    deductions = privacy_rules.evaluate_device(7, "server", {23})
    assert len(deductions) == 1
    deduction = deductions[0]
    assert deduction["rule_id"] == "telnet_open"
    assert deduction["points"] == 15
    assert deduction["severity"] == "critical"
    assert deduction["hardware_id"] == 7
    assert deduction["remediation_id"]
    assert deduction["title"]
    assert deduction["category"] == "services"


def test_evaluate_device_ftp_and_smb_and_upnp():
    deductions = privacy_rules.evaluate_device(1, None, {21, 139, 1900})
    by_rule = {d["rule_id"]: d for d in deductions}
    assert by_rule["ftp_open"]["points"] == 8
    assert by_rule["ftp_open"]["severity"] == "warning"
    assert by_rule["legacy_smb_netbios"]["points"] == 8
    assert by_rule["upnp_exposed"]["points"] == 10
    assert by_rule["upnp_exposed"]["severity"] == "warning"


def test_evaluate_device_gateway_escalates_severity_and_points():
    deductions = privacy_rules.evaluate_device(2, "router", {21, 23})
    by_rule = {d["rule_id"]: d for d in deductions}
    # warning → critical, points ×1.5 rounded up
    assert by_rule["ftp_open"]["severity"] == "critical"
    assert by_rule["ftp_open"]["points"] == 12
    # critical stays critical, points still escalate
    assert by_rule["telnet_open"]["severity"] == "critical"
    assert by_rule["telnet_open"]["points"] == 23


def test_evaluate_device_unmatched_ports_ignored():
    assert privacy_rules.evaluate_device(1, "server", {80, 443, 22}) == []


def test_evaluate_device_categories_by_rule():
    deductions = privacy_rules.evaluate_device(1, None, {21, 137, 1900})
    by_rule = {d["rule_id"]: d for d in deductions}
    assert by_rule["ftp_open"]["category"] == "services"
    assert by_rule["legacy_smb_netbios"]["category"] == "protocols"
    assert by_rule["upnp_exposed"]["category"] == "protocols"


# ── device scoring & badges ──────────────────────────────────────────────────


def test_score_device_subtracts_and_clamps_to_zero():
    deductions = [{"points": 60}, {"points": 60}]
    assert privacy_rules.score_device(deductions) == 0
    assert privacy_rules.score_device([{"points": 15}]) == 85
    assert privacy_rules.score_device([]) == 100


def test_badge_severity_is_max_severity():
    deductions = [
        {"severity": "info"},
        {"severity": "critical"},
        {"severity": "warning"},
    ]
    assert privacy_rules.badge_severity(deductions) == "critical"
    assert privacy_rules.badge_severity([{"severity": "info"}]) == "info"
    assert privacy_rules.badge_severity([]) is None


# ── grades ────────────────────────────────────────────────────────────────────


def test_grade_bands():
    assert privacy_rules.grade_for(100) == "A"
    assert privacy_rules.grade_for(90) == "A"
    assert privacy_rules.grade_for(89) == "B"
    assert privacy_rules.grade_for(80) == "B"
    assert privacy_rules.grade_for(79) == "C"
    assert privacy_rules.grade_for(70) == "C"
    assert privacy_rules.grade_for(69) == "D"
    assert privacy_rules.grade_for(60) == "D"
    assert privacy_rules.grade_for(59) == "F"
    assert privacy_rules.grade_for(0) == "F"


# ── evaluate_network ─────────────────────────────────────────────────────────


def test_evaluate_network_empty_inputs_scores_100_grade_a():
    result = privacy_rules.evaluate_network([], [])
    assert result["score"] == 100
    assert result["grade"] == "A"
    assert result["deductions"] == []
    assert result["checks"] == []


def test_evaluate_network_ok_and_unknown_checks_do_not_deduct():
    checks = [_check("captive_portal", "ok"), _check("dns_tamper", "unknown")]
    result = privacy_rules.evaluate_network([], checks)
    assert result["score"] == 100
    assert result["deductions"] == []


def test_evaluate_network_check_deductions_apply():
    checks = [_check("captive_portal", "warning"), _check("dns_filtering_absent", "info")]
    result = privacy_rules.evaluate_network([], checks)
    # 100 − 10 − 5
    assert result["score"] == 85
    rule_ids = {d["rule_id"] for d in result["deductions"]}
    assert rule_ids == {"captive_portal", "dns_filtering_absent"}
    severities = {d["rule_id"]: d["severity"] for d in result["deductions"]}
    assert severities["dns_filtering_absent"] == "info"
    categories = {d["rule_id"]: d["category"] for d in result["deductions"]}
    assert categories["captive_portal"] == "network"
    assert categories["dns_filtering_absent"] == "dns"


def test_network_check_rule_categories():
    assert privacy_rules.NETWORK_CHECK_RULES["dns_tamper"]["category"] == "dns"
    assert privacy_rules.NETWORK_CHECK_RULES["dns_filtering_absent"]["category"] == "dns"
    assert privacy_rules.NETWORK_CHECK_RULES["captive_portal"]["category"] == "network"


def test_evaluate_network_critical_check_clamps_to_55():
    checks = [_check("dns_tamper", "critical")]
    result = privacy_rules.evaluate_network([], checks)
    # 100 − 30 = 70, but critical clamps to ≤55
    assert result["score"] == 55
    assert result["grade"] == "F"


def test_evaluate_network_device_aggregate_caps_at_40():
    # 20 devices with telnet open (−15 each) would be −300 uncapped;
    # top-10 = −150, capped at −40.
    device_deductions = []
    for hardware_id in range(20):
        device_deductions.extend(privacy_rules.evaluate_device(hardware_id, None, {23}))
    result = privacy_rules.evaluate_network(device_deductions, [])
    assert result["score"] == 60
    # all device findings are preserved in the snapshot deduction list
    assert len([d for d in result["deductions"] if d["hardware_id"] is not None]) == 20


def test_evaluate_network_device_aggregate_uses_ten_largest():
    # 12 small deductions of 3 points: top-10 = 30 (< 40 cap)
    device_deductions = [
        {
            "rule_id": "ftp_open",
            "title": "t",
            "points": 3,
            "severity": "warning",
            "remediation_id": "disable_ftp",
            "hardware_id": i,
        }
        for i in range(12)
    ]
    result = privacy_rules.evaluate_network(device_deductions, [])
    assert result["score"] == 70


def test_evaluate_network_combined_checks_and_devices():
    checks = [_check("captive_portal", "warning")]
    device_deductions = privacy_rules.evaluate_device(1, None, {23})
    result = privacy_rules.evaluate_network(device_deductions, checks)
    # 100 − 10 (check) − 15 (device) = 75
    assert result["score"] == 75
    assert result["grade"] == "C"
    assert result["checks"] == checks


# ── evaluate_network with ignores ────────────────────────────────────────────


def test_evaluate_network_no_ignores_matches_default_behavior():
    checks = [_check("captive_portal", "warning")]
    result = privacy_rules.evaluate_network([], checks, ignored=frozenset())
    assert result["score"] == 90
    assert result["ignored_deductions"] == []
    assert len(result["deductions"]) == 1


def test_evaluate_network_ignored_check_excluded_from_score_and_deductions():
    checks = [_check("captive_portal", "warning"), _check("dns_filtering_absent", "info")]
    result = privacy_rules.evaluate_network(
        [], checks, ignored=frozenset({("captive_portal", None)})
    )
    # only dns_filtering_absent (−5) counts now
    assert result["score"] == 95
    active_rule_ids = {d["rule_id"] for d in result["deductions"]}
    assert active_rule_ids == {"dns_filtering_absent"}
    ignored_rule_ids = {d["rule_id"] for d in result["ignored_deductions"]}
    assert ignored_rule_ids == {"captive_portal"}


def test_evaluate_network_ignored_device_finding_excluded():
    device_deductions = privacy_rules.evaluate_device(5, None, {23})  # telnet_open, −15
    result = privacy_rules.evaluate_network(
        device_deductions, [], ignored=frozenset({("telnet_open", 5)})
    )
    assert result["score"] == 100
    assert result["deductions"] == []
    assert len(result["ignored_deductions"]) == 1
    assert result["ignored_deductions"][0]["hardware_id"] == 5


def test_evaluate_network_ignore_key_is_specific_to_hardware_id():
    # ignoring telnet_open for device 99 should not suppress device 5's telnet_open
    device_deductions = privacy_rules.evaluate_device(5, None, {23})
    result = privacy_rules.evaluate_network(
        device_deductions, [], ignored=frozenset({("telnet_open", 99)})
    )
    assert result["score"] == 85
    assert len(result["deductions"]) == 1
    assert result["ignored_deductions"] == []
