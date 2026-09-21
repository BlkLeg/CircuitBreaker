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
INSTALLER = REPO_ROOT / "install.sh"
SETUP = REPO_ROOT / "deploy" / "setup.sh"

UNINSTALLER = REPO_ROOT / "uninstall.sh"

TABLES = ["CB_PHASE_WEIGHTS_INSTALL", "CB_PHASE_WEIGHTS_UPGRADE", "CB_PHASE_WEIGHTS_UNINSTALL"]

# The branch in install.sh::main() that hands off to run_upgrade() and exits
# before ever reaching the fresh-install phases (deps/database/services/start).
# Deliberately matched on the unbraced "$UPGRADE_MODE" spelling this branch
# uses, which is different from the braced "${UPGRADE_MODE}" spelling the
# earlier cb_ui_use_weights branch uses a few lines above it — so this can
# only match the run_upgrade hand-off, not the weights-table selection.
_UPGRADE_HANDOFF_MARKER = 'if [[ "$UPGRADE_MODE" == "true" ]]; then\n      run_upgrade'


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


def _ordered_phase_begins(text: str) -> list[str]:
    """The keys `cb_phase_begin` opens, in the order they appear in the text.

    Same anchor and guard-prefix handling as `_used_phase_keys`. `begin` alone
    is enough to detect a duplicate key or to sum weights: every `begin` a flow
    opens is followed by a matching `end` for the same key, so counting begins
    once per open is equivalent to counting the weight that open contributes.
    """
    return re.findall(r"^\s*(?:_cb_phase\s+)?cb_phase_begin\s+([a-z_]+)", text, re.MULTILINE)


def _install_main_split() -> tuple[list[str], list[str]]:
    """Split install.sh::main()'s phase-begin sequence at the run_upgrade hand-off.

    Everything before the hand-off (preflight/bundle/files) runs in every mode.
    Everything after it (deps/database/services/start) only runs on a fresh
    install — the upgrade branch calls run_upgrade() and exits first.
    """
    text = INSTALLER.read_text(encoding="utf-8")
    marker = text.index(_UPGRADE_HANDOFF_MARKER)
    return _ordered_phase_begins(text[:marker]), _ordered_phase_begins(text[marker:])


def _no_duplicates(sequence: list[str]) -> list[str]:
    """The keys that appear more than once in an ordered phase-begin sequence."""
    seen: dict[str, int] = {}
    for key in sequence:
        seen[key] = seen.get(key, 0) + 1
    return sorted(key for key, count in seen.items() if count > 1)


# What each table's flow actually opens at runtime. CB_PHASE_WEIGHTS_UPGRADE is
# the one table two scripts share: install.sh::main() opens preflight/bundle/
# files against it before handing off to run_upgrade() (deploy/setup.sh), which
# opens the other five phases against the same live table in the same shell.
# Scanning install.sh's whole file (as a plain-install check would) would wrongly
# fold in deps/database/services/start too, which only run on the non-upgrade
# branch — so the upgrade flow uses the mode-aware prefix from
# _install_main_split() instead of the raw file scan.
def _install_flow_keys() -> set[str]:
    prefix, suffix = _install_main_split()
    return set(prefix) | set(suffix)


def _upgrade_flow_keys() -> set[str]:
    prefix, _suffix = _install_main_split()
    return set(prefix) | _used_phase_keys(SETUP)


def _uninstall_flow_keys() -> set[str]:
    return _used_phase_keys(UNINSTALLER)


_FLOW_KEYS = {
    "CB_PHASE_WEIGHTS_INSTALL": (_install_flow_keys, "install.sh (fresh install)"),
    "CB_PHASE_WEIGHTS_UPGRADE": (
        _upgrade_flow_keys,
        "install.sh::main() + deploy/setup.sh::run_upgrade()",
    ),
    "CB_PHASE_WEIGHTS_UNINSTALL": (_uninstall_flow_keys, "uninstall.sh"),
}


@pytest.mark.parametrize("table", sorted(TABLES))
def test_weights_sum_to_one_hundred(table: str) -> None:
    weights = _declared_weights(table)
    total = sum(weights.values())
    assert total == 100, f"{table} sums to {total}, not 100: {weights}"


@pytest.mark.parametrize("table", sorted(TABLES))
def test_every_runtime_phase_is_declared(table: str) -> None:
    declared = set(_declared_weights(table))
    keys_fn, label = _FLOW_KEYS[table]
    used = keys_fn()
    assert used, f"no cb_phase_begin/end calls found for {label}"
    undeclared = used - declared
    assert not undeclared, (
        f"{label} opens phases {sorted(undeclared)} that {table} does not "
        "declare, so they contribute no weight and the bar jumps."
    )


@pytest.mark.parametrize("table", sorted(TABLES))
def test_every_declared_phase_is_used(table: str) -> None:
    declared = set(_declared_weights(table))
    keys_fn, label = _FLOW_KEYS[table]
    unused = declared - keys_fn()
    assert not unused, (
        f"{table} declares {sorted(unused)}, which {label} never opens, "
        "so the bar can never reach 100%."
    )


# ──────────────────────────────────────────────────────────────────────────
# Composition tests.
#
# The three tests above check one script against one table at a time, which
# is exactly what missed this bug: install.sh::main() and run_upgrade() (in
# deploy/setup.sh) run in the same shell, against the same live table, on the
# same upgrade invocation, but each was checked only against
# CB_PHASE_WEIGHTS_UPGRADE in isolation. main() opened preflight/bundle/files
# and CB_PHASE_WEIGHTS_UPGRADE declared them, so its per-script test passed;
# run_upgrade() opened its own preflight/backup/bundle/apply/start and
# CB_PHASE_WEIGHTS_UPGRADE declared those too, so its per-script test also
# passed. Composed at runtime, preflight and bundle were opened twice each,
# and _CB_DONE_WEIGHT summed to 125 — the bar hit 100% before the upgrade
# actually finished. These tests build the real composed sequence for each
# flow and check it directly.
# ──────────────────────────────────────────────────────────────────────────


def test_install_sequence_has_no_duplicate_keys() -> None:
    prefix, suffix = _install_main_split()
    sequence = prefix + suffix
    dupes = _no_duplicates(sequence)
    assert not dupes, (
        f"install.sh::main()'s fresh-install sequence opens {dupes} more than "
        f"once: {sequence}. A key opened twice contributes its weight twice, "
        "so the bar overshoots before the install finishes."
    )


def test_install_sequence_sums_to_one_hundred() -> None:
    prefix, suffix = _install_main_split()
    sequence = prefix + suffix
    weights = _declared_weights("CB_PHASE_WEIGHTS_INSTALL")
    total = sum(weights[key] for key in sequence)
    assert total == 100, (
        f"install.sh's fresh-install sequence {sequence} sums to {total} against "
        f"CB_PHASE_WEIGHTS_INSTALL, not 100: {weights}"
    )


def test_upgrade_sequence_has_no_duplicate_keys() -> None:
    prefix, _suffix = _install_main_split()
    run_upgrade_keys = _ordered_phase_begins(SETUP.read_text(encoding="utf-8"))
    sequence = prefix + run_upgrade_keys
    dupes = _no_duplicates(sequence)
    assert not dupes, (
        f"the upgrade path opens {dupes} more than once across install.sh's "
        f"pre-handoff phases and run_upgrade()'s own phases: {sequence}. A key "
        "opened twice contributes its weight twice, so the bar hits 100% before "
        "the upgrade actually finishes."
    )


def test_upgrade_sequence_sums_to_one_hundred() -> None:
    prefix, _suffix = _install_main_split()
    run_upgrade_keys = _ordered_phase_begins(SETUP.read_text(encoding="utf-8"))
    sequence = prefix + run_upgrade_keys
    weights = _declared_weights("CB_PHASE_WEIGHTS_UPGRADE")
    total = sum(weights[key] for key in sequence)
    print(f"upgrade composed sequence {sequence} sums to {total}")
    assert total == 100, (
        f"the upgrade path's composed sequence {sequence} sums to {total} "
        f"against CB_PHASE_WEIGHTS_UPGRADE, not 100: {weights}"
    )
