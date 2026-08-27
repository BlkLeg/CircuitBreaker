"""The uninstaller must not abort silently half-way through the uninstall.

Every prompt in uninstall.sh reads from `/dev/tty` rather than from stdin, and
that is deliberate: the advertised invocation is `curl ... | bash`, where stdin
is the downloaded script itself, so a `read` from stdin would eat the rest of
the source. But `/dev/tty` only resolves for a process that has a controlling
terminal. Under cron, a CI runner, `ssh host '...'` without `-t`, or any
`docker run` without `-t`, the open returns ENXIO, `read` returns non-zero, and
`set -e` ends the script on the spot.

The spot it ended at was the *first* prompt -- which comes after the container
has already been stopped and removed. The operator got exit 1, one line of
bash's own stderr about `/dev/tty`, and a host that still had the image, Caddy,
the config directory and `/usr/local/bin/cb` on it. Through a pipe, with stderr
going nowhere, that is an uninstaller that appears to do nothing and in fact
half-uninstalled the product.

So the question "can this process be asked anything at all?" has to be answered
before the first destructive step, not discovered after it.

What is *not* being changed here: an operator who has a terminal and answers
nothing -- EOF on the read, a closed pipe mid-run -- must still abort rather
than fall through to a destructive default. That is pinned by
`test_uninstall_volume_prompt.py::test_an_unanswerable_prompt_aborts_instead_of_deleting`
and it is correct. No answer is not consent; this file is about the case where
no answer was ever *possible*.

The whole shipped script is run for real against stub binaries, because the
defect is an ordering property -- what has already happened by the time the
script gives up -- and only a real run can observe that ordering.
"""

from __future__ import annotations

import fcntl
import os
import pty
import re
import select
import subprocess
import termios
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
UNINSTALL_SH = REPO_ROOT / "uninstall.sh"

# The stub reports the container as both running and present, so the script
# takes the branch that stops and removes it -- the destructive work that the
# aborted run used to have already done by the time it gave up. Everything else
# answers "not found" so the run stays on the shortest path to the first prompt.
DOCKER_STUB = """#!/usr/bin/env bash
echo "docker $*" >> "$DOCKER_LOG"
if [ "$1" = "ps" ]; then
  echo "circuit-breaker"
  exit 0
fi
# `<noun> inspect` is how the script asks "does this still exist?". Answering
# no keeps the run on the shortest path: no Caddy volumes, no network, no
# image to remove. Everything else -- stop, rm -- succeeds, because the point
# of the fixture is to let the destructive steps actually happen and then see
# whether they did.
if [ "$2" = "inspect" ]; then
  exit 1
fi
exit 0
"""

# uninstall.sh calls sudo, systemctl and certutil on paths this test must never
# reach and must certainly never act on -- /etc/hosts, /usr/local/bin/cb, the
# system trust store. None of them are reachable before the first prompt, but a
# test that runs a real uninstaller wants the seatbelt regardless of what a
# later edit does to the ordering.
REFUSE_STUB = """#!/usr/bin/env bash
echo "REFUSED: $0 $*" >> "$DOCKER_LOG"
exit 1
"""


@pytest.fixture()
def sandbox(tmp_path):
    """A PATH of stubs, an isolated HOME, and the log they all write to."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "docker").write_text(DOCKER_STUB, encoding="utf-8")
    (bin_dir / "docker").chmod(0o755)
    for name in ("sudo", "systemctl", "certutil", "launchctl"):
        (bin_dir / name).write_text(REFUSE_STUB, encoding="utf-8")
        (bin_dir / name).chmod(0o755)

    home = tmp_path / "home"
    home.mkdir()
    log = tmp_path / "docker.log"

    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "HOME": str(home),
        "DOCKER_LOG": str(log),
        "CB_CONFIG_DIR": str(home / ".circuit-breaker"),
    }
    return {"env": env, "log": log, "home": home}


def _commands(log: Path) -> list[str]:
    return log.read_text(encoding="utf-8").splitlines() if log.exists() else []


def _destructive(log: Path) -> list[str]:
    """Every logged call that changed something on the host."""
    verbs = ("stop", "rm", "rmi", "image rm", "volume rm", "network rm")
    out = []
    for line in _commands(log):
        args = line.split()[1:]
        if any(a in verbs for a in args) or line.startswith("REFUSED:"):
            out.append(line)
    return out


def _run_without_a_terminal(sandbox) -> subprocess.CompletedProcess:
    """Run the shipped uninstaller in a session with no controlling terminal.

    `start_new_session=True` is `setsid(2)`: the child leads a new session and
    inherits no controlling terminal, so `/dev/tty` fails to open exactly as it
    does under cron, in CI and over a tty-less ssh. Doing it this way rather
    than shelling out to setsid(1) also means the result does not depend on how
    pytest itself was launched.
    """
    return subprocess.run(
        ["bash", str(UNINSTALL_SH)],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        env=sandbox["env"],
        start_new_session=True,
        timeout=60,
    )


# --------------------------------------------------------------------------
# No terminal: give up before touching anything, and say so.
# --------------------------------------------------------------------------


def test_a_host_with_no_terminal_loses_nothing(sandbox):
    """The heart of it: no prompt can be answered, so no step may have run.

    Before the preflight this failed with `docker stop` and `docker rm` already
    in the log -- the container was gone and the script then died at the volume
    prompt with nothing else cleaned up.
    """
    _run_without_a_terminal(sandbox)
    assert _destructive(sandbox["log"]) == [], (
        "the uninstaller changed the host and then aborted at a prompt it "
        "could never have answered:\n  " + "\n  ".join(_commands(sandbox["log"]))
    )


def test_the_abort_explains_itself_on_stdout(sandbox):
    """Exit 1 and one line of bash's own stderr is not a message.

    Asserted against stdout specifically. `curl ... | bash` from cron or CI is
    routinely run with stderr discarded, and bash's `/dev/tty: No such device
    or address` is the only thing the old failure produced -- it names the
    symptom, not the cause, and not what the operator should do instead.
    """
    result = _run_without_a_terminal(sandbox)
    assert re.search(r"terminal", result.stdout, re.IGNORECASE), (
        "nothing on stdout tells the operator a terminal is what was "
        f"missing:\n{result.stdout}{result.stderr}"
    )
    assert re.search(r"nothing (has been|was) removed", result.stdout, re.IGNORECASE), (
        "the operator is not told the host is untouched, which is the one "
        f"thing they need to know before re-running:\n{result.stdout}"
    )


def test_the_abort_is_still_a_failure_exit(sandbox):
    """Guard, not the pin: giving up must not start reporting success.

    This passed before the fix too -- `set -e` already exited 1. It is here so
    that a preflight which prints its explanation and then falls through, or
    one that `exit 0`s because "nothing went wrong", is caught.
    """
    result = _run_without_a_terminal(sandbox)
    assert result.returncode != 0, (
        "the uninstaller reported success without uninstalling anything: "
        f"{result.stdout}"
    )


# --------------------------------------------------------------------------
# A real terminal: the preflight must let the operator through.
# --------------------------------------------------------------------------


def test_a_real_terminal_still_reaches_the_data_volume_prompt(sandbox):
    """The control. A preflight that always aborts would pass everything above.

    The script is run on a real pty so `/dev/tty` opens, and is watched until
    the data-volume prompt appears -- proving the preflight is a gate on the
    absence of a terminal and not on the prompts themselves. It is killed at
    the prompt rather than answered: past that point the script reaches sudo,
    /etc/hosts and /usr/local/bin/cb, and no test has any business going there.
    """
    master, slave = pty.openpty()

    def _acquire_controlling_tty():  # pragma: no cover - runs in the child
        os.setsid()
        fcntl.ioctl(slave, termios.TIOCSCTTY, 0)

    proc = subprocess.Popen(
        ["bash", str(UNINSTALL_SH)],
        stdin=slave,
        stdout=slave,
        stderr=slave,
        env=sandbox["env"],
        preexec_fn=_acquire_controlling_tty,
        close_fds=True,
    )
    os.close(slave)

    seen = ""
    deadline = time.monotonic() + 30
    try:
        while time.monotonic() < deadline:
            ready, _, _ = select.select([master], [], [], 0.5)
            if ready:
                try:
                    chunk = os.read(master, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                seen += chunk.decode(errors="replace")
                if "[y/N]" in seen:
                    break
            elif proc.poll() is not None:
                break
    finally:
        proc.kill()
        proc.wait(timeout=10)
        os.close(master)

    assert "[y/N]" in seen, (
        "with a controlling terminal the uninstaller never reached the "
        f"data-volume prompt -- the preflight is refusing a usable tty:\n{seen}"
    )
    assert any(
        line.startswith("docker rm circuit-breaker") for line in _commands(sandbox["log"])
    ), (
        "the interactive path no longer removes the container:\n  "
        + "\n  ".join(_commands(sandbox["log"]))
    )
