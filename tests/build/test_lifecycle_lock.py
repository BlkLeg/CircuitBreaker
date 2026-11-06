"""NPM-03/10: deploy/lib/lifecycle.sh, the host-wide lifecycle lock, driven through real processes.

Every case runs bash (or Python's fcntl.flock, the primitive the native state
utility uses) as separate processes against a disposable state root under
tmp_path, through the library's CB_LIFECYCLE_ROOT test seam. The seam is
refused as root by design (ruling R8), so when the suite itself runs as root
(a CI image without a USER line) those cases skip in place and one root-only
case re-runs this whole module as an unprivileged uid over a temporary root
that uid owns; root also tests the seam's refusal, and an untrusted owner,
directly. Nothing here touches the real /var/lib/circuitbreaker-lifecycle: an
unprivileged caller of the real lock is refused before the library looks at
the filesystem at all.

Each script runs under `set -Eeuo pipefail` with an ERR trap, the shape of
install.sh, so a library function that trips errexit or the trap shows up as
an `ERR-TRAP` line and fails the case.
"""

from __future__ import annotations

import os
import re
import select
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / "deploy" / "lib" / "lifecycle.sh"
EXIT_CODES_JS = ROOT / "packages" / "cli" / "src" / "exit-codes.js"
FIXED_ROOT = "/var/lib/circuitbreaker-lifecycle"

PRELUDE = (
    "set -Eeuo pipefail\n"
    "trap 'echo \"ERR-TRAP: $BASH_COMMAND\" >&2' ERR\n"
    f'source "{LIB}"\n'
)
# Takes the lock, says so, and holds it until its stdin closes.
HOLD = 'cb_lifecycle_lock_acquire "cb update" || exit $?\necho "ready $$"\nread -r _ || true\n'
# Takes the lock, then performs its "mutation": touching the file named by $MUTATION.
MUTATE = 'cb_lifecycle_lock_acquire "setup.sh upgrade" || exit $?\ntouch "$MUTATION"\n'
OP = "op-20261001-001"

AS_ROOT = os.geteuid() == 0
# Root cannot use the disposable-root seam (ruling R8) and would take the real lock.
seam = pytest.mark.skipif(
    AS_ROOT, reason="runs unprivileged: CB_LIFECYCLE_ROOT is refused as root (ruling R8); root re-runs it unprivileged"
)
# The unprivileged uid and gid a root run drops to. Not nobody (65534): that is the kernel's
# overflow uid, which a user namespace inside the dropped run shows for every unmapped owner,
# so root-owned ancestors would read as owned by the caller itself and be trusted.
DROP_UID = DROP_GID = 54321
root_only = pytest.mark.skipif(
    not AS_ROOT, reason="needs root to drop privileges; an unprivileged run executes these cases directly"
)


def env_for(state: Path | str | None, extra: dict[str, str] | None = None) -> dict[str, str]:
    """The test's environment without any inherited lifecycle variables, plus the seam."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CB_LIFECYCLE_", "_CB_LIFECYCLE_"))}
    if state is not None:
        env["CB_LIFECYCLE_ROOT"] = str(state)
    env.update(extra or {})
    return env


def sh(script: str, state: Path | str | None, extra: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """Run one bash process with the library sourced."""
    return subprocess.run(
        ["bash", "-c", PRELUDE + script],
        capture_output=True, text=True, env=env_for(state, extra), timeout=30, check=False,
    )


def userns(*mapping: str) -> list[str]:
    """The argv prefix of a user namespace with this uid mapping, or a skip where none can be made."""
    argv = ["unshare", "--user", *mapping]
    if shutil.which("unshare") is None or subprocess.run(
        [*argv, "true"], capture_output=True, check=False
    ).returncode != 0:
        pytest.skip(f"needs an unprivileged user namespace (unshare {' '.join(mapping)})")
    return argv


def clean(result: subprocess.CompletedProcess[str]) -> str:
    """Assert that nothing tripped the ERR trap, and return stderr."""
    assert "ERR-TRAP" not in result.stderr, result.stderr
    return result.stderr


def start_ticks(pid: int) -> str:
    """Field 22 of /proc/PID/stat: the process start time, which a reused PID does not share."""
    raw = Path(f"/proc/{pid}/stat").read_text()
    return raw[raw.rindex(")") + 2:].split()[19]


class Proc:
    """A background process that prints one line when ready and runs until its stdin closes."""

    def __init__(self, argv: list[str], env: dict[str, str]) -> None:
        self.p = subprocess.Popen(
            argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
        )
        self._pending = b""

    def line(self, timeout: float = 15) -> str:
        """Read the next stdout line, failing instead of hanging.

        Reads the raw descriptor into our own buffer: select() on the text wrapper misses lines that
        an earlier readline() already pulled into Python's buffer, and would then wait for nothing.
        """
        assert self.p.stdout is not None
        fd = self.p.stdout.fileno()
        while b"\n" not in self._pending:
            ready, _, _ = select.select([fd], [], [], timeout)
            assert ready, "the process printed nothing"
            chunk = os.read(fd, 65536)
            assert chunk, f"the process exited first: rc={self.p.wait()} stderr={self.stderr()}"
            self._pending += chunk
        text, self._pending = self._pending.split(b"\n", 1)
        return text.decode("utf-8", "replace").strip()

    def stderr(self) -> str:
        """Everything the process wrote to stderr; only valid once it has exited."""
        assert self.p.stderr is not None
        return self.p.stderr.read() if self.p.poll() is not None else ""

    def finish(self) -> int:
        """Close stdin and wait for the exit status."""
        assert self.p.stdin is not None
        if not self.p.stdin.closed:
            self.p.stdin.close()
        return self.p.wait(timeout=15)

    def kill(self) -> None:
        """SIGKILL: no trap runs, no cleanup happens."""
        if self.p.poll() is None:
            self.p.send_signal(signal.SIGKILL)
            self.p.wait(timeout=15)

    def close(self) -> None:
        """Kill if still running and close every pipe."""
        self.kill()
        for stream in (self.p.stdin, self.p.stdout, self.p.stderr):
            if stream is not None:
                stream.close()


@pytest.fixture
def procs() -> Iterator[list[Proc]]:
    started: list[Proc] = []
    yield started
    for proc in started:
        proc.close()


def bash_bg(procs: list[Proc], script: str, state: Path, extra: dict[str, str] | None = None) -> Proc:
    proc = Proc(["bash", "-c", PRELUDE + script], env_for(state, extra))
    procs.append(proc)
    return proc


def python_holder(procs: list[Proc], lock: Path) -> Proc:
    """The npm path's native side reaches the same lock through fcntl.flock (Python's stdlib)."""
    code = (
        "import fcntl, sys\n"
        "f = open(sys.argv[1], 'rb')\n"
        "fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
        "print('ready', flush=True)\n"
        "sys.stdin.read()\n"
    )
    proc = Proc([sys.executable, "-c", code, str(lock)], env_for(None))
    procs.append(proc)
    return proc


def contend(state: Path | str | None, tmp_path: Path, extra: dict[str, str] | None = None) -> tuple[int, str]:
    """Try to take the lock and then mutate; report the exit code and whether it mutated."""
    marker = tmp_path / "mutated"
    marker.unlink(missing_ok=True)
    r = sh(MUTATE, state, {"MUTATION": str(marker), **(extra or {})})
    err = clean(r)
    if r.returncode != 0:
        assert not marker.exists(), "mutated without the lock"
    return r.returncode, err


def mode(path: Path) -> int:
    return stat.S_IMODE(path.lstat().st_mode)


def owner_record(state: Path) -> dict[str, str]:
    lines = (state / "private" / "owner").read_text().splitlines()
    return dict(line.split("=", 1) for line in lines)


def make_state(state: Path) -> Path:
    """Create the tree through the library and release it; returns the lock path."""
    r = sh('cb_lifecycle_lock_acquire "cb update"\ncb_lifecycle_lock_release', state)
    assert r.returncode == 0, r.stderr
    clean(r)
    return state / "private" / "lock"


# --- constants and resolution -------------------------------------------------------------


def test_exit_codes_are_the_contract_values() -> None:
    js = dict(re.findall(r"^\s+([A-Z]+): (\d+),$", EXIT_CODES_JS.read_text(), re.MULTILINE))
    lib = dict(re.findall(r"^CB_LIFECYCLE_EXIT_([A-Z]+)=(\d+)$", LIB.read_text(), re.MULTILINE))
    assert lib == {name: js[name] for name in ("USAGE", "PERMISSION", "PREFLIGHT", "MANUAL", "LOCKED")}


def test_the_root_is_fixed_whatever_identity_or_cache_the_caller_has(tmp_path: Path) -> None:
    extra = {
        "CB_DATA_DIR": str(tmp_path / "data"), "CB_IDENTITY_PATH": str(tmp_path / "id.json"),
        "HOME": str(tmp_path / "home"), "XDG_CACHE_HOME": str(tmp_path / "cache"),
        "npm_config_cache": str(tmp_path / "npm"),
    }
    r = sh("cb_lifecycle_root", None, extra)
    assert r.returncode == 0, r.stderr
    assert r.stdout == FIXED_ROOT + "\n"
    clean(r)


@seam
def test_sourcing_and_resolving_create_nothing(tmp_path: Path) -> None:
    state = tmp_path / "state"
    r = sh("cb_lifecycle_root", state)
    assert r.returncode == 0, r.stderr
    assert r.stdout == f"{state}\n"
    assert not state.exists()
    assert list(tmp_path.iterdir()) == []


@seam
def test_an_unprivileged_caller_of_the_real_lock_gets_6_before_anything(tmp_path: Path) -> None:
    code, err = contend(None, tmp_path)
    assert code == 6
    assert "sudo" in err


@pytest.mark.parametrize("value", ["relative/state", "/a/../b", "/a/./b", "/a//b", "/a/b/", "/a\nb", "/a b"])
@seam
def test_a_malformed_seam_path_is_usage(tmp_path: Path, value: str) -> None:
    code, err = contend(value, tmp_path)
    assert code == 2
    assert "CB_LIFECYCLE_ROOT" in err
    assert value not in err, "the refused value is echoed"


def test_the_seam_is_refused_as_root(tmp_path: Path) -> None:
    script = PRELUDE + MUTATE
    env = env_for(tmp_path / "state", {"MUTATION": str(tmp_path / "mutated")})
    argv = ["bash", "-c", script] if AS_ROOT else [*userns("--map-root-user"), "bash", "-c", script]
    r = subprocess.run(argv, capture_output=True, text=True, env=env, timeout=30, check=False)
    assert r.returncode == 2, r.stderr
    assert "CB_LIFECYCLE_ROOT" in clean(r)
    assert not (tmp_path / "state").exists()
    assert not (tmp_path / "mutated").exists()


# --- the private tree ----------------------------------------------------------------------


@seam
def test_first_acquisition_creates_private_modes_under_a_permissive_umask(tmp_path: Path) -> None:
    state = tmp_path / "state"
    r = sh('umask 000\ncb_lifecycle_lock_acquire "cb update"\necho "pid=$BASHPID"', state)
    assert r.returncode == 0, r.stderr
    assert clean(r) == ""
    assert mode(state) == 0o755
    assert mode(state / "private") == 0o700
    assert mode(state / "private" / "lock") == 0o600
    assert mode(state / "private" / "owner") == 0o600
    assert sorted(p.name for p in (state / "private").iterdir()) == ["lock", "owner"]
    assert sorted(p.name for p in state.iterdir()) == ["private"]
    record = owner_record(state)
    assert record["pid"] == r.stdout.strip().removeprefix("pid=")
    assert record["label"] == "cb update"
    assert record["operation"] == ""
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", record["since"])
    assert set(record) == {"pid", "start", "euid", "label", "since", "operation"}


@seam
def test_release_keeps_the_lock_file_and_its_inode(tmp_path: Path, procs: list[Proc]) -> None:
    state = tmp_path / "state"
    lock = make_state(state)
    inode = lock.stat().st_ino
    holder = bash_bg(procs, HOLD + "cb_lifecycle_lock_release\necho released\nread -r _ || true\n", state)
    holder.line()
    assert holder.p.stdin is not None
    holder.p.stdin.write("\n")
    holder.p.stdin.flush()
    assert holder.line() == "released"
    # Released while the process lives on: a contender gets it, and the file stayed put.
    assert contend(state, tmp_path)[0] == 0
    assert lock.stat().st_ino == inode
    assert lock.stat().st_size == 0
    holder.finish()


# --- contention -----------------------------------------------------------------------------


@seam
def test_a_second_caller_gets_10_before_its_mutation_whatever_its_identity(
    tmp_path: Path, procs: list[Proc]
) -> None:
    state = tmp_path / "state"
    holder = bash_bg(procs, HOLD, state, {"CB_DATA_DIR": "/srv/a", "HOME": str(tmp_path / "h1")})
    holder_pid = holder.line().split()[1]
    code, err = contend(state, tmp_path, {"CB_DATA_DIR": "/srv/b", "CB_IDENTITY_PATH": "/x.json", "HOME": "/"})
    assert code == 10
    assert f"pid {holder_pid}" in err
    assert "cb update" in err
    assert holder.finish() == 0
    assert contend(state, tmp_path)[0] == 0


@seam
def test_a_python_flock_holder_and_a_shell_caller_exclude_each_other(tmp_path: Path, procs: list[Proc]) -> None:
    state = tmp_path / "state"
    lock = make_state(state)
    py = python_holder(procs, lock)
    assert py.line() == "ready"
    code, err = contend(state, tmp_path)
    assert code == 10
    # The recorded owner is the long-gone make_state process; it is not named as the holder.
    assert "has exited" in err
    py.finish()

    holder = bash_bg(procs, HOLD, state)
    holder.line()
    try_lock = (
        "import fcntl, sys\nf = open(sys.argv[1], 'rb')\n"
        "try:\n    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)\nexcept BlockingIOError:\n    sys.exit(10)\n"
    )
    probe = subprocess.run(
        [sys.executable, "-c", try_lock, str(lock)], capture_output=True, text=True, timeout=30, check=False,
    )
    assert probe.returncode == 10, probe.stderr
    holder.finish()


@seam
def test_owner_diagnostics_never_carry_argv(tmp_path: Path, procs: list[Proc]) -> None:
    state = tmp_path / "state"
    proc = Proc(
        ["bash", "-c", PRELUDE + HOLD, "cb", "update", "--token=hunter2", "--password", "hunter2"],
        env_for(state, {"CB_ADMIN_PASSWORD": "hunter2"}),
    )
    procs.append(proc)
    proc.line()
    code, err = contend(state, tmp_path)
    assert code == 10
    assert "hunter2" not in err
    assert "hunter2" not in (state / "private" / "owner").read_text()
    proc.finish()


@pytest.mark.parametrize("label", ["", "cb update --token=x", "Cb", "cb\nupdate", "a b c d e", "x" * 65])
@seam
def test_a_label_outside_the_plain_shape_is_refused(tmp_path: Path, label: str) -> None:
    r = sh('cb_lifecycle_lock_acquire "$LABEL" || exit $?', tmp_path / "state", {"LABEL": label})
    assert r.returncode == 2
    clean(r)
    assert not (tmp_path / "state").exists()


# --- handoff ----------------------------------------------------------------------------------


def child_script(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(PRELUDE + body)
    return path


@seam
def test_nested_calls_join_the_held_lock_without_deadlock(tmp_path: Path, procs: list[Proc]) -> None:
    state = tmp_path / "state"
    grandchild = child_script(
        tmp_path, "grandchild.sh",
        'cb_lifecycle_lock_acquire "restore.sh"\necho "grandchild joined $CB_LIFECYCLE_OPERATION"\n'
        "cb_lifecycle_lock_release\n",
    )
    child = child_script(
        tmp_path, "child.sh",
        'cb_lifecycle_lock_acquire "setup.sh upgrade"\necho "child joined $CB_LIFECYCLE_OPERATION"\n'
        'cb_lifecycle_lock_acquire "setup.sh upgrade"\n'  # re-entry in the same shell
        f'bash "{grandchild}"\n'
        "cb_lifecycle_lock_release\n",
    )
    parent = bash_bg(
        procs,
        f'cb_lifecycle_lock_acquire "cb update"\ncb_lifecycle_lock_bind_operation {OP}\n'
        f'bash "{child}"\necho "ready $$"\nread -r _ || true\n',
        state,
    )
    assert parent.line() == f"child joined {OP}"
    assert parent.line() == f"grandchild joined {OP}"
    assert parent.line().startswith("ready ")
    # The children released their copies; the parent still holds the lock.
    assert contend(state, tmp_path)[0] == 10
    assert parent.finish() == 0
    assert "ERR-TRAP" not in parent.stderr()
    assert contend(state, tmp_path)[0] == 0


@pytest.mark.parametrize(
    "fd",
    ["0", "1", "2", "3", "9", "abc", "3; touch pwned", "$(touch pwned)", "99999999999", "-1", " 10", "010"],
)
@seam
def test_a_claim_in_the_environment_alone_grants_nothing(tmp_path: Path, procs: list[Proc], fd: str) -> None:
    state = tmp_path / "state"
    holder = bash_bg(procs, HOLD, state)
    holder.line()
    code, _ = contend(state, tmp_path, {"CB_LIFECYCLE_LOCK_FD": fd, "CB_LIFECYCLE_OPERATION": ""})
    assert code == 10
    code, _ = contend(state, tmp_path, {"_CB_LIFECYCLE_LOCK_FD": fd, "_CB_LIFECYCLE_LOCK_ID": "0:0"})
    assert code == 10
    assert not (Path.cwd() / "pwned").exists()
    assert not (tmp_path / "pwned").exists()
    holder.finish()


@pytest.mark.parametrize("target", ["lock", "other"])
@seam
def test_a_descriptor_that_does_not_hold_the_lock_grants_nothing(
    tmp_path: Path, procs: list[Proc], target: str
) -> None:
    state = tmp_path / "state"
    holder = bash_bg(procs, HOLD, state)
    holder.line()
    (tmp_path / "other").write_text("")
    path = state / "private" / "lock" if target == "lock" else tmp_path / "other"
    marker = tmp_path / "mutated"
    r = sh(f'exec 7<"{path}"\nexport CB_LIFECYCLE_LOCK_FD=7 CB_LIFECYCLE_OPERATION=\n' + MUTATE, state,
           {"MUTATION": str(marker)})
    assert r.returncode == 10
    assert "unproven lock handoff" in clean(r)
    assert not marker.exists()
    holder.finish()


@seam
def test_stale_owner_metadata_grants_nothing(tmp_path: Path, procs: list[Proc]) -> None:
    state = tmp_path / "state"
    lock = make_state(state)
    # A record that names a live process, with an operation, and a PID file beside it.
    live = Proc(["bash", "-c", "echo ready; read -r _ || true"], env_for(None))
    procs.append(live)
    live.line()
    pid = live.p.pid
    (state / "private" / "owner").write_text(
        f"pid={pid}\nstart={start_ticks(pid)}\neuid={os.geteuid()}\nlabel=cb update\n"
        f"since=2026-10-01T00:00:00Z\noperation={OP}\n"
    )
    (state / "private" / "pid").write_text(f"{pid}\n")

    # A fresh descriptor plus the recorded operation, while the lock is free: a normal acquisition.
    r = sh(f'exec 7<"{lock}"\nexport CB_LIFECYCLE_LOCK_FD=7 CB_LIFECYCLE_OPERATION={OP}\n'
           'cb_lifecycle_lock_acquire "install.sh"\necho "op=[$CB_LIFECYCLE_OPERATION] pid=$BASHPID"', state)
    assert r.returncode == 0, r.stderr
    assert "unproven lock handoff" in clean(r)
    op, me = r.stdout.split()
    assert op == "op=[]"
    record = owner_record(state)
    assert record["pid"] == me.removeprefix("pid=")
    assert record["operation"] == ""
    assert record["label"] == "install.sh"

    # The same claim while a Python process holds the lock (and leaves the record stale): 10.
    (state / "private" / "owner").write_text(
        f"pid={pid}\nstart={start_ticks(pid)}\neuid={os.geteuid()}\nlabel=cb update\n"
        f"since=2026-10-01T00:00:00Z\noperation={OP}\n"
    )
    py = python_holder(procs, lock)
    py.line()
    marker = tmp_path / "mutated"
    r = sh(f'exec 7<"{lock}"\nexport CB_LIFECYCLE_LOCK_FD=7 CB_LIFECYCLE_OPERATION={OP}\n' + MUTATE, state,
           {"MUTATION": str(marker)})
    assert r.returncode == 10
    clean(r)
    assert not marker.exists()
    py.finish()
    live.finish()


@pytest.mark.parametrize("claimed", ["op-20261001-002", "op-2026", "op-20260230-001", "", "op-20261001-001\n"])
@seam
def test_the_operation_context_must_match_the_holder(tmp_path: Path, procs: list[Proc], claimed: str) -> None:
    state = tmp_path / "state"
    marker = tmp_path / "mutated"
    child = child_script(tmp_path, "child.sh", MUTATE)
    parent = bash_bg(
        procs,
        f'cb_lifecycle_lock_acquire "cb update"\ncb_lifecycle_lock_bind_operation {OP}\n'
        f'rc=0\nCB_LIFECYCLE_OPERATION="$CLAIMED" bash "{child}" || rc=$?\necho "child $rc"\n'
        f'rc=0\nbash "{child}" || rc=$?\necho "honest $rc"\nread -r _ || true\n',
        state,
        {"CLAIMED": claimed, "MUTATION": str(marker)},
    )
    assert parent.line() == "child 10"
    assert not marker.exists()
    assert parent.line() == "honest 0"
    assert marker.exists()
    assert parent.finish() == 0
    assert "ERR-TRAP" not in parent.stderr()


FORGED_OP = "op-20261001-999"
# Ways a child could arrive carrying the library's internal state, which the same-shell
# fast path used to trust, together with a wrong operation context.
INTERNAL_STATE_CARRIERS = {
    # Exported by hand into the child's environment.
    "environment": (
        "",
        (
            f'_CB_LIFECYCLE_LOCK_FD="$CB_LIFECYCLE_LOCK_FD" _CB_LIFECYCLE_LOCK_DEPTH=1 '
            f'CB_LIFECYCLE_OPERATION={FORGED_OP} bash "$CHILD"'
        ),
    ),
    # The same, naming the child's own PID as the owner (exec keeps the subshell's PID).
    "environment naming the child's pid": (
        "",
        (
            f'( exec env _CB_LIFECYCLE_LOCK_FD="$CB_LIFECYCLE_LOCK_FD" _CB_LIFECYCLE_LOCK_PID="$BASHPID" '
            f'_CB_LIFECYCLE_LOCK_DEPTH=1 CB_LIFECYCLE_OPERATION={FORGED_OP} bash "$CHILD" )'
        ),
    ),
    # A `set -a` span around the acquisition, as cb uses around other assignments.
    "set -a around the acquisition": ("set -a\n", f'CB_LIFECYCLE_OPERATION={FORGED_OP} bash "$CHILD"'),
}


@pytest.mark.parametrize("carrier", list(INTERNAL_STATE_CARRIERS))
@seam
def test_inherited_internal_state_never_skips_the_operation_check(
    tmp_path: Path, procs: list[Proc], carrier: str
) -> None:
    state = tmp_path / "state"
    marker = tmp_path / "mutated"
    child = child_script(tmp_path, "child.sh", 'env | grep -c "^_CB_LIFECYCLE_" >"$SEEN" || true\n' + MUTATE)
    prefix, forged = INTERNAL_STATE_CARRIERS[carrier]
    parent = bash_bg(
        procs,
        f'{prefix}cb_lifecycle_lock_acquire "cb update"\ncb_lifecycle_lock_bind_operation {OP}\nset +a\n'
        f'rc=0\n{forged} || rc=$?\necho "forged $rc"\n'
        'rc=0\nbash "$CHILD" || rc=$?\necho "honest $rc"\nread -r _ || true\n',
        state,
        {"CHILD": str(child), "MUTATION": str(marker), "SEEN": str(tmp_path / "seen")},
    )
    assert parent.line() == "forged 10"
    assert not marker.exists(), "a forged operation context mutated under the lock"
    assert parent.line() == "honest 0"
    assert marker.exists()
    if carrier.startswith("set -a"):
        assert (tmp_path / "seen").read_text().strip() == "0", "set -a exported the library's internal state"
    assert parent.finish() == 0
    assert "ERR-TRAP" not in parent.stderr()


@seam
def test_a_forged_nesting_depth_does_not_outlive_the_childs_release(tmp_path: Path, procs: list[Proc]) -> None:
    # Right descriptor, right operation, and a nesting depth the child never acquired.
    state = tmp_path / "state"
    child = child_script(
        tmp_path, "child.sh",
        'cb_lifecycle_lock_acquire "restore.sh"\ncb_lifecycle_lock_release\n'
        'echo "child after release ${CB_LIFECYCLE_LOCK_FD-unset}"\n',
    )
    parent = bash_bg(
        procs,
        f'cb_lifecycle_lock_acquire "cb update"\ncb_lifecycle_lock_bind_operation {OP}\n'
        '( exec env _CB_LIFECYCLE_LOCK_FD="$CB_LIFECYCLE_LOCK_FD" _CB_LIFECYCLE_LOCK_ID=0:0 '
        '_CB_LIFECYCLE_LOCK_PID="$BASHPID" _CB_LIFECYCLE_LOCK_DEPTH=5 bash "$CHILD" )\nread -r _ || true\n',
        state,
        {"CHILD": str(child)},
    )
    assert parent.line() == "child after release unset"
    assert parent.finish() == 0
    assert "ERR-TRAP" not in parent.stderr()


@seam
def test_reentry_in_the_holding_shell_checks_the_operation_too(tmp_path: Path, procs: list[Proc]) -> None:
    state = tmp_path / "state"
    holder = bash_bg(
        procs,
        f'cb_lifecycle_lock_acquire "cb restore"\ncb_lifecycle_lock_bind_operation {OP}\n'
        f'rc=0\nCB_LIFECYCLE_OPERATION={FORGED_OP} cb_lifecycle_lock_acquire "cb backup" || rc=$?\n'
        'echo "rejoin $rc $CB_LIFECYCLE_OPERATION"\nread -r _ || true\n'
        'cb_lifecycle_lock_release\necho released\nread -r _ || true\n',
        state,
    )
    assert holder.line() == f"rejoin 10 {OP}"
    assert contend(state, tmp_path)[0] == 10
    assert holder.p.stdin is not None
    holder.p.stdin.write("\n")
    holder.p.stdin.flush()
    # One release frees it: the refused rejoin did not count as a nesting level.
    assert holder.line() == "released"
    assert contend(state, tmp_path)[0] == 0
    assert holder.finish() == 0
    assert "ERR-TRAP" not in holder.stderr()


@seam
def test_an_inner_release_keeps_the_outer_lock(tmp_path: Path, procs: list[Proc]) -> None:
    # cb's cmd_restore calls cmd_backup in the same shell, and both take the lock (ruling R10).
    state = tmp_path / "state"
    lock = state / "private" / "lock"
    holder = bash_bg(
        procs,
        'cmd_backup() { cb_lifecycle_lock_acquire "cb backup" || return $?; cb_lifecycle_lock_release; }\n'
        f'cb_lifecycle_lock_acquire "cb restore"\ncb_lifecycle_lock_bind_operation {OP}\n'
        "cmd_backup\ncmd_backup\n"
        # A subshell is its own holder: its release drops its own copy, not a level of the parent's.
        '( cmd_backup; echo "subshell after release ${CB_LIFECYCLE_LOCK_FD-unset}" )\n'
        'echo "ready $CB_LIFECYCLE_LOCK_FD $CB_LIFECYCLE_OPERATION"\nread -r _ || true\n'
        'cb_lifecycle_lock_release\necho "released ${CB_LIFECYCLE_LOCK_FD-unset}"\nread -r _ || true\n',
        state,
    )
    assert holder.line() == "subshell after release unset"
    ready = holder.line().split()
    assert ready[0] == "ready" and ready[2:] == [OP]
    assert contend(state, tmp_path)[0] == 10
    try_lock = (
        "import fcntl, sys\nf = open(sys.argv[1], 'rb')\n"
        "try:\n    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)\nexcept BlockingIOError:\n    sys.exit(10)\n"
    )
    probe = subprocess.run(
        [sys.executable, "-c", try_lock, str(lock)], capture_output=True, text=True, timeout=30, check=False,
    )
    assert probe.returncode == 10, "an inner release dropped the outer operation's lock"
    assert holder.p.stdin is not None
    holder.p.stdin.write("\n")
    holder.p.stdin.flush()
    assert holder.line() == "released unset"
    assert contend(state, tmp_path)[0] == 0
    assert holder.finish() == 0
    assert "ERR-TRAP" not in holder.stderr()


@seam
def test_only_the_acquirer_binds_an_operation(tmp_path: Path, procs: list[Proc]) -> None:
    state = tmp_path / "state"
    r = sh(f"cb_lifecycle_lock_bind_operation {OP} || exit $?", state)
    assert r.returncode == 2
    clean(r)
    child = child_script(
        tmp_path, "child.sh",
        'cb_lifecycle_lock_acquire "restore.sh"\nrc=0\n'
        'cb_lifecycle_lock_bind_operation op-20261001-002 || rc=$?\necho "child bind $rc"\n',
    )
    parent = bash_bg(
        procs,
        'cb_lifecycle_lock_acquire "cb update"\n'
        'rc=0; cb_lifecycle_lock_bind_operation op-bad || rc=$?; echo "malformed $rc"\n'
        f'cb_lifecycle_lock_bind_operation {OP}\necho "bound $CB_LIFECYCLE_OPERATION"\n'
        f'cb_lifecycle_lock_bind_operation {OP}\necho "again ok"\n'
        'rc=0; cb_lifecycle_lock_bind_operation op-20261001-003 || rc=$?; echo "rebind $rc"\n'
        f'bash "{child}"\nread -r _ || true\n',
        state,
    )
    assert parent.line() == "malformed 2"
    assert parent.line() == f"bound {OP}"
    assert parent.line() == "again ok"
    assert parent.line() == "rebind 2"
    assert parent.line() == "child bind 2"
    assert owner_record(state)["operation"] == OP
    assert parent.finish() == 0


# --- crashes ---------------------------------------------------------------------------------


@seam
def test_sigkill_of_a_lone_holder_releases_exclusion(tmp_path: Path, procs: list[Proc]) -> None:
    state = tmp_path / "state"
    holder = bash_bg(procs, HOLD, state)
    holder.line()
    assert contend(state, tmp_path)[0] == 10
    holder.kill()
    assert contend(state, tmp_path)[0] == 0


def _running(pid: int) -> bool:
    """Whether pid is still a live process. A zombie has exited and closed every descriptor; it
    stays in /proc until reaped, which an orphan's pid 1 in a container may never do."""
    try:
        raw = Path(f"/proc/{pid}/stat").read_text()
    except FileNotFoundError:
        return False
    return raw[raw.rindex(")") + 2:].split()[0] != "Z"


def _wait_for(path: Path, timeout: float = 15) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists() and path.read_text().endswith("\n"):
            return path.read_text().strip()
        time.sleep(0.02)
    raise AssertionError(f"{path} never appeared")


@seam
def test_sigkill_of_the_parent_keeps_exclusion_until_the_mutating_child_exits(
    tmp_path: Path, procs: list[Proc]
) -> None:
    state = tmp_path / "state"
    ready, go = tmp_path / "child-ready", tmp_path / "go"
    child = child_script(
        tmp_path, "child.sh",
        f'cb_lifecycle_lock_acquire "restore.sh"\necho "$BASHPID" >"{ready}"\n'
        f'for _ in $(seq 1500); do [[ -e "{go}" ]] && exit 0; sleep 0.02; done\nexit 1\n',
    )
    parent = bash_bg(
        procs,
        f'cb_lifecycle_lock_acquire "cb update"\ncb_lifecycle_lock_bind_operation {OP}\n'
        f'bash "{child}" &\necho "ready $$"\nwait\n',
        state,
    )
    parent.line()
    child_pid = int(_wait_for(ready))
    try:
        parent.kill()
        assert contend(state, tmp_path)[0] == 10
        go.write_text("")
        deadline = time.monotonic() + 15
        while _running(child_pid) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not _running(child_pid), "the child never exited"
        assert contend(state, tmp_path)[0] == 0
    finally:
        if _running(child_pid):
            os.kill(child_pid, signal.SIGKILL)


REPORT = 'echo "$BASHPID ${CB_LIFECYCLE_LOCK_FD-unset} ${CB_LIFECYCLE_OPERATION-unset} ${CB_LIFECYCLE_EVENT_FD-unset}" >"$1"'
STARTERS = {
    # Started in the background by the lock holder.
    "spawned": f"cb_lifecycle_spawn_unlocked bash -c '{REPORT}; exec sleep 60' helper \"$PIDFILE\"\n",
    # Run in the foreground, leaving a daemon behind when it returns.
    "daemonizing": f"cb_lifecycle_run_unlocked bash -c '({REPORT}; exec sleep 60) &' helper \"$PIDFILE\"\n",
}


@pytest.mark.parametrize("how", list(STARTERS))
@seam
def test_an_unlocked_helper_does_not_keep_the_lock(tmp_path: Path, procs: list[Proc], how: str) -> None:
    state = tmp_path / "state"
    pidfile = tmp_path / "helper"
    parent = bash_bg(
        procs,
        # A daemon holding the event descriptor would keep the coordinator reading until it exits.
        f'exec {{ev}}>"{tmp_path / "events"}"\nexport CB_LIFECYCLE_EVENT_FD=$ev\n'
        f'cb_lifecycle_lock_acquire "cb restart"\ncb_lifecycle_lock_bind_operation {OP}\n'
        + STARTERS[how]
        + 'echo "ready $CB_LIFECYCLE_LOCK_FD $CB_LIFECYCLE_EVENT_FD"\nread -r _ || true\n',
        state,
        {"PIDFILE": str(pidfile)},
    )
    fd, event_fd = parent.line().split()[1:]
    helper_pid, lock_fd, operation, event = _wait_for(pidfile).split()
    try:
        assert (lock_fd, operation, event) == ("unset", "unset", "unset")
        assert not Path(f"/proc/{helper_pid}/fd/{fd}").exists()
        assert not Path(f"/proc/{helper_pid}/fd/{event_fd}").exists()
        parent.kill()
        assert _running(int(helper_pid))
        assert contend(state, tmp_path)[0] == 0
    finally:
        os.kill(int(helper_pid), signal.SIGKILL)


# --- substitutions -----------------------------------------------------------------------------


def _symlinked_root(tmp_path: Path) -> Path:
    real = tmp_path / "real"
    make_state(real)
    (tmp_path / "state").symlink_to(real)
    return tmp_path / "state"


def _symlinked_ancestor(tmp_path: Path) -> Path:
    (tmp_path / "realparent").mkdir(mode=0o755)
    make_state(tmp_path / "realparent" / "state")
    (tmp_path / "link").symlink_to(tmp_path / "realparent")
    return tmp_path / "link" / "state"


def _symlinked_private(tmp_path: Path) -> Path:
    make_state(tmp_path / "other")
    state = tmp_path / "state"
    state.mkdir(mode=0o755)
    (state / "private").symlink_to(tmp_path / "other" / "private")
    return state


def _symlinked_lock(tmp_path: Path) -> Path:
    state = tmp_path / "state"
    make_state(state)
    (tmp_path / "decoy").write_text("")
    (tmp_path / "decoy").chmod(0o600)
    lock = state / "private" / "lock"
    lock.unlink()
    lock.symlink_to(tmp_path / "decoy")
    return state


def _hardlinked_lock(tmp_path: Path) -> Path:
    state = tmp_path / "state"
    make_state(state)
    os.link(state / "private" / "lock", tmp_path / "second-name")
    return state


def _writable_ancestor(tmp_path: Path) -> Path:
    parent = tmp_path / "open"
    parent.mkdir()
    parent.chmod(0o777)
    return parent / "state"


def _sticky_ancestor_not_root(tmp_path: Path) -> Path:
    parent = tmp_path / "sticky"
    parent.mkdir()
    parent.chmod(0o1777)
    return parent / "state"


def _loose(path_in_state: str, perm: int) -> object:
    def build(tmp_path: Path) -> Path:
        state = tmp_path / "state"
        make_state(state)
        (state / path_in_state).chmod(perm)
        return state
    return build


def _private_is_a_file(tmp_path: Path) -> Path:
    state = tmp_path / "state"
    state.mkdir(mode=0o755)
    (state / "private").write_text("")
    return state


def _lock_is_a_directory(tmp_path: Path) -> Path:
    state = tmp_path / "state"
    make_state(state)
    (state / "private" / "lock").unlink()
    (state / "private" / "lock").mkdir(mode=0o700)
    return state


SUBSTITUTIONS = {
    "root is a symlink": _symlinked_root,
    "an ancestor is a symlink": _symlinked_ancestor,
    "private is a symlink": _symlinked_private,
    "lock is a symlink": _symlinked_lock,
    "lock has a second name": _hardlinked_lock,
    "an ancestor is writable by others": _writable_ancestor,
    "a sticky ancestor not owned by root": _sticky_ancestor_not_root,
    "root is group-writable": _loose(".", 0o775),
    "private is readable by others": _loose("private", 0o755),
    "private is readable by the group": _loose("private", 0o750),
    "lock is readable by others": _loose("private/lock", 0o644),
    "private is a file": _private_is_a_file,
    "lock is a directory": _lock_is_a_directory,
}


@pytest.mark.parametrize("case", list(SUBSTITUTIONS))
@seam
def test_a_substituted_or_loosened_tree_is_refused_with_6(tmp_path: Path, case: str) -> None:
    state = SUBSTITUTIONS[case](tmp_path)  # type: ignore[operator]
    before = sorted(str(p) for p in tmp_path.rglob("*"))
    code, err = contend(state, tmp_path)
    assert code == 6, err
    assert "lifecycle lock:" in err
    after = sorted(str(p) for p in tmp_path.rglob("*") if p.name != "mutated")
    assert after == before, "a refused tree was changed"
    if case == "lock is a symlink":
        assert (tmp_path / "decoy").read_text() == ""


@seam
def test_a_missing_parent_is_not_created(tmp_path: Path) -> None:
    code, err = contend(tmp_path / "absent" / "state", tmp_path)
    assert code == 7
    assert "does not exist" in err
    assert not (tmp_path / "absent").exists()


@seam
def test_an_untrusted_owner_is_refused_with_6(tmp_path: Path) -> None:
    # Our own uid stays mapped; root is not, so every root-owned ancestor reads as the overflow uid.
    argv = userns(f"--map-user={os.geteuid()}", f"--map-group={os.getegid()}")
    marker = tmp_path / "mutated"
    r = subprocess.run(
        [*argv, "bash", "-c", PRELUDE + MUTATE], capture_output=True, text=True, timeout=30, check=False,
        env=env_for(tmp_path / "state", {"MUTATION": str(marker)}),
    )
    assert r.returncode == 6, r.stderr
    assert "owned by uid" in clean(r)
    assert not (tmp_path / "state").exists()
    assert not marker.exists()


# --- started as root ---------------------------------------------------------------------------


@pytest.fixture
def dropped_base() -> Iterator[Path]:
    """A temporary directory owned by DROP_UID, below ancestors it may enter and the library trusts."""
    base = Path(tempfile.mkdtemp(prefix="cb-lifecycle-lock-"))
    try:
        os.chown(base, DROP_UID, DROP_GID)
        yield base
    finally:
        shutil.rmtree(base)


def dropped_env(base: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    """env_for(None) for a process running as DROP_UID, with every writable location inside base."""
    return env_for(None, {
        "HOME": str(base), "TMPDIR": str(base), "USER": "cb-lock-test", "LOGNAME": "cb-lock-test",
        "PYTHONDONTWRITEBYTECODE": "1", **(extra or {}),
    })


@root_only
def test_as_root_every_case_runs_unprivileged(dropped_base: Path) -> None:
    assert str(DROP_UID) != Path("/proc/sys/kernel/overflowuid").read_text().strip()
    r = subprocess.run(
        [sys.executable, "-m", "pytest", str(Path(__file__).resolve()), "-q", "-rs", "-p", "no:cacheprovider",
         f"--basetemp={dropped_base / 'pytest'}"],
        capture_output=True, text=True, cwd=dropped_base, env=dropped_env(dropped_base), timeout=600, check=False,
        user=DROP_UID, group=DROP_GID, extra_groups=[],
    )
    assert r.returncode == 0, r.stdout + r.stderr
    summary = r.stdout.strip().splitlines()[-1]
    assert re.match(r"\d+ passed", summary), summary
    # Only this module's root-only cases and the user-namespace cases may skip there: every seam case runs.
    reasons = re.findall(r"^SKIPPED \[\d+\] \S+: (.*)$", r.stdout, re.MULTILINE)
    allowed = ("needs root to drop privileges", "needs an unprivileged user namespace")
    assert all(reason.startswith(allowed) for reason in reasons), reasons


@root_only
def test_as_root_an_ancestor_owned_by_another_uid_is_refused_with_6(dropped_base: Path) -> None:
    # The namespace-free form of test_an_untrusted_owner_is_refused_with_6, which container seccomp may skip.
    stranger = DROP_UID + 1
    foreign = dropped_base / "foreign"
    foreign.mkdir(mode=0o755)
    os.chown(foreign, stranger, stranger)
    marker = dropped_base / "mutated"
    r = subprocess.run(
        ["bash", "-c", PRELUDE + MUTATE], capture_output=True, text=True, timeout=30, check=False,
        cwd=dropped_base, user=DROP_UID, group=DROP_GID, extra_groups=[],
        env=dropped_env(dropped_base, {"CB_LIFECYCLE_ROOT": str(foreign / "state"), "MUTATION": str(marker)}),
    )
    assert r.returncode == 6, r.stderr
    assert f"owned by uid {stranger}" in clean(r)
    assert not (foreign / "state").exists()
    assert not marker.exists()
