"""Unit coverage for public AppError context projection."""

from __future__ import annotations

from app.core.errors import ConflictError


def test_ip_conflict_context_includes_sanitized_entity_name() -> None:
    err = ConflictError(
        "This IP address conflicts with an existing asset.",
        error_code="ip_conflict",
        fields={"ip_address": "Choose an available address."},
        context={
            "conflicts": [
                {
                    "entity_type": "hardware",
                    "entity_id": 7,
                    "entity_name": "nas-01",
                    "conflicting_ip": "192.168.10.20",
                    "conflicting_port": None,
                    "protocol": None,
                    "secret": "must-not-leak",
                }
            ],
            "extra": "drop-me",
        },
    )
    assert err.context is not None
    assert err.context == {
        "conflicts": [
            {
                "entity_type": "hardware",
                "entity_id": 7,
                "entity_name": "nas-01",
                "conflicting_ip": "192.168.10.20",
                "conflicting_port": None,
                "protocol": None,
            }
        ]
    }


def test_ip_conflict_entity_name_is_truncated() -> None:
    long_name = "x" * 500
    err = ConflictError(
        "conflict",
        error_code="ip_conflict",
        context={
            "conflicts": [{"entity_type": "hardware", "entity_id": 1, "entity_name": long_name}]
        },
    )
    assert err.context is not None
    assert len(err.context["conflicts"][0]["entity_name"]) == 200


def test_non_ip_conflict_drops_context() -> None:
    err = ConflictError(
        "busy",
        error_code="transfer_busy",
        context={"conflicts": [{"entity_name": "nope"}]},
    )
    assert err.context is None
