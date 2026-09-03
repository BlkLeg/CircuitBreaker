"""Fast static ratchets for Phase 1 production promises."""

from __future__ import annotations

import ast
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "apps/backend/src/app"
sys.path.insert(0, str(ROOT / "apps/backend/src"))

#: Modules that can open an outbound connection. Membership is by *module*, not
#: by (module, verb): the previous version listed ten specific pairs, so
#: `httpx.put`, `httpx.stream`, `httpx.delete` and `requests.put` all sailed
#: past a gate whose entire job is to keep egress at one choke point.
EGRESS_MODULES = {"httpx", "requests", "aiohttp", "urllib3", "boto3"}

#: The names on those modules that actually open a connection. Matching on the
#: module alone flagged `httpx.HTTPError`, `httpx.URL` and
#: `urllib3.disable_warnings`, none of which touch the network — a gate that
#: cries wolf gets an allowlist bolted on, and then it is back where it started.
NETWORK_ATTRS = {
    "Client",
    "AsyncClient",
    "Session",
    "ClientSession",
    "PoolManager",
    "client",
    "resource",
    "connect",
    "get",
    "post",
    "put",
    "patch",
    "delete",
    "head",
    "options",
    "request",
    "stream",
    "send",
    "urlopen",
}

#: `urllib.request.urlopen(...)` and friends: a dotted owner rather than a bare
#: Name, which the old `isinstance(owner, ast.Name)` test skipped silently.
EGRESS_DOTTED_OWNERS = {"urllib.request", "urllib3.util"}


def _python_files() -> list[Path]:
    return sorted(APP.rglob("*.py"))


def _dotted(node: ast.AST) -> str | None:
    """Render `a.b.c` from an attribute chain, or None if it is not one."""
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    parts.append(current.id)
    return ".".join(reversed(parts))


def _egress_module_aliases(tree: ast.AST) -> dict[str, str]:
    """Local name -> egress module, covering `import httpx as hx`.

    An alias defeated the old check completely: it compared the owner's local
    name against the literal module name, so two extra characters at the import
    site made a call invisible.
    """
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in EGRESS_MODULES:
                    aliases[alias.asname or alias.name] = root
    return aliases


def _imported_egress_callables(tree: ast.AST) -> dict[str, str]:
    """Local name -> `module.attr`, covering `from httpx import Client as C`."""
    found: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or not node.module:
            continue
        root = node.module.split(".")[0]
        if root not in EGRESS_MODULES:
            continue
        for alias in node.names:
            if alias.name in NETWORK_ATTRS:
                found[alias.asname or alias.name] = f"{root}.{alias.name}"
    return found


def test_http_clients_are_only_constructed_by_the_egress_layer() -> None:
    """One choke point for outbound HTTP (B2), enforced against the forms that
    actually occur rather than the one that was written first.

    The original matched `<Name>.<verb>(...)` against ten hard-coded pairs.
    Probed against thirteen realistic spellings, twelve passed: aliased imports,
    from-imports, every verb outside the ten, `aiohttp` (absent entirely),
    `urlopen`, and `boto3.resource`. A gate that catches only the style already
    migrated does not keep B2 true; it just stops it being re-broken in the one
    way nobody was going to.
    """
    violations: list[str] = []
    for path in _python_files():
        if path == APP / "core/egress.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        aliases = _egress_module_aliases(tree)
        imported = _imported_egress_callables(tree)

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            location = f"{path.relative_to(ROOT)}:{node.lineno}"

            if isinstance(node.func, ast.Name):
                # `Client()` / `urlopen()` reached through a from-import.
                if node.func.id in imported:
                    violations.append(f"{location} calls {imported[node.func.id]}")
                continue

            if not isinstance(node.func, ast.Attribute):
                continue
            owner = _dotted(node.func.value)
            if owner is None:
                continue
            known_owner = (
                owner in aliases or owner in EGRESS_MODULES or owner in EGRESS_DOTTED_OWNERS
            )
            if known_owner and node.func.attr in NETWORK_ATTRS:
                violations.append(f"{location} calls {owner}.{node.func.attr}")

    assert not violations, (
        "outbound HTTP is constructed outside app.core.egress:\n"
        + "\n".join(violations)
        + "\n\nCB_AIRGAP is enforced in core/egress.py and nowhere else, so a client built "
        "here is a promise the product cannot keep. Route it through the helpers there."
    )


def test_full_session_token_is_only_minted_inside_issue_session() -> None:
    service = APP / "services/auth_service.py"
    tree = ast.parse(service.read_text(encoding="utf-8"), filename=str(service))
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    violations: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id != "create_token":
            continue
        current: ast.AST | None = node
        while current is not None and not isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            current = parents.get(current)
        if not isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)) or current.name != "issue_session":
            violations.append(node.lineno)
    assert not violations, f"auth_service creates a full session outside issue_session: {violations}"

    # Outside auth_service, create_token is reserved for the documented
    # user_id=0 service-account sentinel. Challenge credentials use jwt.encode
    # with their own audience and are not full sessions.
    external: list[str] = []
    for path in _python_files():
        if path in {service, APP / "core/security.py"}:
            continue
        other = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(other):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            if node.func.id != "create_token":
                continue
            if not node.args or not isinstance(node.args[0], ast.Constant) or node.args[0].value != 0:
                external.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert not external, "full sessions bypass issue_session:\n" + "\n".join(external)


def test_retired_fastapi_users_login_router_is_not_mounted() -> None:
    main = (APP / "main.py").read_text(encoding="utf-8")
    auth = (APP / "api/auth.py").read_text(encoding="utf-8")
    assert "auth_jwt_router" not in main
    assert "get_auth_router" not in auth


def test_worker_inventory_is_present_in_every_runtime_contract() -> None:
    workers = {
        "discovery",
        "notification",
        "telemetry",
        "integration",
        "monitor_scheduler",
        "monitor_poll",
        "monitor_probe_dispatch",
    }
    sources = {
        "dispatch": APP / "workers/main.py",
        "mono": ROOT / "docker/supervisord.mono.conf",
        "native target": ROOT / "deploy/systemd/circuitbreaker.target",
        "native cli": ROOT / "deploy/cli/cb",
        "package api unit": ROOT / "packaging/circuit-breaker.service",
        "package cli": ROOT / "cb",
    }
    for label, path in sources.items():
        text = path.read_text(encoding="utf-8")
        missing = sorted(worker for worker in workers if worker not in text)
        assert not missing, f"{label} worker inventory is missing {missing}"


def test_airgap_rejects_public_http_before_dns(monkeypatch) -> None:
    from app.core import egress
    from app.core.url_validation import WEBHOOK_POLICY, validate_outbound_url

    monkeypatch.setenv("CB_AIRGAP", "true")
    egress.invalidate_airgap_cache()
    called = False

    def forbidden_dns(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("DNS must not run for public HTTP in air-gap mode")

    monkeypatch.setattr(socket, "getaddrinfo", forbidden_dns)
    try:
        validate_outbound_url("https://example.com/feed", WEBHOOK_POLICY)
    except ConnectionError as exc:
        assert "Public HTTP" in str(exc)
    else:
        raise AssertionError("public HTTP was allowed in air-gap mode")
    assert called is False


def test_airgap_allows_private_lan_but_rejects_mixed_dns(monkeypatch) -> None:
    from app.core import egress
    from app.core.url_validation import MONITOR_TARGET_POLICY, validate_outbound_url

    monkeypatch.setenv("CB_AIRGAP", "true")
    egress.invalidate_airgap_cache()

    def private_dns(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.2.3.4", 8080))]

    monkeypatch.setattr(socket, "getaddrinfo", private_dns)
    validated = validate_outbound_url("http://monitor.lan:8080", MONITOR_TARGET_POLICY)
    assert validated.addresses == ("10.2.3.4",)

    def mixed_dns(*args, **kwargs):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.2.3.4", 8080)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 8080)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", mixed_dns)
    try:
        validate_outbound_url("http://monitor.lan:8080", MONITOR_TARGET_POLICY)
    except ConnectionError as exc:
        assert "mixed" in str(exc)
    else:
        raise AssertionError("mixed public/private DNS answer was allowed")


#: The one module allowed to mint a token carrying the session audience.
#: `core/security.py` owns `create_token`; `services/auth_service.py` owns
#: `issue_session`, which is the only thing permitted to call it for a user.
_SESSION_MINTING_ALLOWLIST = {"core/security.py"}

#: `core/security.py:319`. A token carrying this audience is accepted by
#: `resolve_optional_user_id_sync` as a full session.
_SESSION_AUDIENCE_LITERAL = "fastapi-users:auth"


def _aliases_of(tree: ast.AST, target: str) -> set[str]:
    """Every local name bound to *target* by an import in this module."""
    names = {target}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == target and alias.asname:
                    names.add(alias.asname)
    return names


def test_no_token_carries_the_session_audience_outside_the_issuer() -> None:
    """B4's actual defect class, which the ratchet above cannot see.

    `test_full_session_token_is_only_minted_inside_issue_session` matches bare
    `ast.Name` calls to `create_token`. Three ways past it, all realistic:

      * `security.create_token(...)` — an attribute call, not a Name;
      * `from ... import create_token as _ct` — a different local name;
      * `jwt.encode({..., "aud": SESSION_AUDIENCE, ...})` — no `create_token`
        anywhere, and this is the one that matters. `SESSION_AUDIENCE` is a
        module constant, `resolve_optional_user_id_sync` accepts *any*
        signature-valid JWT carrying it plus a `user_id`, and
        `is_session_revoked` returns True only when a revoked row exists — so a
        token minted this way is bearer-usable and permanently unrevocable.
        That is B28/F11 exactly.

    Four files already call `jwt.encode` directly. All currently use their own
    non-session audiences, so the property holds today; nothing gated the next
    one.
    """
    violations: list[str] = []

    for path in _python_files():
        relative = str(path.relative_to(APP))
        if relative in _SESSION_MINTING_ALLOWLIST:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        minting_names = _aliases_of(tree, "create_token")

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue

            # Attribute and aliased forms of create_token, which the Name-only
            # check above lets through. auth_service is exempt because the other
            # test already pins create_token there to issue_session, and the
            # user_id=0 service-account sentinel stays allowed everywhere.
            called = None
            if isinstance(node.func, ast.Name):
                called = node.func.id
            elif isinstance(node.func, ast.Attribute):
                called = node.func.attr
            if (
                called in minting_names
                and relative != "services/auth_service.py"
                and not (
                    node.args
                    and isinstance(node.args[0], ast.Constant)
                    and node.args[0].value == 0
                )
            ):
                violations.append(f"{relative}:{node.lineno} calls {called}")

            # A raw encode carrying the session audience.
            if not isinstance(node.func, ast.Attribute) or node.func.attr != "encode":
                continue
            for arg in node.args:
                if not isinstance(arg, ast.Dict):
                    continue
                for key, value in zip(arg.keys, arg.values, strict=True):
                    if not isinstance(key, ast.Constant) or key.value not in {"aud", "audience"}:
                        continue
                    names = (
                        value.id
                        if isinstance(value, ast.Name)
                        else value.attr
                        if isinstance(value, ast.Attribute)
                        else value.value
                        if isinstance(value, ast.Constant)
                        else None
                    )
                    if names in {"SESSION_AUDIENCE", _SESSION_AUDIENCE_LITERAL}:
                        violations.append(
                            f"{relative}:{node.lineno} encodes a token with the session audience"
                        )

    assert not violations, (
        "a bearer token carrying the session audience is minted outside the one issuer:\n"
        + "\n".join(violations)
        + "\n\nSuch a token is accepted as a full session and can never be revoked, because "
        "revocation checks for the presence of a session row that was never written. Route it "
        "through app.services.auth_service.issue_session, or give it its own audience."
    )
