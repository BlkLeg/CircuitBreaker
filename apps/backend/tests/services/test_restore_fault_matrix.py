"""ACC-15 — the restore fault matrix, against the real verifier and snapshot builder.

ACC-15: "Reject or recover safely from disk full, permission failure, corrupt archive,
checksum mismatch, missing vault key, incompatible schema, and partial snapshot."
Acceptance: automated verification reports the precise cause.

Every `cb restore` — docker, compose and binary mode alike — runs the archive through
``services/backup/verify.py`` (via ``app.cli snapshot verify`` / ``--snapshot-verify``)
before it stops, drops or writes anything, so a refusal here is a restore that never
began. The tests therefore go through ``app.cli.main`` where the operator does, assert
the exit status and the sentence the operator reads, and assert the archive and its
directory are exactly as they were: verification touches nothing.

The backup side of the same faults — disk full and permission failure while a snapshot is
being written — is exercised against ``build_snapshot`` with the failure injected at the
syscall boundary (an ``OSError`` carrying the real errno), because running out of disk
or losing write permission cannot be arranged portably inside a test, and root — which
CI containers run as — ignores directory permissions entirely.

The restore.sh half of the matrix (the native restore, including what it must NOT do to
the database, uploads and vault key when it refuses) lives in
``tests/build/test_restore_fault_matrix.py``.
"""

from __future__ import annotations

import errno
import gzip
import hashlib
import io
import json
import os
import tarfile
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import IO, Any

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from cryptography.fernet import Fernet

from app.cli import main
from app.scripts.cli_admin import alembic_ini_path
from app.services.backup import snapshot as snapshot_module
from app.services.backup.snapshot import SNAPSHOT_FORMAT_VERSION, BackupError, build_snapshot
from app.services.backup.verify import SnapshotProblem, verify_archive

ROOT = "cb-snapshot-20260927-000000"
INSTALLED_VERSION = "1.0.0"


# ── Fixtures: an archive shaped exactly like the one build_snapshot writes ─────────────


def _head_revision() -> str:
    """The migration head this build ships — what a same-version snapshot records."""
    script = ScriptDirectory.from_config(Config(str(alembic_ini_path())))
    return script.get_heads()[0]


def _dump(*, vault_key: str, revision: str, complete: bool = True) -> bytes:
    """A plain pg_dump: header, the two COPY blocks the verifier reads, and the trailer."""
    lines = [
        "--",
        "-- PostgreSQL database dump",
        "--",
        "",
        "COPY public.alembic_version (version_num) FROM stdin;",
        revision,
        "\\.",
        "",
        "COPY public.app_settings (id, vault_key_hash, vault_key_rotated_at) FROM stdin;",
        f"1\t{hashlib.sha256(vault_key.encode()).hexdigest()}\t\\N",
        "\\.",
        "",
    ]
    if complete:
        lines += ["--", "-- PostgreSQL database dump complete", "--", ""]
    return "\n".join(lines).encode()


def _file(name: str, payload: bytes) -> tuple[tarfile.TarInfo, bytes]:
    info = tarfile.TarInfo(name)
    info.size = len(payload)
    info.mode = 0o600
    return info, payload


def _directory(name: str) -> tuple[tarfile.TarInfo, None]:
    info = tarfile.TarInfo(name)
    info.type = tarfile.DIRTYPE
    info.mode = 0o700
    return info, None


def _write_tar(dest: Path, entries: Iterable[tuple[tarfile.TarInfo, bytes | None]]) -> Path:
    with tarfile.open(dest, "w:gz") as tf:
        for info, payload in entries:
            tf.addfile(info, io.BytesIO(payload) if payload is not None else None)
    return dest


def _snapshot(
    tmp_path: Path,
    *,
    vault_key: str | None = None,
    dump: bytes | None = None,
    db_gz: bytes | None = None,
    uploads: int = 2,
    manifest: dict[str, Any] | None = None,
    drop: Iterable[str] = (),
    extra: Iterable[tuple[tarfile.TarInfo, bytes | None]] = (),
) -> Path:
    """A snapshot archive; each keyword breaks exactly one thing about it."""
    key = vault_key if vault_key is not None else Fernet.generate_key().decode()
    if db_gz is None:
        db_gz = gzip.compress(
            dump if dump is not None else _dump(vault_key=key, revision=_head_revision())
        )
    body: dict[str, Any] = {
        "format_version": SNAPSHOT_FORMAT_VERSION,
        "install_mode": "docker",
        "cb_version": INSTALLED_VERSION,
        "created_at": "2026-09-27T00:00:00+00:00",
        "db_name": "circuitbreaker",
        "uploads_count": uploads,
        "db_checksum_sha256": hashlib.sha256(db_gz).hexdigest(),
        "config_files": [],
    }
    body.update(manifest or {})
    members: dict[str, bytes] = {
        "db.sql.gz": db_gz,
        "vault.key": key.encode(),
        "manifest.json": json.dumps(body).encode(),
    }
    # Incompressible, so a flipped byte lands in stored deflate data: only the gzip CRC
    # can tell the difference, which is the check under test in the corruption case.
    for index in range(uploads):
        members[f"uploads/file-{index}.bin"] = os.urandom(64 * 1024)
    dropped = set(drop)
    entries: list[tuple[tarfile.TarInfo, bytes | None]] = [
        _directory(ROOT),
        _directory(f"{ROOT}/uploads"),
    ]
    entries += [
        _file(f"{ROOT}/{name}", payload) for name, payload in members.items() if name not in dropped
    ]
    entries += list(extra)
    dest = tmp_path / "archives" / "cb-snapshot-20260927-000000.tar.gz"
    dest.parent.mkdir(parents=True, exist_ok=True)
    return _write_tar(dest, entries)


def _directory_state(directory: Path) -> dict[str, str]:
    """Name → sha256 of every file under *directory*: 'touches nothing' made checkable."""
    return {
        str(path.relative_to(directory)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def _refused(
    archive: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    *,
    installed_version: str = INSTALLED_VERSION,
) -> str:
    """Run `cb restore`'s verify step on *archive*; assert it refused and touched nothing.

    Returns what the operator read on stderr.
    """
    monkeypatch.setenv("CB_VERSION", installed_version)
    before = _directory_state(archive.parent)
    capsys.readouterr()

    status = main(["snapshot", "verify", str(archive)])

    captured = capsys.readouterr()
    assert status == 1, f"the verifier accepted an archive it must refuse:\n{captured.out}"
    assert "Traceback" not in captured.err, captured.err
    assert captured.err.strip(), "refused without telling the operator why"
    assert _directory_state(archive.parent) == before, "verification modified files"
    return captured.err


# ── The control: none of the refusals below is bought by refusing a good archive ─────


def test_acc15_control_a_whole_snapshot_verifies_through_the_cli(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CB_VERSION", INSTALLED_VERSION)
    archive = _snapshot(tmp_path)

    status = main(["snapshot", "verify", str(archive)])

    captured = capsys.readouterr()
    assert status == 0, captured.err
    assert json.loads(captured.out)["db_name"] == "circuitbreaker"


# ── Disk full ─────────────────────────────────────────────────────────────────────────


class _FillsUp:
    """A writable file that runs out of space after *budget* bytes, as a full disk does."""

    def __init__(self, raw: IO[bytes], budget: int) -> None:
        self._raw = raw
        self._budget = budget

    def write(self, data: bytes) -> int:
        if len(data) > self._budget:
            self._raw.write(data[: self._budget])
            self._budget = 0
            raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))
        self._budget -= len(data)
        return self._raw.write(data)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._raw, name)

    def __enter__(self) -> _FillsUp:
        return self

    def __exit__(self, *exc: object) -> None:
        self._raw.close()


def _fake_pg_dump(monkeypatch: pytest.MonkeyPatch, bin_dir: Path, payload: bytes) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    (bin_dir / "dump.sql").write_bytes(payload)
    script = bin_dir / "pg_dump"
    script.write_text(f'#!/bin/sh\ncat "{bin_dir / "dump.sql"}"\n', encoding="utf-8")
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")


async def _build(tmp_path: Path, key: str) -> Path:
    uploads = tmp_path / "uploads"
    uploads.mkdir(exist_ok=True)
    (uploads / "logo.png").write_bytes(os.urandom(256 * 1024))
    return await build_snapshot(
        backup_dir=tmp_path / "backups",
        db_url="postgresql://cb@localhost:5432/circuitbreaker",
        vault_key=key,
        uploads_dir=uploads,
        cb_version=INSTALLED_VERSION,
    )


@pytest.mark.asyncio
async def test_acc15_disk_full_while_writing_a_snapshot_leaves_no_false_recovery_point(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ENOSPC mid-pack: a clear BackupError, the previous snapshot intact and restorable,
    and nothing under a `cb-snapshot-*.tar.gz` name that retention would count."""
    monkeypatch.setenv("CB_DATA_DIR", str(tmp_path / "data"))
    key = Fernet.generate_key().decode()
    _fake_pg_dump(monkeypatch, tmp_path / "bin", _dump(vault_key=key, revision=_head_revision()))
    good = await _build(tmp_path, key)
    good_bytes = good.read_bytes()

    real_fdopen = os.fdopen

    def _full_disk(fd: int, *args: Any, **kwargs: Any) -> _FillsUp:
        return _FillsUp(real_fdopen(fd, *args, **kwargs), budget=4096)

    monkeypatch.setattr(snapshot_module.os, "fdopen", _full_disk)
    # Usually in the same second as the good build, so the failing run computes the very
    # name the good snapshot already has — which is the case that used to delete it.

    with pytest.raises(BackupError) as excinfo:
        await _build(tmp_path, key)

    assert "No space left on device" in str(excinfo.value)
    backups = sorted(path.name for path in (tmp_path / "backups").iterdir())
    assert backups == [good.name], f"a failed snapshot left files behind: {backups}"
    assert good.read_bytes() == good_bytes
    assert verify_archive(good, installed_version=INSTALLED_VERSION)["uploads_count"] == 1
    staging_root = tmp_path / "data" / "tmp"
    assert not any(staging_root.glob("cb-snapshot-*")), "staging was not cleaned up"


# ── Permission failure ────────────────────────────────────────────────────────────────


def test_acc15_an_unreadable_archive_is_refused_as_a_permission_problem(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Refused with the cause named, not a traceback and not 'not a gzip tarball'.

    Root ignores file modes, so under root the EACCES that open(2) would return is raised
    at the same call instead of arranged with chmod.
    """
    archive = _snapshot(tmp_path)
    if os.geteuid() == 0:
        import app.services.backup.verify as verify_module

        real_open: Callable[..., Any] = verify_module.gzip.open

        def _denied(path: Any, *args: Any, **kwargs: Any) -> Any:
            if Path(path) == archive:
                raise PermissionError(errno.EACCES, os.strerror(errno.EACCES), str(path))
            return real_open(path, *args, **kwargs)

        monkeypatch.setattr(verify_module.gzip, "open", _denied)
        message = _refused(archive, capsys, monkeypatch)
    else:
        archive.chmod(0)
        try:
            message = _refused(archive, capsys, monkeypatch)
        finally:
            archive.chmod(0o600)

    assert "permission denied" in message.lower()
    assert "Nothing has been changed" in message


@pytest.mark.asyncio
async def test_acc15_an_unwritable_backup_directory_fails_the_snapshot_cleanly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """EACCES creating the archive: a BackupError naming it, and no file left behind."""
    monkeypatch.setenv("CB_DATA_DIR", str(tmp_path / "data"))
    key = Fernet.generate_key().decode()
    _fake_pg_dump(monkeypatch, tmp_path / "bin", _dump(vault_key=key, revision=_head_revision()))
    real_open = os.open

    def _denied(path: Any, flags: int, mode: int = 0o777, **kwargs: Any) -> int:
        if str(path).startswith(str(tmp_path / "backups")):
            raise PermissionError(errno.EACCES, os.strerror(errno.EACCES), str(path))
        return real_open(path, flags, mode, **kwargs)

    monkeypatch.setattr(snapshot_module.os, "open", _denied)

    with pytest.raises(BackupError) as excinfo:
        await _build(tmp_path, key)

    assert "Permission denied" in str(excinfo.value)
    assert list((tmp_path / "backups").iterdir()) == []


# ── Corrupt archive ───────────────────────────────────────────────────────────────────


def test_acc15_a_truncated_archive_is_refused_not_a_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The regression: a half-copied archive escaped the verifier as a raw EOFError."""
    archive = _snapshot(tmp_path)
    data = archive.read_bytes()
    archive.write_bytes(data[: len(data) // 2])

    message = _refused(archive, capsys, monkeypatch)

    assert "truncated" in message.lower()


@pytest.mark.parametrize(
    "damage",
    ["flip-a-byte-in-uploads", "drop-the-gzip-trailer"],
)
def test_acc15_a_corrupt_archive_is_refused_before_anything_is_unpacked(
    damage: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The regression: both of these verified clean, because only the three required
    members were read and the gzip CRC at the end of the stream never was."""
    archive = _snapshot(tmp_path)
    data = bytearray(archive.read_bytes())
    if damage == "flip-a-byte-in-uploads":
        middle = len(data) // 2
        data[middle] ^= 0xFF
    else:
        del data[-4:]
    archive.write_bytes(bytes(data))

    message = _refused(archive, capsys, monkeypatch)

    assert "corrupt" in message.lower() or "truncated" in message.lower()


def _symlink(name: str, target: str) -> tuple[tarfile.TarInfo, None]:
    info = tarfile.TarInfo(name)
    info.type = tarfile.SYMTYPE
    info.linkname = target
    return info, None


def _hardlink(name: str, target: str) -> tuple[tarfile.TarInfo, None]:
    info = tarfile.TarInfo(name)
    info.type = tarfile.LNKTYPE
    info.linkname = target
    return info, None


@pytest.mark.parametrize(
    ("label", "extra", "expected"),
    [
        ("symlink-out", [_symlink(f"{ROOT}/uploads/passwd", "/etc/passwd")], "symbolic link"),
        ("hardlink", [_hardlink(f"{ROOT}/uploads/shadow", "/etc/shadow")], "hard link"),
        (
            "dotdot",
            [_file(f"{ROOT}/uploads/../../../etc/cron.d/x", b"* * * * * root id\n")],
            "unsafe path",
        ),
        ("absolute", [_file("/etc/cron.d/x", b"* * * * * root id\n")], "unsafe path"),
        ("second-root", [_file("other/vault.key", b"x")], "more than one top-level"),
        ("duplicate", [_file(f"{ROOT}/vault.key", Fernet.generate_key())], "more than once"),
    ],
)
def test_acc15_a_malicious_archive_is_refused_before_it_can_be_unpacked(
    label: str,
    extra: list[tuple[tarfile.TarInfo, bytes | None]],
    expected: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Links, absolute paths, `..`, a second root and a repeated name: every one is a way
    for `tar -x` to write outside the restore tree or to restore bytes nobody verified."""
    archive = _snapshot(tmp_path, extra=extra)

    message = _refused(archive, capsys, monkeypatch)

    assert expected in message, f"{label}: {message}"
    assert "Nothing has been changed" in message


# ── Checksum mismatch ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("tamper", ["manifest-checksum", "swapped-dump"])
def test_acc15_a_checksum_mismatch_is_refused(
    tamper: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = Fernet.generate_key().decode()
    if tamper == "manifest-checksum":
        archive = _snapshot(tmp_path, vault_key=key, manifest={"db_checksum_sha256": "0" * 64})
    else:
        # A whole, valid dump — just not the one the manifest's checksum was taken over.
        other = gzip.compress(_dump(vault_key=key, revision=_head_revision()) + b"-- edited\n")
        archive = _snapshot(
            tmp_path,
            vault_key=key,
            db_gz=other,
            manifest={"db_checksum_sha256": hashlib.sha256(b"original").hexdigest()},
        )

    message = _refused(archive, capsys, monkeypatch)

    assert "checksum mismatch" in message


# ── Missing or wrong vault key ────────────────────────────────────────────────────────


@pytest.mark.parametrize("fault", ["missing", "empty", "not-a-key", "another-install's-key"])
def test_acc15_a_missing_or_wrong_vault_key_is_refused(
    fault: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Restoring any of these writes a key that opens nothing over the one that does."""
    real_key = Fernet.generate_key().decode()
    dump = _dump(vault_key=real_key, revision=_head_revision())
    if fault == "missing":
        archive = _snapshot(tmp_path, vault_key=real_key, drop={"vault.key"})
        expected = "missing required member(s): vault.key"
    elif fault == "empty":
        archive = _snapshot(tmp_path, vault_key="", dump=dump)
        expected = "is empty"
    elif fault == "not-a-key":
        archive = _snapshot(tmp_path, vault_key="correct-horse-battery-staple", dump=dump)
        expected = "is not a vault key"
    else:
        archive = _snapshot(tmp_path, vault_key=Fernet.generate_key().decode(), dump=dump)
        expected = "does not match the database"

    message = _refused(archive, capsys, monkeypatch)

    assert expected in message


# ── Incompatible schema ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize("fault", ["unknown-revision", "newer-format", "newer-release"])
def test_acc15_an_incompatible_schema_is_refused(
    fault: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A schema this build cannot migrate or run. The revision check is the one that
    cannot be fooled by the label on the archive, and --force does not waive it."""
    key = Fernet.generate_key().decode()
    if fault == "unknown-revision":
        archive = _snapshot(
            tmp_path, vault_key=key, dump=_dump(vault_key=key, revision="ffffffffffff")
        )
        expected = "schema revision ffffffffffff"
        # `cb restore --force` clears CB_VERSION; the revision check must survive that.
        message = _refused(archive, capsys, monkeypatch, installed_version="")
    elif fault == "newer-format":
        archive = _snapshot(
            tmp_path, vault_key=key, manifest={"format_version": SNAPSHOT_FORMAT_VERSION + 1}
        )
        expected = f"uses snapshot format {SNAPSHOT_FORMAT_VERSION + 1}"
        message = _refused(archive, capsys, monkeypatch)
    else:
        archive = _snapshot(tmp_path, vault_key=key, manifest={"cb_version": "9.0.0"})
        expected = "newer than the installed"
        message = _refused(archive, capsys, monkeypatch)

    assert expected in message


def test_acc15_every_revision_this_build_ships_is_accepted(tmp_path: Path) -> None:
    """The other side of the revision check: an older snapshot is an upgrade, not a refusal."""
    script = ScriptDirectory.from_config(Config(str(alembic_ini_path())))
    revisions = [revision.revision for revision in script.walk_revisions()]
    oldest = revisions[-1]
    key = Fernet.generate_key().decode()
    archive = _snapshot(tmp_path, vault_key=key, dump=_dump(vault_key=key, revision=oldest))

    manifest = verify_archive(
        archive, installed_version=INSTALLED_VERSION, known_revisions=revisions
    )

    assert manifest["db_name"] == "circuitbreaker"


# ── Partial snapshot ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "fault",
    ["dump-cut-short", "dump-gzip-cut-short", "empty-dump", "missing-uploads", "missing-config"],
)
def test_acc15_a_partial_snapshot_is_refused(
    fault: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every one of these carries a checksum that matches what is in the archive, so the
    checksum alone passed them all; each restores less than was backed up."""
    key = Fernet.generate_key().decode()
    whole = _dump(vault_key=key, revision=_head_revision())
    if fault == "dump-cut-short":
        archive = _snapshot(
            tmp_path,
            vault_key=key,
            dump=_dump(vault_key=key, revision=_head_revision(), complete=False),
        )
        expected = "never reaches '-- PostgreSQL database dump complete'"
    elif fault == "dump-gzip-cut-short":
        archive = _snapshot(tmp_path, vault_key=key, db_gz=gzip.compress(whole)[:-12])
        expected = "not a complete gzip stream"
    elif fault == "empty-dump":
        archive = _snapshot(tmp_path, vault_key=key, db_gz=gzip.compress(b""))
        expected = "no database in this snapshot"
    elif fault == "missing-uploads":
        archive = _snapshot(tmp_path, vault_key=key, dump=whole, manifest={"uploads_count": 3})
        expected = "records 3 uploaded file(s) and the archive contains 2"
    else:
        archive = _snapshot(
            tmp_path, vault_key=key, dump=whole, manifest={"config_files": ["config/.env"]}
        )
        expected = "config/.env"

    message = _refused(archive, capsys, monkeypatch)

    assert expected in message
    assert (
        "partial" in message.lower() or "incomplete" in message.lower() or "no database" in message
    )


@pytest.mark.asyncio
async def test_acc15_a_killed_snapshot_is_never_a_recovery_point(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A snapshot killed mid-pack (SIGKILL runs no cleanup) leaves only a `.part` file,
    which retention does not count and the next run sweeps once it is stale."""
    from app.services.backup.pruner import prune_local

    monkeypatch.setenv("CB_DATA_DIR", str(tmp_path / "data"))
    backups = tmp_path / "backups"
    backups.mkdir()
    orphan = backups / "cb-snapshot-20260101-000000.tar.gz.part"
    orphan.write_bytes(b"half an archive")
    stale = snapshot_module.datetime.now().timestamp() - 7 * 3600
    os.utime(orphan, (stale, stale))

    assert prune_local(backups, keep=1) == [], "retention treated a partial file as a snapshot"

    key = Fernet.generate_key().decode()
    _fake_pg_dump(monkeypatch, tmp_path / "bin", _dump(vault_key=key, revision=_head_revision()))
    built = await _build(tmp_path, key)

    assert not orphan.exists(), "the stale partial from the killed run was not swept"
    assert [path.name for path in backups.iterdir()] == [built.name]
    assert built.stat().st_mode & 0o777 == 0o600


def test_acc15_verification_is_read_only_even_when_it_refuses(tmp_path: Path) -> None:
    """Direct call, no CLI: a refusal raises SnapshotProblem and writes nothing anywhere
    next to the archive (the CLI-level tests assert the same through `_refused`)."""
    archive = _snapshot(tmp_path, manifest={"db_checksum_sha256": "0" * 64})
    before = _directory_state(tmp_path)

    with pytest.raises(SnapshotProblem):
        verify_archive(archive, installed_version=INSTALLED_VERSION)

    assert _directory_state(tmp_path) == before
