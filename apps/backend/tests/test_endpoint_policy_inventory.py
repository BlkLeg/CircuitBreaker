"""SEC-3 endpoint policy reconciliation.

This test is intentionally structural: every externally reachable FastAPI route
must either carry an enforced auth dependency or be present in the reviewed
public/protocol allowlist.
"""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any

from fastapi.routing import APIRoute, APIWebSocketRoute

from app.main import app

_AUTH_DEPENDENCIES = frozenset(
    {
        "app.core.security.require_auth_always",
        "app.core.security.require_write_auth",
        "app.core.rbac.require_role.<locals>._dep",
        "app.core.rbac.require_scope.<locals>._dep",
    }
)
_READ_DEPENDENCIES = frozenset(
    {
        "app.core.rbac.require_role.<locals>._dep",
        "app.core.rbac.require_scope.<locals>._dep",
    }
)


def _dependency_calls(dependant: Any) -> set[str]:
    call = getattr(dependant, "call", None)
    module = getattr(call, "__module__", None)
    qualname = getattr(call, "__qualname__", getattr(call, "__name__", None))
    calls = {f"{module}.{qualname}"}
    for child in dependant.dependencies:
        calls.update(_dependency_calls(child))
    return calls


def _route_key(route: APIRoute | APIWebSocketRoute) -> tuple[str, tuple[str, ...], str]:
    if isinstance(route, APIRoute):
        return ("http", tuple(sorted(route.methods or [])), route.path)
    return ("websocket", ("WEBSOCKET",), route.path)


def _is_auth_enforced(route: APIRoute | APIWebSocketRoute) -> bool:
    return bool(_dependency_calls(route.dependant) & _AUTH_DEPENDENCIES)


def _load_policy() -> dict[str, Any]:
    policy_path = files("app.security").joinpath("endpoint_policy.json")
    return json.loads(policy_path.read_text(encoding="utf-8"))


def _load_inventory() -> dict[str, Any]:
    inventory_path = files("app.security").joinpath("endpoint_inventory.json")
    return json.loads(inventory_path.read_text(encoding="utf-8"))


def _rbac_policy(calls: set[str], public_entry: dict[str, Any] | None) -> str:
    if public_entry:
        return "none"
    if "app.core.security.require_write_auth" in calls:
        return "editor-or-admin-or-write-scope"
    if calls & _READ_DEPENDENCIES:
        return "declared-role-or-scope"
    if "app.core.security.require_auth_always" in calls:
        return "authenticated-session"
    return "unclassified"


def _auth_policy(calls: set[str], public_entry: dict[str, Any] | None) -> str:
    if public_entry:
        return public_entry["policy"]
    if calls & _AUTH_DEPENDENCIES:
        return "authenticated"
    return "unclassified"


def _public_policy_by_route_key() -> dict[tuple[str, tuple[str, ...], str], dict[str, Any]]:
    return {
        (
            entry["transport"],
            tuple(sorted(entry["methods"])),
            entry["path"],
        ): entry
        for entry in _load_policy()["routes"]
    }


def test_public_endpoint_policy_entries_are_well_formed():
    policy = _load_policy()
    seen: set[tuple[str, tuple[str, ...], str]] = set()

    assert policy["version"] == 1
    for entry in policy["routes"]:
        key = (
            entry["transport"],
            tuple(sorted(entry["methods"])),
            entry["path"],
        )
        assert key not in seen, f"duplicate endpoint policy entry: {key}"
        seen.add(key)
        assert entry["transport"] in {"http", "websocket"}
        assert entry["policy"]
        assert entry["public_reason"]
        assert entry["disclosure"]
        if entry["transport"] == "websocket":
            assert entry["methods"] == ["WEBSOCKET"]


def test_runtime_routes_reconcile_with_public_endpoint_policy():
    reviewed_public = set(_public_policy_by_route_key())
    runtime_routes = [
        route for route in app.routes if isinstance(route, (APIRoute, APIWebSocketRoute))
    ]
    runtime_keys = {_route_key(route) for route in runtime_routes}

    stale_policy = reviewed_public - runtime_keys
    assert not stale_policy, "endpoint policy contains routes absent from runtime: " + ", ".join(
        f"{transport} {','.join(methods)} {path}"
        for transport, methods, path in sorted(stale_policy)
    )

    unclassified = [
        _route_key(route)
        for route in runtime_routes
        if not _is_auth_enforced(route) and _route_key(route) not in reviewed_public
    ]
    assert not unclassified, "runtime routes lack auth dependency and policy entry: " + ", ".join(
        f"{transport} {','.join(methods)} {path}"
        for transport, methods, path in sorted(unclassified)
    )


def test_full_endpoint_inventory_matches_runtime_routes():
    public_policy = _public_policy_by_route_key()
    runtime_routes = [
        route for route in app.routes if isinstance(route, (APIRoute, APIWebSocketRoute))
    ]
    expected: list[dict[str, Any]] = []
    for route in runtime_routes:
        key = _route_key(route)
        public_entry = public_policy.get(key)
        calls = sorted(_dependency_calls(route.dependant))
        endpoint = getattr(route, "endpoint", None)
        expected.append(
            {
                "transport": key[0],
                "methods": list(key[1]),
                "path": key[2],
                "name": route.name,
                "endpoint_module": getattr(endpoint, "__module__", None),
                "endpoint_name": getattr(endpoint, "__qualname__", None),
                "auth_policy": _auth_policy(set(calls), public_entry),
                "rbac_policy": _rbac_policy(set(calls), public_entry),
                "tenant_policy": "single-tenant-per-deployment; tenant selectors ignored",
                "disclosure": (
                    public_entry["disclosure"]
                    if public_entry
                    else "authenticated response; see route response model/schema"
                ),
                "dependency_calls": calls,
            }
        )

    expected.sort(key=lambda row: (row["transport"], row["path"], row["methods"], row["name"]))

    inventory = _load_inventory()
    assert inventory["version"] == 1
    assert inventory["route_count"] == len(expected)
    assert inventory["routes"] == expected
