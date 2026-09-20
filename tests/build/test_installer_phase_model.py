"""The weights must sum to 100 and cover every phase the installer opens.

A weight table that does not sum to 100 makes the bar stop short or saturate
early; a phase opened at runtime that the table does not know makes it jump.
Both are the "confidently wrong" failure the ETA rules exist to avoid, arriving
by a different route.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UI = REPO_ROOT / "deploy" / "lib" / "ui.sh"
INSTALLER = REPO_ROOT / "install.sh"


def _declared_weights() -> dict[str, int]:
    text = UI.read_text(encoding="utf-8")
    block = re.search(r"declare -gA CB_PHASE_WEIGHTS=\((.*?)\)", text, re.DOTALL)
    assert block, "CB_PHASE_WEIGHTS not found in deploy/lib/ui.sh"
    return {key: int(value) for key, value in re.findall(r"\[(\w+)\]=(\d+)", block.group(1))}


def _used_phase_keys() -> set[str]:
    text = INSTALLER.read_text(encoding="utf-8")
    # Anchored to the start of a (whitespace-stripped) line: a real call sits
    # alone on its line, but prose describing one does not, e.g.
    # "# poll. cb_phase_end supplies the final weight a moment later." would
    # otherwise be misread as a phase named "supplies".
    return set(re.findall(r"^\s*cb_phase_(?:begin|end)\s+([a-z_]+)", text, re.MULTILINE))


def test_weights_sum_to_one_hundred() -> None:
    weights = _declared_weights()
    total = sum(weights.values())
    assert total == 100, f"phase weights sum to {total}, not 100: {weights}"


def test_every_runtime_phase_is_declared() -> None:
    declared = set(_declared_weights())
    used = _used_phase_keys()
    assert used, "no cb_phase_begin/end calls found in install.sh"
    undeclared = used - declared
    assert not undeclared, (
        f"install.sh opens phases {sorted(undeclared)} that CB_PHASE_WEIGHTS "
        "does not declare, so they contribute no weight and the bar jumps."
    )


def test_every_declared_phase_is_used() -> None:
    declared = set(_declared_weights())
    unused = declared - _used_phase_keys()
    assert not unused, (
        f"CB_PHASE_WEIGHTS declares {sorted(unused)}, which install.sh never "
        "opens, so the bar can never reach 100%."
    )
