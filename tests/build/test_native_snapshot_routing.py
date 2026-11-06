"""Exercise the native backup adapter without an installed application."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def run(tmp_path, *, verify_fails=False, dump_fails=False):
    cb = (ROOT / "cb").read_text()
    import re
    presentation = "\n".join(re.search(r"^" + name + r"\(\) \{\n.*?^\}", cb, re.M | re.S).group() for name in ("_cb_heading", "_cb_present_begin", "_cb_present_end"))
    block = presentation + "\n_cb_snapshot_runtime() {" + cb.split("_cb_snapshot_runtime() {", 1)[1].split("# ── restore", 1)[0]
    binary = tmp_path / "runtime"
    binary.write_text(f'''#!/bin/bash
printf '%s\\n' "$@" >> '{tmp_path}/argv'
case "$1" in
--snapshot-create) {'exit 1' if dump_fails else f"printf snapshot > '{tmp_path}/snapshot.tar.gz'; echo '{tmp_path}/snapshot.tar.gz'"} ;;
--snapshot-verify) {'exit 1' if verify_fails else 'exit 0'} ;;
esac
''')
    binary.chmod(0o755)
    env = tmp_path / "native.env"
    env.write_text("CB_VAULT_KEY=test-fixture\nCB_DB_URL=postgresql://fixture\n")
    script = f'''set -euo pipefail
_cb_lock() {{ :; }}
cb_lifecycle_mark_mutation() {{ :; }}
_cb_missing_dirs() {{ :; }}
_cb_hand_back() {{ :; }}
_require_postgres_client() {{ :; }}
_require_binary() {{ [[ -x "$1" ]]; }}
_info() {{ :; }}
_ok() {{ echo "$*"; }}
_fail() {{ echo "$*" >&2; exit 1; }}
_CONF=fixture.conf
CB_MODE=native
CB_NATIVE_BIN='{binary}'
CB_BINARY_ENV_FILE='{env}'
CB_BACKUP_DIR='{tmp_path}/backups'
GR= Y= R= P= V= G=
{block}
cmd_backup
'''
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True)


def test_native_backup_uses_installed_runtime_and_verifies_before_reporting(tmp_path):
    result = run(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "Backup written to" in result.stdout
    args = (tmp_path / "argv").read_text()
    assert "--snapshot-create" in args
    assert "--snapshot-verify" in args
    assert (tmp_path / "snapshot.tar.gz").stat().st_mode & 0o777 == 0o600


def test_native_failed_dump_never_reports_backup(tmp_path):
    result = run(tmp_path, dump_fails=True)
    assert result.returncode != 0
    assert "Backup written to" not in result.stdout


def test_native_corrupt_snapshot_never_reports_verified_backup(tmp_path):
    result = run(tmp_path, verify_fails=True)
    assert result.returncode != 0
    assert "Backup written to" not in result.stdout
    assert "verification failed" in result.stderr
