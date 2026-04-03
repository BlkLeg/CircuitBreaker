"""Unit tests for device_role_service — pure logic, no live DB."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.services.device_role_service import (
    get_hint_map,
    get_hostname_map,
    get_rank_map,
    get_valid_slugs,
)


def _make_role(slug: str, rank: int, hints: list, patterns: list, is_builtin: bool = True):
    r = MagicMock()
    r.slug = slug
    r.rank = rank
    r.device_type_hints = hints
    r.hostname_patterns = patterns
    r.is_builtin = is_builtin
    return r


def _mock_db(roles: list):
    """Return a mock db Session whose query(...).order_by(...).all() returns roles."""
    db = MagicMock()
    db.query.return_value.order_by.return_value.all.return_value = roles
    return db


def test_get_valid_slugs_returns_all_slugs():
    roles = [
        _make_role("router", 2, [], []),
        _make_role("phone", 5, ["mobile_device"], ["iphone"]),
    ]
    db = _mock_db(roles)
    slugs = get_valid_slugs.__wrapped__(db, 0)
    assert slugs == {"router", "phone"}


def test_get_rank_map_returns_slug_to_rank():
    roles = [
        _make_role("firewall", 1, [], []),
        _make_role("router", 2, [], []),
        _make_role("phone", 5, [], []),
    ]
    db = _mock_db(roles)
    rank_map = get_rank_map.__wrapped__(db, 0)
    assert rank_map == {"firewall": 1, "router": 2, "phone": 5}


def test_get_hint_map_maps_device_type_to_role():
    roles = [
        _make_role("phone", 5, ["mobile_device", "ios_device"], []),
        _make_role("ip_camera", 5, ["ip_camera"], []),
    ]
    db = _mock_db(roles)
    hint_map = get_hint_map.__wrapped__(db, 0)
    assert hint_map["mobile_device"] == "phone"
    assert hint_map["ios_device"] == "phone"
    assert hint_map["ip_camera"] == "ip_camera"


def test_get_hostname_map_sorted_longest_first():
    roles = [
        _make_role("phone", 5, [], ["iphone", "samsung-galaxy"]),
        _make_role("tablet", 5, [], ["ipad"]),
    ]
    db = _mock_db(roles)
    pairs = get_hostname_map.__wrapped__(db, 0)
    patterns = [p for p, _ in pairs]
    # longest-first: "samsung-galaxy" (14) before "iphone" (6) before "ipad" (4)
    assert patterns[0] == "samsung-galaxy"


def test_get_hint_map_first_role_wins_on_conflict():
    """If two roles claim the same device_type hint, the lower-rank one wins."""
    roles = [
        _make_role("router", 2, ["router"], []),
        _make_role("misc", 5, ["router"], []),
    ]
    db = _mock_db(roles)
    hint_map = get_hint_map.__wrapped__(db, 0)
    assert hint_map["router"] == "router"
