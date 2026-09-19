"""SRV-06: the `cb` wrappers around the administration surface, actually run.

Both `cb` scripts are executed here against a stand-in binary rather than
grepped. Two properties are only true if the script runs:

*Exit codes survive the wrapper.* `cb migrate status` exits 3 when the schema
is behind so a deployment script can branch on it. A wrapper that swallowed the
child's status — which is what `set -e` plus a trailing `|| true`, or an `echo`
after the call, quietly does — would turn that into 0 and a deployment would
step over a database it had been told not to touch.

*The arguments arrive intact.* `cb token rotate 3 --overlap-hours 6` has to
reach `app.cli` as those five words. A wrapper that dropped `"${@:2}"`, or
re-split on whitespace, produces a command that runs and does something else.
"""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_ROOT_CLI = _REPO_ROOT / "cb"
_NATIVE_CLI = _REPO_ROOT / "deploy" / "cli" / "cb"

ADMIN_GROUPS = ("migrate", "token", "user", "agent")


@pytest.fixture
def fake_binary(tmp_path):
    """A stand-in for the frozen Circuit Breaker binary.

    Records the argv it was handed and exits 3 — the code `migrate status` uses
    for "behind" — so a wrapper that loses either is visible.
    """
    recorded = tmp_path / "argv.txt"
    binary = tmp_path / "circuit-breaker"
    binary.write_text(f'#!/usr/bin/env bash\nprintf "%s\\n" "$@" > {recorded}\nexit 3\n')
    binary.chmod(binary.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return binary, recorded


def _run(script: Path, args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(script), *args],
        capture_output=True,
        text=True,
        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": env.get("HOME", "/"), **env},
    )


@pytest.mark.parametrize("group", ADMIN_GROUPS)
def test_root_cli_forwards_the_admin_groups_and_their_exit_code(group, tmp_path, fake_binary):
    binary, recorded = fake_binary
    config_dir = tmp_path / "conf"
    config_dir.mkdir()
    (config_dir / "install.conf").write_text(
        f"CB_MODE=binary\nCB_BINARY={binary}\nCB_BINARY_ENV_FILE={tmp_path / 'unit.env'}\n"
    )
    (tmp_path / "unit.env").write_text("CB_DB_URL=postgresql://example/db\n")

    result = _run(
        _ROOT_CLI,
        [group, "list", "--json"],
        {"CB_CONFIG_DIR": str(config_dir), "HOME": str(tmp_path)},
    )

    assert result.returncode == 3, result.stdout + result.stderr
    assert recorded.read_text().split("\n")[:4] == ["--admin", group, "list", "--json"]


def _install_identity(tmp_path: Path, binary: Path) -> Path:
    """An installed `package`-mode host, which is what the native `cb` requires.

    Since the identity work in `67dbefb8`, every administration command is
    gated on an install identity (or a legacy install.conf); without one the
    wrapper refuses with exit 1 before it ever reaches the binary, and nothing
    about argv or exit-code forwarding can be observed. `package` maps to
    CB_MODE=binary, which is the branch that execs CB_BINARY directly.

    `CB_IDENTITY_PATH` rather than a file under HOME: `_load_install_identity`
    searches /etc before $HOME, so a host that happens to have Circuit Breaker
    installed would otherwise supply its own identity to this test.
    """
    env_file = tmp_path / "circuit-breaker.env"
    env_file.write_text("CB_DB_URL=postgresql://example/db\n")
    identity = tmp_path / "install-identity.json"
    identity.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "mode": "package",
                "version": "0.0.0-test",
                "installed_at": "2026-01-01T00:00:00Z",
                "data_dir": str(tmp_path / "data"),
                "env_file": str(env_file),
                "cli_path": str(binary),
            }
        )
    )
    return identity


@pytest.mark.parametrize("group", ADMIN_GROUPS)
def test_native_cli_forwards_the_admin_groups_and_their_exit_code(group, tmp_path, fake_binary):
    binary, recorded = fake_binary
    identity = _install_identity(tmp_path, binary)

    result = _run(
        _NATIVE_CLI,
        [group, "list", "--json"],
        {
            "CB_IDENTITY_PATH": str(identity),
            "CB_BINARY": str(binary),
            "HOME": str(tmp_path),
        },
    )

    assert result.returncode == 3, result.stdout + result.stderr
    assert recorded.read_text().split("\n")[:4] == ["--admin", group, "list", "--json"]


@pytest.mark.parametrize("group", ADMIN_GROUPS)
def test_native_cli_refuses_an_admin_group_without_an_install_identity(
    group, tmp_path, fake_binary
):
    """The gate itself, so the fixture above cannot quietly stop exercising it.

    A host with no identity must be told so and must not reach the binary --
    exit 1 with the repair guidance, not the binary's own status.
    """
    binary, recorded = fake_binary

    result = _run(
        _NATIVE_CLI,
        [group, "list", "--json"],
        {
            "CB_IDENTITY_PATH": str(tmp_path / "absent.json"),
            "CB_BINARY": str(binary),
            "HOME": str(tmp_path),
        },
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert "requires install identity" in result.stdout + result.stderr
    assert not recorded.exists()


def test_arguments_with_flags_and_values_arrive_intact(tmp_path, fake_binary):
    binary, recorded = fake_binary
    config_dir = tmp_path / "conf"
    config_dir.mkdir()
    (config_dir / "install.conf").write_text(f"CB_MODE=binary\nCB_BINARY={binary}\n")

    _run(
        _ROOT_CLI,
        ["token", "rotate", "3", "--overlap-hours", "6"],
        {"CB_CONFIG_DIR": str(config_dir), "HOME": str(tmp_path)},
    )

    assert recorded.read_text().split("\n")[:6] == [
        "--admin",
        "token",
        "rotate",
        "3",
        "--overlap-hours",
        "6",
    ]


def test_a_missing_binary_is_a_sentence_not_exit_127(tmp_path):
    """The guard every other binary-mode command already has, on this path too."""
    config_dir = tmp_path / "conf"
    config_dir.mkdir()
    (config_dir / "install.conf").write_text(
        f"CB_MODE=binary\nCB_BINARY={tmp_path / 'not-installed'}\n"
    )

    result = _run(
        _ROOT_CLI,
        ["migrate", "status"],
        {"CB_CONFIG_DIR": str(config_dir), "HOME": str(tmp_path)},
    )

    assert result.returncode == 1
    assert "not found" in result.stderr
    assert "127" not in result.stderr


def test_the_container_passthrough_keeps_stdin_open():
    """`cb user create --password-stdin` is the only way to set a password without argv.

    `docker exec` without `-i` closes the child's stdin, so the password never
    arrives and the one command written specifically to keep a secret out of
    every process listing on the host cannot be used.
    """
    text = _ROOT_CLI.read_text()
    passthrough = re.search(r"^_admin_cli\(\) \{(.+?)^\}", text, flags=re.MULTILINE | re.DOTALL)
    assert passthrough, "the repo-root cb no longer has a single admin passthrough"
    assert "docker exec -i " in passthrough.group(1)


@pytest.mark.parametrize("script", [_ROOT_CLI, _NATIVE_CLI])
def test_no_admin_command_is_reimplemented_in_bash(script):
    """Each group is one line that forwards, and nothing else.

    A shell that inserted an api_tokens row, or flipped an agent's status with
    psql, would be a second definition of a security rule — the shape of INC-15,
    where `cb backup` grew its own archive builder and produced artifacts the
    documented restore path rejected.
    """
    text = script.read_text()
    for group in ADMIN_GROUPS:
        body = re.search(rf"^cmd_{group}\(\)\s*\{{(.*?)\}}", text, flags=re.MULTILINE | re.DOTALL)
        assert body, f"{script} has no cmd_{group}"
        assert body.group(1).strip() == f'_admin_cli {group} "$@";'


@pytest.mark.parametrize("script", [_ROOT_CLI, _NATIVE_CLI])
def test_the_help_text_lists_the_admin_commands(script):
    text = script.read_text()
    for group in ADMIN_GROUPS:
        assert re.search(rf"echo .*\b{group}\b", text), f"{script} help does not mention {group}"
