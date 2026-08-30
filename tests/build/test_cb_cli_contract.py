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
    """`install.conf` and `~/.circuit-breaker/env` are read but never written.

    No installer creates either one. That is allowed — but the docs used to say
    the installer wrote `install.conf`, which sent users looking for a file that
    never existed. If an installer ever starts writing them, update the docs and
    delete this test; until then it has to stay honest.
    """
    for name in ("install.conf", "$HOME/.circuit-breaker/env"):
        bare = name.split("/")[-1]
        assert not _writers_of(f"/etc/circuit-breaker/{bare}"), (
            f"something now creates {bare}; the docs' 'you write it yourself' wording is stale"
        )

    docs = DOCS.read_text()
    assert "no installer writes it" in docs
    assert "No installer ships the repo-root `cb`" in docs
    assert "## Known gaps" in docs
    assert "which the installer places alongside" not in docs, (
        "docs claim an installer places /usr/local/bin/uninstall-circuit-breaker; nothing does"
    )


# ── doctor exit behaviour ─────────────────────────────────────────────────────

_STUBBED = ("nc", "psql", "curl", "systemctl", "journalctl")
_REAL_TOOLS = (
    "bash", "grep", "sed", "tail", "head", "cat", "date", "xargs", "id",
    "stat", "dirname", "basename", "tr", "awk", "cut", "df", "ls", "sleep",
    "mkdir", "rm",
)


def _harness(tmp_path: Path, *, healthy: bool) -> tuple[Path, dict[str, str]]:
    """A PATH containing only stubs plus the real coreutils the scripts call.

    `sudo` is deliberately absent: the native doctor re-execs itself under sudo
    when it is not root, and without that escape hatch the test could not
    observe the exit status at all.
    """
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    rc = 0 if healthy else 1
    for name in _STUBBED:
        (stubs / name).write_text(f"#!/bin/sh\nexit {rc}\n")
    (stubs / "redis-cli").write_text(
        "#!/bin/sh\necho PONG\n" if healthy else "#!/bin/sh\nexit 1\n"
    )
    # Pinned so the SELinux/firewalld branches behave the same on every host.
    (stubs / "getenforce").write_text("#!/bin/sh\necho Disabled\n")
    if healthy:
        (stubs / "firewall-cmd").write_text('#!/bin/sh\necho "443/tcp"\n')
    for stub in stubs.iterdir():
        stub.chmod(0o755)

    real = tmp_path / "real"
    real.mkdir()
    for tool in _REAL_TOOLS:
        found = shutil.which(tool)
        if found:
            (real / tool).symlink_to(found)

    env = {
        "HOME": str(tmp_path),
        "PATH": f"{stubs}:{real}",
        "CB_DATA_DIR": str(tmp_path / "data"),
    }
    return stubs, env


def _bash() -> str:
    found = shutil.which("bash")
    if not found:
        pytest.skip("bash is not installed")
    return found


def _run(script: Path, env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [_bash(), str(script), "doctor"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


@pytest.mark.skipif(
    os.path.exists("/etc/circuitbreaker/.env"),
    reason="host has a real native install; deploy/cli/cb would source its config",
)
@pytest.mark.parametrize("healthy", [False, True], ids=["failing", "healthy"])
def test_native_doctor_exit_status_follows_the_verdict(tmp_path: Path, healthy: bool):
    _, env = _harness(tmp_path, healthy=healthy)
    result = _run(NATIVE_CLI, env)
    if healthy:
        assert result.returncode == 0, result.stdout + result.stderr
        assert "All systems operational." in result.stdout
    else:
        assert "check(s) failed" in result.stdout
        assert result.returncode != 0, (
            "deploy/cli/cb doctor reported failures and still exited 0 — "
            "nothing polling it can act on the verdict, and the repo-root `cb` "
            "exits non-zero here\n"
            + result.stdout
        )


@pytest.mark.parametrize("healthy", [False, True], ids=["failing", "healthy"])
def test_root_doctor_exit_status_follows_the_verdict(tmp_path: Path, healthy: bool):
    _, env = _harness(tmp_path, healthy=healthy)
    conf_dir = tmp_path / "conf"
    conf_dir.mkdir()
    binary_env = tmp_path / "binary.env"
    # Points the data-dir check at a path that does not exist so it is skipped
    # deterministically, and leaves CB_DB_URL unset so the psql probe is too.
    binary_env.write_text(f"CB_DATA_DIR={tmp_path / 'absent'}\n")
    (conf_dir / "install.conf").write_text(
        f"CB_MODE=binary\nCB_PORT=8080\nCB_BINARY_ENV_FILE={binary_env}\n"
    )
    env = {**env, "CB_CONFIG_DIR": str(conf_dir)}

    result = _run(ROOT_CLI, env)
    if healthy:
        assert result.returncode == 0, result.stdout + result.stderr
        assert "All checks passed." in result.stdout
    else:
        assert "check(s) failed" in result.stdout
        assert result.returncode != 0, result.stdout


def test_both_doctors_end_on_the_verdict_not_on_an_echo():
    """The static half of the same guarantee, so a rewrite cannot lose it."""
    assert ROOT_CLI.read_text().rstrip().count("[[ $failed -eq 0 ]]") >= 1
    native = NATIVE_CLI.read_text()
    body = native.split("cmd_doctor()", 1)[1].split("\ncmd_logs()", 1)[0]
    assert body.rstrip().rstrip("}").rstrip().endswith("[[ $FAILED -eq 0 ]]"), (
        "cmd_doctor must end on the verdict; a trailing echo makes it always exit 0"
    )
