"""SEC-3 endpoint policy reconciliation.

This test is intentionally structural: every externally reachable FastAPI route
must either carry an enforced auth dependency or be present in the reviewed
public/protocol allowlist.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from importlib.resources import files
from pathlib import Path
from typing import Any

from fastapi.dependencies.utils import get_dependant
from fastapi.routing import APIRoute, APIWebSocketRoute
from fastapi.staticfiles import StaticFiles
from starlette.routing import Mount, Route

import app.main as main_module
from app.main import app

_REPO_ROOT = Path(__file__).resolve().parents[3]
_ENDPOINT_POLICY_REPO_PATH = "apps/backend/src/app/security/endpoint_policy.json"

# main.py registers exactly one of these, depending on whether a frontend build
# directory exists: the SPA fallback when it does, the landing page when it does not.
_SPA_FALLBACK_KEY = ("http", ("GET",), "/{full_path:path}")
_API_LANDING_KEY = ("http", ("GET",), "/")

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


def _inherited_dependency_calls(dependencies: Iterable[Any], path: str) -> frozenset[str]:
    """Qualified names contributed by router-level `dependencies=[...]`.

    Old FastAPI merged these into every route's own dependant when
    include_router() copied the route. Lazy inclusion leaves them on the
    wrapper, so the auth check and the inventory have to fold them back in or
    every router that enforces auth at mount time looks unauthenticated.
    """
    calls: set[str] = set()
    for dependency in dependencies:
        call = getattr(dependency, "dependency", None)
        if call is None:
            continue
        calls.update(_dependency_calls(get_dependant(path=path, call=call)))
    return frozenset(calls)


def _iter_runtime_routes(
    routes: Iterable[Any], prefix: str = "", inherited: frozenset[str] = frozenset()
) -> Iterator[tuple[str, APIRoute | APIWebSocketRoute, frozenset[str]]]:
    """Yield (full path, route) for every API route reachable from the app.

    FastAPI 0.138 stopped copying `include_router()` routes into `app.routes`.
    Each call now leaves a `fastapi.routing._IncludedRouter` holding the real
    router on `.original_router` and the mount prefix on
    `.include_context.prefix`, so the flat paths this gate reconciles against
    have to be rebuilt by walking the wrapper and concatenating prefixes. A
    router included twice under different prefixes is two real URL surfaces and
    is yielded twice, which is what the inventory must record.
    """
    for route in routes:
        if isinstance(route, (APIRoute, APIWebSocketRoute)):
            yield f"{prefix}{route.path}", route, inherited
            continue
        nested = getattr(route, "original_router", None)
        if nested is None:
            continue
        context = getattr(route, "include_context", None)
        nested_prefix = getattr(context, "prefix", "") or ""
        full_prefix = f"{prefix}{nested_prefix}"
        contributed = _inherited_dependency_calls(
            getattr(context, "dependencies", None) or [], full_prefix
        )
        yield from _iter_runtime_routes(nested.routes, full_prefix, inherited | contributed)


def _runtime_routes() -> list[tuple[str, APIRoute | APIWebSocketRoute, frozenset[str]]]:
    return list(_iter_runtime_routes(app.routes))


def _route_key(path: str, route: APIRoute | APIWebSocketRoute) -> tuple[str, tuple[str, ...], str]:
    if isinstance(route, APIRoute):
        return ("http", tuple(sorted(route.methods or [])), path)
    return ("websocket", ("WEBSOCKET",), path)


def _is_auth_enforced(
    route: APIRoute | APIWebSocketRoute, inherited: frozenset[str] = frozenset()
) -> bool:
    return bool((_dependency_calls(route.dependant) | inherited) & _AUTH_DEPENDENCIES)


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

    def classify(routes: Iterable[Any]) -> None:
        for route in routes:
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
            # A router wrapper is understood, but only because the traversal
            # above follows it — descend so nothing inside escapes classification.
            nested = getattr(route, "original_router", None)
            if nested is not None:
                classify(nested.routes)
                continue
            unrecognized.append(f"{type(route).__module__}.{type(route).__name__}")

    classify(app.routes)

    assert not unrecognized, (
        "app.routes contains entries this gate cannot classify, so the endpoint "
        "inventory would silently under-report the real surface: " + ", ".join(sorted(unrecognized))
    )


def test_runtime_routes_reconcile_with_public_endpoint_policy():
    reviewed_public = set(_public_policy_by_route_key())
    runtime_routes = _runtime_routes()
    runtime_keys = {_route_key(path, route) for path, route, _ in runtime_routes}

    stale_policy = reviewed_public - runtime_keys

    # main.py branches on `_frontend_dir`: with a build it serves the SPA
    # fallback, without one it serves a static landing page at "/". The two are
    # mutually exclusive, so the policy declares both and exactly one is live.
    # Excuse only the one that structurally cannot exist in this configuration
    # (CI runs this suite without building the frontend). The reverse direction
    # below is untouched: whichever route IS live still has to be declared, so
    # neither can go unreviewed.
    if main_module._frontend_dir is None:
        stale_policy = stale_policy - {_SPA_FALLBACK_KEY}
    else:
        stale_policy = stale_policy - {_API_LANDING_KEY}

    assert not stale_policy, "endpoint policy contains routes absent from runtime: " + ", ".join(
        f"{transport} {','.join(methods)} {path}"
        for transport, methods, path in sorted(stale_policy)
    )

    unclassified = [
        _route_key(path, route)
        for path, route, inherited in runtime_routes
        if not _is_auth_enforced(route, inherited)
        and _route_key(path, route) not in reviewed_public
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
    runtime_routes = _runtime_routes()
    runtime_static = _static_file_mounts()
    expected: list[dict[str, Any]] = []
    expected_static: list[dict[str, Any]] = []
    for path, route, inherited in runtime_routes:
        key = _route_key(path, route)
        public_entry = public_policy.get(key)
        calls = sorted(_dependency_calls(route.dependant) | inherited)
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


# (METHOD, path) -> why this write needs no role gate. Follows the exemption shape of
# `_UNMOUNTED_ROUTERS` (INC-05) and `UNLISTED_ROUTES` (INC-21): a reason is mandatory,
# and a stale entry fails its own test.
_SELF_SERVICE = (
    "self-service: the acting user is the only subject, so a role gate would lock a "
    "viewer out of their own account"
)
_FASTAPI_USERS_SUPERUSER = (
    "gated by fastapi-users' own current_user(superuser=True) dependency, which this "
    "gate cannot name because it is not one of ours"
)
_READ_SHAPED_POST = "POST-shaped read: validates a candidate IP and writes nothing"

_UNGATED_WRITE_EXEMPTIONS: dict[tuple[str, str], str] = {
    ("DELETE", "/api/v1/auth/me"): _SELF_SERVICE,
    ("PUT", "/api/v1/auth/me/avatar"): _SELF_SERVICE,
    ("POST", "/api/v1/auth/mfa/setup"): _SELF_SERVICE,
    ("POST", "/api/v1/auth/mfa/activate"): _SELF_SERVICE,
    ("POST", "/api/v1/auth/mfa/disable"): _SELF_SERVICE,
    ("POST", "/api/v1/auth/mfa/backup-codes/regenerate"): _SELF_SERVICE,
    ("PATCH", "/api/v1/users/me"): _SELF_SERVICE,
    ("PATCH", "/api/v1/users/me/password"): _SELF_SERVICE,
    ("DELETE", "/api/v1/users/me/sessions"): _SELF_SERVICE,
    ("DELETE", "/api/v1/users/me/sessions/{session_id}"): _SELF_SERVICE,
    ("PATCH", "/api/v1/users/{id}"): _FASTAPI_USERS_SUPERUSER,
    ("DELETE", "/api/v1/users/{id}"): _FASTAPI_USERS_SUPERUSER,
    ("POST", "/api/v1/ip-check"): _READ_SHAPED_POST,
    ("POST", "/api/v1/services/check-ip"): _READ_SHAPED_POST,
    # The legacy tenant surface answers 410 Gone for every method and touches
    # nothing; it stays mounted so stale clients get an explicit answer (ADR 0003).
    ("POST", "/api/v1/tenants"): "410 Gone for every method; no behavior to authorize",
    ("PUT", "/api/v1/tenants"): "410 Gone for every method; no behavior to authorize",
    ("PATCH", "/api/v1/tenants"): "410 Gone for every method; no behavior to authorize",
    ("DELETE", "/api/v1/tenants"): "410 Gone for every method; no behavior to authorize",
    ("POST", "/api/v1/tenants/{legacy_path:path}"): (
        "410 Gone for every method; no behavior to authorize"
    ),
    ("PUT", "/api/v1/tenants/{legacy_path:path}"): (
        "410 Gone for every method; no behavior to authorize"
    ),
    ("PATCH", "/api/v1/tenants/{legacy_path:path}"): (
        "410 Gone for every method; no behavior to authorize"
    ),
    ("DELETE", "/api/v1/tenants/{legacy_path:path}"): (
        "410 Gone for every method; no behavior to authorize"
    ),
}

_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _http_routes() -> Iterator[tuple[str, APIRoute, frozenset[str]]]:
    for path, route, inherited in _runtime_routes():
        if isinstance(route, APIRoute):
            yield path, route, inherited


def _has_write_gate(calls: set[str]) -> bool:
    """True when a write route names a role, a scope, or the write-auth dependency.

    The one definition of "this write is authorized by something", shared by the
    test that demands it and the test that retires exemptions once it appears.
    """
    return bool(calls & _READ_DEPENDENCIES) or "app.core.security.require_write_auth" in calls


def test_no_write_route_is_merely_authenticated():
    """A write reachable by any authenticated user is an authorization decision nobody made.

    `POST /api/v1/privacy-findings/ignore` — suppressing a security finding — sat at
    `authenticated-session` and the inventory recorded it faithfully, because the
    inventory is generated from the code it describes.
    """
    public = _public_policy_by_route_key()
    offenders: list[str] = []

    for path, route, inherited in _http_routes():
        methods = set(route.methods or []) & _WRITE_METHODS
        if not methods:
            continue
        if _route_key(path, route) in public:
            continue
        calls = _dependency_calls(route.dependant) | inherited
        if _has_write_gate(calls):
            continue
        for method in sorted(methods):
            if (method, path) in _UNGATED_WRITE_EXEMPTIONS:
                continue
            offenders.append(f"{method} {path}")

    assert not offenders, (
        "these write routes declare no role or write scope, so any authenticated user "
        "may call them. Add a require_role/require_scope dependency, or add an entry to "
        "_UNGATED_WRITE_EXEMPTIONS with a reason: " + ", ".join(sorted(offenders))
    )


def test_ungated_write_exemptions_still_exist():
    """An exemption rots two ways, and both hide the next real ungated write.

    The route disappears, and the entry documents nothing. Or the route acquires a
    require_role/require_scope/require_write_auth gate and the entry keeps asserting
    the write is ungated when the code says otherwise — a false record of the ungated
    surface that would silently re-excuse the route if the gate were ever removed.
    """
    gates: dict[tuple[str, str], set[str]] = {}
    for path, route, inherited in _http_routes():
        calls = _dependency_calls(route.dependant) | inherited
        for method in route.methods or []:
            gates[(method, path)] = calls

    stale = sorted(
        f"{method} {path}"
        for (method, path) in _UNGATED_WRITE_EXEMPTIONS
        if (method, path) not in gates
    )
    assert not stale, "_UNGATED_WRITE_EXEMPTIONS names routes that no longer exist: " + ", ".join(
        stale
    )

    now_gated = sorted(
        f"{method} {path}"
        for (method, path) in _UNGATED_WRITE_EXEMPTIONS
        if _has_write_gate(gates[(method, path)])
    )
    assert not now_gated, (
        "_UNGATED_WRITE_EXEMPTIONS excuses writes that now declare a role or write "
        "scope, so the exemption no longer describes the code. Delete these entries: "
        + ", ".join(now_gated)
    )
