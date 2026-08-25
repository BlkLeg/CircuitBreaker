"""A restore must stop the processes that are actually running, on the layout it is on.

Two defects this file pins:

* `cb restore` in docker/compose mode ran `supervisorctl stop backend workers` — two names
  `docker/supervisord.mono.conf` does not define, against a supervisord with no control
  socket at all. `2>/dev/null` hid the failure and a `_warn … continuing` downgraded it,
  after which the schema was dropped and the dump replayed while the API and six workers
  were still writing.
* `cb`'s `binary` mode is the distro-package layout (`/usr/local/bin/circuit-breaker`,
  `/etc/circuit-breaker/circuit-breaker.env`, `circuit-breaker.service`), but it handed the
  archive to `deploy/scripts/restore.sh`, which had the install.sh-native layout hardcoded:
  it stopped a unit that does not exist there (`|| true`, so silently nothing), dropped the
  database as roles that do not exist there, and wrote the vault key into a file the
  package's unit never reads. A restore reported success and left every encrypted column
  unreadable.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
CB = REPO / "cb"
SUPERVISORD_CONF = REPO / "docker" / "supervisord.mono.conf"
RESTORE_SH = REPO / "deploy" / "scripts" / "restore.sh"


def _cb_source() -> str:
    return CB.read_text(encoding="utf-8")


def _cb_function_body(name: str) -> str:
    src = _cb_source()
    start = src.index(f"{name}()")
    return src[start : src.index("\ncmd_", start + 1)]


# ── supervisord: the programs that exist, and the ones cb stops ──────────────────────


def _supervisord_programs() -> dict[str, int]:
    """Every `[program:NAME]` in the mono supervisord config, with its numprocs."""
    programs: dict[str, int] = {}
    current: str | None = None
    for raw in SUPERVISORD_CONF.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("[program:") and line.endswith("]"):
            current = line[len("[program:") : -1]
            programs[current] = 1
        elif line.startswith("["):
            current = None
        elif current and line.startswith("numprocs"):
            programs[current] = int(line.split("=", 1)[1].strip())
    return programs


def _cb_stop_targets() -> list[str]:
    """The `_CB_APP_PROGRAMS` array `cb` hands to `supervisorctl stop`."""
    match = re.search(r"_CB_APP_PROGRAMS=\(\s*(.*?)\n\)", _cb_source(), re.S)
    assert match, "cb no longer declares the _CB_APP_PROGRAMS array it stops"
    return [token.strip().strip("'\"") for token in match.group(1).split() if token.strip()]


def test_cb_stops_program_names_supervisord_actually_defines() -> None:
    programs = _supervisord_programs()
    for target in _cb_stop_targets():
        name = target[:-2] if target.endswith(":*") else target
        assert name in programs, (
            f"cb stops '{target}', which docker/supervisord.mono.conf does not define — "
            "this is exactly the `backend workers` miss that let the schema be dropped "
            "under a live API"
        )


def test_multi_process_programs_are_addressed_as_a_group() -> None:
    """`numprocs > 1` makes the bare name a *group*; `supervisorctl stop <name>` misses it."""
    programs = _supervisord_programs()
    targets = _cb_stop_targets()
    for name, numprocs in programs.items():
        if numprocs > 1 and name in {t[:-2] for t in targets if t.endswith(":*")} | set(targets):
            assert f"{name}:*" in targets, (
                f"'{name}' runs {numprocs} processes; it must be stopped as '{name}:*'"
            )


def test_every_application_program_is_stopped_and_no_datastore_is() -> None:
    programs = _supervisord_programs()
    stopped = {t[:-2] if t.endswith(":*") else t for t in _cb_stop_targets()}

    application = {n for n in programs if n == "backend-api" or n.startswith("worker-")}
    assert application <= stopped, (
        f"these write to the database during a restore and are not stopped: "
        f"{sorted(application - stopped)}"
    )

    for datastore in ("postgres", "pgbouncer"):
        assert datastore not in stopped, (
            f"'{datastore}' must stay up — it is what is being restored into"
        )


def test_supervisord_exposes_a_control_socket() -> None:
    """Without these sections supervisorctl cannot reach supervisord at all."""
    conf = SUPERVISORD_CONF.read_text(encoding="utf-8")

    for section in ("[unix_http_server]", "[rpcinterface:supervisor]", "[supervisorctl]"):
        assert section in conf, f"supervisord.mono.conf has no {section} — supervisorctl is dead"

    socket_path = re.search(r"^\s*file\s*=\s*(\S+)", conf, re.M)
    server_url = re.search(r"^\s*serverurl\s*=\s*unix://(\S+)", conf, re.M)
    assert socket_path and server_url
    assert socket_path.group(1) == server_url.group(1), (
        "supervisorctl's serverurl points at a different socket than supervisord opens"
    )


def test_a_failed_stop_aborts_the_restore() -> None:
    """Restoring under live writers must not proceed on a warning."""
    body = _cb_function_body("_restore_container")
    stop = body.index('_CB_SUPERVISORCTL[@]}" stop')
    drop = body.index("DROP SCHEMA")
    between = body[stop:drop]

    assert "_fail" in between, "a failed supervisorctl stop must abort, not warn"
    assert "continuing" not in between, "the stop failure is still downgraded to a warning"
    assert "2>/dev/null" not in between, (
        "the stop's own error output is still discarded — that is what hid the miss"
    )
    assert '_CB_SUPERVISORCTL[@]}" status' in between, (
        "nothing reads the state back, so a stop that did nothing still looks like a stop"
    )


def test_cb_names_the_config_supervisord_is_actually_running() -> None:
    """A bare `supervisorctl` finds Debian's /etc/supervisor/supervisord.conf — a
    different file, pointing at a socket nothing is listening on."""
    launched_with = re.search(
        r"supervisord -c (\S+)",
        (REPO / "docker" / "entrypoint-mono.sh").read_text(encoding="utf-8"),
    )
    assert launched_with, "entrypoint-mono.sh no longer launches supervisord with -c"

    ctl = re.search(r"_CB_SUPERVISORCTL=\(supervisorctl -c (\S+)\)", _cb_source())
    assert ctl, "cb invokes supervisorctl without naming a config"
    assert ctl.group(1) == launched_with.group(1)


# ── binary mode: one layout, consistently ────────────────────────────────────────────


def test_cb_binary_restore_hands_restore_sh_the_packaged_layout() -> None:
    """`binary` is the deb/rpm/apk layout; restore.sh must be told so, not assume the other."""
    body = _cb_function_body("_restore_binary")

    assert "CB_ENV_FILE=" in body and "$CB_BINARY_ENV_FILE" in body, (
        "restore.sh is still left to source /etc/circuitbreaker/.env, which the packaged "
        "unit does not read"
    )
    assert "CB_SERVICE_UNIT=" in body, "restore.sh is not told which systemd unit to stop"
    assert "CB_DB_OWNER=" in body and "CB_DB_SUPERUSER=" in body, (
        "restore.sh is not told which database roles this layout uses"
    )


def test_restore_sh_defaults_stay_the_install_sh_native_layout() -> None:
    """It stays directly callable on the layout it was written for."""
    src = RESTORE_SH.read_text(encoding="utf-8")

    assert re.search(r'ENV_FILE="\$\{CB_ENV_FILE:-/etc/circuitbreaker/\.env\}"', src)
    assert re.search(r'CB_SERVICE_UNIT="\$\{CB_SERVICE_UNIT:-circuitbreaker\.target\}"', src)
    assert re.search(r'CB_DB_OWNER="\$\{CB_DB_OWNER:-breaker\}"', src)
    assert re.search(r'CB_DB_SUPERUSER="\$\{CB_DB_SUPERUSER:-postgres\}"', src)
    assert re.search(r'CB_DB_NAME="\$\{CB_DB_NAME:-circuitbreaker\}"', src)


def test_restore_sh_is_syntactically_valid() -> None:
    assert subprocess.run(["bash", "-n", str(RESTORE_SH)], capture_output=True).returncode == 0


# ── restore.sh, actually run against stubs ───────────────────────────────────────────

requires_shell_tools = pytest.mark.skipif(
    any(shutil.which(tool) is None for tool in ("bash", "tar", "gzip", "jq", "rsync", "sha256sum")),
    reason="restore.sh needs tar/gzip/jq/rsync/sha256sum on the host to run at all",
)

VAULT_KEY = "GkPQ8gGf7uJm2QhZ1a3b4c5d6e7f8g9h0iJkLmNoPqQ="


def _snapshot(tmp_path: Path) -> Path:
    inner = tmp_path / "cb-snapshot-20260824-000000"
    (inner / "uploads").mkdir(parents=True)
    (inner / "uploads" / "probe.txt").write_text("kept", encoding="utf-8")
    gz = gzip.compress(b"-- dump\n")
    (inner / "db.sql.gz").write_bytes(gz)
    (inner / "vault.key").write_text(VAULT_KEY, encoding="utf-8")
    (inner / "manifest.json").write_text(
        json.dumps({"db_checksum_sha256": hashlib.sha256(gz).hexdigest(), "cb_version": "1.0.0"}),
        encoding="utf-8",
    )
    dest = tmp_path / "snap.tar.gz"
    with tarfile.open(dest, "w:gz") as tf:
        tf.add(inner, arcname=inner.name)
    return dest


def _stub_bin(tmp_path: Path) -> Path:
    """Stand-ins for the host tools restore.sh drives, each logging its own argv."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name in ("systemctl", "psql", "dropdb", "createdb", "nginx"):
        script = bindir / name
        body = f'#!/bin/sh\necho "{name} $*" >> "$CB_TEST_LOG"\n'
        if name == "psql":
            body += "cat > /dev/null\n"
        if name == "systemctl":
            body += (
                'if [ "$1" = "cat" ] && [ "${CB_TEST_UNIT_KNOWN:-1}" != "1" ]; then exit 1; fi\n'
            )
        body += "exit 0\n"
        script.write_text(body, encoding="utf-8")
        script.chmod(0o755)
    return bindir


def _run_restore(tmp_path: Path, *, unit_known: bool) -> tuple[subprocess.CompletedProcess, Path]:
    archive = _snapshot(tmp_path)
    bindir = _stub_bin(tmp_path)
    log = tmp_path / "calls.log"
    log.write_text("", encoding="utf-8")

    data_dir = tmp_path / "data"
    (data_dir / "uploads").mkdir(parents=True)
    env_file = tmp_path / "circuit-breaker.env"
    env_file.write_text(f"CB_DATA_DIR={data_dir}\nCB_VAULT_KEY=the-old-key\n", encoding="utf-8")

    proc = subprocess.run(
        ["bash", str(RESTORE_SH), str(archive)],
        input="y\n",
        text=True,
        capture_output=True,
        env={
            **os.environ,
            "PATH": f"{bindir}:{os.environ['PATH']}",
            "CB_TEST_LOG": str(log),
            "CB_TEST_UNIT_KNOWN": "1" if unit_known else "0",
            "CB_ENV_FILE": str(env_file),
            "CB_SERVICE_UNIT": "circuit-breaker.service",
            "CB_DB_NAME": "circuitbreaker",
            "CB_DB_OWNER": "circuitbreaker",
            "CB_DB_SUPERUSER": "postgres",
        },
    )
    return proc, env_file


@requires_shell_tools
def test_restore_sh_writes_the_vault_key_where_it_was_told_to(tmp_path: Path) -> None:
    proc, env_file = _run_restore(tmp_path, unit_known=True)

    assert proc.returncode == 0, proc.stderr
    assert f"CB_VAULT_KEY={VAULT_KEY}" in env_file.read_text(encoding="utf-8"), (
        "the vault key went somewhere the packaged unit does not read"
    )
    calls = (tmp_path / "calls.log").read_text(encoding="utf-8")
    assert "systemctl stop circuit-breaker.service" in calls
    assert "-O circuitbreaker" in calls, "the database was recreated owned by the wrong role"


@requires_shell_tools
def test_restore_sh_refuses_a_unit_this_host_does_not_have(tmp_path: Path) -> None:
    """`systemctl stop … || true` on the wrong layout dropped the database under a live service."""
    proc, env_file = _run_restore(tmp_path, unit_known=False)

    assert proc.returncode != 0, "restore.sh proceeded past a service it never stopped"
    calls = (tmp_path / "calls.log").read_text(encoding="utf-8")
    assert "dropdb" not in calls, "the database was dropped anyway"
    assert "the-old-key" in env_file.read_text(encoding="utf-8")
