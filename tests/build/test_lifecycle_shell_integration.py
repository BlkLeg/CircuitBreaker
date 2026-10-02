"""NPM-03/10: every direct-shell lifecycle entrypoint takes the one host lock (sub-plan 03 Task 5a).

install.sh, uninstall.sh, deploy/setup.sh, deploy/scripts/restore.sh and cb each
take the host-wide lifecycle lock (deploy/lib/lifecycle.sh) before their first
conflicting side effect, so a mutation started from any of them refuses with 10
while another entrypoint holds the lock, and changes nothing. The inventory and
the conflict table are specs/install/lifecycle-contract.md §11.

Every case runs the real scripts as separate processes over a disposable state
root through the library's CB_LIFECYCLE_ROOT seam, with every command that
would reach outside the test (docker, systemctl, sudo, curl, the PostgreSQL
client) replaced by a stub that logs its argv. The stub `sudo` never runs what
it is given. The seam is refused as root (ruling R8), so as root every case
skips in place and one root-only case re-runs this module as an unused uid.
"""

from __future__ import annotations

import importlib.util
import os
import re
import secrets
import select
import shutil
import signal
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / "deploy" / "lib" / "lifecycle.sh"
CB = ROOT / "cb"
INSTALL_SH = ROOT / "install.sh"
UNINSTALL_SH = ROOT / "uninstall.sh"
SETUP_SH = ROOT / "deploy" / "setup.sh"
RESTORE_SH = ROOT / "deploy" / "scripts" / "restore.sh"
CONTRACT = ROOT / "specs" / "install" / "lifecycle-contract.md"

AS_ROOT = os.geteuid() == 0
# Root cannot use the disposable-root seam (ruling R8) and would take the real lock.
seam = pytest.mark.skipif(
    AS_ROOT, reason="runs unprivileged: CB_LIFECYCLE_ROOT is refused as root (ruling R8); root re-runs it unprivileged"
)
root_only = pytest.mark.skipif(
    not AS_ROOT, reason="needs root to drop privileges; an unprivileged run executes these cases directly"
)
# The unprivileged uid a root run drops to, as in tests/build/test_lifecycle_lock.py.
DROP_UID = DROP_GID = 54321

HELD = "another lifecycle operation holds the host lock"
LOCKED, PERMISSION = 10, 6


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# restore.sh's own harness (stubs, an env file, uploads, a real snapshot) is reused as is.
_matrix = _load("restore_fault_matrix", ROOT / "tests" / "build" / "test_restore_fault_matrix.py")


def _clean_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if not k.startswith(("CB_", "_CB_"))}


# --- stubs --------------------------------------------------------------------------------

# Logs its argv. docker answers the handful of queries cb and the installers make so the
# happy paths complete; `docker restart` blocks while $CB_TEST_BLOCK exists, which turns a
# running `cb restart` into a lock holder the test controls.
_DOCKER = r"""#!/bin/sh
echo "docker $*" >> "$CB_TEST_LOG"
case "$1" in
  info) exit 0 ;;
  ps) echo "${CB_TEST_CONTAINER:-cbtest}"; exit 0 ;;
  restart)
    if [ -n "${CB_TEST_BLOCK:-}" ]; then
      echo "blocked" > "$CB_TEST_BLOCK.ready"
      while [ -e "$CB_TEST_BLOCK" ]; do sleep 0.05; done
    fi
    exit 0 ;;
  cp)
    case "$2" in
      *:*) src="${2#*:}"; printf 'snapshot' > "$3/$(basename "$src")" ;;
    esac
    exit 0 ;;
  exec)
    case "$*" in
      *"snapshot create"*) echo "/data/backups/cb-snapshot-20261001-000000.tar.gz" ;;
      *"snapshot verify"*) echo "format_version: 1" ;;
      *supervisorctl*status*) echo "backend-api STOPPED" ;;
      *"df -Pk"*) echo "Filesystem 1024-blocks Used Available Capacity Mounted on"
                  echo "/dev/x 10485760 1 10485760 1% /data" ;;
    esac
    exit 0 ;;
esac
exit 0
"""
_LOGGER = '#!/bin/sh\necho "{name} $*" >> "$CB_TEST_LOG"\nexit 0\n'
# A sudo that never escalates. Each entrypoint re-runs itself through
# `sudo -- env CB_LIFECYCLE_ELEVATED=1 HOME=... <allowlist> bash <script> ...`
# (cb_lifecycle_elevate): that re-run is executed as this same unprivileged
# user. By default it keeps the test's environment, and so the CB_LIFECYCLE_ROOT
# seam and the stubs' configuration, which a real sudo would not; with
# CB_TEST_SUDO_CLEAR it clears the environment first, as sudo's env_reset does,
# so only what the re-run passes through env(1) arrives. `sudo -v` answers
# CB_TEST_SUDO_V_RC. Any other command is logged as a side effect, never run.
# Its own invocations go to a separate log so "no side effect" stays checkable.
_SUDO = r"""#!/bin/sh
echo "sudo $*" >> "$CB_TEST_LOG.sudo"
if [ "$1" = "-v" ]; then
  exit "${CB_TEST_SUDO_V_RC:-0}"
fi
while [ $# -gt 0 ]; do
  case "$1" in
    --) shift; break ;;
    -*) shift ;;
    *) break ;;
  esac
done
case "$*" in
  "env CB_LIFECYCLE_ELEVATED=1 "*)
    if [ -n "${CB_TEST_SUDO_CLEAR:-}" ]; then
      exec env -i PATH="$PATH" CB_TEST_LOG="$CB_TEST_LOG" "$@"
    fi
    exec "$@" ;;
esac
echo "sudo $*" >> "$CB_TEST_LOG"
exit 0
"""


def _stubs(tmp_path: Path) -> Path:
    stubs = tmp_path / "stubs"
    stubs.mkdir(exist_ok=True)
    (stubs / "docker").write_text(_DOCKER)
    (stubs / "sudo").write_text(_SUDO)
    for name in ("systemctl", "curl", "journalctl", "pg_dump", "nginx", "userdel", "update-ca-certificates"):
        (stubs / name).write_text(_LOGGER.format(name=name))
    for stub in stubs.iterdir():
        stub.chmod(0o755)
    return stubs


def _calls(log: Path) -> list[str]:
    return log.read_text().splitlines() if log.exists() else []


def _sudo_calls(env: dict[str, str]) -> list[str]:
    return _calls(Path(env["CB_TEST_LOG"] + ".sudo"))


def _reran_through_sudo(env: dict[str, str]) -> bool:
    return any("CB_LIFECYCLE_ELEVATED=1" in call for call in _sudo_calls(env))


# --- a lock holder, through the library (the npm coordinator's native helper's shape) -------


class Holder:
    """A bash process holding the host lock until its stdin closes."""

    def __init__(self, state: Path, label: str = "npm update") -> None:
        script = (
            "set -Eeuo pipefail\n"
            f'source "{LIB}"\n'
            f'cb_lifecycle_lock_acquire "{label}" || exit $?\n'
            'echo ready\nread -r _ || true\n'
        )
        env = {**_clean_env(), "CB_LIFECYCLE_ROOT": str(state)}
        self.p = subprocess.Popen(
            ["bash", "-c", script], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, env=env,
        )
        assert self.p.stdout is not None
        ready, _, _ = select.select([self.p.stdout], [], [], 15)
        assert ready and self.p.stdout.readline().strip() == "ready", self.p.stderr

    def close(self) -> None:
        if self.p.poll() is None:
            assert self.p.stdin is not None
            self.p.stdin.close()
            try:
                self.p.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.p.send_signal(signal.SIGKILL)
                self.p.wait(timeout=15)
        for stream in (self.p.stdout, self.p.stderr):
            if stream is not None:
                stream.close()


@pytest.fixture
def state(tmp_path: Path) -> Path:
    return tmp_path / "lifecycle"


@pytest.fixture
def held(state: Path) -> Iterator[Holder]:
    holder = Holder(state)
    yield holder
    holder.close()


def _lock_is_free(state: Path) -> bool:
    script = f'source "{LIB}"\ncb_lifecycle_lock_acquire "npm status"\n'
    r = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, timeout=30,
        env={**_clean_env(), "CB_LIFECYCLE_ROOT": str(state)}, check=False,
    )
    return r.returncode == 0


def _owner_label(state: Path) -> str:
    lines = (state / "private" / "owner").read_text().splitlines()
    return dict(line.split("=", 1) for line in lines)["label"]


# --- cb ------------------------------------------------------------------------------------


def _cb_env(tmp_path: Path, mode: str, state: Path | None) -> dict[str, str]:
    stubs = _stubs(tmp_path)
    conf = tmp_path / "conf"
    conf.mkdir(exist_ok=True)
    (conf / "install.conf").write_text(
        f"CB_MODE={mode}\nCB_CONTAINER=cbtest\nCB_PORT=8080\nCB_VOLUME=cbtest-data\n"
        f"CB_IMAGE=ghcr.io/blkleg/circuitbreaker:latest\nCB_BACKUP_DIR={tmp_path / 'backups'}\n"
    )
    (conf / "env").write_text(f"CB_JWT_SECRET={secrets.token_hex(32)}\n")
    env = {
        **_clean_env(),
        "HOME": str(tmp_path),
        "PATH": f"{stubs}:/usr/bin:/bin",
        "CB_CONFIG_DIR": str(conf),
        "CB_IDENTITY_PATH": str(tmp_path / "no-install-identity.json"),
        "CB_TEST_LOG": str(tmp_path / "calls.log"),
    }
    if state is not None:
        env["CB_LIFECYCLE_ROOT"] = str(state)
    return env


def _cb(env: dict[str, str], *args: str, stdin: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(CB), *args], cwd=ROOT, env=env, input=stdin,
        capture_output=True, text=True, timeout=120, check=False,
    )


def _archive(tmp_path: Path) -> Path:
    archive = tmp_path / "cb-snapshot-20261001-000000.tar.gz"
    archive.write_bytes(b"\x1f\x8b" + b"\0" * 4094)
    return archive


# Each management action that conflicts with lifecycle work (contract §11).
CB_MUTATORS = {
    "restart": ["restart"],
    "update": ["update"],
    "backup": ["backup"],
    "restore": ["restore", "{archive}", "--yes"],
    "vault-recover": ["vault-recover"],
    "migrate upgrade": ["migrate", "upgrade"],
}
# Commands that only read. They never take the lock and never create its state.
CB_READERS = {
    "status": ["status"],
    "logs": ["logs"],
    "info": ["info"],
    "version": ["version"],
    "setup": ["setup"],
    "config validate": ["config", "validate"],
    "migrate status": ["migrate", "status"],
    "help": ["help"],
    "doctor": ["doctor"],
    "diag": ["diag"],
    "resources": ["resources", "--json"],
    "setup-token": ["setup-token"],
}


def _argv(spec: list[str], tmp_path: Path) -> list[str]:
    return [str(_archive(tmp_path)) if a == "{archive}" else a for a in spec]


@pytest.mark.parametrize("name", sorted(CB_MUTATORS))
@seam
def test_a_cb_mutator_refuses_with_10_and_changes_nothing_while_the_lock_is_held(
    tmp_path: Path, state: Path, held: Holder, name: str
) -> None:
    env = _cb_env(tmp_path, "docker", state)
    r = _cb(env, *_argv(CB_MUTATORS[name], tmp_path))
    assert r.returncode == LOCKED, r.stdout + r.stderr
    assert HELD in r.stderr
    assert _reran_through_sudo(env), "cb took the lock without first becoming root"
    assert _calls(Path(env["CB_TEST_LOG"])) == [], "cb reached docker before it had the lock"
    assert not (tmp_path / "backups").exists(), "cb created its backup directory without the lock"


# Every mode's branch of each mutator: `cb update` locks inside the docker and compose
# branches, and native and binary refuse it before any change, so they take no lock.
CB_MODE_CASES = [
    ("compose", ["update"], LOCKED),
    ("native", ["restart"], LOCKED),
    ("binary", ["restart"], LOCKED),
    ("binary", ["vault-recover"], LOCKED),
    ("native", ["update"], 1),
    ("binary", ["update"], 1),
]


@pytest.mark.parametrize(("mode", "argv", "code"), CB_MODE_CASES, ids=[f"{m}-{' '.join(a)}" for m, a, _ in CB_MODE_CASES])
@seam
def test_each_mode_of_a_cb_mutator_refuses_or_locks_before_any_change(
    tmp_path: Path, state: Path, held: Holder, mode: str, argv: list[str], code: int
) -> None:
    env = _cb_env(tmp_path, mode, state)
    r = _cb(env, *argv)
    assert r.returncode == code, r.stdout + r.stderr
    assert (HELD in r.stderr) == (code == LOCKED), r.stderr
    assert _calls(Path(env["CB_TEST_LOG"])) == [], "cb changed something before it had the lock"


@pytest.mark.parametrize("name", sorted(CB_READERS))
@seam
def test_a_read_only_cb_command_takes_no_lock(tmp_path: Path, state: Path, held: Holder, name: str) -> None:
    env = _cb_env(tmp_path, "docker", state)
    r = _cb(env, *CB_READERS[name])
    assert r.returncode != LOCKED, r.stderr
    assert HELD not in r.stderr
    assert "lifecycle lock" not in r.stderr
    assert not _reran_through_sudo(env), f"cb {name} re-ran itself through sudo"


@pytest.mark.parametrize("name", sorted(CB_READERS))
@seam
def test_a_read_only_cb_command_creates_no_lifecycle_state(tmp_path: Path, state: Path, name: str) -> None:
    env = _cb_env(tmp_path, "docker", state)
    _cb(env, *CB_READERS[name])
    assert not state.exists(), f"cb {name} created the lifecycle state root"


@seam
def test_a_cb_mutator_takes_the_lock_when_it_is_free_and_lets_it_go_at_exit(tmp_path: Path, state: Path) -> None:
    env = _cb_env(tmp_path, "docker", state)
    r = _cb(env, "restart")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "docker restart cbtest" in _calls(Path(env["CB_TEST_LOG"]))
    assert _reran_through_sudo(env)
    assert "lifecycle lock" not in r.stderr, "the docker-mode warning is gone: the command is locked"
    assert _owner_label(state) == "cb restart"
    assert _lock_is_free(state)


@seam
def test_a_native_cb_mutator_makes_its_root_changes_directly_under_the_lock(tmp_path: Path, state: Path) -> None:
    """No step escalates on its own past the lock: systemctl runs in the elevated cb itself."""
    env = _cb_env(tmp_path, "native", state)
    r = _cb(env, "restart")
    assert r.returncode == 0, r.stdout + r.stderr
    assert _calls(Path(env["CB_TEST_LOG"])) == ["systemctl restart circuitbreaker.target"]
    assert _owner_label(state) == "cb restart"


def _cb_function(name: str) -> str:
    body = re.search(rf"^{re.escape(name)}\(\) \{{\n.*?^\}}\n", CB.read_text(), re.DOTALL | re.MULTILINE)
    assert body, f"cb has no {name}()"
    return body.group(0)


def test_cb_backup_hands_back_only_what_it_created() -> None:
    """Root re-run of a Docker-mode backup: never chown an existing directory, a system one above all."""
    backup = re.search(r"^cmd_backup\(\) \{\n(.*?)^\}", CB.read_text(), re.DOTALL | re.MULTILINE)
    assert backup, "cb has no cmd_backup()"
    text = backup.group(1)
    hand_back = [line.strip() for line in text.splitlines() if line.strip().startswith("_cb_hand_back")]
    assert hand_back == ['_cb_hand_back ${created_dirs[@]+"${created_dirs[@]}"} "$out" ${encrypted:+"$encrypted"}']
    assert text.index("_cb_missing_dirs") < text.index('mkdir -p "$backup_dir"')
    assert "chown -h " in _cb_function("_cb_hand_back")


def test_cb_lists_only_the_backup_directories_it_will_create(tmp_path: Path) -> None:
    existing = tmp_path / "existing"
    existing.mkdir()
    script = _cb_function("_cb_missing_dirs") + 'for d in "$@"; do echo "== $d"; _cb_missing_dirs "$d"; done\n'
    r = subprocess.run(
        ["bash", "-c", script, "bash", str(existing), str(existing / "a" / "b"), "/etc"],
        capture_output=True, text=True, timeout=30, check=True,
    )
    assert r.stdout.splitlines() == [
        f"== {existing}",
        f"== {existing / 'a' / 'b'}",
        str(existing / "a" / "b"),
        str(existing / "a"),
        "== /etc",
    ]


@seam
def test_cb_restore_nests_its_safety_backup_in_the_same_lock(tmp_path: Path, state: Path) -> None:
    """The safety snapshot is cmd_backup in the same shell: it joins, it does not deadlock."""
    env = _cb_env(tmp_path, "docker", state)
    r = _cb(env, "restore", str(_archive(tmp_path)), "--yes")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "lifecycle lock" not in r.stderr
    calls = _calls(Path(env["CB_TEST_LOG"]))
    assert any("snapshot create" in c for c in calls), calls
    assert any(c.startswith("docker restart") for c in calls), calls
    assert _owner_label(state) == "cb restore"
    assert _lock_is_free(state)


@seam
def test_cb_restore_hands_the_lock_to_restore_sh(tmp_path: Path, state: Path) -> None:
    """binary mode drives deploy/scripts/restore.sh as a child, which joins through the handoff."""
    matrix_env = _matrix._harness(tmp_path)
    snapshot = _matrix._snapshot(tmp_path)
    with Path(matrix_env["CB_ENV_FILE"]).open("a") as env_file:
        env_file.write(f"CB_DATA_DIR={matrix_env['CB_DATA_DIR']}\n")
    binary = tmp_path / "circuit-breaker"
    binary.write_text("#!/bin/sh\necho format_version: 1\n")
    binary.chmod(0o755)
    env = _cb_env(tmp_path, "binary", state)
    with (Path(env["CB_CONFIG_DIR"]) / "install.conf").open("a") as conf:
        conf.write(
            f"CB_BINARY={binary}\nCB_BINARY_ENV_FILE={matrix_env['CB_ENV_FILE']}\n"
            f"CB_RESTORE_SCRIPT={RESTORE_SH}\nCB_SERVICE_UNIT=cb-test.service\n"
        )
    env.update({k: v for k, v in matrix_env.items() if k not in ("PATH", "HOME", "CB_ENV_FILE", "CB_LIFECYCLE_ROOT")})
    env["PATH"] = matrix_env["PATH"].split(os.pathsep)[0] + os.pathsep + env["PATH"]
    env["CB_DB_SUPERUSER"] = matrix_env["CB_DB_SUPERUSER"]
    r = _cb(env, "restore", str(snapshot), "--yes", "--no-safety-snapshot")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Restore complete" in r.stdout
    assert HELD not in r.stderr
    assert _owner_label(state) == "cb restore"
    assert _lock_is_free(state)


@seam
def test_a_cb_mutator_that_sudo_refuses_stops_with_6_before_anything(tmp_path: Path, state: Path) -> None:
    env = {**_cb_env(tmp_path, "docker", state), "CB_TEST_SUDO_V_RC": "1"}
    r = _cb(env, "restart")
    assert r.returncode == PERMISSION, r.stdout + r.stderr
    assert "sudo cb restart" in r.stderr
    assert _calls(Path(env["CB_TEST_LOG"])) == []
    assert not state.exists()


@seam
def test_a_real_escalation_never_lands_on_the_test_seam(tmp_path: Path, state: Path) -> None:
    """sudo drops CB_LIFECYCLE_ROOT; root refuses it anyway. Either way the seam is not the lock."""
    env = {**_cb_env(tmp_path, "native", state), "CB_TEST_SUDO_CLEAR": "1"}
    # Where cb finds the install without its environment: under HOME, which the re-run carries.
    shutil.copytree(env["CB_CONFIG_DIR"], tmp_path / ".circuit-breaker")
    r = _cb(env, "restart")
    assert r.returncode == PERMISSION, r.stdout + r.stderr
    assert _reran_through_sudo(env)
    assert not state.exists(), "an escalated run took the disposable lock"
    assert _calls(Path(env["CB_TEST_LOG"])) == []


@seam
def test_cb_refuses_with_7_when_the_lifecycle_library_is_not_installed(tmp_path: Path, state: Path) -> None:
    if Path("/usr/local/lib/circuitbreaker/lifecycle.sh").exists() or Path(
        "/opt/circuitbreaker/deploy/lib/lifecycle.sh"
    ).exists():
        pytest.skip("this host has an installed lifecycle library, which a lone cb finds")
    lone = tmp_path / "bin" / "cb"
    lone.parent.mkdir()
    shutil.copy(CB, lone)
    env = _cb_env(tmp_path, "docker", state)
    r = subprocess.run(
        ["bash", str(lone), "restart"], cwd=tmp_path, env=env,
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert r.returncode == 7, r.stdout + r.stderr
    assert "lifecycle.sh" in r.stderr
    assert _calls(Path(env["CB_TEST_LOG"])) == []


# --- restore.sh ----------------------------------------------------------------------------


@seam
def test_restore_sh_refuses_with_10_before_it_stops_anything(tmp_path: Path, state: Path, held: Holder) -> None:
    env = {**_matrix._harness(tmp_path), "CB_LIFECYCLE_ROOT": str(state)}
    r = _matrix._run(_matrix._snapshot(tmp_path), env)
    assert r.returncode == LOCKED, r.stdout + r.stderr
    assert HELD in r.stderr
    assert _matrix._calls(env) == []
    assert Path(env["CB_ENV_FILE"]).read_text() == _matrix.ENV_BEFORE


@seam
def test_restore_sh_that_sudo_refuses_stops_with_6(tmp_path: Path) -> None:
    env = {**_matrix._harness(tmp_path), "CB_TEST_SUDO_V_RC": "1"}
    r = _matrix._run(_matrix._snapshot(tmp_path), env)
    assert r.returncode == PERMISSION, r.stdout + r.stderr
    assert _matrix._calls(env) == []


# --- uninstall.sh and install.sh, run the way they are downloaded -------------------------


def _installer_env(tmp_path: Path, state: Path | None, *, piped_sudo: bool = True) -> dict[str, str]:
    stubs = _stubs(tmp_path)
    home = tmp_path / "home"
    (home / ".circuit-breaker").mkdir(parents=True, exist_ok=True)
    (home / ".circuit-breaker" / "keep").write_text("operator config\n")
    env = {
        **_clean_env(),
        "HOME": str(home),
        "PATH": f"{stubs}:/usr/bin:/bin",
        "CB_CONFIG_DIR": str(home / ".circuit-breaker"),
        "CB_IDENTITY_PATH": str(tmp_path / "no-install-identity.json"),
        "CB_TEST_LOG": str(tmp_path / "calls.log"),
        "TERM": "dumb",
    }
    if state is not None:
        env["CB_LIFECYCLE_ROOT"] = str(state)
    if piped_sudo:
        # A piped script has no file to re-run, so it is run as `curl ... | sudo bash`:
        # over the seam that is the elevated, still unprivileged, process.
        env["CB_LIFECYCLE_ELEVATED"] = "1"
    return env


def _piped(script: Path, env: dict[str, str], cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """`curl -fsSL .../script | bash -s -- args`: no file, no deploy/ beside it."""
    return subprocess.run(
        ["bash", "-s", "--", *args], input=script.read_text(), cwd=cwd, env=env,
        capture_output=True, text=True, timeout=120, check=False,
    )


@seam
def test_a_piped_uninstall_sh_refuses_with_10_and_removes_nothing(tmp_path: Path, state: Path, held: Holder) -> None:
    env = _installer_env(tmp_path, state)
    r = _piped(UNINSTALL_SH, env, tmp_path, "--keep-data")
    assert r.returncode == LOCKED, r.stdout + r.stderr
    assert HELD in r.stderr
    assert _calls(Path(env["CB_TEST_LOG"])) == [], "uninstall.sh reached docker or sudo before it had the lock"
    assert (Path(env["CB_CONFIG_DIR"]) / "keep").exists()


@seam
def test_a_piped_uninstall_sh_takes_the_lock_when_it_is_free(tmp_path: Path, state: Path) -> None:
    env = _installer_env(tmp_path, state)
    r = _piped(UNINSTALL_SH, env, tmp_path, "--keep-data")
    assert r.returncode == 0, r.stdout + r.stderr
    assert _owner_label(state) == "uninstall.sh"
    assert _lock_is_free(state)


@seam
def test_uninstall_sh_of_a_native_install_re_runs_through_sudo_and_refuses_with_10(
    tmp_path: Path, state: Path, held: Holder
) -> None:
    identity = tmp_path / "install-identity.json"
    identity.write_text(
        '{"schema_version": 1, "mode": "native", "version": "0.4.7", "installed_at": "2026-10-01T00:00:00Z"}\n'
    )
    env = {**_installer_env(tmp_path, state, piped_sudo=False), "CB_IDENTITY_PATH": str(identity)}
    r = subprocess.run(
        ["bash", str(UNINSTALL_SH), "--keep-data"], cwd=tmp_path, env=env,
        capture_output=True, text=True, timeout=120, check=False,
    )
    assert r.returncode == LOCKED, r.stdout + r.stderr
    assert _reran_through_sudo(env)
    assert _calls(Path(env["CB_TEST_LOG"])) == []


@pytest.mark.parametrize(("script", "args"), [(UNINSTALL_SH, ["--keep-data"]), (INSTALL_SH, ["--docker"])],
                         ids=["uninstall.sh", "install.sh"])
@seam
def test_a_piped_script_run_without_sudo_stops_with_6_and_names_sudo(
    tmp_path: Path, state: Path, script: Path, args: list[str]
) -> None:
    env = _installer_env(tmp_path, state, piped_sudo=False)
    r = _piped(script, env, tmp_path, *args)
    assert r.returncode == PERMISSION, r.stdout + r.stderr
    assert "sudo bash" in r.stdout + r.stderr
    assert _calls(Path(env["CB_TEST_LOG"])) == []
    assert not state.exists()
    assert (Path(env["CB_CONFIG_DIR"]) / "keep").exists()


PIPED_CASES = [(INSTALL_SH, ["--docker"]), (INSTALL_SH, ["--unattended"]), (UNINSTALL_SH, ["--keep-data"])]


def _plant_bash(directory: Path) -> Path:
    """An executable ./bash that records it ran: what an attacker leaves in a shared directory."""
    marker = directory / "planted-ran"
    planted = directory / "bash"
    planted.write_text(f'#!/bin/sh\ntouch "{marker}"\n')
    planted.chmod(0o755)
    return marker


@pytest.mark.parametrize(("script", "args"), PIPED_CASES, ids=["install.sh-docker", "install.sh-native", "uninstall.sh"])
@seam
def test_a_piped_script_never_re_runs_a_file_from_the_working_directory(
    tmp_path: Path, state: Path, script: Path, args: list[str]
) -> None:
    """Piped, bash names the script "bash" inside a function; a ./bash in the working directory must never run.

    v0.4.6's install.sh passed that in-function BASH_SOURCE[0] to sudo, so `curl ... | bash`
    from a directory holding ./bash ran the planted file as root.
    """
    marker = _plant_bash(tmp_path)
    env = _installer_env(tmp_path, state, piped_sudo=False)
    r = _piped(script, env, tmp_path, *args)
    assert not marker.exists(), "the planted ./bash ran"
    assert r.returncode == PERMISSION, r.stdout + r.stderr
    assert "read from a pipe" in r.stdout + r.stderr
    assert "sudo bash" in r.stdout + r.stderr
    assert not any("CB_LIFECYCLE_ELEVATED" in call for call in _sudo_calls(env)), _sudo_calls(env)
    assert _calls(Path(env["CB_TEST_LOG"])) == []
    assert not state.exists()


# A script that sources the library and asks it to re-run $1: the shape of every caller.
_ELEVATE_CALLER = 'source "{lib}"\ncb_lifecycle_elevate "$1" a "b c" || exit $?\necho "elevate returned 0"\n'


def _elevate_env(tmp_path: Path) -> dict[str, str]:
    return {
        **{k: v for k, v in _clean_env().items() if k != "NO_COLOR"},
        "HOME": str(tmp_path),
        "TERM": "dumb",
        "PATH": f"{_stubs(tmp_path)}:/usr/bin:/bin",
        "CB_TEST_LOG": str(tmp_path / "calls.log"),
    }


@seam
@pytest.mark.parametrize("target", ["bash", "other.sh", "missing.sh", ""])
def test_elevate_re_runs_nothing_but_the_running_script(tmp_path: Path, target: str) -> None:
    """A path that is not the file bash is executing, even an existing one, is never handed to sudo."""
    marker = _plant_bash(tmp_path)
    (tmp_path / "other.sh").write_text("#!/bin/sh\nexit 0\n")
    caller = tmp_path / "caller.sh"
    caller.write_text(_ELEVATE_CALLER.format(lib=LIB))
    env = _elevate_env(tmp_path)
    r = subprocess.run(
        ["/usr/bin/bash", str(caller), target], cwd=tmp_path, env=env,
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert r.returncode == PERMISSION, r.stdout + r.stderr
    assert "Nothing was changed" in r.stderr
    assert not marker.exists()
    assert not _reran_through_sudo(env), _sudo_calls(env)


@seam
def test_elevate_refuses_a_real_file_when_bash_reads_the_script_from_a_pipe(tmp_path: Path) -> None:
    """Piped, the shell holds no script file open, so even an existing path is not re-run as root."""
    caller = tmp_path / "caller.sh"
    caller.write_text(_ELEVATE_CALLER.format(lib=LIB))
    env = _elevate_env(tmp_path)
    r = subprocess.run(
        ["bash", "-s", "--", str(caller)], input=caller.read_text(), cwd=tmp_path, env=env,
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert r.returncode == PERMISSION, r.stdout + r.stderr
    assert "not the script being run" in r.stderr
    assert not _reran_through_sudo(env), _sudo_calls(env)


@seam
def test_elevate_refuses_the_v0_4_6_shape_of_a_piped_caller(tmp_path: Path) -> None:
    """The released defect, against the library alone: a piped script passing its in-function BASH_SOURCE[0]."""
    marker = _plant_bash(tmp_path)
    script = (
        LIB.read_text()
        + '\nrequire_root() { cb_lifecycle_elevate "${BASH_SOURCE[0]:-}" "$@"; }\n'
        + 'require_root --docker || exit $?\necho "elevate returned 0"\n'
    )
    env = _elevate_env(tmp_path)
    r = subprocess.run(
        ["bash", "-s"], input=script, cwd=tmp_path, env=env,
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert r.returncode == PERMISSION, r.stdout + r.stderr
    assert not marker.exists(), "the planted ./bash ran"
    assert not _reran_through_sudo(env), _sudo_calls(env)


@seam
def test_elevate_re_runs_the_canonical_path_of_the_running_script(tmp_path: Path) -> None:
    """Named relatively, or through a symlink, the script is re-run by its absolute, resolved path."""
    real = tmp_path / "real"
    real.mkdir()
    caller = real / "caller.sh"
    caller.write_text(_ELEVATE_CALLER.format(lib=LIB))
    link = tmp_path / "linked.sh"
    link.symlink_to(caller)
    env = _elevate_env(tmp_path)
    r = subprocess.run(
        ["bash", "linked.sh", "./linked.sh"], cwd=tmp_path, env=env,
        capture_output=True, text=True, timeout=30, check=False,
    )
    # The stub re-run is still unprivileged and has no seam, so it stops with 6.
    assert r.returncode == PERMISSION, r.stdout + r.stderr
    reruns = [call for call in _sudo_calls(env) if "CB_LIFECYCLE_ELEVATED=1" in call]
    assert reruns == [
        f"sudo -- env CB_LIFECYCLE_ELEVATED=1 HOME={tmp_path} TERM=dumb bash {caller.resolve()} a b c"
    ], reruns


# The steering variables cb, the installers and restore.sh read: none of them may follow
# the operator into the root re-run.
STEERING = (
    "CB_BINARY", "CB_NATIVE_BIN", "CB_BINARY_ENV_FILE", "CB_IDENTITY_PATH", "CB_CONFIG_DIR",
    "CB_BACKUP_DIR", "CB_ROOT_PREFIX", "CB_LIFECYCLE_ROOT", "CB_LIFECYCLE_LOCK_FD", "CB_ADMIN_TOKEN",
)


@seam
def test_the_root_re_run_carries_only_the_allowlist(tmp_path: Path, state: Path) -> None:
    """sudo gets no -E: the re-run receives HOME, the marker and the documented switches, nothing else.

    Run through a sudo that resets the environment as a real one does, the seam does not arrive,
    and the unprivileged re-run refuses with 6 instead of taking the disposable lock.
    """
    env = {**_cb_env(tmp_path, "docker", state), "CB_TEST_SUDO_CLEAR": "1", "TERM": "dumb",
           "CB_AIRGAP": "true", "CB_VERBOSE": "true", "CB_ASSUME_YES": "1", "NO_COLOR": "1"}
    for name in STEERING:
        env.setdefault(name, str(tmp_path / "steer" / name))
    shutil.copytree(env["CB_CONFIG_DIR"], tmp_path / ".circuit-breaker")
    r = _cb(env, "restart")
    assert r.returncode == PERMISSION, r.stdout + r.stderr
    assert "sudo did not run this as root" in r.stderr
    assert not state.exists(), "the seam reached the re-run"
    reruns = [call for call in _sudo_calls(env) if "CB_LIFECYCLE_ELEVATED=1" in call]
    assert len(reruns) == 1, _sudo_calls(env)
    words = reruns[0].split()
    assert words[:3] == ["sudo", "--", "env"], reruns
    assert "-E" not in words and not any(w.startswith("--preserve-env") for w in words)
    carried = {w.split("=", 1)[0] for w in words[3 : words.index("bash")]}
    assert carried == {"CB_LIFECYCLE_ELEVATED", "HOME", "TERM", "NO_COLOR", "CB_AIRGAP", "CB_VERBOSE", "CB_ASSUME_YES"}
    assert not carried & set(STEERING)
    assert _calls(Path(env["CB_TEST_LOG"])) == []


@seam
def test_a_piped_install_sh_refusal_echoes_the_real_arguments_and_no_rerun_footer(tmp_path: Path, state: Path) -> None:
    env = _installer_env(tmp_path, state, piped_sudo=False)
    r = _piped(INSTALL_SH, env, tmp_path, "--docker", "--fqdn", "lab host's.example")
    assert r.returncode == PERMISSION, r.stdout + r.stderr
    assert "install.sh | sudo bash -s -- --docker --fqdn lab\\ host\\'s.example" in r.stdout, r.stdout
    assert "Re-run with full output" not in r.stdout + r.stderr
    assert "Full log" not in r.stdout + r.stderr
    assert _calls(Path(env["CB_TEST_LOG"])) == []


@seam
def test_uninstall_sh_from_a_file_re_runs_itself_through_sudo(tmp_path: Path, state: Path) -> None:
    env = _installer_env(tmp_path, state, piped_sudo=False)
    r = subprocess.run(
        ["bash", str(UNINSTALL_SH), "--keep-data"], cwd=tmp_path, env=env,
        capture_output=True, text=True, timeout=120, check=False,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert _reran_through_sudo(env)
    assert _owner_label(state) == "uninstall.sh"
    assert "without the host lifecycle lock" not in r.stdout + r.stderr


@seam
def test_the_native_install_sh_re_runs_through_sudo_and_refuses_with_10_before_anything(
    tmp_path: Path, state: Path, held: Holder
) -> None:
    env = _installer_env(tmp_path, state, piped_sudo=False)
    log = Path("/tmp/cb-bootstrap.log")
    before = log.stat().st_mtime_ns if log.exists() else None
    r = subprocess.run(
        ["bash", str(INSTALL_SH), "--unattended"], cwd=tmp_path, env=env,
        capture_output=True, text=True, timeout=120, check=False,
    )
    assert r.returncode == LOCKED, r.stdout + r.stderr
    assert HELD in r.stderr
    assert _reran_through_sudo(env)
    assert _calls(Path(env["CB_TEST_LOG"])) == []
    assert (log.stat().st_mtime_ns if log.exists() else None) == before, "the bootstrap log was written"


@seam
def test_a_piped_docker_install_sh_refuses_with_10_before_anything(tmp_path: Path, state: Path, held: Holder) -> None:
    env = _installer_env(tmp_path, state)
    r = _piped(INSTALL_SH, env, tmp_path, "--docker", "--unattended")
    assert r.returncode == LOCKED, r.stdout + r.stderr
    assert HELD in r.stderr
    assert _calls(Path(env["CB_TEST_LOG"])) == []
    assert not (Path(env["HOME"]) / ".circuitbreaker").exists()


@seam
def test_install_sh_takes_the_lock_after_root_and_before_its_first_change() -> None:
    """The native path cannot run unprivileged; its order is pinned instead (the journey runs it)."""
    body = re.search(r"^main\(\) \{\n(.*?)^\}", INSTALL_SH.read_text(), re.DOTALL | re.MULTILINE)
    assert body, "install.sh has no main()"
    text = body.group(1)
    native = text.index("cb_require_native_root")
    lock = text.index('cb_take_lifecycle_lock "install.sh', native)
    for first_change in ('LOG_FILE="/tmp/cb-bootstrap.log"', "cb_ui_init", "stage0_bootstrap_preflight"):
        assert native < lock < text.index(first_change), first_change
    docker = text.index("stage_docker_deploy")
    assert text.index("cb_take_lifecycle_lock") < docker


# --- mixed entrypoints contend on the one lock --------------------------------------------


@pytest.fixture
def cb_restart_holding(tmp_path: Path, state: Path) -> Iterator[Path]:
    """A real `cb restart` stopped inside its mutation, holding the lock."""
    work = tmp_path / "holder"
    work.mkdir()
    env = _cb_env(work, "docker", state)
    block = work / "block"
    block.write_text("")
    env["CB_TEST_BLOCK"] = str(block)
    proc = subprocess.Popen(
        ["bash", str(CB), "restart"], cwd=ROOT, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    ready = Path(str(block) + ".ready")
    for _ in range(600):
        if ready.exists() or proc.poll() is not None:
            break
        select.select([], [], [], 0.05)
    assert ready.exists(), f"cb restart never reached docker restart (rc={proc.poll()})"
    yield state
    block.unlink()
    assert proc.wait(timeout=30) == 0


@seam
def test_mixed_entrypoints_lose_to_a_running_cb_mutation(tmp_path: Path, cb_restart_holding: Path) -> None:
    state = cb_restart_holding
    assert _owner_label(state) == "cb restart"

    work = tmp_path / "contenders"
    work.mkdir()
    env = _installer_env(work, state)
    assert _piped(INSTALL_SH, env, work, "--docker", "--unattended").returncode == LOCKED
    assert _piped(UNINSTALL_SH, env, work, "--keep-data").returncode == LOCKED

    restore_work = work / "restore"
    restore_work.mkdir()
    restore_env = {**_matrix._harness(restore_work), "CB_LIFECYCLE_ROOT": str(state)}
    assert _matrix._run(_matrix._snapshot(restore_work), restore_env).returncode == LOCKED
    assert _matrix._calls(restore_env) == []

    cb_work = work / "cb"
    cb_work.mkdir()
    cb_env = _cb_env(cb_work, "docker", state)
    assert _cb(cb_env, "backup").returncode == LOCKED

    native = subprocess.run(
        ["bash", "-c", f'source "{LIB}"; cb_lifecycle_lock_acquire "npm update"'],
        env={**_clean_env(), "CB_LIFECYCLE_ROOT": str(state)},
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert native.returncode == LOCKED, native.stderr
    assert _calls(Path(env["CB_TEST_LOG"])) == []
    assert _calls(Path(cb_env["CB_TEST_LOG"])) == []


# --- setup.sh, sourced into install.sh's shell -------------------------------------------


def _setup_script(body: str) -> str:
    return (
        "set -Eeuo pipefail\n"
        "trap 'echo \"ERR-TRAP: $BASH_COMMAND\" >&2' ERR\n"
        f'source "{LIB}"\n'
        f'source "{SETUP_SH}"\n' + body
    )


@seam
def test_setup_sh_nests_inside_the_installers_lock_and_survives_a_re_source(state: Path) -> None:
    """install.sh holds the lock; setup.sh's stages take it again; stage9 re-sources the library."""
    body = (
        'cb_lifecycle_lock_acquire "install.sh"\n'
        'cb_setup_take_lifecycle_lock\n'
        f'source "{LIB}"\n'
        'cb_setup_take_lifecycle_lock\n'
        'echo ready\nread -r _ || true\n'
    )
    env = {**_clean_env(), "CB_LIFECYCLE_ROOT": str(state)}
    p = subprocess.Popen(
        ["bash", "-c", _setup_script(body)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, env=env,
    )
    try:
        assert p.stdout is not None and p.stdin is not None
        ready, _, _ = select.select([p.stdout], [], [], 30)
        assert ready and p.stdout.readline().strip() == "ready", p.stderr.read() if p.stderr else ""
        assert _owner_label(state) == "install.sh"
        assert not _lock_is_free(state), "a nested setup.sh stage let the installer's lock go"
        p.stdin.close()
        assert p.wait(timeout=30) == 0
        assert p.stderr is not None and "ERR-TRAP" not in p.stderr.read()
    finally:
        if p.poll() is None:
            p.kill()
            p.wait(timeout=15)
        for stream in (p.stdin, p.stdout, p.stderr):
            if stream is not None:
                stream.close()
    assert _lock_is_free(state)


@seam
def test_setup_sh_on_its_own_refuses_with_10_while_the_lock_is_held(state: Path, held: Holder) -> None:
    r = subprocess.run(
        ["bash", "-c", _setup_script("cb_setup_take_lifecycle_lock\necho mutated\n")],
        env={**_clean_env(), "CB_LIFECYCLE_ROOT": str(state)},
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert r.returncode == LOCKED, r.stderr
    assert "mutated" not in r.stdout


@seam
def test_setup_sh_takes_the_lock_before_preflight_and_upgrade() -> None:
    text = SETUP_SH.read_text()
    for function in ("stage0_preflight", "run_upgrade"):
        body = re.search(rf"^{function}\(\) \{{\n(.*?)^\}}", text, re.DOTALL | re.MULTILINE)
        assert body, function
        first = body.group(1).strip().splitlines()[0]
        assert first == "cb_setup_take_lifecycle_lock", f"{function} starts with {first!r}"


# --- the inventory ------------------------------------------------------------------------


@seam
def test_the_contract_records_the_inventory_of_every_locked_entrypoint() -> None:
    text = CONTRACT.read_text()
    section = text[text.index("## 11. Shell entrypoints and the host lock"):]
    for label in ("install.sh", "install.sh upgrade", "install.sh docker", "setup.sh", "uninstall.sh",
                  "restore.sh", *(f"cb {name}" for name in CB_MUTATORS)):
        assert f"`{label}`" in section, label
    for reader in CB_READERS:
        assert f"`cb {reader}`" in section, reader


@seam
def test_every_locked_label_in_the_scripts_is_in_the_inventory() -> None:
    section = CONTRACT.read_text().split("## 11. Shell entrypoints and the host lock", 1)[1]
    labels: set[str] = set()
    for script in (CB, INSTALL_SH, UNINSTALL_SH, SETUP_SH, RESTORE_SH):
        text = script.read_text()
        labels |= set(re.findall(r'(?:_cb_lock|cb_take_lifecycle_lock|cb_lifecycle_lock_acquire) "([a-z][^"$]*)"', text))
    assert labels, "no lock labels found in the shell entrypoints"
    missing = sorted(label for label in labels if f"`{label}`" not in section)
    assert not missing, f"locked in a script but missing from contract §11: {missing}"


@seam
def test_python_flock_on_the_lock_file_is_the_same_lock(tmp_path: Path, state: Path) -> None:
    """The state utility's primitive (fcntl.flock) and cb contend on one inode."""
    assert _lock_is_free(state)
    code = (
        "import fcntl, sys\n"
        "f = open(sys.argv[1], 'rb')\n"
        "fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
        "print('ready', flush=True)\n"
        "sys.stdin.read()\n"
    )
    p = subprocess.Popen(
        [sys.executable, "-c", code, str(state / "private" / "lock")],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
    )
    try:
        assert p.stdout is not None and p.stdout.readline().strip() == "ready"
        env = _cb_env(tmp_path, "docker", state)
        assert _cb(env, "restart").returncode == LOCKED
        assert _calls(Path(env["CB_TEST_LOG"])) == []
    finally:
        assert p.stdin is not None and p.stdout is not None
        p.stdin.close()
        p.wait(timeout=15)
        p.stdout.close()


# --- started as root ---------------------------------------------------------------------------


@root_only
def test_as_root_every_case_runs_unprivileged() -> None:
    assert str(DROP_UID) != Path("/proc/sys/kernel/overflowuid").read_text().strip()
    base = Path(tempfile.mkdtemp(prefix="cb-lifecycle-shell-"))
    try:
        os.chown(base, DROP_UID, DROP_GID)
        env = {
            **_clean_env(), "HOME": str(base), "TMPDIR": str(base), "USER": "cb-lock-test",
            "LOGNAME": "cb-lock-test", "PYTHONDONTWRITEBYTECODE": "1",
        }
        r = subprocess.run(
            [sys.executable, "-m", "pytest", str(Path(__file__).resolve()), "-q", "-rs", "-p", "no:cacheprovider",
             f"--basetemp={base / 'pytest'}"],
            capture_output=True, text=True, cwd=base, env=env, timeout=900, check=False,
            user=DROP_UID, group=DROP_GID, extra_groups=[],
        )
    finally:
        shutil.rmtree(base)
    assert r.returncode == 0, r.stdout + r.stderr
    summary = r.stdout.strip().splitlines()[-1]
    assert re.match(r"\d+ passed", summary), summary
    reasons = re.findall(r"^SKIPPED \[\d+\] \S+: (.*)$", r.stdout, re.MULTILINE)
    allowed = ("needs root to drop privileges", "this host has an installed lifecycle library")
    assert all(reason.startswith(allowed) for reason in reasons), reasons


# --- INT/TERM at the lock boundary (sub-plan 03 Task 5b) ----------------------------------

INTERRUPTED_AFTER = "after changes began"
_JOURNAL = _load("lifecycle_journal_for_signals", ROOT / "tests" / "build" / "test_lifecycle_journal.py")


def _await(condition: object, what: str, seconds: float = 20.0) -> None:
    """Poll a zero-argument predicate until it holds."""
    assert callable(condition)
    for _ in range(int(seconds / 0.05)):
        if condition():
            return
        select.select([], [], [], 0.05)
    pytest.fail(f"timed out waiting for {what}")


def _spawn(argv: list[str], env: dict[str, str], cwd: Path = ROOT) -> subprocess.Popen[str]:
    return subprocess.Popen(
        argv, cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True,
        # A runner may start the suite with SIGINT ignored, and a shell cannot trap what it inherits ignored.
        preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_DFL),  # noqa: PLW1509
    )


def _await_stdout(proc: subprocess.Popen[str], marker: str) -> str:
    """Read the process's stdout until a line contains the marker."""
    assert proc.stdout is not None
    seen = ""
    while marker not in seen:
        ready, _, _ = select.select([proc.stdout], [], [], 20)
        assert ready, f"never saw {marker!r}: {seen}"
        line = proc.stdout.readline()
        assert line, f"stdout closed before {marker!r}: {seen}{proc.stderr.read() if proc.stderr else ''}"
        seen += line
    return seen


def _interrupt(proc: subprocess.Popen[str], sig: int) -> tuple[int, str]:
    proc.send_signal(sig)
    out, err = proc.communicate(timeout=30)
    return proc.returncode, out + err


def _blocking_stub(env: dict[str, str], name: str, trigger: str) -> Path:
    """A stub that, run as `name trigger`, announces itself and blocks while the block file exists."""
    block = Path(env["CB_TEST_LOG"]).parent / f"{name}.block"
    block.write_text("")
    path = Path(env["PATH"].split(os.pathsep)[0]) / name
    path.write_text(
        "#!/bin/sh\n"
        f'echo "{name} $*" >> "$CB_TEST_LOG"\n'
        f'if [ "$1" = "{trigger}" ] || [ "{trigger}" = "*" ]; then\n'
        f'  touch "{block}.ready"\n'
        f'  while [ -e "{block}" ]; do sleep 0.05; done\n'
        "fi\nexit 0\n"
    )
    path.chmod(0o755)
    return block


@seam
def test_restore_sh_interrupted_before_mutation_exits_130_cleans_staging_and_frees_the_lock(
    tmp_path: Path,
) -> None:
    env = {k: v for k, v in _matrix._harness(tmp_path).items() if k != "CB_ASSUME_YES"}
    proc = _spawn(["bash", str(RESTORE_SH), str(_matrix._snapshot(tmp_path))], env)
    _await_stdout(proc, "STOP the Circuit Breaker service")
    scratch = Path(env["TMPDIR"])
    assert any(scratch.iterdir()), "restore.sh had not staged anything to clean up"
    rc, output = _interrupt(proc, signal.SIGINT)
    assert rc == 130, output
    assert INTERRUPTED_AFTER not in output
    assert not any(scratch.iterdir()), "restore.sh left its staging behind"
    assert not [c for c in _matrix._calls(env) if c.startswith(("systemctl stop", "dropdb"))]
    assert _lock_is_free(Path(env["CB_LIFECYCLE_ROOT"]))


@seam
def test_restore_sh_terminated_after_mutation_exits_143_and_keeps_the_lock_until_its_child_exits(
    tmp_path: Path,
) -> None:
    env = _matrix._harness(tmp_path)
    state = Path(env["CB_LIFECYCLE_ROOT"])
    block = _blocking_stub(env, "systemctl", "stop")
    proc = _spawn(["bash", str(RESTORE_SH), str(_matrix._snapshot(tmp_path))], env)
    _await(lambda: Path(f"{block}.ready").exists(), "systemctl stop")
    proc.send_signal(signal.SIGTERM)
    select.select([], [], [], 0.5)
    assert proc.poll() is None, "restore.sh exited while its child was still running"
    assert not _lock_is_free(state), "the lock was released while a child was still mutating"
    block.unlink()
    out, err = proc.communicate(timeout=30)
    assert proc.returncode == 143, out + err
    assert INTERRUPTED_AFTER in err and "cb doctor" in err
    assert _lock_is_free(state)


@seam
def test_cb_restore_interrupted_before_mutation_exits_130_removes_its_decrypt_staging_and_frees_the_lock(
    tmp_path: Path, state: Path
) -> None:
    env = _cb_env(tmp_path, "docker", state)
    env["TMPDIR"] = str(tmp_path / "scratch")
    Path(env["TMPDIR"]).mkdir()
    block = _blocking_stub(env, "age", "*")
    archive = tmp_path / "snapshot.tar.gz.age"
    archive.write_bytes(b"x")
    identity = tmp_path / "identity.txt"
    identity.write_text("placeholder\n")
    proc = _spawn(["bash", str(CB), "restore", str(archive), "--identity", str(identity), "--yes"], env)
    _await(lambda: Path(f"{block}.ready").exists(), "age")
    assert any(Path(env["TMPDIR"]).iterdir()), "cb restore had not staged anything"
    proc.send_signal(signal.SIGINT)
    block.unlink()  # the trap waits for the running child, so let it finish
    out, err = proc.communicate(timeout=30)
    assert proc.returncode == 130, out + err
    assert INTERRUPTED_AFTER not in out + err
    assert not any(Path(env["TMPDIR"]).iterdir()), "cb restore left its decrypt staging behind"
    assert _lock_is_free(state)


@seam
def test_cb_terminated_after_mutation_exits_143_and_keeps_the_lock_until_its_child_exits(
    tmp_path: Path, state: Path
) -> None:
    env = _cb_env(tmp_path, "docker", state)
    block = tmp_path / "block"
    block.write_text("")
    env["CB_TEST_BLOCK"] = str(block)
    proc = _spawn(["bash", str(CB), "restart"], env)
    _await(lambda: Path(f"{block}.ready").exists(), "docker restart")
    proc.send_signal(signal.SIGTERM)
    select.select([], [], [], 0.5)
    assert proc.poll() is None, "cb exited while docker restart was still running"
    assert not _lock_is_free(state)
    block.unlink()
    out, err = proc.communicate(timeout=30)
    assert proc.returncode == 143, out + err
    assert INTERRUPTED_AFTER in err and "cb doctor" in err
    assert _lock_is_free(state)


def _function_of(path: Path, name: str) -> str:
    body = re.search(rf"^{re.escape(name)}\(\) \{{\n.*?^\}}\n", path.read_text(), re.DOTALL | re.MULTILINE)
    assert body, f"{path.name} has no {name}()"
    return body.group(0)


@seam
def test_install_sh_lock_function_interrupted_before_mutation_exits_130_and_frees_the_lock(
    tmp_path: Path, state: Path
) -> None:
    """install.sh's own cb_take_lifecycle_lock, then a wait: INT before the first change."""
    script = (
        "set -Eeuo pipefail\n"
        f'source "{LIB}"\n'
        + _function_of(INSTALL_SH, "cb_take_lifecycle_lock")
        + 'cb_take_lifecycle_lock "install.sh"\necho ready\nwhile :; do sleep 0.05; done\n'
    )
    proc = _spawn(["bash", "-c", script], {**_clean_env(), "CB_LIFECYCLE_ROOT": str(state)})
    _await_stdout(proc, "ready")
    assert not _lock_is_free(state)
    rc, output = _interrupt(proc, signal.SIGINT)
    assert rc == 130, output
    assert INTERRUPTED_AFTER not in output
    assert _lock_is_free(state)


def test_every_installer_marks_its_first_change_after_the_lock() -> None:
    """The mark sits at the entrypoint's first change, after the lock call and before it."""
    expectations = {
        INSTALL_SH: ['cb_take_lifecycle_lock "install.sh docker"', "cb_lifecycle_mark_mutation", "stage_docker_deploy"],
    }
    for path, order in expectations.items():
        text = path.read_text()
        main = text[text.index("\nmain() {"):]
        positions = [main.index(marker) for marker in order]
        assert positions == sorted(positions), f"{path.name}: {order} are out of order"
    install = INSTALL_SH.read_text()
    assert install.index("cb_lifecycle_mark_mutation", install.index("cb_phase_begin files")) < install.index(
        "stage0_install_bundle", install.index("cb_phase_begin files")
    )
    uninstall = UNINSTALL_SH.read_text()
    lock = uninstall.index('cb_lifecycle_lock_acquire "uninstall.sh"')
    assert lock < uninstall.index("cb_lifecycle_mark_mutation", lock) < uninstall.index("docker stop", lock)
    setup = SETUP_SH.read_text()
    for stage in ("stage1_bootstrap() {", "run_upgrade() {"):
        start = setup.index(stage)
        assert "cb_lifecycle_mark_mutation" in setup[start:start + 400], stage


@seam
def test_an_orchestrated_operation_records_the_interruption_checkpoint(tmp_path: Path, state: Path) -> None:
    plane = tmp_path / "plane"
    plane.mkdir()
    for source in (LIB, ROOT / "deploy" / "scripts" / "lifecycle-state.py", ROOT / "deploy" / "lib" / "bundle-signature.sh"):
        shutil.copyfile(source, plane / source.name)
        (plane / source.name).chmod(0o755 if source.suffix == ".py" else 0o644)
    plane.chmod(0o755)

    def run(mark: bool, sig: int) -> tuple[int, str, dict[str, object]]:
        shutil.rmtree(state, ignore_errors=True)
        script = (
            "set -Eeuo pipefail\n"
            f'source "{plane / "lifecycle.sh"}"\n'
            f'CB_LIFECYCLE_SYSTEM_PYTHON="{_JOURNAL.SYSTEM_PYTHON}"\n'
            'cb_lifecycle_lock_acquire "cb update" || exit $?\n'
            f"{_JOURNAL.TRANSACTION}"
            "cb_lifecycle_arm_interrupt\n"
            + (
                "cb_lifecycle_checkpoint state=staged || exit $?\n"
                "cb_lifecycle_checkpoint state=verified || exit $?\n"
                "cb_lifecycle_checkpoint state=recovery_saved recovery_operation_id=$CB_LIFECYCLE_OPERATION "
                f"recovery_manifest_digest={_JOURNAL.MANIFEST} || exit $?\n"
                "cb_lifecycle_checkpoint state=applying || exit $?\n"
                "cb_lifecycle_mark_mutation\n"
                if mark
                else ""
            )
            + "echo ready\nwhile :; do sleep 0.05; done\n"
        )
        proc = _spawn(["bash", "-c", script], {**_clean_env(), "CB_LIFECYCLE_ROOT": str(state)})
        _await_stdout(proc, "ready")
        rc, output = _interrupt(proc, sig)
        journals = list((state / "private" / "operations").glob("*/journal.json"))
        assert len(journals) == 1, output
        import json

        return rc, output, json.loads(journals[0].read_text())

    rc, output, journal = run(False, signal.SIGINT)
    last = journal["checkpoints"][-1]
    assert rc == 130, output
    assert (last["state"], last["cause"], last["outcome"]) == ("interrupted", "interrupted", "interrupted"), journal

    rc, output, journal = run(True, signal.SIGTERM)
    last = journal["checkpoints"][-1]
    assert rc == 143, output
    assert INTERRUPTED_AFTER in output
    assert (last["state"], last["cause"]) == ("recovery_required", "interrupted"), journal
    assert _lock_is_free(state)
