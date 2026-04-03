"""Unit tests for role auto-assignment logic in discovery_import_service."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.services.discovery_import_service import _resolve_role_for_result


def _result(device_type: str | None, device_confidence: int | None, hostname: str | None):
    r = MagicMock()
    r.device_type = device_type
    r.device_confidence = device_confidence
    r.hostname = hostname
    return r


def test_high_confidence_device_type_match_assigns_role():
    """device_type match + confidence >= 70 -> auto-assign role slug."""
    result = _result("ip_camera", 85, None)
    hint_map = {"ip_camera": "ip_camera"}
    hostname_pairs = []
    role, suggestion = _resolve_role_for_result(result, hint_map, hostname_pairs)
    assert role == "ip_camera"
    assert suggestion is None


def test_low_confidence_device_type_match_sets_suggestion_only():
    """device_type match + confidence < 70 -> role=None, suggestion set."""
    result = _result("ip_camera", 50, None)
    hint_map = {"ip_camera": "ip_camera"}
    hostname_pairs = []
    role, suggestion = _resolve_role_for_result(result, hint_map, hostname_pairs)
    assert role is None
    assert suggestion == "ip_camera"


def test_hostname_pattern_match_assigns_phone_at_65():
    """Hostname pattern match + confidence >= 65 -> auto-assign phone role."""
    result = _result(None, 70, "John-iPhone")
    hint_map = {}
    hostname_pairs = [("iphone", "phone"), ("ipad", "tablet")]
    role, suggestion = _resolve_role_for_result(result, hint_map, hostname_pairs)
    assert role == "phone"
    assert suggestion is None


def test_hostname_match_below_65_sets_suggestion():
    """Hostname match + confidence < 65 -> no auto-assign, suggestion set."""
    result = _result(None, 40, "Samsung-Galaxy")
    hint_map = {}
    hostname_pairs = [("samsung", "phone"), ("galaxy", "phone")]
    role, suggestion = _resolve_role_for_result(result, hint_map, hostname_pairs)
    assert role is None
    assert suggestion == "phone"


def test_no_match_returns_none_none():
    """No match -> (None, None)."""
    result = _result("unknown_type", 90, "desktop-001")
    hint_map = {"ip_camera": "ip_camera"}
    hostname_pairs = [("iphone", "phone")]
    role, suggestion = _resolve_role_for_result(result, hint_map, hostname_pairs)
    assert role is None
    assert suggestion is None
