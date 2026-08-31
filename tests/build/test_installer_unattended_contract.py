"""The installer must run where nobody is watching it.

`--unattended` exists for Proxmox LXC provisioning, and the documented entry
point is `curl -fsSL ... | sudo bash`. Both mean the same thing: no TTY, no
operator to answer a question, and — because every package command in this
installer redirects to $LOG_FILE — no way for a question to even reach a screen.

Three v0.4.0 failures were all this one assumption:

* `clear` in cb_header() exits 1 when TERM is unset. Under `set -e` that aborted
  the installer before its first line of output, in exactly the environments
  --unattended was written for.
* No DEBIAN_FRONTEND, so debconf could prompt. No NEEDRESTART_MODE, so
  needrestart — default on Ubuntu Server since 22.04 — asked which services to
  restart on any host updated but not rebooted. Either hangs forever, silently.
* A failed `docker pull` was fatal, so an air-gapped or rate-limited host failed
  an install whose core path never needed the image.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALLER = REPO_ROOT / "install.sh"
SETUP = REPO_ROOT / "deploy" / "setup.sh"


def test_package_operations_cannot_stop_to_ask_a_question():
    """debconf and needrestart prompts are unrecoverable here: the prompt goes to
    the log file and the installer blocks on a terminal showing nothing."""
    for script in (INSTALLER, SETUP):
        text = script.read_text(encoding="utf-8")
        rel = script.relative_to(REPO_ROOT).as_posix()
        assert re.search(r"^export DEBIAN_FRONTEND=noninteractive$", text, re.MULTILINE), (
            f"{rel} runs package operations without exporting "
            f"DEBIAN_FRONTEND=noninteractive. Every apt command here redirects to "
            f"$LOG_FILE, so a debconf prompt hangs the install with no output, no "
            f"timeout, and nothing on screen to explain it."
        )
        assert re.search(r"^export NEEDRESTART_MODE=a$", text, re.MULTILINE), (
            f"{rel} must set NEEDRESTART_MODE=a. needrestart ships by default on "
            f"Ubuntu Server 22.04+ and hooks DPkg::Post-Invoke; on any host that "
            f"has been updated but not rebooted it asks which services to restart, "
            f"which is an invisible, permanent hang."
        )


def test_no_terminal_dependent_command_can_abort_the_installer():
    """`clear` exits non-zero without TERM, and `set -e` turns that into an abort
    before the header is even printed."""
    text = INSTALLER.read_text(encoding="utf-8")
    for match in re.finditer(r"^(\s*)(clear|tput\b[^\n]*)$", text, re.MULTILINE):
        line = text[: match.start()].count("\n") + 1
        raise AssertionError(
            f"install.sh:{line}: bare `{match.group(2).strip()}` aborts the whole "
            f"installer under `set -e` when TERM is unset — cloud-init, Ansible, "
            f"cron, Proxmox LXC, and `ssh host 'bash install.sh'` all have no TERM. "
            f"Guard it: `clear 2>/dev/null || true`."
        )


def test_optional_container_telemetry_never_aborts_the_install():
    """Docker telemetry degrades everywhere else in this file; the image pull was
    the one step that killed the install instead."""
    body = re.search(
        r"stage3_configure_docker_proxy\(\)\s*\{(.*?)\n\}",
        SETUP.read_text(encoding="utf-8"),
        re.DOTALL,
    )
    assert body, "deploy/setup.sh no longer defines stage3_configure_docker_proxy"
    assert "cb_fail" not in body.group(1), (
        "stage3_configure_docker_proxy must not cb_fail. Container telemetry is "
        "opt-in: Docker being absent warns and returns, a Docker CE install "
        "failure warns, and a proxy that will not start warns and sets "
        "DOCKER_PROXY_ENABLED=false. An unreachable registry — an air-gapped "
        "host, a Docker Hub rate limit, an egress proxy — must degrade the same "
        "way rather than fail an install whose core path never needed the image."
    )


def test_failure_diagnostics_run_at_failure_time_not_when_they_are_armed():
    """CB_STAGE_DIAGS entries are eval'd by cb_fail. They are written as
    double-quoted array elements, so an unescaped `$(...)` or `$var` in one is
    expanded at *assignment* time — on the success path, before the stage it
    documents has even run. The command substitution executes there and the
    result is baked in; by the time cb_fail eval's the string, the interesting
    part is a literal that was resolved minutes ago, usually to nothing.

    Nobody catches that by reading the output, because the output is only ever
    seen on a failure the author is not present for. So it is checked here: a
    diagnostic's runtime expansions must be escaped (`\\$(`, `\\$b`), leaving
    only deliberate installer-side interpolation like ${LOG_FILE} unescaped.
    """
    text = INSTALLER.read_text(encoding="utf-8")
    for match in re.finditer(r'^\s*"([^"\\]*(?:\\.[^"\\]*)*)::(.*)"\s*$', text, re.MULTILINE):
        command = match.group(2)
        line = text[: match.start()].count("\n") + 1
        # ${NAME} is installer-side interpolation and intended; $( and bare $x
        # are runtime and must be escaped as \$( and \$x.
        for bad in re.finditer(r'(?<!\\)\$(?!\{)', command):
            raise AssertionError(
                f"install.sh:{line}: diagnostic {match.group(1)!r} contains an "
                f"unescaped `${command[bad.end():bad.end() + 12]}...`, which bash "
                f"expands when the array is assigned rather than when cb_fail runs "
                f"it. Escape it as `\\$` so the eval sees it, or move the value "
                f"into ${{BRACED}} form if the installer really is meant to "
                f"substitute it up front."
            )
