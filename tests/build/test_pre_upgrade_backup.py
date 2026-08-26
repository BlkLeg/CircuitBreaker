"""`bash install.sh --upgrade` may not claim a backup it did not take.

run_upgrade() dumps the database before it stops the services, and the operator
is told "Backup saved: <path>" -- which is the only signal they get that a
rollback artifact exists. Every way that dump could fail was swallowed:

  * ``2>/dev/null`` threw away pg_dump's own diagnosis, so the install log had
    nothing to explain the empty file.
  * ``|| true`` turned every non-zero exit into success, and ``cb_ok`` ran
    unconditionally afterwards.
  * The dump went to ``-p 6432``, pgbouncer, which runs ``pool_mode =
    transaction`` (deploy/config/pgbouncer.ini). pg_dump needs one session for
    the whole run, so a transaction pool cannot serve it. The rest of the
    product dumps against 5432 direct, which is what CB_DB_URL points at.
  * ``pg_dump`` was unqualified. PGDG installs it under ``$PG_BIN_DIR``
    (/usr/pgsql-15/bin on the dnf families), which is not on root's PATH -- so
    on Fedora/RHEL/Rocky the command was "not found" and the operator still
    read "Backup saved".
  * ``${CB_DATA_DIR}/backups`` is created by stage1_bootstrap, which
    run_upgrade never calls. Upgrading an install that predates that directory
    made the output redirection itself fail, before pg_dump ever ran.

The upgrade then stopped the services and ran migrations. Post-1.0 downgrade is
rejected (docs/release/1.0.0-compatibility-policy.md), so "restore the
pre-upgrade backup" is the documented recovery -- against a file that was empty
or absent.

These tests run the shipped block in a sandbox with a stub pg_dump rather than
asserting on its text, because the swallow was a property of how the pieces
composed, not of any one token.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SETUP_SH = REPO_ROOT / "deploy" / "setup.sh"

# The block as run_upgrade() runs it: from its own cb_step banner up to the
# outer `fi` that closes the "is pgbouncer up?" test. Anchored on two-space
# indentation so the nested `fi` of the failure guard cannot end the match.
BLOCK_RE = re.compile(
    r'^  cb_step "Creating pre-upgrade backup"\n.*?^  fi$',
    re.MULTILINE | re.DOTALL,
)

# cb_step/cb_ok/cb_warn/cb_fail live in install.sh, which sources setup.sh.
# cb_fail's contract is the one that matters here: it prints, runs diagnostics
# and `exit 1`s.
HARNESS = """\
set -euo pipefail
cb_step() {{ echo "STEP|$1"; }}
cb_ok()   {{ echo "OK|$1"; }}
cb_warn() {{ echo "WARN|$1"; }}
cb_fail() {{ echo "FAIL|$1"; echo "HINT|${{2:-}}"; exit 1; }}
run_backup() {{
{block}
}}
run_backup
"""

PG_DUMP_STUB = """\
#!/usr/bin/env bash
printf '%s\\n' "$@" > "$CB_TEST_ARGV"
case "$CB_TEST_PGDUMP" in
  ok)     echo "-- PostgreSQL database dump"; exit 0 ;;
  fail)   echo "pg_dump: error: connection to server failed" >&2; exit 1 ;;
  empty)  exit 0 ;;
esac
"""

SYSTEMCTL_STUB = """\
#!/usr/bin/env bash
[[ "${1:-}" == "is-active" && "${CB_TEST_PGBOUNCER:-active}" == "active" ]]
"""

# The sandbox has no `breaker` user, so the real chown would fail the block for a
# reason that has nothing to do with what is under test. Stub it and record the
# argv instead, which also lets the ownership handoff itself be asserted --
# run_upgrade runs as root with umask 022, and a backups directory left root:root
# is one the breaker-run backend cannot write its scheduled dumps into.
CHOWN_STUB = """\
#!/usr/bin/env bash
printf '%s\\n' "$@" >> "$CB_TEST_CHOWN"
"""


def _block() -> str:
    match = BLOCK_RE.search(SETUP_SH.read_text(encoding="utf-8"))
    assert match is not None, (
        "the pre-upgrade backup block was not found in deploy/setup.sh -- "
        "if run_upgrade was restructured, re-anchor this test on it"
    )
    return match.group(0)


class Run:
    def __init__(
        self,
        proc: subprocess.CompletedProcess,
        data_dir: Path,
        argv: Path,
        chown: Path,
    ):
        self.proc = proc
        self.data_dir = data_dir
        self._argv = argv
        self._chown = chown

    @property
    def stdout(self) -> str:
        return self.proc.stdout

    @property
    def returncode(self) -> int:
        return self.proc.returncode

    @property
    def argv(self) -> list[str]:
        if not self._argv.exists():
            return []
        return self._argv.read_text(encoding="utf-8").split()

    @property
    def chown_argv(self) -> list[str]:
        if not self._chown.exists():
            return []
        return self._chown.read_text(encoding="utf-8").split()

    @property
    def dumps(self) -> list[Path]:
        backups = self.data_dir / "backups"
        return sorted(backups.glob("pre-upgrade-*.sql")) if backups.is_dir() else []


def run_backup(
    tmp_path: Path,
    *,
    pg_dump: str = "ok",
    pgbouncer: str = "active",
    on_path: bool = True,
    make_backups_dir: bool = True,
) -> Run:
    """Execute the shipped block against stub binaries.

    `on_path` controls whether pg_dump is also reachable without $PG_BIN_DIR;
    turning it off is how the dnf families see the world.
    """
    data_dir = tmp_path / "data"
    (data_dir / "logs").mkdir(parents=True)
    if make_backups_dir:
        (data_dir / "backups").mkdir()

    pg_bin = tmp_path / "pgsql-15" / "bin"
    pg_bin.mkdir(parents=True)
    stub_path = tmp_path / "path"
    stub_path.mkdir()

    for target in [pg_bin / "pg_dump"] + ([stub_path / "pg_dump"] if on_path else []):
        target.write_text(PG_DUMP_STUB, encoding="utf-8")
        target.chmod(0o755)
    (stub_path / "systemctl").write_text(SYSTEMCTL_STUB, encoding="utf-8")
    (stub_path / "systemctl").chmod(0o755)
    (stub_path / "chown").write_text(CHOWN_STUB, encoding="utf-8")
    (stub_path / "chown").chmod(0o755)

    argv = tmp_path / "argv"
    chown = tmp_path / "chown-argv"
    log_file = data_dir / "logs" / "install.log"
    proc = subprocess.run(
        ["bash", "-c", HARNESS.format(block=_block())],
        capture_output=True,
        text=True,
        env={
            "PATH": f"{stub_path}:/usr/bin:/bin",
            "CB_DATA_DIR": str(data_dir),
            "CB_DB_PASSWORD": "s3cret",
            "PG_BIN_DIR": str(pg_bin),
            "LOG_FILE": str(log_file),
            "CB_TEST_PGDUMP": pg_dump,
            "CB_TEST_PGBOUNCER": pgbouncer,
            "CB_TEST_ARGV": str(argv),
            "CB_TEST_CHOWN": str(chown),
        },
    )
    return Run(proc, data_dir, argv, chown)


def test_a_working_dump_is_still_reported_as_saved(tmp_path):
    """The happy path must be untouched by the guard."""
    run = run_backup(tmp_path)
    assert run.returncode == 0, run.proc.stderr
    assert "OK|Backup saved:" in run.stdout
    assert len(run.dumps) == 1
    assert run.dumps[0].read_text(encoding="utf-8").startswith("-- PostgreSQL")


def test_a_failed_dump_does_not_report_a_backup(tmp_path):
    """The regression: pg_dump exits 1 and the operator is told it was saved."""
    run = run_backup(tmp_path, pg_dump="fail")
    assert "OK|Backup saved:" not in run.stdout, (
        "the upgrade claimed a backup after pg_dump exited non-zero"
    )


def test_a_failed_dump_aborts_the_upgrade(tmp_path):
    """Services are stopped and migrations run next; there is no second chance."""
    run = run_backup(tmp_path, pg_dump="fail")
    assert run.returncode != 0
    assert "FAIL|" in run.stdout


def test_a_failed_dump_leaves_no_truncated_artifact_behind(tmp_path):
    """An empty .sql next to real ones is worse than none: it looks like a backup."""
    run = run_backup(tmp_path, pg_dump="fail")
    assert run.dumps == []


def test_pg_dump_stderr_reaches_the_install_log(tmp_path):
    """`tail -50 install.log` is the hint cb_fail gives; it must contain the cause."""
    run = run_backup(tmp_path, pg_dump="fail")
    log = (run.data_dir / "logs" / "install.log").read_text(encoding="utf-8")
    assert "connection to server failed" in log


def test_a_silent_empty_dump_is_treated_as_a_failure(tmp_path):
    """A zero-byte file that exits 0 restores nothing. Refuse it too."""
    run = run_backup(tmp_path, pg_dump="empty")
    assert "OK|Backup saved:" not in run.stdout
    assert run.returncode != 0
    assert run.dumps == []


def test_dump_targets_postgres_directly_not_the_transaction_pool(tmp_path):
    """pgbouncer runs pool_mode = transaction; pg_dump needs one whole session."""
    run = run_backup(tmp_path)
    assert "5432" in run.argv, run.argv
    assert "6432" not in run.argv, (
        "pg_dump was pointed at pgbouncer, which cannot hold a session open for it"
    )


def test_pg_dump_is_resolved_through_pg_bin_dir(tmp_path):
    """PGDG puts pg_dump outside root's PATH on the dnf families."""
    run = run_backup(tmp_path, on_path=False)
    assert run.returncode == 0, run.proc.stderr
    assert "OK|Backup saved:" in run.stdout
    assert len(run.dumps) == 1
    assert run.dumps[0].read_text(encoding="utf-8").startswith("-- PostgreSQL")


def test_a_created_backups_directory_is_handed_to_breaker(tmp_path):
    """Creating it as root is only half the job.

    run_upgrade runs as root with umask 022, so a bare mkdir leaves the
    directory root:root 0755 -- and the backend runs as breaker. Creating it
    without handing it over fixes this one dump and permanently breaks every
    scheduled one (services/db_backup.py and the daily snapshot both write
    here), which trades a visible failure for a silent one.
    """
    run = run_backup(tmp_path, make_backups_dir=False)
    assert run.returncode == 0, run.proc.stderr
    assert "breaker:breaker" in run.chown_argv, (
        "the backups directory was created but never chowned to breaker -- "
        f"chown was called with {run.chown_argv!r}"
    )
    assert str(run.data_dir / "backups") in run.chown_argv


def test_backups_directory_is_created_before_the_dump(tmp_path):
    """run_upgrade never calls stage1_bootstrap, which is what creates it."""
    run = run_backup(tmp_path, make_backups_dir=False)
    assert run.returncode == 0, run.proc.stderr
    assert "OK|Backup saved:" in run.stdout
    assert len(run.dumps) == 1
    assert run.dumps[0].read_text(encoding="utf-8").startswith("-- PostgreSQL")


def test_pgbouncer_down_still_only_warns(tmp_path):
    """Nothing to dump is a different situation from a dump that broke."""
    run = run_backup(tmp_path, pgbouncer="inactive")
    assert run.returncode == 0, run.proc.stderr
    assert "WARN|" in run.stdout
    assert "OK|Backup saved:" not in run.stdout


def test_pgbouncer_liveness_check_is_not_the_dump_target(tmp_path):
    """The systemctl probe names pgbouncer only because it proves Postgres is up."""
    block = _block()
    assert "circuitbreaker-pgbouncer" in block
