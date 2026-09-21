"""The post-uninstall port check must wait for the port, not sample it once.

uninstall.sh removes the nginx site and calls `systemctl reload nginx`. That
returns when nginx's master accepts the SIGHUP — the master reconfigures and
retires its old workers afterwards, on its own schedule, so the listening
socket outlives the reload by a short and variable interval.

The journey used to probe the port exactly once, immediately after `cb
uninstall` returned, and fail if anything answered. Whether that passed came
down to timing. It was proven nondeterministic rather than argued: debian12
failed with

    ::error::something is still serving :8088 after uninstall

and then passed the same assertion on a re-run of the identical commit, while
the other five distros passed both times.

A leftover listener is still a failure, and still the thing worth catching —
what an operator reports is a service still answering minutes after they
removed it, not one answering for two hundred milliseconds while nginx
reloads. These tests pin both halves: the check tolerates a port that closes
shortly after uninstall, and still fails on one that never closes.
"""

from __future__ import annotations

import re
import subprocess
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JOURNEY = ROOT / "scripts" / "ci" / "installer-journey.sh"

_MARKER = "# The port has to be free again."


def _port_check_block() -> str:
    """The post-uninstall port assertion, from its comment to 'uninstall clean'."""
    text = JOURNEY.read_text(encoding="utf-8")
    start = text.index(_MARKER)
    end = text.index('echo "uninstall clean"', start) + len('echo "uninstall clean"')
    return text[start:end]


def _run(tmp_path: Path, answers: int) -> subprocess.CompletedProcess[str]:
    """Run the block with a curl stub that answers `answers` times then stops.

    answers=0  -> port already closed
    answers=3  -> closes a few seconds after uninstall (the real reload window)
    answers=-1 -> never closes (a genuine leak)
    """
    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()
    curl = stub_dir / "curl"
    curl.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            n="{answers}"
            count_file="{tmp_path}/calls"
            echo x >> "$count_file"
            calls=$(wc -l < "$count_file")
            if [ "$n" -lt 0 ]; then exit 0; fi
            if [ "$calls" -le "$n" ]; then exit 0; fi
            exit 7
            """
        ),
        encoding="utf-8",
    )
    curl.chmod(0o755)

    script = (
        textwrap.dedent(
            """
            set -euo pipefail
            PORT=8088
            BASE="http://127.0.0.1:${PORT}/api/v1"
            fail() { printf '::error::%s\\n' "$1" >&2; exit 1; }
            # Shorten the real 30s budget; the leak path is about the deadline
            # being enforced, not about how long it is.
            CB_JOURNEY_UNINSTALL_WAIT=3
            """
        )
        + _port_check_block()
    )
    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        timeout=120,
        env={"PATH": f"{stub_dir}:/usr/bin:/bin", "LC_ALL": "C"},
    )


def test_a_port_that_is_already_closed_passes_immediately(tmp_path):
    result = _run(tmp_path, answers=0)
    assert result.returncode == 0, result.stderr
    assert "uninstall clean" in result.stdout


def test_a_port_that_closes_during_the_nginx_reload_window_passes(tmp_path):
    """This is the case that failed debian12 on one run and passed on the next."""
    result = _run(tmp_path, answers=3)
    assert result.returncode == 0, (
        "the check must tolerate nginx taking a moment to drop its listening "
        "socket after `systemctl reload` returns:\n" + result.stderr
    )
    assert "uninstall clean" in result.stdout
    calls = (tmp_path / "calls").read_text(encoding="utf-8").count("x")
    assert calls > 1, f"the check must retry, not sample once; it probed {calls} time(s)"


def test_a_port_that_never_closes_still_fails(tmp_path):
    """The assertion's whole reason to exist. Waiting must not mean forgiving."""
    result = _run(tmp_path, answers=-1)
    assert result.returncode != 0, "a listener that outlives uninstall must fail the journey"
    assert "still serving :8088" in result.stderr, result.stderr


def test_the_check_is_bounded():
    """A poll with no deadline hangs the job instead of failing it."""
    block = _port_check_block()
    assert re.search(r"SECONDS\s*\+\s*uninstall_port_wait", block), (
        "the wait must carry an explicit deadline; an unbounded loop turns a "
        "leaked listener into a job timeout instead of a named failure"
    )
    assert "fail " in block, "the deadline must end in fail(), not in a silent break"
