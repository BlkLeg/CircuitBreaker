"""Switching to the PostgreSQL account goes through runuser, never su first.

systemd 262's sysusers creates system accounts with an account expiry of
1970-01-02 (`postgres:!*:20763:::::1:` on Arch), so that they can never log in.
`su` runs the PAM account stack and refuses an expired account outright —
"su: User account has expired" — so deploy/setup.sh's `su postgres -c initdb`
stopped every fresh Arch install at "Preparing database". `runuser` is the
util-linux tool for root switching to a service account: the same -s/-c
interface without the account check. Other distributions meet the same thing
as they move to systemd 262.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SETUP_SH = ROOT / "deploy" / "setup.sh"
RESTORE_SH = ROOT / "deploy" / "scripts" / "restore.sh"

# A direct `su` to a named account, the shape that fails on an expired account.
_DIRECT_SU = re.compile(r'(?<![\w-])su\s+(-s\s+\S+\s+)?("?\$\{?\w+\}?"?|postgres|breaker)\s+-c\b')


def _code(path: Path) -> list[str]:
    return [line for line in path.read_text(encoding="utf-8").splitlines() if not line.lstrip().startswith("#")]


def _function(path: Path, name: str) -> str:
    text = path.read_text(encoding="utf-8")
    match = re.search(rf"^{re.escape(name)}\(\) \{{\n(.*?)^\}}\n", text, re.DOTALL | re.MULTILINE)
    assert match, f"{path.name} defines no {name}()"
    return f"{name}() {{\n{match.group(1)}}}\n"


def test_setup_sh_switches_to_postgres_only_through_cb_run_as() -> None:
    offenders = [line.strip() for line in _code(SETUP_SH) if _DIRECT_SU.search(line)]
    # The one su left is cb_run_as's own fallback.
    assert offenders == ['su -s /bin/sh "$1" -c "$2"'], offenders


def test_restore_sh_tries_runuser_before_su() -> None:
    body = _function(RESTORE_SH, "_as_superuser")
    assert body.index("runuser -s /bin/sh") < body.index("su -s /bin/sh"), (
        "_as_superuser must prefer runuser; su is only for a host without util-linux"
    )


def _stub_bin(tmp_path: Path, names: list[str]) -> Path:
    """A PATH holding stubs that log which switcher ran and its argv, then run nothing."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls"
    for name in names:
        stub = bin_dir / name
        stub.write_text(f'#!/bin/sh\nprintf "%s %s\\n" "{name}" "$*" >> "{log}"\n')
        stub.chmod(0o755)
    return bin_dir


def _run_cb_run_as(tmp_path: Path, switchers: list[str]) -> str:
    bin_dir = _stub_bin(tmp_path, switchers)
    script = _function(SETUP_SH, "cb_run_as") + 'cb_run_as postgres "initdb -D /data"\n'
    # Only the stubs and the shell itself: no real runuser or su can be found.
    env = {"PATH": str(bin_dir), "HOME": str(tmp_path)}
    bash = "/bin/bash" if os.path.exists("/bin/bash") else "/usr/bin/bash"
    result = subprocess.run([bash, "-c", script], env=env, capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode == 0, result.stderr
    return (tmp_path / "calls").read_text(encoding="utf-8")


def test_cb_run_as_uses_runuser_when_it_exists(tmp_path: Path) -> None:
    calls = _run_cb_run_as(tmp_path, ["runuser", "su"])
    assert calls == "runuser -s /bin/sh postgres -c initdb -D /data\n"


def test_cb_run_as_falls_back_to_su_without_runuser(tmp_path: Path) -> None:
    calls = _run_cb_run_as(tmp_path, ["su"])
    assert calls == "su -s /bin/sh postgres -c initdb -D /data\n"
