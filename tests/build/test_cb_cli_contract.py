"""The two `cb` scripts must point at files that exist, and `doctor` must fail loudly.

Two regressions this file exists to stop, both of which shipped:

1. The repo-root `cb` read `/etc/circuit-breaker/env` in binary mode. Nothing
   creates that path — `packaging/postinstall.sh` generates
   `/etc/circuit-breaker/circuit-breaker.env`, which is also what the unit files
   name in `EnvironmentFile=`. `cb config validate` therefore validated an empty
   ambient environment and called it fine. This exact mistake was fixed once
   before and came back, because the path was spelled out at four call sites and
   nothing checked it against the installers.

2. `deploy/cli/cb`'s `cmd_doctor` ended on `echo ""`, so it exited 0 no matter
   how many checks failed, while the repo-root `cb` returned the verdict. No
   installer gates on it — `install.sh` names `cb doctor` in a post-failure
   hint and in the diagnostics it collects once a stage has already failed —
   but an operator or a wrapper script polling the command has no other signal,
   and the two CLIs must not disagree about what a failed check means. The
   existing parity test compares command *names*, which is precisely why a
   behavioural divergence this large survived it.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ROOT_CLI = ROOT / "cb"
NATIVE_CLI = ROOT / "deploy" / "cli" / "cb"
DOCS = ROOT / "docs" / "cb-cli.md"

# Absolute system paths that look like an environment file: the basename is
# `env` or ends in `.env`. Anything under a user's $HOME is operator territory
# and is covered by test_operator_supplied_paths_are_documented_as_such instead.
# /usr is left out on purpose — the only match there is the `#!/usr/bin/env`
# shebang, which is an interpreter, not a config file.
_ENV_PATH_RE = re.compile(r"/(?:etc|run|var|opt)/[A-Za-z0-9._/-]*")

# Where an installer, package script or unit file could legitimately create one.
_CREATOR_GLOBS = (
    "install.sh",
    "uninstall.sh",
    "deploy/**/*.sh",
    "deploy/**/*.service",
    "deploy/**/*.py",
    "packaging/**/*.sh",
    "packaging/**/*.service",
    "packaging/**/*.yaml",
    "packaging/PKGBUILD",
    "scripts/**/*.sh",
    "docker/**/*.sh",
)


def _env_paths(script: Path) -> set[str]:
    found = set()
    for candidate in _ENV_PATH_RE.findall(script.read_text()):
        name = candidate.rsplit("/", 1)[-1]
        if name == "env" or name.endswith(".env"):
            found.add(candidate)
    return found


def _creator_files() -> list[Path]:
    files: list[Path] = []
    for pattern in _CREATOR_GLOBS:
        files.extend(p for p in ROOT.glob(pattern) if p.is_file())
    return files


def _writers_of(path: str) -> list[str]:
    """Files that actually *create* `path`, not merely mention it.

    A redirect, a `tee`, or a `cp`/`mv`/`install`/`touch` onto the path counts.
    `chmod`/`chown`/`source`/`grep` lines do not — those are consumers, and a
    file that is only ever consumed is exactly the bug being guarded against.
    """
    escaped = re.escape(path)
    boundary = r"(?![A-Za-z0-9._-])"

    def _patterns(target: str) -> tuple[re.Pattern[str], ...]:
        return (
            re.compile(r">>?\s*[\"']?" + target + boundary),
            re.compile(r"\btee\b(?:\s+-a)?\s+[\"']?" + target + boundary),
            re.compile(r"\b(?:cp|mv|install|touch)\b[^\n]*?" + target + boundary),
        )

    hits = []
    for candidate in _creator_files():
        text = candidate.read_text(errors="replace")
        if path not in text:
            continue

        # Follow one level of variable indirection, and only where the variable's
        # own default *is* this path. packaging/postinstall.sh, preinstall.sh and
        # rollback.sh all take their paths as `VAR="${CB_OVERRIDE:-/the/path}"`,
        # deliberately, so the hooks can be exercised without installing a package
        # as root -- and a creation through that variable is still a creation.
        # Anything whose default is a different path is not followed, so this
        # cannot be used to launder a script that never writes the file.
        aliases = [escaped]
        for match in re.finditer(
            r"^\s*([A-Za-z_][A-Za-z0-9_]*)=\"?\$\{[A-Za-z_][A-Za-z0-9_]*:-" + escaped + r"\}\"?\s*$",
            text, re.M,
        ):
            aliases.append(r"\$\{?" + re.escape(match.group(1)) + r"\}?")

        matchers = tuple(rx for alias in aliases for rx in _patterns(alias))
        for line in text.splitlines():
            if any(rx.search(line) for rx in matchers):
                hits.append(str(candidate.relative_to(ROOT)))
                break
    return hits


@pytest.mark.parametrize("script", [ROOT_CLI, NATIVE_CLI], ids=["root", "native"])
def test_every_system_env_file_the_clis_read_is_created_by_the_repo(script: Path):
    paths = _env_paths(script)
    assert paths, f"{script} referenced no env file at all — did the extraction break?"
    orphans = {p: _writers_of(p) for p in sorted(paths)}
    missing = [p for p, writers in orphans.items() if not writers]
    assert not missing, (
        f"{script.relative_to(ROOT)} reads env file(s) nothing in the repo creates: "
        f"{missing}. Point them at what the installer actually writes "
        "(/etc/circuit-breaker/circuit-breaker.env for the packages, "
        "/etc/circuitbreaker/.env for deploy/setup.sh) — or make an installer write them."
    )


def test_binary_mode_env_file_is_defined_once():
    """The four-site duplication is what let the wrong path creep back in."""
    text = ROOT_CLI.read_text()
    assert 'CB_BINARY_ENV_FILE="${CB_BINARY_ENV_FILE:-/etc/circuit-breaker/circuit-breaker.env}"' in text
    assert "/etc/circuit-breaker/env" not in text, (
        "the repo-root cb is back on /etc/circuit-breaker/env; postinstall.sh writes "
        "circuit-breaker.env and the units name circuit-breaker.env"
    )


def test_operator_supplied_paths_are_documented_as_such():
    """Legacy install.conf / host env files are secondary to install identity."""
    assert not _writers_of("/etc/circuit-breaker/env"), (
        "something creates /etc/circuit-breaker/env; packages write circuit-breaker.env"
    )
    docs = DOCS.read_text()
    assert "install-identity.json" in docs
    assert "compatibility" in docs.lower() or "legacy" in docs.lower()
    assert "which the installer places alongside" not in docs


# ── doctor exit behaviour ─────────────────────────────────────────────────────

_STUBBED = ("nc", "psql", "curl", "systemctl", "journalctl", "docker")
_REAL_TOOLS = (
    "bash", "grep", "sed", "tail", "head", "cat", "date", "xargs", "id",
    "stat", "dirname", "basename", "tr", "awk", "cut", "df", "ls", "sleep",
    "mkdir", "rm", "python3", "mktemp", "chmod", "mv",
)


def _bash() -> str:
    found = shutil.which("bash")
    if not found:
        pytest.skip("bash is not installed")
    return found


def _harness(tmp_path: Path, *, healthy: bool) -> tuple[Path, dict[str, str]]:
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    rc = 0 if healthy else 1
    for name in _STUBBED:
        (stubs / name).write_text(f"#!/bin/sh\nexit {rc}\n")
    (stubs / "redis-cli").write_text(
        "#!/bin/sh\necho PONG\n" if healthy else "#!/bin/sh\nexit 1\n"
    )
    (stubs / "circuit-breaker").write_text(
        "#!/bin/sh\necho 'selftest OK'\nexit 0\n"
        if healthy
        else "#!/bin/sh\necho 'selftest FAILED'\nexit 1\n"
    )
    (stubs / "getenforce").write_text("#!/bin/sh\necho Disabled\n")
    if healthy:
        (stubs / "firewall-cmd").write_text('#!/bin/sh\necho "443/tcp"\n')
    for stub in stubs.iterdir():
        stub.chmod(0o755)

    path_dirs = [str(stubs)]
    for tool in _REAL_TOOLS:
        located = shutil.which(tool)
        if located:
            path_dirs.append(str(Path(located).parent))
    seen: set[str] = set()
    ordered: list[str] = []
    for d in path_dirs:
        if d not in seen:
            seen.add(d)
            ordered.append(d)

    env = {
        "PATH": ":".join(ordered),
        "HOME": str(tmp_path / "home"),
        "CB_DOCTOR_LINES": "5",
        "CB_BINARY": str(stubs / "circuit-breaker"),
        "CB_NATIVE_BIN": str(stubs / "circuit-breaker"),
    }
    return stubs, env


def _run(script: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [_bash(), str(script), "doctor"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


@pytest.mark.parametrize("healthy", [False, True], ids=["failing", "healthy"])
def test_native_doctor_exit_status_follows_the_verdict(tmp_path: Path, healthy: bool):
    _, env = _harness(tmp_path, healthy=healthy)
    identity = tmp_path / "install-identity.json"
    (tmp_path / "data").mkdir()
    identity.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "mode": "native",
                "version": "0.4.2",
                "data_dir": str(tmp_path / "data"),
                "cli_path": "/usr/local/bin/cb",
                "health_url": "http://127.0.0.1:8000/api/v1/readyz",
                "installed_at": "2026-09-16T12:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    env = {**env, "CB_IDENTITY_PATH": str(identity)}
    result = _run(NATIVE_CLI, env)
    if healthy:
        assert result.returncode == 0, result.stdout + result.stderr
        assert "All checks passed." in result.stdout
    else:
        assert result.returncode != 0, result.stdout
        assert "FAILED" in result.stdout


@pytest.mark.parametrize("healthy", [False, True], ids=["failing", "healthy"])
def test_root_doctor_exit_status_follows_the_verdict(tmp_path: Path, healthy: bool):
    _, env = _harness(tmp_path, healthy=healthy)
    identity = tmp_path / "pkg-identity.json"
    binary_env = tmp_path / "binary.env"
    binary_env.write_text(f"CB_DATA_DIR={tmp_path / 'absent'}\n")
    identity.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "mode": "package",
                "version": "0.4.2",
                "data_dir": str(tmp_path / "absent"),
                "env_file": str(binary_env),
                "cli_path": "/usr/local/bin/cb",
                "health_url": "http://127.0.0.1:8000/api/v1/readyz",
                "installed_at": "2026-09-16T12:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    env = {
        **env,
        "CB_IDENTITY_PATH": str(identity),
        "CB_BINARY_ENV_FILE": str(binary_env),
    }
    result = _run(ROOT_CLI, env)
    if healthy:
        assert result.returncode == 0, result.stdout + result.stderr
        assert "All checks passed." in result.stdout
    else:
        assert result.returncode != 0, result.stdout
        assert "FAILED" in result.stdout


def test_both_doctors_end_on_the_verdict_not_on_an_echo():
    root = ROOT_CLI.read_text()
    assert root.count("[[ $failed -eq 0 ]]") >= 1
    native = NATIVE_CLI.read_text()
    body = native.split("cmd_doctor()", 1)[1].split("\ncmd_logs()", 1)[0]
    assert "[[ $failed -eq 0 ]]" in body


def test_doctor_does_not_use_eval():
    """Doctor probes must run as argv helpers, not eval'd strings."""
    body = ROOT_CLI.read_text().split("cmd_doctor()", 1)[1].split("\ncmd_logs()", 1)[0]
    assert "eval \"" not in body
    assert "eval '" not in body
    assert "eval $" not in body


@pytest.mark.parametrize("script", [ROOT_CLI, NATIVE_CLI], ids=["root", "native"])
def test_doctor_runs_artifact_selftest(tmp_path: Path, script: Path):
    """cb doctor must run the artifact self-test and report its result."""
    _, env = _harness(tmp_path, healthy=True)
    identity = tmp_path / "install-identity.json"
    (tmp_path / "data").mkdir()
    identity.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "mode": "native",
                "version": "0.4.2",
                "data_dir": str(tmp_path / "data"),
                "cli_path": "/usr/local/bin/cb",
                "health_url": "http://127.0.0.1:8000/api/v1/readyz",
                "installed_at": "2026-09-16T12:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    env = {**env, "CB_IDENTITY_PATH": str(identity)}
    result = _run(script, env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "selftest" in result.stdout

