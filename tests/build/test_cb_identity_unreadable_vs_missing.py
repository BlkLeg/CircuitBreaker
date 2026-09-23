"""An install the caller cannot read is not an install that is missing.

`/etc/circuitbreaker` defaults to root:breaker:0755 (deploy/setup.sh's DIRS
table) precisely so an unprivileged caller CAN traverse it and read the
identity file (0644) without sudo — see the comment on that table entry. But
the directory can still end up tighter than that on some hosts (manual
hardening, a restrictive umask, an NFS mount's own ACLs), and when it does, an
unprivileged caller gets EACCES on the *directory*, so every `[[ -f ... ]]`
against the file is false — byte-for-byte indistinguishable from a host that
has never been installed. This is what the tests below simulate directly,
with a synthetic 0o000 directory rather than depending on the real installer's
default.

`cb doctor` used to report that as:

    ✗  Install identity               FAILED
       → Re-run the installer so install-identity.json is written

on a completely healthy deployment, and then stop: identity decides CB_MODE,
and with no mode doctor returns before running any other check. The operator
sees two red checks, a truncated report, and advice to reinstall over a working
system. The fallback selftest in that same branch then fails too, because the
binary carries cap_net_raw and PyInstaller's onefile parent check cannot read
/proc for a non-dumpable process unprivileged — so the truncated report is also
maximally alarming.

The CLI already drew this distinction for `.env` ("Cannot read … Try: sudo cb
doctor"); identity never got it. These tests pin that it now does, and — just
as importantly — that a genuinely absent identity still says MISSING, because
telling someone with no install to try sudo is the same failure inverted.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CB = ROOT / "cb"

RUNNING_AS_ROOT = os.geteuid() == 0


def _run_cb(*args: str, identity: Path, home: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["CB_IDENTITY_PATH"] = str(identity)
    env["HOME"] = str(home)
    return subprocess.run(
        [str(CB), *args], capture_output=True, text=True, env=env, cwd=str(ROOT), check=False
    )


def _hidden_identity(tmp_path: Path) -> Path:
    """A valid identity inside a directory the caller cannot traverse."""
    config_dir = tmp_path / "etc-circuitbreaker"
    config_dir.mkdir()
    identity = config_dir / "install-identity.json"
    identity.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "mode": "native",
                "version": "0.4.2",
                "installed_at": "2026-09-21T12:00:00Z",
                "data_dir": "/var/lib/circuitbreaker",
            }
        ),
        encoding="utf-8",
    )
    config_dir.chmod(0o000)
    return identity


def test_info_names_the_unreadable_path_instead_of_claiming_it_is_missing(tmp_path):
    identity = _hidden_identity(tmp_path)
    home = tmp_path / "home"
    try:
        result = _run_cb("info", identity=identity, home=home)
    finally:
        identity.parent.chmod(0o700)

    if RUNNING_AS_ROOT:
        # root traverses whatever the mode says, so it simply reads the file.
        # That is the same property from the other side: the CLI reports on
        # what this caller can actually reach.
        assert result.returncode == 0, result.stdout + result.stderr
        return

    combined = result.stdout + result.stderr
    assert "MISSING" not in result.stdout, (
        "a readable-only-by-root identity was reported as missing:\n" + combined
    )
    assert "UNREADABLE" in result.stdout, combined
    assert "sudo" in combined, "the operator must be told the fix is sudo, not reinstalling"
    assert str(identity.parent) in combined, "name the path that could not be read"


def test_info_json_keeps_its_error_code_and_adds_the_path(tmp_path):
    """Consumers switch on `error`; CLAUDE.md's compatibility rule says add a
    field alongside it rather than renaming it."""
    identity = _hidden_identity(tmp_path)
    home = tmp_path / "home"
    try:
        result = _run_cb("info", "--json", identity=identity, home=home)
    finally:
        identity.parent.chmod(0o700)

    if RUNNING_AS_ROOT:
        assert result.returncode == 0, result.stdout + result.stderr
        return

    payload = json.loads(result.stdout.strip())
    assert payload["error"] == "install_identity_missing", "the error code is a contract"
    assert payload["unreadable_path"] == str(identity.parent)
    assert "sudo" in payload["remediation"]


def test_doctor_says_sudo_rather_than_reinstall(tmp_path):
    identity = _hidden_identity(tmp_path)
    home = tmp_path / "home"
    try:
        result = _run_cb("doctor", identity=identity, home=home)
    finally:
        identity.parent.chmod(0o700)

    if RUNNING_AS_ROOT:
        return

    combined = result.stdout + result.stderr
    assert "sudo cb doctor" in combined, combined
    assert "Re-run the installer so install-identity.json is written" not in combined, (
        "reinstalling is the wrong advice for a permissions problem:\n" + combined
    )


def test_a_genuinely_absent_identity_still_says_missing(tmp_path):
    """The inverse failure. Someone with no install must not be sent to sudo."""
    absent = tmp_path / "nowhere" / "install-identity.json"
    home = tmp_path / "home"
    result = _run_cb("info", identity=absent, home=home)

    assert result.returncode != 0
    assert "MISSING" in result.stdout, result.stdout + result.stderr
    assert "UNREADABLE" not in result.stdout
    assert "Re-run the installer" in result.stdout


def test_absent_identity_json_reports_no_unreadable_path(tmp_path):
    absent = tmp_path / "nowhere" / "install-identity.json"
    home = tmp_path / "home"
    result = _run_cb("info", "--json", identity=absent, home=home)

    payload = json.loads(result.stdout.strip())
    assert payload["error"] == "install_identity_missing"
    assert payload["unreadable_path"] == ""
