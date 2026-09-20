"""The weights must sum to 100 and cover every phase the installer opens.

A weight table that does not sum to 100 makes the bar stop short or saturate
early; a phase opened at runtime that the table does not know makes it jump.
Both are the "confidently wrong" failure the ETA rules exist to avoid, arriving
by a different route.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
UI = REPO_ROOT / "deploy" / "lib" / "ui.sh"

TABLES = {
    "CB_PHASE_WEIGHTS_INSTALL": REPO_ROOT / "install.sh",
    "CB_PHASE_WEIGHTS_UPGRADE": REPO_ROOT / "deploy" / "setup.sh",
    "CB_PHASE_WEIGHTS_UNINSTALL": REPO_ROOT / "uninstall.sh",
}


def _declared_weights(table: str) -> dict[str, int]:
    text = UI.read_text(encoding="utf-8")
    block = re.search(rf"declare -gA {table}=\((.*?)\)", text, re.DOTALL)
    assert block, f"{table} not found in deploy/lib/ui.sh"
    return {key: int(value) for key, value in re.findall(r"\[(\w+)\]=(\d+)", block.group(1))}


def _used_phase_keys(script: Path) -> set[str]:
    text = script.read_text(encoding="utf-8")
    # Anchored to the start of a (whitespace-stripped) line: a real call sits
    # alone on its line, but prose describing one does not, e.g.
    # "# poll. cb_phase_end supplies the final weight a moment later." would
    # otherwise be misread as a phase named "supplies". uninstall.sh calls
    # through the `_cb_phase` guard (the library may be absent there), so the
    # optional leading "_cb_phase " is part of a real call site too.
    return set(
        re.findall(r"^\s*(?:_cb_phase\s+)?cb_phase_(?:begin|end)\s+([a-z_]+)", text, re.MULTILINE)
    )


@pytest.mark.parametrize("table", sorted(TABLES))
def test_weights_sum_to_one_hundred(table: str) -> None:
    weights = _declared_weights(table)
    total = sum(weights.values())
    assert total == 100, f"{table} sums to {total}, not 100: {weights}"


@pytest.mark.parametrize("table,script", sorted(TABLES.items()))
def test_every_runtime_phase_is_declared(table: str, script: Path) -> None:
    declared = set(_declared_weights(table))
    used = _used_phase_keys(script)
    assert used, f"no cb_phase_begin/end calls found in {script.name}"
    undeclared = used - declared
    assert not undeclared, (
        f"{script.name} opens phases {sorted(undeclared)} that {table} does not "
        "declare, so they contribute no weight and the bar jumps."
    )


@pytest.mark.parametrize("table,script", sorted(TABLES.items()))
def test_every_declared_phase_is_used(table: str, script: Path) -> None:
    declared = set(_declared_weights(table))
    unused = declared - _used_phase_keys(script)
    assert not unused, (
        f"{table} declares {sorted(unused)}, which {script.name} never opens, "
        "so the bar can never reach 100%."
    )
