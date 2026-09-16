"""GOV-05 / SRV-06: one CLI surface — repo-root cb and deploy/cli/cb stay in sync.

Both paths are the same implementation (native bundles copy the canonical CLI).
docs/cb-cli.md must describe the commands both actually dispatch.
"""

from __future__ import annotations

import filecmp
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ROOT_CLI = ROOT / "cb"
NATIVE_CLI = ROOT / "deploy" / "cli" / "cb"
DOCS = ROOT / "docs" / "cb-cli.md"

REQUIRED_COMMANDS = {
    "info",
    "status",
    "doctor",
    "setup",
    "setup-token",
    "logs",
    "restart",
    "update",
    "backup",
    "restore",
    "version",
    "uninstall",
}


def _dispatched_commands(script: Path) -> set[str]:
    """Commands the script's top-level `case` dispatcher handles."""
    text = script.read_text()
    return set(re.findall(r"^[ ]{2}([a-z][a-z-]*)\)", text, flags=re.MULTILINE))


def _documented_commands() -> set[str]:
    """Commands with their own `### \\`cb <name>\\`` section, plus table names."""
    text = DOCS.read_text()
    from_headings = set(re.findall(r"^### `cb ([a-z][a-z-]*)", text, flags=re.MULTILINE))
    from_table = set(re.findall(r"`([a-z][a-z-]*)`", _availability_table()))
    return from_headings | from_table


def _availability_table() -> str:
    table = re.search(
        r"^## Command availability by install mode$(.+?)^## ",
        DOCS.read_text(),
        flags=re.MULTILINE | re.DOTALL,
    )
    assert table, "docs/cb-cli.md has no 'Command availability by install mode' section"
    return table.group(1)


def test_root_and_native_cli_are_the_same_implementation():
    """deploy/cli/cb must match repo-root cb (unified operator surface)."""
    assert ROOT_CLI.is_file() and NATIVE_CLI.is_file()
    assert filecmp.cmp(ROOT_CLI, NATIVE_CLI, shallow=False), (
        "deploy/cli/cb drifted from repo-root cb — copy the canonical CLI again"
    )


def test_root_cli_implements_every_required_command():
    missing = REQUIRED_COMMANDS - _dispatched_commands(ROOT_CLI)
    assert not missing, f"repo-root cb is missing: {sorted(missing)}"


def test_native_cli_implements_every_required_command():
    missing = REQUIRED_COMMANDS - _dispatched_commands(NATIVE_CLI)
    assert not missing, f"deploy/cli/cb is missing: {sorted(missing)}"


def test_both_clis_expose_config_validate():
    for script in (ROOT_CLI, NATIVE_CLI):
        assert "config" in _dispatched_commands(script), f"{script} has no config command"


def test_documented_commands_exist_in_cli():
    documented = _documented_commands()
    assert documented, "no documented commands found"
    dispatched = _dispatched_commands(ROOT_CLI)
    # Table lists compound names like "config validate" → config
    missing = {c for c in documented if c not in dispatched and c != "validate"}
    assert not missing, f"CLI lacks documented commands: {sorted(missing)}"


def test_no_cli_divergence():
    only_root = _dispatched_commands(ROOT_CLI) - _dispatched_commands(NATIVE_CLI)
    only_native = _dispatched_commands(NATIVE_CLI) - _dispatched_commands(ROOT_CLI)
    assert not only_root and not only_native, (
        f"CLI divergence: root-only={sorted(only_root)} native-only={sorted(only_native)}"
    )


def test_docs_record_the_availability_of_every_command():
    body = _availability_table()
    for command in _dispatched_commands(ROOT_CLI):
        if command in {"help"}:
            continue
        assert f"`{command}" in body, f"{command} is not listed in the availability table"
