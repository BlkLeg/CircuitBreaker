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


def _harness(
    tmp_path: Path, *, env_file: bool, healthy: bool, docker_fail: str = ""
) -> tuple[Path, dict[str, str]]:
    """A `cb update` sandbox: stubbed docker/curl, and a log of every call.

    `sleep` is stubbed to a no-op so the unhealthy case exhausts the poll in
    milliseconds instead of two minutes.

    `docker_fail` is a space-separated list of docker subcommands the stub
    should exit 1 on ("rename", "run", "inspect"). The rollback behaviour below
    is only reachable when one of them fails, and a stub that always exits 0
    asserts nothing about it.
    """
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    log = tmp_path / "calls.log"

    (stubs / "docker").write_text(
        "#!/bin/sh\n"
        f'echo "docker $*" >> "{log}"\n'
        "for f in $CB_TEST_DOCKER_FAIL; do\n"
        '  [ "$1" = "$f" ] && { echo "docker: stubbed failure for $1" >&2; exit 1; }\n'
        "done\n"
        "exit 0\n"
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
        "CB_TEST_DOCKER_FAIL": docker_fail,
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


# ── the rollback itself (the `-prev` container is all there is to go back to) ─


def test_a_failed_rename_does_not_destroy_the_container_it_could_not_rename(tmp_path: Path):
    """The rename *is* the rollback; falling back to `docker rm` deletes it.

    The old line was `docker rename ... 2>/dev/null || docker rm "$CB_CONTAINER"`,
    so any rename failure removed the pre-upgrade container with the reason sent
    to /dev/null -- the precise outcome the rename exists to prevent, performed
    silently, after which the failure messages went on to advise rolling back to
    a container that no longer existed.
    """
    result, calls = _run_update(tmp_path, env_file=True, healthy=True, docker_fail="rename")

    removed = [
        line for line in calls.splitlines() if re.match(r"docker rm (-f )?circuit-breaker$", line)
    ]
    assert not removed, (
        "the rename failed and cb update removed the container anyway, destroying "
        "the rollback:\n" + calls
    )
    assert result.returncode != 0, (
        "the rename failed, so there is no rollback -- cb update must stop rather "
        "than press on:\n" + result.stdout + result.stderr
    )
    assert "docker run" not in calls, (
        "cb update replaced the container after failing to set the old one aside\n" + calls
    )
    output = result.stdout + result.stderr
    assert "stubbed failure" in output, (
        "docker rename's own reason was swallowed; the operator is told a rollback "
        "is impossible without being told why\n" + output
    )
    assert "docker start circuit-breaker" in output, (
        "the refusal must say how to bring the untouched container back up\n" + output
    )


def test_the_printed_rollback_command_actually_reaches_the_rename(tmp_path: Path):
    """`docker run` failing at creation leaves no container for `docker rm` to find.

    The message chained the two with `&&`, so pasting it ran `docker rm`, got
    exit 1 for a container that was never created, short-circuited, and never
    reached the rename that restores service. The recovery line is extracted
    from the real output and executed against a stub docker here, because a
    recovery instruction is only worth printing if running it does something.
    """
    result, _ = _run_update(tmp_path, env_file=True, healthy=True, docker_fail="run")
    output = result.stdout + result.stderr

    assert result.returncode != 0, output
    recovery = [
        line.strip()
        for line in output.splitlines()
        if "docker rename circuit-breaker-prev circuit-breaker" in line
    ]
    assert recovery, "the failure named no way back to the previous container\n" + output

    # `docker rm` exits 1 for the container that was never created, exactly as
    # it would against a real daemon.
    replay_log = tmp_path / "replay.log"
    stubs = tmp_path / "stubs"
    (stubs / "docker").write_text(
        f'#!/bin/sh\necho "docker $*" >> "{replay_log}"\n[ "$1" = "rm" ] && exit 1\nexit 0\n'
    )
    (stubs / "docker").chmod(0o755)
    subprocess.run(
        ["/bin/sh", "-c", recovery[0]],
        env={"PATH": f"{stubs}:/usr/bin:/bin"},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    replayed = replay_log.read_text() if replay_log.exists() else ""
    assert "docker rename circuit-breaker-prev circuit-breaker" in replayed, (
        "running the printed recovery never reached the rename -- `docker rm` exited "
        "1 for a container that was never created and the chain short-circuited, so "
        "an operator who pasted it faithfully is still down:\n" + replayed
    )
    assert "docker start circuit-breaker" in replayed, (
        "the recovery renamed the container back but never started it\n" + replayed
    )


def test_no_previous_container_is_not_reported_as_a_rollback(tmp_path: Path):
    """`cb update` with nothing to replace must not promise a `-prev` that is not there."""
    result, calls = _run_update(
        tmp_path, env_file=True, healthy=True, docker_fail="inspect run"
    )
    output = result.stdout + result.stderr

    assert result.returncode != 0, output
    assert "docker rename" not in calls, (
        "there was no container to set aside and cb update renamed one anyway\n" + calls
    )
    advertised = output.replace("docker rm -f circuit-breaker-prev", "")
    assert "circuit-breaker-prev" not in advertised, (
        "the failure advertised a rollback container that was never created\n" + output
    )


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

    `docker/entrypoint-mono.sh` exports `CB_DATA_DIR` into its own process tree
    only, so nothing it does is visible to an exec'd process. Dockerfile.mono
    carries `ENV CB_DATA_DIR=/data` and covers the shipped mono image for that
    reason — but `docker/backend.Dockerfile`, which is compose mode's cb-backend,
    declares no such ENV at all. A single-quoted `sh -c` body that dereferences
    `${CB_DATA_DIR}` without an explicit `-e` expands it to the empty string
    there, and every staging path in the restore block silently becomes
    `/tmp/...` again, which is the whole defect coming back through the side
    door. The existing calls all pass it; this keeps the next one honest.

    (An earlier version of this docstring said neither Dockerfile set it. Only
    the compose one does not; the claim is corrected here rather than dropped,
    because "the mono image is covered" is exactly the reasoning that would
    otherwise justify removing the `-e` from a call site.)
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


def test_every_exec_of_the_application_python_is_given_the_data_dir():
    """The Python reads `CB_DATA_DIR` too, and its fallback is not on the volume.

    The scan above covers `sh -c` bodies, where an unset variable shows up as a
    path that starts with a slash. The other half of the surface is the backend's
    own CLI: `services/db_backup.py` resolves `_data_dir` from this variable at
    import time and falls back to `/var/lib/circuitbreaker`, and
    `services/vault_service.py` falls back to `$PWD/data`. Neither raises. So
    `cb backup` run without it in compose mode builds a snapshot rooted at a path
    the volume is not mounted at — capturing no uploads — and reports success,
    which is the same class of silent-wrong-directory failure as the tmpfs one and
    is why it is pinned beside it rather than trusted to the image.
    """
    text = ROOT_CLI.read_text()
    execs = re.compile(
        r"docker exec\b(?P<flags>(?:[^\n]|\\\n)*?)"
        r"(?:\\\n\s*)?\"\$CB_BACKEND_CONTAINER\"(?P<tail>(?:[^\n]|\\\n)*?python -m app\.cli)",
        re.MULTILINE,
    )
    found = list(execs.finditer(text))
    assert found, "no docker exec runs `python -m app.cli` — the scan is broken"
    for match in found:
        assert '-e "CB_DATA_DIR=${CB_DATA_DIR}"' in match.group("flags"), (
            "this docker exec runs the backend's own CLI without passing "
            "CB_DATA_DIR, so the container resolves its data directory from a "
            "fallback rather than from the volume this install actually uses:\n"
            + match.group(0)[:400]
        )


def test_the_mono_image_and_its_entrypoint_name_the_same_data_directory():
    """Two routes to one directory, and only one of them `docker exec` can see.

    `docker/entrypoint-mono.sh` defaults to /data for the processes it starts;
    `Dockerfile.mono`'s ENV is what an exec'd process gets; and `cb` in docker
    mode addresses that same container at its own default. If any of the three
    drifted, `cb` would be staging a restore, and the backend would be reading
    uploads, in different places — with nothing failing to say so.
    """
    mono = (ROOT / "Dockerfile.mono").read_text()
    entry = (ROOT / "docker" / "entrypoint-mono.sh").read_text()
    cli = ROOT_CLI.read_text()

    image_env = re.search(r"^\s*CB_DATA_DIR=(\S+?)\s*\\?$", mono, re.MULTILINE)
    assert image_env, (
        "Dockerfile.mono no longer sets ENV CB_DATA_DIR. `docker exec` builds its "
        "environment from the image, so without it every `cb` call into the mono "
        "container that forgets an explicit -e resolves the data directory to "
        "something that is not the volume."
    )
    assert image_env.group(1) == "/data", image_env.group(1)

    assert '"${CB_DATA_DIR:-/data}"' in entry, (
        "docker/entrypoint-mono.sh's fallback no longer agrees with the image ENV"
    )
    assert 'CB_DATA_DIR="/data"' in cli, (
        "cb's docker-mode default no longer agrees with the mono image's ENV"
    )


def test_docs_say_which_restore_path_takes_the_bare_pre_upgrade_dump():
    """`cb restore` does not take one; restore.sh does. The docs have to say which."""
    docs = DOCS.read_text()
    assert "pre-upgrade-*.sql" in docs, (
        "docs/cb-cli.md never mentions the bare pre-upgrade dump, which is the "
        "artifact install.sh --upgrade hands the operator as their rollback"
    )
    assert "deploy/scripts/restore.sh" in docs


# ── the restore free-space preflight ─────────────────────────────────────────
#
# Moving staging off /tmp and onto the data volume was right, and it put the space a
# restore transiently needs onto the volume Postgres is writing into: the copied
# archive, the tree it untars to and the gunzipped db.sql all live there at once.
# Running out happens after the schema has been dropped, which is the worst place in
# the sequence to discover it.

_RESTORE_DOCKER_STUB = """#!/bin/sh
echo "docker $*" >> "$CB_TEST_LOG"
case "$1" in
  info) exit 0 ;;
  ps)   echo circuit-breaker; exit 0 ;;
esac
case "$*" in
  *"df -Pk"*)
    # No CB_TEST_FREE_KB models a container whose df cannot answer.
    [ -n "$CB_TEST_FREE_KB" ] || exit 1
    echo "Filesystem 1024-blocks Used Available Capacity Mounted on"
    echo "/dev/vda1 10485760 10485760 $CB_TEST_FREE_KB 99% /data"
    exit 0 ;;
esac
exit 0
"""

# 4 MiB, written for real rather than sparse: `cb` sizes the archive with `du -k`,
# which reports blocks on disk.
_ARCHIVE_KB = 4 * 1024


def _run_restore(tmp_path: Path, free_kb: str) -> tuple[subprocess.CompletedProcess, str]:
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    log = tmp_path / "calls.log"
    (stubs / "docker").write_text(_RESTORE_DOCKER_STUB)
    (stubs / "sleep").write_text("#!/bin/sh\nexit 0\n")
    for stub in stubs.iterdir():
        stub.chmod(0o755)

    conf_dir = tmp_path / "conf"
    conf_dir.mkdir()
    (conf_dir / "install.conf").write_text(
        "CB_MODE=docker\nCB_CONTAINER=circuit-breaker\nCB_PORT=8080\n"
    )

    archive = tmp_path / "cb-snapshot-20260826-020000.tar.gz"
    archive.write_bytes(b"\x1f\x8b" + b"\0" * (_ARCHIVE_KB * 1024 - 2))

    result = subprocess.run(
        [_bash(), str(ROOT_CLI), "restore", str(archive), "--yes", "--no-safety-snapshot"],
        cwd=ROOT,
        env={
            "HOME": str(tmp_path),
            "PATH": f"{stubs}:/usr/bin:/bin",
            "CB_CONFIG_DIR": str(conf_dir),
            "CB_TEST_LOG": str(log),
            "CB_TEST_FREE_KB": free_kb,
        },
        capture_output=True,
        text=True,
        timeout=120,
    )
    return result, log.read_text() if log.exists() else ""


def test_restore_refuses_a_volume_that_cannot_hold_the_unpacked_archive(tmp_path: Path):
    """The refusal has to land before the archive is copied, not during the unpack."""
    result, calls = _run_restore(tmp_path, free_kb="2048")
    output = result.stdout + result.stderr

    assert result.returncode != 0, (
        "cb restore began a restore onto a data volume with less free space than "
        "the archive it was about to unpack there\n" + output + calls
    )
    assert "docker cp" not in calls, (
        "cb restore copied the archive into the container before checking whether "
        "there was room to unpack it:\n" + calls
    )
    assert "Not enough room" in output, output
    assert "4 MiB" in output and "2 MiB" in output, (
        "the refusal does not tell the operator how much is there and how much is "
        "needed, which is the only actionable part of it\n" + output
    )


def test_restore_proceeds_when_the_volume_has_room(tmp_path: Path):
    """The control: the preflight must not be bought by refusing healthy restores."""
    result, calls = _run_restore(tmp_path, free_kb="10485760")
    output = result.stdout + result.stderr

    assert "Not enough room" not in output, output
    assert "docker cp" in calls, (
        "cb restore never reached the copy on a volume with 10 GiB free\n" + output + calls
    )


def test_an_unmeasurable_volume_warns_rather_than_blocking_the_recovery(tmp_path: Path):
    """A recovery is not blocked on a measurement the container could not produce."""
    result, calls = _run_restore(tmp_path, free_kb="")
    output = result.stdout + result.stderr

    assert "Could not measure free space" in output, (
        "df produced nothing and cb restore said nothing about it\n" + output
    )
    assert "docker cp" in calls, (
        "cb restore refused a recovery because df could not answer\n" + output + calls
    )
