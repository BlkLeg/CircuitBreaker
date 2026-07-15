"""Pure privacy-scoring ruleset — no I/O, no DB, no network.

Deduction shape (used verbatim in DB, API, and frontend):
    {"rule_id", "title", "points", "severity", "remediation_id", "hardware_id"}
"""

from __future__ import annotations

import math

from app.core.constants import (
    PRIVACY_CRITICAL_CHECK_CEILING,
    PRIVACY_DEVICE_AGGREGATE_CAP,
    PRIVACY_DEVICE_AGGREGATE_TOP_N,
    PRIVACY_FALLBACK_GRADE,
    PRIVACY_GATEWAY_POINTS_MULTIPLIER,
    PRIVACY_GRADE_BANDS,
    PRIVACY_MAX_SCORE,
    PRIVACY_MIN_SCORE,
)

GATEWAY_ROLES = frozenset({"router", "firewall", "gateway"})

_SEVERITY_RANK = {"info": 0, "warning": 1, "critical": 2}
_SEVERITY_ESCALATION = {"info": "warning", "warning": "critical", "critical": "critical"}

# Check statuses that mean the finding fired (vs ok/unknown which never deduct)
_FIRING_STATUSES = frozenset({"info", "warning", "critical"})

DEVICE_RULES: dict[str, dict] = {
    "telnet_open": {
        "title": "Telnet service exposed",
        "points": 15,
        "severity": "critical",
        "remediation_id": "disable_telnet",
        "ports": frozenset({23}),
    },
    "ftp_open": {
        "title": "FTP service exposed",
        "points": 8,
        "severity": "warning",
        "remediation_id": "disable_ftp",
        "ports": frozenset({21}),
    },
    "legacy_smb_netbios": {
        "title": "Legacy SMB/NetBIOS services exposed",
        "points": 8,
        "severity": "warning",
        "remediation_id": "disable_legacy_smb",
        "ports": frozenset({137, 138, 139}),
    },
    "upnp_exposed": {
        "title": "UPnP service exposed",
        "points": 10,
        "severity": "warning",
        "remediation_id": "disable_upnp",
        "ports": frozenset({1900, 5000}),
    },
}

NETWORK_CHECK_RULES: dict[str, dict] = {
    "captive_portal": {
        "title": "Captive portal or connectivity interference detected",
        "points": 10,
        "severity": "warning",
        "remediation_id": "captive_portal_info",
    },
    "dns_tamper": {
        "title": "DNS responses appear tampered with",
        "points": 30,
        "severity": "critical",
        "remediation_id": "dns_tamper_response",
    },
    "dns_filtering_absent": {
        "title": "No DNS-level malware filtering on this network",
        "points": 5,
        "severity": "info",
        "remediation_id": "setup_dns_filtering",
    },
}


def _build_deduction(
    rule_id: str, rule: dict, points: int, severity: str, hardware_id: int | None
) -> dict:
    return {
        "rule_id": rule_id,
        "title": rule["title"],
        "points": points,
        "severity": severity,
        "remediation_id": rule["remediation_id"],
        "hardware_id": hardware_id,
    }


def evaluate_device(hardware_id: int | None, role: str | None, open_ports: set[int]) -> list[dict]:
    """Evaluate one device's scan-proven open ports against the device rules."""
    is_gateway = (role or "").lower() in GATEWAY_ROLES
    deductions = []
    for rule_id, rule in DEVICE_RULES.items():
        if not (rule["ports"] & open_ports):
            continue
        points, severity = rule["points"], rule["severity"]
        if is_gateway:
            points = math.ceil(points * PRIVACY_GATEWAY_POINTS_MULTIPLIER)
            severity = _SEVERITY_ESCALATION[severity]
        deductions.append(_build_deduction(rule_id, rule, points, severity, hardware_id))
    return deductions


def score_device(deductions: list[dict]) -> int:
    """Device score: 100 minus its deduction points, clamped to 0–100."""
    raw_score = PRIVACY_MAX_SCORE - sum(d["points"] for d in deductions)
    return max(PRIVACY_MIN_SCORE, min(PRIVACY_MAX_SCORE, raw_score))


def badge_severity(deductions: list[dict]) -> str | None:
    """A device's badge severity = max severity among its deductions."""
    if not deductions:
        return None
    return max((d["severity"] for d in deductions), key=lambda s: _SEVERITY_RANK.get(s, -1))


def grade_for(score: int) -> str:
    for grade, threshold in PRIVACY_GRADE_BANDS:
        if score >= threshold:
            return grade
    return PRIVACY_FALLBACK_GRADE


def _device_aggregate_points(device_deductions: list[dict]) -> int:
    largest = sorted((d["points"] for d in device_deductions), reverse=True)
    top_sum = sum(largest[:PRIVACY_DEVICE_AGGREGATE_TOP_N])
    return min(PRIVACY_DEVICE_AGGREGATE_CAP, top_sum)


def evaluate_network(device_deductions: list[dict], check_results: list[dict]) -> dict:
    """Combine device deductions and network-check results into one network score.

    Returns {"score", "grade", "deductions", "checks"} — deductions carry every
    device finding (for the flagged-devices UI) plus one entry per fired check;
    the score math caps device volume so it alone cannot zero the score.
    """
    check_deductions = []
    has_critical_check = False
    for check in check_results:
        if check["status"] == "critical":
            has_critical_check = True
        rule = NETWORK_CHECK_RULES.get(check["check_id"])
        if rule is None or check["status"] not in _FIRING_STATUSES:
            continue
        check_deductions.append(
            _build_deduction(check["check_id"], rule, rule["points"], rule["severity"], None)
        )

    check_points = sum(d["points"] for d in check_deductions)
    score = PRIVACY_MAX_SCORE - check_points - _device_aggregate_points(device_deductions)
    if has_critical_check:
        score = min(score, PRIVACY_CRITICAL_CHECK_CEILING)
    score = max(PRIVACY_MIN_SCORE, min(PRIVACY_MAX_SCORE, score))

    return {
        "score": score,
        "grade": grade_for(score),
        "deductions": check_deductions + list(device_deductions),
        "checks": list(check_results),
    }
