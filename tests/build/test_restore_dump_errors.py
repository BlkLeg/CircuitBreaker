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
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
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
