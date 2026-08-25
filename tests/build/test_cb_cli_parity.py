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


def _availability_table() -> str:
    """The body of the 'Command availability by install mode' table."""
    table = re.search(
        r"^## Command availability by install mode$(.+?)^## ",
        DOCS.read_text(),
        flags=re.MULTILINE | re.DOTALL,
    )
    assert table, "docs/cb-cli.md has no 'Command availability by install mode' section"
    return table.group(1)


def _native_absent_commands() -> set[str]:
    """Commands the availability table marks as absent from the native CLI.

    Derived rather than listed. This test used to hardcode `vault-recover` as
    the single permitted divergence, which made the *second* documented one
    (`restore`, added with the backup/restore parity batch) a build failure
    even though docs/cb-cli.md introduced it deliberately and explains it two
    paragraphs below the table. A hardcoded exemption cannot tell "we decided
    this and wrote it down" apart from "this drifted", so it flagged both the
    same way and had to be edited to accept a decision it could not see.

    Reading the Native column keeps the teeth and drops the maintenance: a
    command may be missing from `deploy/cli/cb` only if the table says `—` for
    Native, and adding a divergence without documenting it still fails. Every
    row's first cell is a backtick-quoted command list, so `config validate`
    contributes `config` — the dispatcher name, which is what we compare with.
    """
    absent: set[str] = set()
    rows = re.findall(r"^\|(.+?)\|(.+?)\|", _availability_table(), flags=re.MULTILINE)
    for commands, native in rows:
        if native.strip() == "—":
            absent |= set(re.findall(r"`([a-z][a-z-]*)", commands))
    return absent


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
    exempt = _native_absent_commands()
    for script in (ROOT_CLI, NATIVE_CLI):
        missing = documented - _dispatched_commands(script) - exempt
        assert not missing, f"{script} lacks documented commands: {sorted(missing)}"


def test_divergences_are_exactly_the_documented_ones():
    """Commands that are not shared must be exactly the ones the docs declare.

    Two are declared today, both for the same reason — the native installer
    owns the state the command touches, so the command belongs to the other
    installer path rather than to both:

      * `vault-recover` writes a vault key the docker/compose/binary installer
        path owns; a native install keeps that key in /etc/circuitbreaker/.env,
        which systemd and deploy/setup.sh own.
      * `restore` drives a full-state replacement; a native install runs
        deploy/scripts/restore.sh directly, which is the implementation
        `cb restore` itself shells out to in `binary` mode.

    Both are real differences, so they are pinned here — and the docs must say
    so, since that is where the assertion reads them from — rather than being
    papered over. A divergence that nobody wrote into the table still fails.
    """
    documented_divergence = _native_absent_commands()
    assert documented_divergence, "the availability table declares no native-absent commands"
    only_root = _dispatched_commands(ROOT_CLI) - _dispatched_commands(NATIVE_CLI)
    only_native = _dispatched_commands(NATIVE_CLI) - _dispatched_commands(ROOT_CLI)
    assert only_root == documented_divergence, (
        f"repo-root-only commands {sorted(only_root)} do not match the ones "
        f"docs/cb-cli.md marks absent for Native: {sorted(documented_divergence)}"
    )
    assert not only_native, f"unexpected native-only commands: {sorted(only_native)}"


def test_docs_record_the_availability_of_every_command():
    """Every command in either CLI appears in the install-mode table."""
    body = _availability_table()
    for command in _dispatched_commands(ROOT_CLI) | _dispatched_commands(NATIVE_CLI):
        assert f"`{command}" in body, f"{command} is not listed in the availability table"
