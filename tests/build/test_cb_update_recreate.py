"""`cb update` (docker mode) must not destroy a working install it cannot rebuild.

The docker branch of `cmd_update` stops and removes the running container, then
recreates it from `CB_IMAGE` alone. Two things went wrong in that order:

1. The `--env-file` was optional — `[[ -f "$CB_CONFIG_DIR/env" ]] && env_args=(…)`.
   `~/.circuit-breaker/env` is operator-supplied and nothing in the repo writes it
   (see tests/build/test_cb_cli_contract.py), so an operator who created the
   container with `docker run -e CB_JWT_SECRET=… -e NATS_AUTH_TOKEN=…` and never
   wrote that file had those values live only in the container's own config —
   which `docker rm` deletes. The replacement then started with none of them and
   `docker/entrypoint-mono.sh` exits FATAL on the first missing secret. The check
   has to happen *before* the stop/rm, where refusing still costs nothing.

2. `docker run -d` exits 0 as soon as the container is *created*; the entrypoint's
   FATAL is a restart loop that happens afterwards. So `cb update` printed
   "Updated and restarted." over a dead install. `cb restore` already polls
   /api/v1/livez before it claims success — the update path polls the same way.

Also pinned here: the recreated container must not be handed
`--security-opt seccomp=unconfined`. Nothing in docker-compose.yml or the
documented run command asks for it, and it silently drops the default syscall
filter on every upgrade.

The staging-directory assertions cover `cb restore`, which staged the archive,
the extracted tree and the uncompressed db.sql under /tmp — a 100 MB tmpfs in
the shipped mono container, far smaller than a real snapshot.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ROOT_CLI = ROOT / "cb"
DOCS = ROOT / "docs" / "cb-cli.md"

# `_bash` is borrowed rather than copied: it carries the one registered
# "bash is not installed" skip for this directory (SKIP-025/026's neighbour in
# specs/1.0.0/release-control/skip-register.csv), and a second copy of the
# marker would be a second unregistered skip for the same host condition.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.build.test_cb_cli_contract import _bash  # noqa: E402


def _harness(tmp_path: Path, *, env_file: bool, healthy: bool) -> tuple[Path, dict[str, str]]:
    """A `cb update` sandbox: stubbed docker/curl, and a log of every call.

    `sleep` is stubbed to a no-op so the unhealthy case exhausts the poll in
    milliseconds instead of two minutes.
    """
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    log = tmp_path / "calls.log"

    (stubs / "docker").write_text(
        f'#!/bin/sh\necho "docker $*" >> "{log}"\nexit 0\n'
    )
    (stubs / "curl").write_text(
        f'#!/bin/sh\necho "curl $*" >> "{log}"\nexit {0 if healthy else 1}\n'
    )
    (stubs / "sleep").write_text("#!/bin/sh\nexit 0\n")
    for stub in stubs.iterdir():
        stub.chmod(0o755)

    conf_dir = tmp_path / "conf"
    conf_dir.mkdir()
    (conf_dir / "install.conf").write_text(
        "CB_MODE=docker\n"
        "CB_CONTAINER=circuit-breaker\n"
        "CB_VOLUME=circuit-breaker-data\n"
        "CB_PORT=8080\n"
        "CB_IMAGE=ghcr.io/blkleg/circuitbreaker:latest\n"
    )
    if env_file:
        (conf_dir / "env").write_text("CB_JWT_SECRET=" + "a" * 64 + "\n")

    env = {
        "HOME": str(tmp_path),
        "PATH": f"{stubs}:/usr/bin:/bin",
        "CB_CONFIG_DIR": str(conf_dir),
    }
    return log, env


def _run_update(tmp_path: Path, **kw) -> tuple[subprocess.CompletedProcess, str]:
    log, env = _harness(tmp_path, **kw)
    result = subprocess.run(
        [_bash(), str(ROOT_CLI), "update"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return result, log.read_text() if log.exists() else ""


def test_update_refuses_before_destroying_when_the_env_file_is_missing(tmp_path: Path):
    result, calls = _run_update(tmp_path, env_file=False, healthy=True)

    assert result.returncode != 0, (
        "cb update recreated the container with no --env-file; the replacement "
        "starts without CB_JWT_SECRET and exits FATAL\n" + result.stdout + result.stderr
    )
    assert "docker stop" not in calls, (
        "cb update destroyed the running container before discovering it could "
        "not rebuild one:\n" + calls
    )
    assert "docker rm" not in calls, calls
    assert "docker run" not in calls, calls
    assert "env" in (result.stdout + result.stderr), (
        "the refusal must name the file the operator has to write\n"
        + result.stdout
        + result.stderr
    )


def test_update_passes_the_operator_env_file_to_docker_run(tmp_path: Path):
    result, calls = _run_update(tmp_path, env_file=True, healthy=True)

    assert result.returncode == 0, result.stdout + result.stderr
    run_lines = [line for line in calls.splitlines() if line.startswith("docker run")]
    assert len(run_lines) == 1, calls
    assert f"--env-file {tmp_path / 'conf' / 'env'}" in run_lines[0], run_lines[0]


def test_update_does_not_drop_the_default_seccomp_profile(tmp_path: Path):
    _, calls = _run_update(tmp_path, env_file=True, healthy=True)

    assert "seccomp" not in calls, (
        "the recreated container is handed --security-opt seccomp=unconfined; "
        "nothing in docker-compose.yml or the documented run command needs it\n" + calls
    )


def test_update_confirms_the_replacement_is_healthy_before_claiming_success(tmp_path: Path):
    result, calls = _run_update(tmp_path, env_file=True, healthy=True)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "/api/v1/livez" in calls, (
        "cb update reported success without ever asking the replacement whether "
        "it was serving\n" + calls
    )
    assert "Updated and restarted." in result.stdout


def test_update_reports_a_container_that_never_comes_back_as_a_failure(tmp_path: Path):
    result, calls = _run_update(tmp_path, env_file=True, healthy=False)

    assert "/api/v1/livez" in calls
    assert result.returncode != 0, (
        "the replacement never answered /livez and cb update still exited 0\n"
        + result.stdout
        + result.stderr
    )
    assert "did not become healthy" in (result.stdout + result.stderr)


# ── restore staging (the `cb` half of the snapshot tmpfs defect) ──────────────


def test_restore_stages_on_the_data_volume_not_the_container_tmpfs():
    """/tmp is a 100 MB tmpfs in the mono container; a snapshot is not."""
    text = ROOT_CLI.read_text()
    # Every mention of the staging path must be rooted at ${CB_DATA_DIR}; a bare
    # /tmp/cb-restore anywhere is the defect. The lookbehind is what distinguishes
    # the two, since one is a suffix of the other.
    stray = re.findall(r"(?<!\$\{CB_DATA_DIR\})/tmp/cb-restore\S*", text)
    assert not stray, (
        "cb restore still stages under /tmp, which is a 100 MB tmpfs in the "
        "shipped mono container — the archive, the extracted tree and the "
        f"uncompressed db.sql all have to live under ${{CB_DATA_DIR}}/tmp: {stray}"
    )
    assert "${CB_DATA_DIR}/tmp/cb-restore.tar.gz" in text
    assert "${CB_DATA_DIR}/tmp/cb-restore" in text


def test_restore_creates_its_staging_directory_before_copying_into_it():
    """compose's backend image never creates ${CB_DATA_DIR}/tmp; only the mono entrypoint does."""
    text = ROOT_CLI.read_text()
    mkdir_at = text.find('mkdir -p "${CB_DATA_DIR}/tmp"')
    copy_at = text.find('docker cp "$archive"')
    assert mkdir_at != -1, "nothing creates ${CB_DATA_DIR}/tmp before the archive is copied there"
    assert copy_at != -1, "the restore path no longer copies the archive into the container"
    assert mkdir_at < copy_at, "the staging directory is created after the copy into it"


def test_docs_no_longer_claim_update_works_without_the_env_file():
    docs = DOCS.read_text()
    assert "works without it" not in docs, (
        "docs/cb-cli.md still tells operators `cb update` works without "
        "~/.circuit-breaker/env; the command now refuses rather than recreating "
        "a container with no secrets"
    )


def test_every_container_side_script_that_uses_cb_data_dir_is_given_it():
    """`docker exec` sees the image's ENV, not the entrypoint's exports.

    Neither Dockerfile.mono nor docker/backend.Dockerfile sets `CB_DATA_DIR`;
    `docker/entrypoint-mono.sh` exports it into its own process tree only. So a
    single-quoted `sh -c` body that dereferences `${CB_DATA_DIR}` without an
    explicit `-e` expands it to the empty string — and every staging path in the
    restore block silently becomes `/tmp/...` again, which is the whole defect
    coming back through the side door. The existing calls all pass it; this keeps
    the next one honest.
    """
    text = ROOT_CLI.read_text()
    exec_with_script = re.compile(
        r"docker exec\b(?P<flags>(?:[^\n']|\\\n)*?)sh -c '(?P<body>[^']*)'",
        re.MULTILINE,
    )
    blocks = [m for m in exec_with_script.finditer(text) if "${CB_DATA_DIR}" in m.group("body")]
    assert blocks, "no container-side script uses ${CB_DATA_DIR} — the scan is broken"
    for match in blocks:
        assert '-e "CB_DATA_DIR=${CB_DATA_DIR}"' in match.group("flags"), (
            "this docker exec runs a script that reads ${CB_DATA_DIR} but never "
            "passes it in, so it expands to nothing inside the container:\n"
            + match.group(0)[:400]
        )
