"""ACC-15 — the restore fault matrix, against the real deploy/scripts/restore.sh.

ACC-15: "Reject or recover safely from disk full, permission failure, corrupt archive,
checksum mismatch, missing vault key, incompatible schema, and partial snapshot."

restore.sh is the native restore: `cb restore` drives it on a package host, and it is
run directly for disaster recovery when `cb` or the binary is part of what was lost — so
it cannot lean on the backend verifier and has to refuse every one of these by itself.
The property asserted for each fault is the one that matters to an operator: the script
exits non-zero with the cause, says nothing has been changed, and it is true —

* the service was never stopped (`systemctl stop` never ran),
* the database was never dropped, recreated or replayed into (`dropdb`, `createdb` and
  `psql` never ran),
* the environment file holding CB_VAULT_KEY is byte-for-byte what it was, and
* the uploads directory is byte-for-byte what it was.

The script runs for real, under bash, with real tar, gzip, sha256sum, sed and awk. Only
what would reach outside the test is stubbed: systemctl and the PostgreSQL client tools
(which log their argv instead), rsync when the host has none, and jq when the host has
none (a stub that answers the four queries the script makes). `df` and `tar -x` are
stubbed only in the two disk-full cases, because a full filesystem cannot be arranged
portably inside a test. CB_DB_SUPERUSER is set to the user running the test: as root,
restore.sh otherwise switches to the `postgres` OS user, whose PATH has no stubs.

The backend verifier's half of the matrix is apps/backend/tests/services/
test_restore_fault_matrix.py.
"""

from __future__ import annotations

import base64
import getpass
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
RESTORE_SH = ROOT / "deploy" / "scripts" / "restore.sh"
SNAPSHOT_PY = (
    ROOT / "apps" / "backend" / "src" / "app" / "services" / "backup" / "snapshot.py"
)
CB_COPIES = (ROOT / "cb", ROOT / "deploy" / "cli" / "cb")

SNAP_ROOT = "cb-snapshot-20260927-000000"
ENV_BEFORE = "CB_VAULT_KEY=the-key-this-host-runs-on\nCB_DB_PASSWORD=unchanged\n"
UPLOAD_BEFORE = b"the logo this host is serving"

PG_DUMP_HEADER = "--\n-- PostgreSQL database dump\n--\n\n"
PG_DUMP_TRAILER = "\n--\n-- PostgreSQL database dump complete\n--\n\n"

_LOGGING_STUB = (
    '#!/bin/sh\necho "$(basename "$0") $*" >> "$CB_TEST_LOG"\n{extra}exit 0\n'
)

# rsync -a --delete SRC/ DST/, which is the only way restore.sh calls it.
_RSYNC_STUB = """#!/bin/sh
for arg in "$@"; do prev="$dest"; dest="$arg"; done
rm -rf "${dest%/}" && mkdir -p "${dest%/}" && cp -a "${prev%/}/." "${dest%/}/"
"""

# Enough of jq for restore.sh when the host has none: `.`, `.key`, `.key // default`
# and `(.key // [])[]`, with and without -r. Used only when jq is not installed.
_JQ_STUB = """import json
import sys

args = sys.argv[1:]
raw = args[0] == "-r"
if raw:
    args = args[1:]
expr, path = args[0], args[1]
with open(path, encoding="utf-8") as handle:
    data = json.load(handle)
if expr == ".":
    print(json.dumps(data, indent=2))
    sys.exit(0)
iterate = expr.startswith("(") and expr.endswith(")[]")
if iterate:
    expr = expr[1:-3]
key, _, default = expr.partition(" // ")
value = data.get(key.lstrip(".")) if isinstance(data, dict) else None
if value is None:
    if default == "empty":
        sys.exit(0)
    value = json.loads(default) if default else None
for item in (value or []) if iterate else [value]:
    print(item if raw and isinstance(item, str) else json.dumps(item))
"""


# ── Fixtures ──────────────────────────────────────────────────────────────────────────


def _vault_key() -> str:
    """An ephemeral key of the Fernet shape (32 url-safe base64 bytes); never hardcoded."""
    return base64.urlsafe_b64encode(os.urandom(32)).decode()


def _dump(vault_key: str, *, complete: bool = True) -> bytes:
    body = (
        PG_DUMP_HEADER
        + "CREATE TABLE restore_probe (id integer PRIMARY KEY);\n"
        + "COPY public.app_settings (id, vault_key_hash, vault_key_rotated_at) FROM stdin;\n"
        + f"1\t{hashlib.sha256(vault_key.encode()).hexdigest()}\t\\N\n"
        + "\\.\n"
    )
    return (body + (PG_DUMP_TRAILER if complete else "")).encode()


def _entry(
    name: str, payload: bytes | None = None, **attrs: Any
) -> tuple[tarfile.TarInfo, bytes | None]:
    info = tarfile.TarInfo(name)
    if payload is None and "type" not in attrs:
        info.type = tarfile.DIRTYPE
        info.mode = 0o755
    else:
        info.size = len(payload or b"")
        info.mode = 0o644
    for attr, value in attrs.items():
        setattr(info, attr, value)
    return info, payload


def _snapshot(
    tmp_path: Path,
    *,
    vault_key: str | None = None,
    dump: bytes | None = None,
    db_gz: bytes | None = None,
    manifest: dict[str, Any] | None = None,
    extra: Iterable[tuple[tarfile.TarInfo, bytes | None]] = (),
) -> Path:
    """A snapshot shaped like build_snapshot's; each keyword breaks one thing about it."""
    key = vault_key if vault_key is not None else _vault_key()
    if db_gz is None:
        db_gz = gzip.compress(dump if dump is not None else _dump(key), mtime=0)
    uploads = {"uploads/logo.png": os.urandom(32 * 1024), "uploads/a/b.txt": b"nested"}
    body: dict[str, Any] = {
        "format_version": 1,
        "cb_version": "1.0.0",
        "uploads_count": len(uploads),
        "db_checksum_sha256": hashlib.sha256(db_gz).hexdigest(),
        "config_files": [],
    }
    body.update(manifest or {})
    entries = [
        _entry(SNAP_ROOT),
        _entry(f"{SNAP_ROOT}/uploads"),
        _entry(f"{SNAP_ROOT}/uploads/a"),
        _entry(f"{SNAP_ROOT}/db.sql.gz", db_gz),
        _entry(f"{SNAP_ROOT}/vault.key", key.encode() + b"\n"),
        _entry(f"{SNAP_ROOT}/manifest.json", json.dumps(body, indent=2).encode()),
    ]
    entries += [
        _entry(f"{SNAP_ROOT}/{name}", payload) for name, payload in uploads.items()
    ]
    entries += list(extra)
    archive = tmp_path / "in" / f"{SNAP_ROOT}.tar.gz"
    archive.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "w:gz") as tf:
        for info, payload in entries:
            tf.addfile(info, io.BytesIO(payload) if payload is not None else None)
    return archive


# restore.sh re-runs itself through sudo to take the root-only host lifecycle lock
# (deploy/lib/lifecycle.sh, cb_lifecycle_elevate). This sudo never escalates: the
# re-run executes as this same user, keeping the environment (and the seam) as
# `sudo -E` would, `sudo -v` answers CB_TEST_SUDO_V_RC, and anything else is refused.
_SUDO_STUB = """#!/bin/sh
if [ "$1" = "-v" ]; then
  exit "${CB_TEST_SUDO_V_RC:-0}"
fi
while [ $# -gt 0 ]; do
  case "$1" in
    --) shift; break ;;
    -*) shift ;;
    *) break ;;
  esac
done
case "$*" in
  "env CB_LIFECYCLE_ELEVATED=1 "*) exec "$@" ;;
esac
echo "sudo (test stub) refuses to run: $*" >&2
exit 1
"""


def _harness(tmp_path: Path) -> dict[str, str]:
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    for name in ("systemctl", "dropdb", "createdb", "nginx"):
        (stubs / name).write_text(_LOGGING_STUB.format(extra=""))
    (stubs / "psql").write_text(_LOGGING_STUB.format(extra="cat > /dev/null\n"))
    (stubs / "sudo").write_text(_SUDO_STUB)
    if shutil.which("rsync") is None:
        (stubs / "rsync").write_text(_RSYNC_STUB)
    if shutil.which("jq") is None:
        (stubs / "jq_stub.py").write_text(_JQ_STUB)
        (stubs / "jq").write_text(
            f'#!/bin/sh\nexec "{sys.executable}" "{stubs / "jq_stub.py"}" "$@"\n'
        )
    for stub in stubs.iterdir():
        stub.chmod(0o755)

    env_file = tmp_path / "etc" / "circuitbreaker.env"
    env_file.parent.mkdir(parents=True)
    env_file.write_text(ENV_BEFORE)
    uploads = tmp_path / "data" / "uploads"
    uploads.mkdir(parents=True)
    (uploads / "logo.png").write_bytes(UPLOAD_BEFORE)
    scratch = tmp_path / "tmp"
    scratch.mkdir()

    return {
        "PATH": f"{stubs}{os.pathsep}{os.environ['PATH']}",
        "HOME": str(tmp_path),
        "TMPDIR": str(scratch),
        "CB_ENV_FILE": str(env_file),
        "CB_SERVICE_UNIT": "cb-test.service",
        "CB_DATA_DIR": str(tmp_path / "data"),
        "CB_DB_SUPERUSER": getpass.getuser(),
        "CB_ASSUME_YES": "1",
        "CB_TEST_LOG": str(tmp_path / "calls.log"),
        # restore.sh takes the host lifecycle lock before anything else. Over a
        # disposable root for an unprivileged run; as root the seam is refused
        # (ruling R8) and the run takes the host's own lock, as production does.
        **({} if os.geteuid() == 0 else {"CB_LIFECYCLE_ROOT": str(tmp_path / "lifecycle")}),
    }


def _stub(env: dict[str, str], name: str, body: str) -> None:
    path = Path(env["PATH"].split(os.pathsep)[0]) / name
    path.write_text(body)
    path.chmod(0o755)


def _run(archive: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [shutil.which("bash") or "bash", str(RESTORE_SH), str(archive)],
        stdin=subprocess.DEVNULL,
        check=False,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _calls(env: dict[str, str]) -> list[str]:
    log = Path(env["CB_TEST_LOG"])
    return log.read_text().splitlines() if log.exists() else []


def _assert_refused_and_untouched(
    result: subprocess.CompletedProcess[str], env: dict[str, str], *, cause: str
) -> None:
    """The ACC-15 property: refused, cause named, and nothing on the host changed."""
    combined = result.stdout + result.stderr
    assert result.returncode != 0, (
        "restore.sh accepted an input it must refuse:\n" + combined
    )
    assert cause.lower() in combined.lower(), (
        f"the cause ({cause!r}) was not reported:\n{combined}"
    )
    assert "Nothing has been changed" in combined, combined
    assert "Restore complete" not in result.stdout, combined
    touched = [
        call
        for call in _calls(env)
        if call.startswith(("systemctl stop", "dropdb", "createdb", "psql"))
    ]
    assert not touched, (
        "restore.sh stopped the service or touched the database:\n" + "\n".join(touched)
    )
    assert Path(env["CB_ENV_FILE"]).read_text() == ENV_BEFORE, (
        "the vault key file was modified"
    )
    uploads = Path(env["CB_DATA_DIR"]) / "uploads"
    assert sorted(p.name for p in uploads.rglob("*")) == ["logo.png"], (
        "uploads were modified"
    )
    assert (uploads / "logo.png").read_bytes() == UPLOAD_BEFORE


# ── The control ───────────────────────────────────────────────────────────────────────


def test_acc15_control_a_whole_snapshot_still_restores(tmp_path: Path) -> None:
    key = _vault_key()
    env = _harness(tmp_path)
    result = _run(_snapshot(tmp_path, vault_key=key), env)
    combined = result.stdout + result.stderr

    assert result.returncode == 0, combined
    assert "Restore complete" in result.stdout, combined
    calls = _calls(env)
    assert any(call.startswith("systemctl stop") for call in calls), calls
    assert any(call.startswith("psql") for call in calls), calls
    assert f"CB_VAULT_KEY={key}" in Path(env["CB_ENV_FILE"]).read_text()
    restored = Path(env["CB_DATA_DIR"]) / "uploads"
    assert (restored / "a" / "b.txt").read_bytes() == b"nested"
    # Validation happens before the stop, and the stop before the drop.
    stop = result.stdout.index("==> Stopping")
    assert (
        result.stdout.index("Checksum OK")
        < stop
        < result.stdout.index("==> Restoring database")
    )


# ── Disk full ─────────────────────────────────────────────────────────────────────────


def test_acc15_disk_full_is_refused_before_the_service_is_stopped(
    tmp_path: Path,
) -> None:
    env = _harness(tmp_path)
    _stub(
        env,
        "df",
        "#!/bin/sh\necho 'Filesystem 1024-blocks Used Available Capacity Mounted on'\n"
        "echo '/dev/full 1000000 999999 1 100% /'\n",
    )
    result = _run(_snapshot(tmp_path), env)
    _assert_refused_and_untouched(result, env, cause="not enough free space")


def test_acc15_enospc_while_unpacking_is_refused_before_the_service_is_stopped(
    tmp_path: Path,
) -> None:
    """The measurement can be wrong; the write failing must be caught just as early."""
    env = _harness(tmp_path)
    real_tar = shutil.which("tar")
    _stub(
        env,
        "tar",
        "#!/bin/sh\n"
        'case "$1" in -x*) echo "tar: db.sql.gz: Cannot write: No space left on device" >&2; exit 2 ;; esac\n'
        f'exec "{real_tar}" "$@"\n',
    )
    result = _run(_snapshot(tmp_path), env)
    _assert_refused_and_untouched(result, env, cause="No space left on device")


# ── Permission failure ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("target", ["uploads", "env-file"])
def test_acc15_an_unwritable_target_is_refused_before_the_service_is_stopped(
    target: str, tmp_path: Path
) -> None:
    """A regular file where a directory must be created: unwritable even for root, which
    `chmod` cannot arrange (root ignores modes)."""
    env = _harness(tmp_path)
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, not a directory")
    if target == "uploads":
        # Keep the pre-restore uploads where the untouched-check looks for them.
        env["CB_DATA_DIR"] = str(blocker / "data")
        result = _run(_snapshot(tmp_path), env)
        env["CB_DATA_DIR"] = str(tmp_path / "data")
        cause = "The uploads directory"
    else:
        original = env["CB_ENV_FILE"]
        env["CB_ENV_FILE"] = str(blocker / "circuitbreaker.env")
        result = _run(_snapshot(tmp_path), env)
        env["CB_ENV_FILE"] = original
        cause = "The environment file"
    _assert_refused_and_untouched(result, env, cause=cause)


# ── Corrupt archive ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("damage", ["truncated", "flipped-byte"])
def test_acc15_a_corrupt_archive_is_refused(damage: str, tmp_path: Path) -> None:
    env = _harness(tmp_path)
    archive = _snapshot(tmp_path)
    data = bytearray(archive.read_bytes())
    if damage == "truncated":
        del data[len(data) // 2 :]
    else:
        data[len(data) // 2] ^= 0xFF
    archive.write_bytes(bytes(data))

    _assert_refused_and_untouched(_run(archive, env), env, cause="corrupt or truncated")


@pytest.mark.parametrize(
    ("label", "extra", "cause"),
    [
        (
            "symlink",
            [
                _entry(
                    f"{SNAP_ROOT}/uploads/passwd",
                    None,
                    type=tarfile.SYMTYPE,
                    linkname="/etc/passwd",
                )
            ],
            "links or special files",
        ),
        (
            "dotdot",
            [_entry(f"{SNAP_ROOT}/uploads/../../escape.txt", b"outside")],
            "outside the restore directory",
        ),
        (
            "absolute",
            [_entry("/tmp/cb-acc15-escape.txt", b"outside")],
            "outside the restore directory",
        ),
        ("second-root", [_entry("other/vault.key", b"x")], "exactly one top-level"),
        ("duplicate", [_entry(f"{SNAP_ROOT}/vault.key", b"x\n")], "more than once"),
    ],
)
def test_acc15_a_malicious_archive_is_refused_before_it_is_unpacked(
    label: str,
    extra: list[tuple[tarfile.TarInfo, bytes | None]],
    cause: str,
    tmp_path: Path,
) -> None:
    env = _harness(tmp_path)
    result = _run(_snapshot(tmp_path, extra=extra), env)
    _assert_refused_and_untouched(result, env, cause=cause)
    assert not (tmp_path / "escape.txt").exists()


# ── Checksum mismatch ─────────────────────────────────────────────────────────────────


def test_acc15_a_checksum_mismatch_is_refused(tmp_path: Path) -> None:
    env = _harness(tmp_path)
    archive = _snapshot(tmp_path, manifest={"db_checksum_sha256": "0" * 64})
    _assert_refused_and_untouched(_run(archive, env), env, cause="checksum mismatch")


# ── Missing or wrong vault key ────────────────────────────────────────────────────────


@pytest.mark.parametrize("fault", ["empty", "not-a-key", "another-install's-key"])
def test_acc15_a_missing_or_wrong_vault_key_is_refused(
    fault: str, tmp_path: Path
) -> None:
    env = _harness(tmp_path)
    real_key = _vault_key()
    if fault == "empty":
        archive = _snapshot(tmp_path, vault_key="", dump=_dump(real_key))
        cause = "vault.key inside snapshot is empty"
    elif fault == "not-a-key":
        archive = _snapshot(
            tmp_path, vault_key="correct-horse-battery-staple", dump=_dump(real_key)
        )
        cause = "is not a vault key"
    else:
        archive = _snapshot(tmp_path, vault_key=_vault_key(), dump=_dump(real_key))
        cause = "does not match the database"
    _assert_refused_and_untouched(_run(archive, env), env, cause=cause)


# ── Incompatible schema ───────────────────────────────────────────────────────────────


def test_acc15_a_newer_snapshot_format_is_refused(tmp_path: Path) -> None:
    """restore.sh has no build to compare revisions against (it runs when the build may be
    gone); the snapshot layout version is the schema promise it can check."""
    env = _harness(tmp_path)
    archive = _snapshot(tmp_path, manifest={"format_version": 2})
    _assert_refused_and_untouched(_run(archive, env), env, cause="uses format 2")


def test_the_format_version_restore_sh_reads_is_the_one_the_builder_writes() -> None:
    """Two copies of one number; a builder bump without a restore.sh bump would make every
    new snapshot unrestorable by the disaster-recovery path."""
    builder = re.search(
        r"^SNAPSHOT_FORMAT_VERSION = (\d+)$", SNAPSHOT_PY.read_text(), re.MULTILINE
    )
    script = re.search(
        r"^SUPPORTED_FORMAT_VERSION=(\d+)$", RESTORE_SH.read_text(), re.MULTILINE
    )
    assert builder and script
    assert builder.group(1) == script.group(1)


# ── Partial snapshot ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "fault", ["dump-cut-short", "dump-gzip-cut-short", "missing-uploads"]
)
def test_acc15_a_partial_snapshot_is_refused(fault: str, tmp_path: Path) -> None:
    """Each of these carries a checksum that matches its own (short) contents."""
    env = _harness(tmp_path)
    key = _vault_key()
    if fault == "dump-cut-short":
        archive = _snapshot(tmp_path, vault_key=key, dump=_dump(key, complete=False))
        cause = "is incomplete"
    elif fault == "dump-gzip-cut-short":
        archive = _snapshot(
            tmp_path, vault_key=key, db_gz=gzip.compress(_dump(key))[:-12]
        )
        cause = "not a complete gzip stream"
    else:
        archive = _snapshot(tmp_path, vault_key=key, manifest={"uploads_count": 5})
        cause = "partial snapshot"
    _assert_refused_and_untouched(_run(archive, env), env, cause=cause)


def test_acc15_a_bare_dump_cut_short_is_refused_before_the_service_is_stopped(
    tmp_path: Path,
) -> None:
    """The pre-upgrade rollback artifact: a header and no trailer is a dump a full disk
    or a kill cut short, and psql would replay the part it has and report success."""
    env = _harness(tmp_path)
    dump = tmp_path / "pre-upgrade-20260927-000000.sql"
    dump.write_bytes(_dump(_vault_key(), complete=False))
    _assert_refused_and_untouched(_run(dump, env), env, cause="is incomplete")


# ── cb's container path: unpack before anything is stopped ────────────────────────────


@pytest.mark.parametrize("cli", CB_COPIES, ids=lambda path: str(path.relative_to(ROOT)))
def test_cb_container_restore_unpacks_before_it_stops_the_application(
    cli: Path,
) -> None:
    """The container restore cannot run in a unit test (it drives `docker exec`), so its
    ordering is pinned here: a full volume or an unwritable staging directory must fail
    the unpack while the application is still running, not after it was stopped."""
    source = cli.read_text()
    body = source[source.index("_restore_container() {") :]
    body = body[: body.index("\n}\n")]
    unpack = body.index("tar -xzf")
    stop = body.index('stop "${_CB_APP_PROGRAMS[@]}"')
    drop = body.index("DROP SCHEMA public CASCADE")
    assert unpack < stop < drop
