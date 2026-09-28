"""Runtime behavior of scripts/ci/tier2-mono-smoke.sh, driven with stub
`docker`, `curl` and `sudo` binaries.

Nobody can run the real compose smoke on the machine these tests run on
(rootless podman, no compose provider — see the task-1 report). This is the
next best thing: it drives the actual script, unmodified, against fakes that
log every invocation and return scripted output, so the control-flow claims
(the EXIT trap always tears down, the refuse-to-start guard fires before
anything is touched, the diagnostics capture strips secrets) are proven
rather than asserted from reading the text.

The script is copied into an isolated fake repo root rather than pointed at
this repository, because scripts/ci/lib/common.sh derives CB_REPO_ROOT from
its own on-disk location (three directories up from scripts/ci/lib/), not
from an environment variable or the caller's cwd. Copying the same relative
layout into tmp_path makes the copy believe tmp_path is the repository root,
so nothing here can touch this developer's real .env or compose stack.
"""

from __future__ import annotations

import json
import stat
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_SRC = REPO_ROOT / "scripts" / "ci" / "tier2-mono-smoke.sh"
COMMON_SRC = REPO_ROOT / "scripts" / "ci" / "lib" / "common.sh"

_SECRET = "super-secret-value"

DOCKER_STUB = textwrap.dedent(
    r"""
    #!/usr/bin/env bash
    # Records every invocation (one line per call) and returns canned output
    # for the handful of subcommands tier2-mono-smoke.sh actually calls
    # before it fails at the /livez wait (this stub never lets a container
    # become live, so nothing past that point is exercised).
    printf '%s\n' "$*" >> "${STUB_DOCKER_LOG}"

    case "$*" in
      "compose -f docker-compose.yml ps -q")
        printf '%s' "${STUB_PS_Q_OUTPUT:-}"
        exit 0 ;;
      "compose -f docker-compose.yml up -d")
        exit 0 ;;
      "compose -f docker-compose.yml ps")
        echo "NAME               STATUS"
        exit 0 ;;
      "compose -f docker-compose.yml ps -a")
        echo "NAME               STATUS"
        exit 0 ;;
      "compose -f docker-compose.yml logs --no-color --timestamps")
        echo "stub container log"
        exit 0 ;;
      "compose -f docker-compose.yml down -v --remove-orphans")
        exit 0 ;;
      "inspect circuitbreaker")
        cat <<'JSON'
    [{"Id": "stub", "Config": {"Env": ["CB_DB_PASSWORD=super-secret-value", "PATH=/usr/bin"]}}]
    JSON
        exit 0 ;;
      "inspect -f {{.RestartCount}} circuitbreaker")
        echo 0
        exit 0 ;;
      *)
        echo "stub docker: unhandled invocation: $*" >&2
        exit 1 ;;
    esac
    """
).lstrip()

CURL_STUB = textwrap.dedent(
    """
    #!/usr/bin/env bash
    # Simulates a container that never becomes reachable: every probe fails.
    exit 1
    """
).lstrip()

SUDO_STUB = textwrap.dedent(
    r"""
    #!/usr/bin/env bash
    # Drops a leading -n (tier2-mono-smoke.sh always passes it) and execs
    # the rest directly — this test never needs privilege escalation, only
    # the command to actually run.
    args=("$@")
    if [ "${args[0]:-}" = "-n" ]; then
      args=("${args[@]:1}")
    fi
    exec "${args[@]}"
    """
).lstrip()


def _make_executable(path: Path) -> None:
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _sandbox_repo(tmp_path: Path) -> Path:
    """Copy the script and its one dependency into an isolated fake repo."""
    sandbox_root = tmp_path / "repo"
    dest_lib_dir = sandbox_root / "scripts" / "ci" / "lib"
    dest_lib_dir.mkdir(parents=True)
    dest_script = dest_lib_dir.parent / "tier2-mono-smoke.sh"
    dest_script.write_text(SCRIPT_SRC.read_text(encoding="utf-8"), encoding="utf-8")
    (dest_lib_dir / "common.sh").write_text(COMMON_SRC.read_text(encoding="utf-8"), encoding="utf-8")
    _make_executable(dest_script)
    return sandbox_root


def _write_stub(bin_dir: Path, name: str, content: str) -> None:
    path = bin_dir / name
    path.write_text(content, encoding="utf-8")
    _make_executable(path)


def _stub_path_env(tmp_path: Path, *, ps_q_output: str = "") -> tuple[dict, Path]:
    bin_dir = tmp_path / "stubbin"
    bin_dir.mkdir()
    _write_stub(bin_dir, "docker", DOCKER_STUB)
    _write_stub(bin_dir, "curl", CURL_STUB)
    _write_stub(bin_dir, "sudo", SUDO_STUB)
    docker_log = tmp_path / "docker-calls.log"
    docker_log.write_text("", encoding="utf-8")
    env = {
        # Stub bin dir first so docker/curl/sudo resolve to the fakes; the
        # real system dirs after it so bash, python3, coreutils (mkdir, cp,
        # awk, grep, shred, seq, cat) still resolve to the real thing.
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "STUB_DOCKER_LOG": str(docker_log),
        "STUB_PS_Q_OUTPUT": ps_q_output,
        # Fast retry loops: this is a stub run, not a real container.
        "CB_SMOKE_SLEEP": "0",
    }
    return env, docker_log


def _run(sandbox_root: Path, env: dict, image: str = "circuitbreaker:test") -> subprocess.CompletedProcess:
    script = sandbox_root / "scripts" / "ci" / "tier2-mono-smoke.sh"
    return subprocess.run(
        ["bash", str(script), image],
        capture_output=True,
        text=True,
        cwd=sandbox_root,
        env=env,
        timeout=60,
    )


def test_a_container_that_never_goes_live_still_tears_down_and_leaves_evidence(tmp_path):
    """Item 8(a): stub curl always fails the /livez probe. The script must
    exit 1 (not hang, not exit 0), collect_diagnostics must have run (the
    diagnostics dir exists), teardown must have run (.env is gone and
    `docker compose down -v` was actually invoked), and the real exit code
    from the failed assertion — not the trap's own — must be what is
    reported."""
    sandbox_root = _sandbox_repo(tmp_path)
    env, docker_log = _stub_path_env(tmp_path)

    result = _run(sandbox_root, env)

    assert result.returncode == 1, result.stderr
    assert "never reported live" in result.stdout + result.stderr

    diagnostics = sandbox_root / "artifacts" / "diagnostics"
    assert diagnostics.is_dir(), "collect_diagnostics did not run from the EXIT trap"

    assert not (sandbox_root / ".env").exists(), "teardown did not remove .env"

    calls = docker_log.read_text(encoding="utf-8")
    assert "compose -f docker-compose.yml down -v --remove-orphans" in calls, (
        "teardown did not call `docker compose down -v`"
    )


def test_the_inspect_capture_strips_secrets_before_writing_the_artifact(tmp_path):
    """Item 4: the stub docker inspect returns Config.Env holding a live
    secret (CB_DB_PASSWORD=super-secret-value). ::add-mask:: never reaches an
    uploaded artifact, so the secret must not survive into inspect.json."""
    sandbox_root = _sandbox_repo(tmp_path)
    env, _ = _stub_path_env(tmp_path)

    _run(sandbox_root, env)

    inspect_json = sandbox_root / "artifacts" / "diagnostics" / "inspect.json"
    assert inspect_json.is_file(), "the inspect capture did not write a file"
    raw = inspect_json.read_text(encoding="utf-8")
    assert _SECRET not in raw, "the secret from Config.Env leaked into inspect.json"

    parsed = json.loads(raw)
    assert "Env" not in parsed[0]["Config"], "Config.Env was not stripped"


def test_refuses_to_start_when_env_already_exists(tmp_path):
    """Item 1: a pre-existing .env is very likely a developer's real
    deployment config (`cp .env.example .env`). The script must refuse
    before installing the trap, and must not touch that file at all."""
    sandbox_root = _sandbox_repo(tmp_path)
    env, docker_log = _stub_path_env(tmp_path)

    existing_env = sandbox_root / ".env"
    marker = "EXISTING_DEVELOPER_SETTING=do-not-touch\n"
    existing_env.write_text(marker, encoding="utf-8")

    result = _run(sandbox_root, env)

    assert result.returncode == 2, result.stderr
    assert ".env" in result.stderr

    assert existing_env.read_text(encoding="utf-8") == marker, (
        "the refuse-to-start guard must not modify an existing .env"
    )
    # Nothing docker-side should have run at all: the guard for .env fires
    # before the compose-stack check or anything else.
    assert docker_log.read_text(encoding="utf-8") == ""


def test_refuses_to_start_when_a_stack_is_already_running(tmp_path):
    """Item 1: docker-compose.yml pins both the compose project and
    `container_name: circuitbreaker`, so a running stack under that name is
    very likely the developer's own. `up -d` would recreate it and
    teardown's `down -v` would remove it, so the script must refuse first."""
    sandbox_root = _sandbox_repo(tmp_path)
    env, docker_log = _stub_path_env(tmp_path, ps_q_output="existing-container-id")

    result = _run(sandbox_root, env)

    assert result.returncode == 2, result.stderr
    assert "running" in result.stderr.lower()

    assert not (sandbox_root / ".env").exists(), "the guard must not write .env before refusing"

    calls = docker_log.read_text(encoding="utf-8")
    assert "compose -f docker-compose.yml ps -q" in calls
    assert "up -d" not in calls, "the script must not start compose once it has refused"
    assert "down -v" not in calls, "the script must not tear down a stack it never started"
