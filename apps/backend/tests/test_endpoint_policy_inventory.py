"""SEC-3 endpoint policy reconciliation.

This test is intentionally structural: every externally reachable FastAPI route
must either carry an enforced auth dependency or be present in the reviewed
public/protocol allowlist.
"""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path
from typing import Any

from fastapi.routing import APIRoute, APIWebSocketRoute
from fastapi.staticfiles import StaticFiles
from starlette.routing import Mount, Route

from app.main import app

_REPO_ROOT = Path(__file__).resolve().parents[3]
_ENDPOINT_POLICY_REPO_PATH = "apps/backend/src/app/security/endpoint_policy.json"

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


def _static_file_mounts() -> list[Mount]:
    return [
        route
        for route in app.routes
        if isinstance(route, Mount) and isinstance(route.app, StaticFiles)
    ]


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


def _static_policy_by_route_key() -> dict[tuple[str, tuple[str, ...], str], dict[str, Any]]:
    return {
        (
            entry["transport"],
            tuple(sorted(entry["methods"])),
            entry["path"],
        ): entry
        for entry in _load_policy().get("static_surfaces", [])
    }


def _static_surface_key(route: Mount) -> tuple[str, tuple[str, ...], str]:
    return ("http", ("GET", "HEAD"), f"{route.path.rstrip('/')}/{{path:path}}")


def test_public_endpoint_policy_entries_are_well_formed():
    policy = _load_policy()
    seen: set[tuple[str, tuple[str, ...], str]] = set()

    assert policy["version"] == 1
    review = policy["security_review"]
    assert review["requirement"] == "SEC-07"
    assert review["owner"] == "security-owner"
    assert review["reviewer"] == "security-owner"
    assert review["codeowners_path"] == ".github/CODEOWNERS"
    assert review["codeowners_owner"] == "@blkleg"
    assert "security-owner review" in review["required_review"]

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

    seen_static: set[tuple[str, tuple[str, ...], str]] = set()
    for entry in policy.get("static_surfaces", []):
        key = (
            entry["transport"],
            tuple(sorted(entry["methods"])),
            entry["path"],
        )
        assert key not in seen_static, f"duplicate static surface policy entry: {key}"
        seen_static.add(key)
        assert entry["transport"] == "http"
        assert entry["methods"] == ["GET", "HEAD"]
        assert entry["path"].endswith("/{path:path}")
        assert entry["policy"]
        assert entry["public_reason"]
        assert entry["disclosure"]


def test_public_endpoint_allowlist_requires_codeowner_review():
    codeowners_path = _REPO_ROOT / ".github" / "CODEOWNERS"
    codeowners = codeowners_path.read_text(encoding="utf-8").splitlines()
    branch_protection = (_REPO_ROOT / ".github" / "branch-protection.md").read_text(
        encoding="utf-8"
    )

    matching_lines = [
        line
        for line in codeowners
        if line.strip()
        and not line.lstrip().startswith("#")
        and line.split()[0] == _ENDPOINT_POLICY_REPO_PATH
    ]
    assert matching_lines == [f"{_ENDPOINT_POLICY_REPO_PATH} @blkleg"], (
        "SEC-07 public endpoint policy must require security-owner CODEOWNERS review"
    )
    assert "Require review from Code Owners: \u2713 Enabled" in branch_protection
    assert "SEC-07 Public Route Review Gate" in branch_protection


def test_every_runtime_route_is_a_kind_this_gate_understands():
    """No route object may be silently skipped by the reconciliation below.

    The other tests in this file iterate `app.routes` and ignore anything that
    is not an APIRoute, an APIWebSocketRoute, or a StaticFiles mount. That
    `continue` is the gate's blind spot: a framework change or an `app.mount()`
    of a sub-application would drop routes out of the inventory without failing
    anything, leaving SEC-06's "every endpoint declares a policy" claim covering
    a fraction of the real surface. FastAPI 0.141 does exactly this — it stores
    an internal `_IncludedRouter` wrapper in `app.routes` instead of the flat
    routes — so this assertion is what turns that drift into a loud failure.
    """
    declared_framework = {
        ("http", tuple(sorted(entry["methods"])), entry["path"])
        for entry in _load_policy().get("framework_surfaces", [])
    }

    unrecognized: list[str] = []
    for route in app.routes:
        if isinstance(route, (APIRoute, APIWebSocketRoute)):
            continue
        if isinstance(route, Mount):
            if isinstance(route.app, StaticFiles):
                continue
            unrecognized.append(f"{type(route).__name__} mount at {route.path}")
            continue
        if isinstance(route, Route):
            key = ("http", tuple(sorted(route.methods or [])), route.path)
            if key in declared_framework:
                continue
            unrecognized.append(f"undeclared framework route {route.path}")
            continue
        unrecognized.append(f"{type(route).__module__}.{type(route).__name__}")

    assert not unrecognized, (
        "app.routes contains entries this gate cannot classify, so the endpoint "
        "inventory would silently under-report the real surface: " + ", ".join(sorted(unrecognized))
    )


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


def test_static_file_surfaces_reconcile_with_public_endpoint_policy():
    reviewed_static = _static_policy_by_route_key()
    runtime_static = _static_file_mounts()
    runtime_keys = {_static_surface_key(route) for route in runtime_static}

    stale_static = {
        key
        for key, entry in reviewed_static.items()
        if key not in runtime_keys and not entry.get("optional")
    }
    assert not stale_static, "static policy contains surfaces absent from runtime: " + ", ".join(
        f"{transport} {','.join(methods)} {path}"
        for transport, methods, path in sorted(stale_static)
    )

    unclassified = [
        _static_surface_key(route)
        for route in runtime_static
        if _static_surface_key(route) not in reviewed_static
    ]
    assert not unclassified, "static file mounts lack public policy entry: " + ", ".join(
        f"{transport} {','.join(methods)} {path}"
        for transport, methods, path in sorted(unclassified)
    )


def test_full_endpoint_inventory_matches_runtime_routes():
    public_policy = _public_policy_by_route_key()
    static_policy = _static_policy_by_route_key()
    runtime_routes = [
        route for route in app.routes if isinstance(route, (APIRoute, APIWebSocketRoute))
    ]
    runtime_static = _static_file_mounts()
    expected: list[dict[str, Any]] = []
    expected_static: list[dict[str, Any]] = []
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
    for route in runtime_static:
        key = _static_surface_key(route)
        entry = static_policy.get(key)
        expected_static.append(
            {
                "transport": "http",
                "methods": ["GET", "HEAD"],
                "path": key[2],
                "name": route.name,
                "mount_class": f"{route.app.__class__.__module__}.{route.app.__class__.__name__}",
                "auth_policy": entry["policy"] if entry else "unclassified",
                "rbac_policy": "none" if entry else "unclassified",
                "tenant_policy": "single-tenant-per-deployment; tenant selectors ignored",
                "public_reason": entry["public_reason"] if entry else "",
                "disclosure": entry["disclosure"] if entry else "",
            }
        )

    expected_static.sort(key=lambda row: (row["transport"], row["path"], row["methods"]))

    inventory = _load_inventory()
    assert inventory["version"] == 1
    assert inventory["route_count"] == len(expected)
    assert inventory["static_surface_count"] == len(expected_static)
    assert inventory["routes"] == expected
    assert inventory["static_surfaces"] == expected_static
