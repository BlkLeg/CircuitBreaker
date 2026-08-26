"""The uninstaller's data-volume prompt must default to keeping the data.

uninstall.sh removes a container and an image, both of which come back from a
`docker pull` and an `install.sh` re-run. The data volume does not: it holds the
inventory, the topology, the user accounts and the vault key, and once
`docker volume rm` returns there is nothing left to restore from.

That one irreversible step used to be the one with the destructive default. The
prompt read `[Y/n]` and the case arm that retained the volume was
`[nN][oO]|[nN]`, so *only* a literal n/N/no/NO spared the data. A bare Enter
deleted it. So did "nope", "No thanks" and any stray keystroke -- every near
miss on the answer landed on the destructive branch, which is exactly backwards
for the one action in the script that cannot be undone.

An answer of EOF was already safe, and still is, but only by accident of
`set -e`: `read` returns non-zero and the whole uninstaller aborts on the spot.
That is asserted here too, so a later change that drops `set -e` or adds a
`|| true` cannot quietly turn a closed pipe into a deleted database.

The same script already had the safe shape in its Linux and macOS cleanup
sections (`[y/N]` with a `[yY]*` glob), so the fix is to make the volume prompt
match its own neighbours rather than to invent anything.

These tests run the shipped block itself in a bash sandbox with a stub `docker`,
so they assert what an operator's answer actually does, not how the source is
worded. The one text assertion covers the prompt's `[y/N]` marker, because a
prompt that advertises a default it does not honour is its own defect.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
UNINSTALL_SH = REPO_ROOT / "uninstall.sh"


def _volume_block() -> str:
    """The data-volume prompt and its case statement, lifted from the script.

    uninstall.sh runs top to bottom -- it stops containers, removes images and
    calls sudo -- so it cannot be sourced. The block is extracted instead, and
    the only edit made to it is swapping the /dev/tty read for stdin, since a
    pytest process has no controlling terminal to answer from.
    """
    text = UNINSTALL_SH.read_text(encoding="utf-8")
    match = re.search(
        r"^# Remove the data volume$\n.*?^esac$", text, re.MULTILINE | re.DOTALL
    )
    assert match is not None, (
        "the '# Remove the data volume' block was not found in uninstall.sh -- "
        "if it was renamed or restructured, update this test to match"
    )
    block = match.group(0)
    assert "< /dev/tty" in block, "the volume prompt no longer reads from /dev/tty"
    return block.replace("< /dev/tty", "< /dev/stdin")


HARNESS = """
set -e
COLOUR_RESET=''
aCOLOUR=('' '' '' '' '')
CB_VOLUME='circuit-breaker-data'
Show() { echo "Show $1: $2"; }
docker() { echo "docker $*" >> "$DOCKER_LOG"; return 0; }
"""


def _answer(reply: str, tmp_path: Path) -> list[str]:
    """Feed one answer to the prompt; return the docker commands it ran."""
    log = tmp_path / "docker.log"
    result = subprocess.run(
        ["bash", "-c", HARNESS + _volume_block()],
        input=reply,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "DOCKER_LOG": str(log)},
    )
    assert not result.stderr.strip(), (
        f"the sandbox itself broke for {reply!r}, so its verdict means "
        f"nothing: {result.stderr}"
    )
    return log.read_text(encoding="utf-8").splitlines() if log.exists() else []


def _deleted(reply: str, tmp_path: Path) -> bool:
    return any(line.startswith("docker volume rm") for line in _answer(reply, tmp_path))


# Answers that must leave the data alone. "\n" is a bare Enter and "" is a read
# that saw EOF -- the two ways an operator ends up answering nothing at all.
RETAINING = ["\n", "n\n", "N\n", "no\n", "NO\n", "nope\n", "No thanks\n", "q\n", "1\n"]

CONFIRMING = ["y\n", "Y\n", "yes\n", "YES\n", "Yes\n"]


@pytest.mark.parametrize("reply", RETAINING)
def test_only_an_explicit_yes_deletes_the_volume(reply, tmp_path):
    """Enter, EOF and every near miss must spare the volume, not destroy it."""
    assert not _deleted(reply, tmp_path), (
        f"answering {reply!r} ran `docker volume rm` -- the irreversible branch "
        "must require an explicit yes"
    )


@pytest.mark.parametrize("reply", CONFIRMING)
def test_an_explicit_yes_still_deletes_the_volume(reply, tmp_path):
    """The prompt must stay usable: a deliberate yes removes the volume."""
    assert _deleted(reply, tmp_path), f"answering {reply!r} did not remove the volume"


def test_the_prompt_advertises_the_retaining_default():
    """The [y/N] marker and the case arms have to tell the same story."""
    block = _volume_block()
    assert "[y/N]" in block, (
        "the data-volume prompt must offer [y/N]; a prompt that shows [Y/n] "
        "tells the operator Enter will delete their data"
    )


def test_an_unanswerable_prompt_aborts_instead_of_deleting(tmp_path):
    """EOF on the read must not fall through to the destructive branch.

    `curl ... | bash` leaves the script reading from a pipe, and a closed
    /dev/tty ends the read with no answer at all. Under `set -e` that aborts
    the uninstaller, which is the right outcome: no answer is not consent.
    """
    log = tmp_path / "docker.log"
    result = subprocess.run(
        ["bash", "-c", HARNESS + _volume_block()],
        input="",
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "DOCKER_LOG": str(log)},
    )
    assert result.returncode != 0, "an unanswered prompt must stop the uninstaller"
    assert not log.exists(), "an unanswered prompt ran docker: " + (
        log.read_text(encoding="utf-8") if log.exists() else ""
    )
