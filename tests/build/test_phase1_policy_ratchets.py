"""Fast static ratchets for Phase 1 production promises."""

from __future__ import annotations

import ast
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "apps/backend/src/app"
sys.path.insert(0, str(ROOT / "apps/backend/src"))

HTTP_CONSTRUCTORS = {
    ("httpx", "Client"),
    ("httpx", "AsyncClient"),
    ("httpx", "get"),
    ("httpx", "post"),
    ("httpx", "request"),
    ("requests", "Session"),
    ("requests", "get"),
    ("requests", "post"),
    ("requests", "request"),
    ("boto3", "client"),
}


def _python_files() -> list[Path]:
    return sorted(APP.rglob("*.py"))


def test_http_clients_are_only_constructed_by_the_egress_layer() -> None:
    violations: list[str] = []
    for path in _python_files():
        if path == APP / "core/egress.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            owner = node.func.value
            if isinstance(owner, ast.Name) and (owner.id, node.func.attr) in HTTP_CONSTRUCTORS:
                violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert not violations, "direct HTTP client construction bypasses app.core.egress:\n" + "\n".join(
        violations
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
