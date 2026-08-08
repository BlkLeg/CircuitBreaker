"""Unit tests for the scan-type vocabulary (Slice 4, D-6).

The API-level contract lives in `tests/test_discovery.py`; these pin the
helper's own semantics, which the schemas and `create_scan_job` share.
"""

import pytest

from app.core.discovery_scan_types import (
    AGENT_SCAN_TYPES,
    ALL_SCAN_TYPES,
    SERVER_SCAN_TYPES,
    validate_scan_types,
)


def test_vocabularies_are_disjoint_and_union_to_all():
    assert SERVER_SCAN_TYPES & AGENT_SCAN_TYPES == frozenset()
    assert ALL_SCAN_TYPES == SERVER_SCAN_TYPES | AGENT_SCAN_TYPES
    assert AGENT_SCAN_TYPES == frozenset({"agent_connect"})


@pytest.mark.parametrize("scan_type", sorted(SERVER_SCAN_TYPES))
def test_every_server_scan_type_is_accepted_for_the_server(scan_type):
    """The vocabulary must admit every type the server executor already runs."""
    assert validate_scan_types([scan_type], scan_agent_id=None) == [scan_type]


def test_agent_scan_type_is_accepted_for_an_agent():
    assert validate_scan_types(["agent_connect"], scan_agent_id=7) == ["agent_connect"]


def test_server_scan_type_is_rejected_for_an_agent():
    with pytest.raises(ValueError, match="nmap"):
        validate_scan_types(["nmap"], scan_agent_id=7)


def test_agent_scan_type_is_rejected_without_an_agent():
    with pytest.raises(ValueError, match="agent_connect"):
        validate_scan_types(["agent_connect"], scan_agent_id=None)


def test_unknown_scan_type_is_rejected():
    with pytest.raises(ValueError, match="bogus"):
        validate_scan_types(["nmap", "bogus"], scan_agent_id=None)


def test_empty_list_is_allowed_for_the_server():
    """Server jobs have always accepted no scan types; the vocabulary keeps that."""
    assert validate_scan_types([], scan_agent_id=None) == []


def test_empty_list_is_rejected_for_an_agent():
    with pytest.raises(ValueError, match="at least one"):
        validate_scan_types([], scan_agent_id=7)


def test_none_is_allowed_for_the_server():
    assert validate_scan_types(None, scan_agent_id=None) == []


def test_duplicates_are_collapsed_in_order():
    assert validate_scan_types(["docker", "nmap", "docker"], scan_agent_id=None) == [
        "docker",
        "nmap",
    ]


def test_non_string_entry_is_rejected():
    with pytest.raises(ValueError):
        validate_scan_types([1], scan_agent_id=None)  # type: ignore[list-item]
