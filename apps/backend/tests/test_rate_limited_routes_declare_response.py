"""Every `@limiter.limit` route must declare a `response: Response` parameter.

slowapi injects `X-RateLimit-*` headers through that parameter and raises when it is
absent:

    Exception: parameter `response` must be an instance of starlette.responses.Response

It raises on the *first* call, not at import, so the route looks fine until someone
uses it. `POST /api/v1/auth/service-account` was decorated without one and returned 500
to every request — the entire service-account feature was unreachable through the API,
and no test noticed because no test called it.

This is structural on purpose: the failure mode is a missing parameter, which is
exactly what static inspection is good at and what a per-route test would only find
route by route.
"""

from __future__ import annotations

import ast
from pathlib import Path

_API_DIR = Path(__file__).resolve().parents[1] / "src" / "app" / "api"


def _is_rate_limited(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for decorator in node.decorator_list:
        dumped = ast.dump(decorator)
        if "limiter" in dumped and "limit" in dumped:
            return True
    return False


def _rate_limited_routes() -> list[tuple[str, int, str, list[str]]]:
    found = []
    for path in sorted(_API_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not _is_rate_limited(node):
                continue
            args = [a.arg for a in node.args.args] + [a.arg for a in node.args.kwonlyargs]
            found.append((str(path.relative_to(_API_DIR)), node.lineno, node.name, args))
    return found


def test_the_scan_finds_the_rate_limited_routes():
    """Guard the guard: an inspection that matches nothing asserts nothing."""
    assert len(_rate_limited_routes()) > 20


def test_every_rate_limited_route_declares_a_response_parameter():
    offenders = [
        f"{path}:{lineno} {name}"
        for path, lineno, name, args in _rate_limited_routes()
        if "response" not in args
    ]

    assert not offenders, (
        "these routes are rate limited but declare no `response: Response` parameter, "
        "so slowapi raises and every call returns 500: " + ", ".join(offenders)
    )


def test_every_rate_limited_route_declares_a_request_parameter():
    """slowapi reads the client key off `request`; without it the route cannot be limited."""
    offenders = [
        f"{path}:{lineno} {name}"
        for path, lineno, name, args in _rate_limited_routes()
        if "request" not in args
    ]

    assert not offenders, (
        "these routes are rate limited but declare no `request` parameter: " + ", ".join(offenders)
    )
