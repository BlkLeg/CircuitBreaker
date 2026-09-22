"""The native worker set must be one list, read everywhere else.

`app.workers.main.WORKER_MODULES` is what the runtime actually dispatches.
`deploy/setup.sh` used to repeat the worker names as quoted literals in two
places (the systemd enable call and the start loop) instead of reading them
from anywhere — so when `integration` and `monitor_probe_dispatch` were added
to `WORKER_MODULES`, `circuitbreaker.target`'s `Wants=` and `cb`'s
`CB_NATIVE_SERVICES`, deploy/setup.sh's two hand-copied lists were never
updated, and every native install silently ran five of the seven workers the
mono image and circuitbreaker.target both expect. This pins every one of
those lists back to `WORKER_MODULES`, so the four can no longer drift
independently.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_SRC = REPO_ROOT / "apps" / "backend" / "src"
SETUP_SH = REPO_ROOT / "deploy" / "setup.sh"
TARGET_UNIT = REPO_ROOT / "deploy" / "systemd" / "circuitbreaker.target"
CB_CLI = REPO_ROOT / "cb"
JOURNEY = REPO_ROOT / "scripts" / "ci" / "installer-journey.sh"

sys.path.insert(0, str(BACKEND_SRC))


def _worker_modules() -> set[str]:
    """The runtime's own worker-type set, read the way the sibling gate does."""
    tree = ast.parse(
        (BACKEND_SRC / "app" / "workers" / "main.py").read_text(encoding="utf-8"),
        filename="main.py",
    )
    for node in ast.walk(tree):
        # WORKER_MODULES carries a `dict[str, str]` annotation, so this is an
        # ast.AnnAssign, not a plain ast.Assign.
        is_worker_modules_target = (
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "WORKER_MODULES" for t in node.targets)
        ) or (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "WORKER_MODULES"
        )
        if is_worker_modules_target and isinstance(node.value, ast.Dict):
            return {
                key.value
                for key in node.value.keys
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            }
    raise AssertionError("No `WORKER_MODULES = {...}` dict literal was found in workers/main.py")


def _setup_sh_worker_types() -> set[str]:
    text = SETUP_SH.read_text(encoding="utf-8")
    block = re.search(r"CB_WORKER_TYPES=\((.*?)\)", text, re.DOTALL)
    assert block, "deploy/setup.sh no longer defines CB_WORKER_TYPES"
    names = {
        line.strip()
        for line in block.group(1).splitlines()
        if line.strip() and not line.strip().startswith("#")
    }
    return names


def _target_wants_workers() -> set[str]:
    text = TARGET_UNIT.read_text(encoding="utf-8")
    return {
        m.group(1)
        for m in re.finditer(r"^Wants=circuitbreaker-worker@([a-z_]+)\.service$", text, re.MULTILINE)
    }


def _cb_cli_native_services_workers() -> set[str]:
    text = CB_CLI.read_text(encoding="utf-8")
    block = re.search(r"CB_NATIVE_SERVICES=\((.*?)\)", text, re.DOTALL)
    assert block, "cb no longer defines CB_NATIVE_SERVICES"
    return set(re.findall(r'"circuitbreaker-worker@([a-z_]+)"', block.group(1)))


def _journey_worker_units() -> set[str]:
    text = JOURNEY.read_text(encoding="utf-8")
    block = re.search(r"CB_WORKER_UNITS=\((.*?)\)", text, re.DOTALL)
    assert block, "installer-journey.sh no longer defines CB_WORKER_UNITS"
    return set(re.findall(r"circuitbreaker-worker@([a-z_]+)", block.group(1)))


def _assert_matches(actual: set[str], expected: set[str], *, where: str) -> None:
    missing = expected - actual
    extra = actual - expected
    assert not missing and not extra, (
        f"{where} lists {sorted(actual)}, but app.workers.main.WORKER_MODULES "
        f"has {sorted(expected)}.\n"
        f"  missing from {where}: {sorted(missing) or 'none'}\n"
        f"  extra in {where}:     {sorted(extra) or 'none'}"
    )


def test_worker_modules_is_not_empty() -> None:
    """Guards every test below against passing vacuously if the parser breaks."""
    assert _worker_modules(), "WORKER_MODULES parsed as empty — the AST reader is broken"


def test_setup_sh_worker_types_matches_worker_modules() -> None:
    _assert_matches(_setup_sh_worker_types(), _worker_modules(), where="deploy/setup.sh's CB_WORKER_TYPES")


def test_target_unit_wants_every_worker() -> None:
    _assert_matches(
        _target_wants_workers(), _worker_modules(), where="circuitbreaker.target's Wants="
    )


def test_cb_cli_native_services_lists_every_worker() -> None:
    _assert_matches(
        _cb_cli_native_services_workers(), _worker_modules(), where="cb's CB_NATIVE_SERVICES"
    )


def test_installer_journey_asserts_every_worker() -> None:
    _assert_matches(
        _journey_worker_units(), _worker_modules(), where="installer-journey.sh's CB_WORKER_UNITS"
    )
