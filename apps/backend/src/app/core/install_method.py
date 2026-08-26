"""How this instance was installed, and the upgrade command that fits it.

The UI must never print a command that fails, so the strings here are the
ones that work against the tree as it stands. `cb update` is deliberately
absent: `cb:462` refuses binary installs, and `cb:57` pins `:latest`, which
`scripts/release_channel.py` never grants to a prerelease -- so `cb update`
on a candidate today is a downgrade. Spec stage 4 replaces this table once
`cb` can be trusted.
"""

from __future__ import annotations

import functools
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

KNOWN_METHODS = (
    "binary",
    "docker",
    "compose",
    "deb",
    "rpm",
    "apk",
    "arch",
    "appimage",
    "unknown",
)

_INSTALL_CONF_PATHS = (
    Path("/etc/circuit-breaker/install.conf"),
    Path.home() / ".circuit-breaker/install.conf",
)

_RELEASES = "https://github.com/BlkLeg/CircuitBreaker/releases"
_INSTALLER = "https://raw.githubusercontent.com/BlkLeg/CircuitBreaker/main/install.sh"
_IMAGE = "ghcr.io/blkleg/circuitbreaker"

_MODE_RE = re.compile(r'^\s*CB_MODE\s*=\s*"?([A-Za-z]+)"?', re.MULTILINE)


def _mode_from_conf() -> str | None:
    for path in _INSTALL_CONF_PATHS:
        try:
            match = _MODE_RE.search(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            continue
        if match and match.group(1) in KNOWN_METHODS:
            return match.group(1)
    return None


def _in_container() -> bool:
    return Path("/.dockerenv").exists()


def _package_owner() -> str | None:
    """Ask the OS whether it owns this executable. Never raises."""
    target = sys.executable
    probes = (
        ("deb", ["dpkg", "-S", target]),
        ("rpm", ["rpm", "-qf", target]),
        ("apk", ["apk", "info", "--who-owns", target]),
    )
    for method, cmd in probes:
        if shutil.which(cmd[0]) is None:
            continue
        try:
            done = subprocess.run(cmd, capture_output=True, timeout=5, check=False)
        except (OSError, subprocess.SubprocessError):
            continue
        if done.returncode == 0:
            # pacman also answers `rpm`-less systems via its own db; check it first.
            if method == "rpm" and shutil.which("pacman"):
                return "arch"
            return method
    return None


@functools.lru_cache(maxsize=1)
def detect_install_method() -> str:
    """First confident answer wins; `unknown` rather than a guess.

    Memoized for the process lifetime: an install cannot change method while
    the process runs, and `_package_owner()` shells out to `dpkg`/`rpm`/`apk`
    when nothing declarative answers first -- that must not happen per
    request. Tests that vary the probed state must call
    `detect_install_method.cache_clear()` between calls.
    """
    declared = os.environ.get("CB_INSTALL_METHOD", "").strip()
    if declared in KNOWN_METHODS:
        return declared

    mode = _mode_from_conf()
    if mode:
        return mode

    if os.environ.get("APPIMAGE", "").strip():
        return "appimage"

    owner = _package_owner()
    if owner:
        return owner

    if _in_container():
        return "docker"

    return "unknown"


def upgrade_command(method: str, target: str | None) -> str:
    """The command an operator runs. Verified against the current tree."""
    version = target or "<version>"
    table = {
        "binary": f"curl -fsSL {_INSTALLER} | sudo bash -s -- --upgrade",
        "docker": (f"docker pull {_IMAGE}:{version} && docker rm -f circuitbreaker && cb start"),
        "compose": f"CB_TAG={version} docker compose up -d --pull always",
        "deb": f"sudo apt-get install --only-upgrade circuit-breaker  # or: {_RELEASES}",
        "rpm": f"sudo dnf upgrade circuit-breaker  # or: {_RELEASES}",
        "apk": f"sudo apk upgrade circuit-breaker  # or: {_RELEASES}",
        "arch": "sudo pacman -Syu circuit-breaker",
        "appimage": f"Download the new AppImage and replace it in place: {_RELEASES}",
        "unknown": f"See the upgrade instructions at {_RELEASES}",
    }
    return table.get(method, table["unknown"])
