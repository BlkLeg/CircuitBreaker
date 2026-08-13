#!/usr/bin/env python3
"""Generate the SEC-3 runtime endpoint inventory.

The script imports the production FastAPI app, walks HTTP and WebSocket routes,
and writes a deterministic JSON inventory used by
tests/test_endpoint_policy_inventory.py.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from importlib.resources import files
from pathlib import Path
from typing import Any

from fastapi.routing import APIRoute, APIWebSocketRoute
from fastapi.staticfiles import StaticFiles
from starlette.routing import Mount

_DUMMY_DB_URL = "postgresql://breaker:dummy@127.0.0.1:5432/circuitbreaker"
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_SRC_ROOT = _BACKEND_ROOT / "src"
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

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


def _load_public_policy() -> dict[tuple[str, tuple[str, ...], str], dict[str, Any]]:
    policy_path = files("app.security").joinpath("endpoint_policy.json")
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    return {
        (entry["transport"], tuple(sorted(entry["methods"])), entry["path"]): entry
        for entry in policy["routes"]
    }


def _load_static_surface_policy() -> dict[tuple[str, tuple[str, ...], str], dict[str, Any]]:
    policy_path = files("app.security").joinpath("endpoint_policy.json")
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    return {
        (entry["transport"], tuple(sorted(entry["methods"])), entry["path"]): entry
        for entry in policy.get("static_surfaces", [])
    }


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


def _route_app_class(route: Mount) -> str:
    return f"{route.app.__class__.__module__}.{route.app.__class__.__name__}"


def build_inventory() -> dict[str, Any]:
    os.environ.setdefault("CB_DB_URL", _DUMMY_DB_URL)

    # Import after CB_DB_URL is set.
    from app.main import app  # noqa: PLC0415

    public_policy = _load_public_policy()
    static_policy = _load_static_surface_policy()
    routes: list[dict[str, Any]] = []
    static_surfaces: list[dict[str, Any]] = []
    for route in app.routes:
        if not isinstance(route, (APIRoute, APIWebSocketRoute)):
            if isinstance(route, Mount) and isinstance(route.app, StaticFiles):
                path = f"{route.path.rstrip('/')}/{{path:path}}"
                key = ("http", ("GET", "HEAD"), path)
                entry = static_policy.get(key)
                static_surfaces.append(
                    {
                        "transport": "http",
                        "methods": ["GET", "HEAD"],
                        "path": path,
                        "name": route.name,
                        "mount_class": _route_app_class(route),
                        "auth_policy": entry["policy"] if entry else "unclassified",
                        "rbac_policy": "none" if entry else "unclassified",
                        "tenant_policy": "single-tenant-per-deployment; tenant selectors ignored",
                        "public_reason": entry["public_reason"] if entry else "",
                        "disclosure": entry["disclosure"] if entry else "",
                    }
                )
            continue
        else:
            transport, methods, path = _route_key(route)
            key = (transport, methods, path)
            public_entry = public_policy.get(key)
            calls = sorted(_dependency_calls(route.dependant))
            endpoint = getattr(route, "endpoint", None)
            routes.append(
                {
                    "transport": transport,
                    "methods": list(methods),
                    "path": path,
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

    routes.sort(key=lambda row: (row["transport"], row["path"], row["methods"], row["name"]))
    static_surfaces.sort(key=lambda row: (row["transport"], row["path"], row["methods"]))
    return {
        "version": 1,
        "generated_by": "apps/backend/scripts/generate_endpoint_inventory.py",
        "route_count": len(routes),
        "static_surface_count": len(static_surfaces),
        "routes": routes,
        "static_surfaces": static_surfaces,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write app/security/endpoint_inventory.json instead of printing to stdout.",
    )
    args = parser.parse_args()

    inventory = build_inventory()
    rendered = json.dumps(inventory, indent=2, sort_keys=True) + "\n"
    if args.write:
        out_path = _BACKEND_ROOT / "src/app/security/endpoint_inventory.json"
        out_path.write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
