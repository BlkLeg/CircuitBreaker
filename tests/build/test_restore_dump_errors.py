"""A dump that does not replay cleanly must fail the restore, not finish it.

`deploy/scripts/restore.sh` step 10 dropped the database, recreated it empty and
piped the snapshot's `db.sql.gz` into `psql` with no `ON_ERROR_STOP`. That is the
one psql invocation in the repo that lacked it. psql's default is to report each
failed statement on stderr and carry on, and to exit 0 as long as it reached the
end of its input -- so a replay that created two tables out of ninety looked
exactly like a replay that created all ninety. `set -e` had nothing to trigger
on, and the script went on to sync uploads, rewrite `CB_VAULT_KEY`, start the
unit and print "Restore complete." over a database with most of its schema
missing. The operator's evidence that the disaster recovery worked was that
sentence.

The failure is not hypothetical on the paths this script exists for: a recovery
host whose PostgreSQL cannot load an extension the snapshot uses, one where the
role the dump grants to does not exist, or a major-version mismatch all produce
exactly this shape -- errors on stderr, exit 0, a partial database.

The three other places this repo replays a dump (`cb:693`, `cb:696`, and
`apps/backend/tests/services/test_snapshot_roundtrip.py`) all pass
`-v ON_ERROR_STOP=1`, so this is the convention being restored rather than a new
one being invented.

The behavioural tests run the real script end to end against a stub PATH. The `psql`
stub models the real thing on the only axis that matters here: an erroring statement is
fatal, and reflected in the exit status, only when `-v ON_ERROR_STOP=1` is on its
command line. Everything else restore.sh shells out to that is not guaranteed on a
developer machine is stubbed too, so this module carries no skip marker -- a skipped
test pins nothing, and REL-19 rightly makes every skip a registered, dated liability.

The second half of the module covers the other artifact this script now takes. `install.sh
--upgrade` writes a bare `pre-upgrade-*.sql` before it migrates, and post-1.0 downgrade is
rejected outright, so that dump is the whole of the rollback for a migration that goes
wrong -- but nothing in the tree would consume it: restore.sh rejected it at the tarball
structure check, and `cb restore` rejected it in the backend verifier. The upgrade
produced a rollback nobody could perform.

The dump is the right artifact for that moment rather than a weaker one. run_upgrade takes
it after `install.sh` has already replaced the binary with the new build and before
migrations run, so the snapshot builder is not available to it -- `run_full_snapshot`
reads `AppSettings` through the new ORM against the old schema -- and a migration changes
the schema, not the uploads and not the vault key. What was missing was a consumer.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESTORE_SH = ROOT / "deploy" / "scripts" / "restore.sh"

# The single token the psql stub treats as a statement the server rejects. Kept to
# one word with no shell metacharacters so it can go straight into the stub's `case`.
BAD_TOKEN = "cb_test_missing_extension"

GOOD_SQL = "CREATE TABLE roundtrip_probe (id integer PRIMARY KEY);\n"
BAD_SQL = (
    GOOD_SQL
    + f"CREATE EXTENSION IF NOT EXISTS {BAD_TOKEN};\n"
    + "CREATE TABLE tail_table (id integer);\n"
)

# Everything restore.sh shells out to that must not be allowed to reach the host.
# `systemctl` is the dangerous one and `dropdb` is the destructive one; a bare exit 0
# is all either needs to be for this script's purposes.
_INERT_STUBS = ("dropdb", "createdb", "systemctl")

# jq and rsync are stubbed rather than taken from the host so the module needs no skip.
# Neither is under test here: jq only reads the manifest restore.sh already checksums by
# hand with sha256sum, and rsync only moves the uploads directory. tar, gzip, sed and
# sha256sum are left real -- they are the checks under the script's own validation
# steps, and they ship with every base system this project supports.
JQ_STUB = """#!/bin/sh
# Enough of jq for restore.sh: `jq . FILE` and `jq -r .db_checksum_sha256 FILE`.
for arg in "$@"; do file="$arg"; done
case "$*" in
  *db_checksum_sha256*)
    sed -n \'s/.*"db_checksum_sha256"[[:space:]]*:[[:space:]]*"\\([^"]*\\)".*/\\1/p\' "$file"
    ;;
  *) cat "$file" ;;
esac
"""

RSYNC_STUB = """#!/bin/sh
# Enough of rsync for restore.sh: `rsync -a --delete SRC/ DST/`.
for arg in "$@"; do prev="$dest"; dest="$arg"; done
rm -rf "${dest%/}" && mkdir -p "${dest%/}" && cp -a "${prev%/}/." "${dest%/}/"
"""

# A stub that behaves the way psql actually does: without ON_ERROR_STOP a failed
# statement is a message on stderr and nothing more, and the exit status only
# reports whether psql itself got to the end of its input. With it, psql stops at
# the first failure and exits 3. Every invocation is logged so a test can assert
# on the argv the script built.
PSQL_STUB = f"""#!/bin/sh
printf '%s\\n' "$*" >> "$CB_TEST_PSQL_LOG"
sql=$(cat)
printf '%s' "$sql" > "$CB_TEST_PSQL_STDIN"
case "$sql" in
  *{BAD_TOKEN}*)
    echo 'ERROR:  extension "{BAD_TOKEN}" is not available' >&2
    case "$*" in
      *ON_ERROR_STOP=1*) exit 3 ;;
    esac
    ;;
esac
exit 0
"""


def _write_snapshot(tmp_path: Path, sql: str) -> Path:
    """A structurally valid snapshot tarball carrying `sql` as its dump."""
    staging = tmp_path / "staging" / "cb-snapshot-20260826-020000"
    (staging / "uploads").mkdir(parents=True)
    (staging / "uploads" / "logo.png").write_bytes(b"not really a png")

    dump = staging / "db.sql.gz"
    # mtime=0 keeps the gzip header, and therefore the checksum, reproducible.
    with dump.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as handle:
            handle.write(sql.encode())

    (staging / "vault.key").write_text("dGVzdC12YXVsdC1rZXk=\n")
    (staging / "manifest.json").write_text(
        json.dumps(
            {
                "created_at": "2026-08-26T02:00:00Z",
                "db_checksum_sha256": hashlib.sha256(dump.read_bytes()).hexdigest(),
            }
        )
    )

    archive = tmp_path / "cb-snapshot-20260826-020000.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(staging, arcname=staging.name)
    return archive


def _harness(tmp_path: Path) -> dict[str, str]:
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    for name in _INERT_STUBS:
        (stubs / name).write_text("#!/bin/sh\nexit 0\n")
    (stubs / "psql").write_text(PSQL_STUB)
    (stubs / "jq").write_text(JQ_STUB)
    (stubs / "rsync").write_text(RSYNC_STUB)
    for stub in stubs.iterdir():
        stub.chmod(0o755)

    env_file = tmp_path / "etc" / "circuitbreaker.env"
    env_file.parent.mkdir(parents=True)
    env_file.write_text("CB_VAULT_KEY=stale-key-from-before-the-restore\n")

    return {
        "PATH": f"{stubs}{os.pathsep}{os.environ['PATH']}",
        "HOME": str(tmp_path),
        "CB_ENV_FILE": str(env_file),
        "CB_SERVICE_UNIT": "cb-test.service",
        "CB_DATA_DIR": str(tmp_path / "data"),
        "CB_TEST_PSQL_LOG": str(tmp_path / "psql-argv.log"),
        "CB_TEST_PSQL_STDIN": str(tmp_path / "psql-stdin.sql"),
    }


def _run(tmp_path: Path, sql: str) -> subprocess.CompletedProcess[str]:
    archive = _write_snapshot(tmp_path, sql)
    return subprocess.run(
        [shutil.which("bash") or "bash", str(RESTORE_SH), str(archive)],
        input="y\n",
        env=_harness(tmp_path),
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_a_dump_that_does_not_replay_cleanly_fails_the_restore(tmp_path: Path):
    """The regression: psql reported the error, exited 0, and the script finished."""
    result = _run(tmp_path, BAD_SQL)
    combined = result.stdout + result.stderr

    assert result.returncode != 0, (
        "restore.sh exited 0 after the dump failed to replay -- the operator's only "
        "signal that disaster recovery worked is this exit status and the line "
        "below it.\n" + combined
    )
    assert "Restore complete" not in result.stdout, (
        "restore.sh reported a completed restore over a partially loaded database:\n"
        + combined
    )
    assert "not restored" in combined.lower() or "did not replay" in combined.lower(), (
        "restore.sh failed without telling the operator the database was not "
        "restored:\n" + combined
    )


def test_the_replay_stops_at_the_first_error_rather_than_running_on(tmp_path: Path):
    """`-v ON_ERROR_STOP=1` has to be on the invocation, not just checked after it."""
    _run(tmp_path, BAD_SQL)
    argv = (tmp_path / "psql-argv.log").read_text()
    assert "ON_ERROR_STOP=1" in argv, (
        "the dump was replayed without ON_ERROR_STOP=1, so psql kept executing "
        "statements after the first failure and exited 0 regardless. psql argv "
        "was:\n" + argv
    )


def test_a_clean_dump_still_restores_end_to_end(tmp_path: Path):
    """The control: nothing above may be bought by failing a healthy restore."""
    result = _run(tmp_path, GOOD_SQL)
    combined = result.stdout + result.stderr

    assert result.returncode == 0, combined
    assert "Restore complete" in result.stdout, combined
    assert (tmp_path / "data" / "uploads" / "logo.png").is_file(), (
        "uploads were not restored:\n" + combined
    )
    env_text = (tmp_path / "etc" / "circuitbreaker.env").read_text()
    assert "CB_VAULT_KEY=dGVzdC12YXVsdC1rZXk=" in env_text, env_text


# ── the bare pre-upgrade dump (the other artifact restore.sh takes) ───────────


def _run_dump(
    tmp_path: Path, sql: str, *, name: str = "pre-upgrade-20260826-020000.sql"
) -> subprocess.CompletedProcess[str]:
    """Run the real script against a bare .sql, the way a rollback does."""
    dump = tmp_path / name
    dump.write_text(sql)
    return subprocess.run(
        [shutil.which("bash") or "bash", str(RESTORE_SH), str(dump)],
        input="y\n",
        env=_harness(tmp_path),
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=120,
    )


# What run_upgrade's `pg_dump ... > pre-upgrade-<ts>.sql` actually writes: psql-replayable
# plain SQL under pg_dump's own header. The header is what tells a truncated artifact from
# a whole one, so it belongs in the fixture rather than being assumed away.
PG_DUMP_HEADER = "--\n-- PostgreSQL database dump\n--\n\n"


def test_a_bare_pre_upgrade_dump_is_restored_rather_than_rejected(tmp_path: Path):
    """The regression: the documented rollback artifact had no consumer.

    `install.sh --upgrade` writes this file and tells the operator it is their way
    back. restore.sh used to answer `tar -tzf` on it, print "Cannot read tarball"
    and exit 1 -- so the only artifact standing between a bad migration and a lost
    install was one no tool in the repository would take.
    """
    result = _run_dump(tmp_path, PG_DUMP_HEADER + GOOD_SQL)
    combined = result.stdout + result.stderr

    assert result.returncode == 0, (
        "restore.sh refused the bare pre-upgrade dump that install.sh --upgrade "
        "writes and documents as the rollback:\n" + combined
    )
    assert "Restore complete" in result.stdout, combined
    replayed = (tmp_path / "psql-stdin.sql").read_text()
    assert "roundtrip_probe" in replayed, (
        "the dump's own SQL never reached psql -- the restore reported success "
        f"without replaying anything:\n{replayed}"
    )


def test_the_bare_dump_is_replayed_with_on_error_stop_too(tmp_path: Path):
    """The new path must not be the one place the ON_ERROR_STOP fix does not reach."""
    _run_dump(tmp_path, PG_DUMP_HEADER + GOOD_SQL)
    argv = (tmp_path / "psql-argv.log").read_text()
    assert "ON_ERROR_STOP=1" in argv, (
        "the bare dump was replayed without ON_ERROR_STOP=1, so psql would run on "
        "past the first failed statement and exit 0. psql argv was:\n" + argv
    )


def test_a_bare_dump_that_does_not_replay_cleanly_fails_the_restore(tmp_path: Path):
    """Same contract as the snapshot path: a partial load is not a restore."""
    result = _run_dump(tmp_path, PG_DUMP_HEADER + BAD_SQL)
    combined = result.stdout + result.stderr

    assert result.returncode != 0, combined
    assert "Restore complete" not in result.stdout, combined


def test_a_bare_dump_leaves_the_vault_key_and_the_uploads_alone(tmp_path: Path):
    """A dump carries neither, and a rollback needs neither changed.

    This is the half that would be silently wrong if the .sql path were bolted onto
    the snapshot path instead of branched out of it: step 12 would read a vault.key
    that does not exist, and step 11 would rsync an uploads/ that does not exist
    over the one this host is still using.
    """
    uploads = tmp_path / "data" / "uploads"
    uploads.mkdir(parents=True)
    (uploads / "logo.png").write_bytes(b"the file this host is still serving")

    result = _run_dump(tmp_path, PG_DUMP_HEADER + GOOD_SQL)
    combined = result.stdout + result.stderr
    assert result.returncode == 0, combined

    assert (uploads / "logo.png").read_bytes() == b"the file this host is still serving", (
        "a database-only restore deleted the uploads it was never given:\n" + combined
    )
    env_text = (tmp_path / "etc" / "circuitbreaker.env").read_text()
    assert "CB_VAULT_KEY=stale-key-from-before-the-restore" in env_text, (
        "a database-only restore rewrote CB_VAULT_KEY, which would make every "
        f"encrypted column on this host unreadable:\n{env_text}"
    )


def test_the_confirmation_says_what_a_database_only_restore_does_not_touch(tmp_path: Path):
    """"REPLACE all data" is not true of this path, and the operator answers y to it."""
    result = _run_dump(tmp_path, PG_DUMP_HEADER + GOOD_SQL)
    prompt = result.stdout[: result.stdout.find("Continue?")]
    assert "NOT touched" in prompt, (
        "the operator was asked to confirm a restore described as replacing all "
        f"data, when uploads and the vault key are left alone:\n{prompt}"
    )


def test_a_truncated_dump_is_refused_before_the_service_is_stopped(tmp_path: Path):
    """A dump killed by a full disk is the failure this path exists to survive.

    Nothing has been destroyed at the point this is caught, which is the whole
    reason the check sits ahead of step 8 rather than being discovered by psql
    after the database has already been dropped.
    """
    result = _run_dump(tmp_path, "-- this file lost its contents\n")
    combined = result.stdout + result.stderr

    assert result.returncode != 0, combined
    assert "==> Stopping" not in result.stdout, (
        "restore.sh stopped the service before noticing the dump was unusable:\n" + combined
    )
    assert "Nothing has been changed" in combined, combined


def test_an_empty_dump_is_refused(tmp_path: Path):
    """`pre-upgrade-*.sql` is deleted on failure upstream; a 0-byte one is still possible."""
    result = _run_dump(tmp_path, "")
    combined = result.stdout + result.stderr
    assert result.returncode != 0, combined
    assert "empty" in combined.lower(), combined


# ── The printed rollback has to survive being pasted ─────────────────────────
#
# deploy/setup.sh prints `sudo /opt/circuitbreaker/deploy/scripts/restore.sh <dump>`
# after a failed upgrade, at the point where it has already stopped
# circuitbreaker.target. Three things made that instruction a trap on a host
# install.sh had itself built, and none of them were reachable through the stubs
# above, because a `dropdb`/`createdb` that always exits 0 cannot express the
# failure:
#
#   * `dropdb -h 127.0.0.1 -U postgres` cannot authenticate. pg_hba.conf is
#     `host all all 127.0.0.1/32 md5`, and setup.sh initdb's the cluster with
#     --auth-host=md5 and never sets a password on the postgres role. dropdb's
#     failure was eaten by `|| true`; createdb was the line that actually died,
#     under set -e, after the service was already stopped.
#   * the owner-side replay ran psql with no PGPASSWORD against the same md5 rule.
#   * on the dnf families the client binaries live under /usr/pgsql-*/bin, which
#     is not on root's PATH -- setup.sh:1608 says so and qualifies its own
#     pg_dump accordingly, while this script called them bare.


def _superuser_stub_that_refuses_tcp(tmp_path: Path) -> dict[str, str]:
    """A createdb/dropdb pair that behaves like the real ones over TCP with md5."""
    env = _harness(tmp_path)
    stubs = Path(env["PATH"].split(os.pathsep)[0])
    refuse = (
        "#!/bin/sh\n"
        'printf \'%s %s\\n\' "$(basename "$0")" "$*" >> "$CB_TEST_SU_LOG"\n'
        'for a in "$@"; do\n'
        '  if [ "$a" = "-h" ]; then\n'
        '    echo "$(basename "$0"): error: connection to server at \\"127.0.0.1\\"'
        ' failed: fe_sendauth: no password supplied" >&2\n'
        "    exit 1\n"
        "  fi\n"
        "done\n"
        "exit 0\n"
    )
    for name in ("dropdb", "createdb"):
        (stubs / name).write_text(refuse)
        (stubs / name).chmod(0o755)
    env["CB_TEST_SU_LOG"] = str(tmp_path / "superuser-argv.log")
    return env


def test_the_superuser_step_does_not_connect_over_tcp(tmp_path: Path):
    """dropdb/createdb must go over the local socket, not -h 127.0.0.1."""
    archive = _write_snapshot(tmp_path, GOOD_SQL)
    env = _superuser_stub_that_refuses_tcp(tmp_path)
    result = subprocess.run(
        [shutil.which("bash") or "bash", str(RESTORE_SH), str(archive)],
        input="y\n",
        env=env,
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=120,
    )

    log = Path(env["CB_TEST_SU_LOG"])
    calls = log.read_text().splitlines() if log.exists() else []
    assert calls, "neither dropdb nor createdb ran at all:\n" + result.stdout + result.stderr
    over_tcp = [c for c in calls if "-h " in c]
    assert not over_tcp, (
        "the superuser step connects over TCP, which pg_hba answers with md5 and "
        "which the postgres role on an install.sh-built host has no password for. "
        "The operator pasting the rollback setup.sh printed loses the service and "
        "restores nothing:\n  " + "\n  ".join(over_tcp)
    )
    assert result.returncode == 0, (
        "the restore did not complete with a superuser step that refuses TCP:\n"
        + result.stdout
        + result.stderr
    )


def test_a_superuser_step_that_fails_says_so_instead_of_dying(tmp_path: Path):
    """createdb failing must report; it used to kill the script under set -e."""
    archive = _write_snapshot(tmp_path, GOOD_SQL)
    env = _harness(tmp_path)
    stubs = Path(env["PATH"].split(os.pathsep)[0])
    (stubs / "createdb").write_text(
        '#!/bin/sh\necho "createdb: error: permission denied" >&2\nexit 1\n'
    )
    (stubs / "createdb").chmod(0o755)
    result = subprocess.run(
        [shutil.which("bash") or "bash", str(RESTORE_SH), str(archive)],
        input="y\n",
        env=env,
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=120,
    )
    combined = result.stdout + result.stderr

    assert result.returncode != 0, "a failed createdb was treated as success:\n" + combined
    assert "could not create database" in combined.lower(), (
        "createdb failed and the script exited without saying what happened -- "
        "which is the whole defect, since the service is already stopped by "
        f"this point:\n{combined}"
    )


def test_the_owner_replay_supplies_a_password(tmp_path: Path):
    """pg_hba is md5 for 127.0.0.1; psql with no PGPASSWORD cannot replay."""
    archive = _write_snapshot(tmp_path, GOOD_SQL)
    env = _harness(tmp_path)
    env["CB_TEST_PGPASSWORD_LOG"] = str(tmp_path / "pgpassword.log")
    stubs = Path(env["PATH"].split(os.pathsep)[0])
    # Prepended, not appended: PSQL_STUB exits from inside its own case, so a
    # line after it never runs.
    (stubs / "psql").write_text(
        PSQL_STUB.replace(
            "#!/bin/sh\n",
            '#!/bin/sh\nprintf \'%s\\n\' "${PGPASSWORD-UNSET}" > "$CB_TEST_PGPASSWORD_LOG"\n',
            1,
        )
    )
    (stubs / "psql").chmod(0o755)
    Path(env["CB_ENV_FILE"]).write_text(
        "CB_VAULT_KEY=stale-key-from-before-the-restore\nCB_DB_PASSWORD=s3cret-from-env-file\n"
    )

    subprocess.run(
        [shutil.which("bash") or "bash", str(RESTORE_SH), str(archive)],
        input="y\n",
        env=env,
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=120,
    )

    seen = Path(env["CB_TEST_PGPASSWORD_LOG"])
    assert seen.exists(), "psql never ran, so nothing about PGPASSWORD was observed"
    value = seen.read_text().strip()
    assert value == "s3cret-from-env-file", (
        "the replay ran without the password from $CB_ENV_FILE, so against the "
        "shipped pg_hba (md5 on 127.0.0.1) it would prompt on a stdin already "
        f"carrying the dump and fail. PGPASSWORD was {value!r}"
    )


def test_the_client_binaries_are_resolved_through_pg_bin_dir(tmp_path: Path):
    """PGDG puts psql outside root's PATH on the dnf families; setup.sh says so."""
    archive = _write_snapshot(tmp_path, GOOD_SQL)
    env = _harness(tmp_path)
    stubs = Path(env["PATH"].split(os.pathsep)[0])

    # The dnf-family shape: nothing on PATH, everything under $PG_BIN_DIR.
    pg_bin = tmp_path / "usr" / "pgsql-15" / "bin"
    pg_bin.mkdir(parents=True)
    for name in ("psql", "dropdb", "createdb"):
        (pg_bin / name).write_text((stubs / name).read_text())
        (pg_bin / name).chmod(0o755)
        (stubs / name).unlink()
    env["PG_BIN_DIR"] = str(pg_bin)

    result = subprocess.run(
        [shutil.which("bash") or "bash", str(RESTORE_SH), str(archive)],
        input="y\n",
        env=env,
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=120,
    )
    combined = result.stdout + result.stderr

    assert "Missing required tools" not in combined, (
        "restore.sh refused to run because it looked for the client binaries on "
        "PATH only. On Fedora/RHEL/Rocky they are under $PG_BIN_DIR, which is "
        f"exactly where setup.sh finds its own pg_dump:\n{combined}"
    )
    assert result.returncode == 0, combined


# ── the rollback has to be executable without a human ───────────────────────
#
# ADR 0005 Phase 3, F11. The upgrade row executes the documented rollback the way
# the docs tell an operator to -- through the shipped
# `/usr/local/bin/circuit-breaker-rollback` wrapper -- over `ssh host '...'`,
# which has no TTY and no stdin. restore.sh's `read -r -p "Continue? [y/N]"` got
# EOF and the restore declined, so the row stopped at the banner having proved
# nothing about the rollback.
#
# Prompting by default is right and is not being changed: this is a destructive
# operation and "no answer is not consent" is the rule
# test_uninstall_volume_prompt.py pins. What was missing is a way to give consent
# *in advance*, which is what any runbook, cron job or recovery script needs --
# and what the tier that has to evidence ADR 0005's Tier 1 rollback guarantee
# needs, since it cannot type.
#
# Deliberately NOT copied from uninstall.sh: that script answers "can this
# process be asked anything at all?" before its first destructive step, because
# its prompt came *after* the container had been removed. restore.sh's prompt
# precedes every destructive step, so the ordering hazard that justified the
# preflight there does not exist here, and a `[ -t 0 ]` gate would only break
# every caller that legitimately pipes an answer.


def test_an_unanswered_prompt_still_aborts(tmp_path: Path):
    """The rule that does not change: EOF is not consent."""
    archive = _write_snapshot(tmp_path, "SELECT 1;\n")
    result = subprocess.run(
        [shutil.which("bash") or "bash", str(RESTORE_SH), str(archive)],
        input="",
        env=_harness(tmp_path),
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode != 0, "an unanswered prompt restored the database anyway"
    log = tmp_path / "psql-argv.log"
    assert not log.exists() or "DROP" not in log.read_text(encoding="utf-8"), (
        "the database was dropped without an answer"
    )


def test_advance_consent_runs_the_restore_without_a_prompt(tmp_path: Path):
    """CB_ASSUME_YES is the documented way to say yes before being asked."""
    archive = _write_snapshot(tmp_path, "SELECT 1;\n")
    env = {**_harness(tmp_path), "CB_ASSUME_YES": "1"}
    result = subprocess.run(
        [shutil.which("bash") or "bash", str(RESTORE_SH), str(archive)],
        input="",
        env=env,
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        f"CB_ASSUME_YES did not carry the restore through:\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert (tmp_path / "psql-argv.log").exists(), "the restore never reached psql"


def test_advance_consent_is_recorded_in_the_output(tmp_path: Path):
    """A destructive action taken without a prompt must still say so, or the
    log of a recovery gives no sign that anyone consented to it."""
    archive = _write_snapshot(tmp_path, "SELECT 1;\n")
    env = {**_harness(tmp_path), "CB_ASSUME_YES": "1"}
    result = subprocess.run(
        [shutil.which("bash") or "bash", str(RESTORE_SH), str(archive)],
        input="",
        env=env,
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=120,
    )
    combined = result.stdout + result.stderr
    assert "CB_ASSUME_YES" in combined, (
        f"the restore proceeded without recording that consent was pre-given:\n{combined}"
    )


def test_the_tier_invokes_the_rollback_non_interactively():
    """The harness side of the same defect: the row must actually pass consent,
    or it stops at the banner exactly as it did on its first execution."""
    tier = ROOT / "scripts/ci/tier3-artifact.sh"
    text = tier.read_text(encoding="utf-8")
    call = re.search(r"^.*circuit-breaker-rollback \"\$BACKUP\".*$", text, re.M)
    assert call, "the tier no longer executes the shipped rollback wrapper"
    assert "CB_ASSUME_YES" in call.group(0), (
        "the tier runs the rollback with no way to answer its confirmation "
        f"prompt, so the rollback half of Tier 1 can never be evidenced:\n  {call.group(0).strip()}"
    )
