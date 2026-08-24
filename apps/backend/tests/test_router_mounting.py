"""Every APIRouter defined under app.api must actually be mounted.

INC-05 was a router — `external_nodes.relations_router` — that was defined,
decorated, and never passed to `include_router`. Nothing failed: the module
imported cleanly, the routes existed as Python objects, and only a request to
one of their paths revealed that they were not part of the application. Two
frontend call sites shipped against them.

This is the backend counterpart of `__tests__/nav-coverage.test.js`, which does
the same for frontend routes that no navigation surface reaches: an unreachable
surface should fail a test, not wait for an audit. Exemptions live in
`_UNMOUNTED_ROUTERS` and must state why.
"""

from __future__ import annotations

import importlib
import pkgutil

from fastapi import APIRouter
from fastapi.routing import APIRoute, APIWebSocketRoute

from app import api as api_package
from app.main import app as fastapi_app

# "app.api.<module>:<attribute>" -> reason it is deliberately not mounted.
_UNMOUNTED_ROUTERS: dict[str, str] = {}


def _api_routers() -> dict[str, APIRouter]:
    routers: dict[str, APIRouter] = {}
    for info in pkgutil.iter_modules(api_package.__path__):
        module = importlib.import_module(f"app.api.{info.name}")
        for attribute, value in vars(module).items():
            if isinstance(value, APIRouter):
                routers[f"app.api.{info.name}:{attribute}"] = value
    return routers


def _mounted_endpoints() -> set[object]:
    return {
        route.endpoint
        for route in fastapi_app.routes
        if isinstance(route, (APIRoute, APIWebSocketRoute))
    }


def test_every_api_router_is_mounted():
    mounted = _mounted_endpoints()
    unmounted: list[str] = []

    for name, router in _api_routers().items():
        if name in _UNMOUNTED_ROUTERS:
            continue
        missing = [
            route.path
            for route in router.routes
            if isinstance(route, (APIRoute, APIWebSocketRoute)) and route.endpoint not in mounted
        ]
        if missing:
            unmounted.append(f"{name} ({', '.join(sorted(missing))})")

    assert not unmounted, (
        "these routers are defined but never mounted, so every path they declare "
        "answers 404 at runtime: " + "; ".join(sorted(unmounted))
    )


def test_unmounted_router_exemptions_still_exist():
    """An exemption for a router that is gone hides the next real one."""
    routers = _api_routers()
    stale = sorted(name for name in _UNMOUNTED_ROUTERS if name not in routers)

    assert not stale, "_UNMOUNTED_ROUTERS names routers that no longer exist: " + ", ".join(stale)
