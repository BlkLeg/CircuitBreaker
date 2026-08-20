"""GOV-05 / SRV-06: one documented CLI surface, not two divergent ones.

Two `cb` scripts ship — `deploy/cli/cb` for native systemd installs and the
repo-root `cb` for docker/compose/binary. They had different command sets, and
docs/cb-cli.md documented only one of them, so half the users followed docs
describing commands they did not have.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ROOT_CLI = ROOT / "cb"
NATIVE_CLI = ROOT / "deploy" / "cli" / "cb"
DOCS = ROOT / "docs" / "cb-cli.md"

# The union both scripts must implement. `vault-recover` is the one genuine
# difference (see test_vault_recover_is_the_only_divergence) and is asserted
# separately rather than being silently exempted here.
REQUIRED_COMMANDS = {
    "status",
    "doctor",
    "logs",
    "restart",
    "update",
    "backup",
    "version",
    "uninstall",
}


def _dispatched_commands(script: Path) -> set[str]:
    """Commands the script's `case` dispatcher actually handles.

    Both dispatchers indent their branches by exactly two spaces; every `case`
    nested inside a function is indented further, so this picks out the
    top-level command dispatch only.
    """
    text = script.read_text()
    return set(re.findall(r"^[ ]{2}([a-z][a-z-]*)\)", text, flags=re.MULTILINE))


def _documented_commands() -> set[str]:
    """Commands with their own `### \\`cb <name>\\`` section in the docs."""
    return set(re.findall(r"^### `cb ([a-z][a-z-]*)", DOCS.read_text(), flags=re.MULTILINE))


def test_root_cli_implements_every_required_command():
    missing = REQUIRED_COMMANDS - _dispatched_commands(ROOT_CLI)
    assert not missing, f"repo-root cb is missing: {sorted(missing)}"


def test_native_cli_implements_every_required_command():
    missing = REQUIRED_COMMANDS - _dispatched_commands(NATIVE_CLI)
    assert not missing, f"deploy/cli/cb is missing: {sorted(missing)}"


def test_both_clis_expose_config_validate():
    """SRV-05's validator is useless if the CLI does not surface it."""
    for script in (ROOT_CLI, NATIVE_CLI):
        assert "config" in _dispatched_commands(script), f"{script} has no config command"


def test_documented_commands_all_exist_in_both_clis():
    """docs/cb-cli.md must not describe a command half the users lack."""
    documented = _documented_commands()
    assert documented, "no documented commands found — check the docs heading format"
    for script in (ROOT_CLI, NATIVE_CLI):
        missing = documented - _dispatched_commands(script) - {"vault-recover"}
        assert not missing, f"{script} lacks documented commands: {sorted(missing)}"


def test_vault_recover_is_the_only_divergence():
    """The one command that is not shared must be exactly the documented one.

    `vault-recover` writes a vault key the docker/compose/binary installer path
    owns; the native installer keeps that key in /etc/circuitbreaker/.env and
    has never shipped the command. That is a real difference, so it is pinned
    here — and the docs must say so — rather than being papered over.
    """
    only_root = _dispatched_commands(ROOT_CLI) - _dispatched_commands(NATIVE_CLI)
    only_native = _dispatched_commands(NATIVE_CLI) - _dispatched_commands(ROOT_CLI)
    assert only_root == {"vault-recover"}, f"unexpected repo-root-only commands: {sorted(only_root)}"
    assert not only_native, f"unexpected native-only commands: {sorted(only_native)}"


def test_docs_record_the_availability_of_every_command():
    """Every command in either CLI appears in the install-mode table."""
    docs = DOCS.read_text()
    table = re.search(
        r"^## Command availability by install mode$(.+?)^## ",
        docs,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert table, "docs/cb-cli.md has no 'Command availability by install mode' section"
    body = table.group(1)
    for command in _dispatched_commands(ROOT_CLI) | _dispatched_commands(NATIVE_CLI):
        assert f"`{command}" in body, f"{command} is not listed in the availability table"
