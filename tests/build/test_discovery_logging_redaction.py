"""Guard discovery enrichment logs against leaking MAC addresses."""

from __future__ import annotations

import ast
from pathlib import Path


SOURCE = (
    Path(__file__).parents[2]
    / "apps"
    / "backend"
    / "src"
    / "app"
    / "services"
    / "discovery_enrich.py"
)


def test_mac_is_not_passed_to_discovery_debug_logging() -> None:
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    debug_calls = 0

    for call in ast.walk(tree):
        if (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr == "debug"
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id == "logger"
        ):
            debug_calls += 1
            assert not any(
                isinstance(node, ast.Name) and node.id == "mac"
                for argument in call.args
                for node in ast.walk(argument)
            )

    assert debug_calls == 1
