"""Snapshot archive verification.

Everything here runs before a restore touches anything. the contract was two backup artifacts and
one restore script that accepted only one of them; the first job of a restore is therefore
to say precisely which artifact it has been handed.

No function in this module writes, extracts to a persistent location, or mutates state.

ACC-15 asks that a restore reject, before anything is destroyed, every input it cannot
apply whole: a corrupt or truncated archive, a checksum mismatch, a missing or wrong vault
key, an incompatible schema and a partial snapshot. Each of those is decided here, from one
streaming pass over the archive:

* The whole gzip stream is read to its end, so its CRC32 and length trailer are checked.
  Reading only the three required members — what this module used to do — accepted an
  archive whose uploads were corrupt or whose tail had been cut off, and the restore then
  discovered it partway through unpacking, after the service had been stopped.
* Every member is admitted by path and type before anything else is read. The restore
  paths unpack with ``tar -x``; an absolute path, a ``..`` component, a symlink or a hard
  link is how an archive writes outside the directory it is unpacked into, and a snapshot
  this product built never contains any of them. A name that appears twice is refused too:
  ``tar -x`` keeps the last copy, and a verifier that read the first would be vouching for
  bytes the restore never applies.
"""

from __future__ import annotations

import gzip
import hashlib
import hmac
import json
import re
import tarfile
import zlib
from collections.abc import Collection
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any

from cryptography.fernet import Fernet

from app.services.backup.snapshot import SNAPSHOT_FORMAT_VERSION

_REQUIRED_MEMBERS = ("db.sql.gz", "vault.key", "manifest.json")

# The shape `cb backup` produced before this batch. Named specifically so an operator
# holding one is told it never was restorable, rather than that db.sql.gz is missing.
_LEGACY_CB_BACKUP_MEMBERS = ("database.sql", "manifest.txt")

# Block size for every streaming read here. Matches snapshot.py's convention.
_STREAM_BLOCK = 1024 * 1024

# Upper bound on what one zlib call may inflate. Without it a small, highly compressible
# db.sql.gz inflates to gigabytes in a single call, and the verifier that exists to stop a
# bad archive from hurting the host becomes the thing that exhausts its memory.
_INFLATE_CHUNK = 4 * 1024 * 1024

# A Fernet key is 44 characters. Anything this large is not a vault key, and reading an
# unbounded member into memory to find that out is the same exhaustion as above.
_MAX_VAULT_KEY_BYTES = 4096
_MAX_MANIFEST_BYTES = 1024 * 1024

# pg_dump's plain format opens with the first line and closes with the second. A dump
# that has the header but never reaches the trailer was cut short while it was written.
_DUMP_HEADER = b"-- PostgreSQL database dump"
_DUMP_TRAILER = b"-- PostgreSQL database dump complete"
_DUMP_HEAD_WINDOW = 1024
# pg_dump 16.10+/17.6+ writes `\unrestrict <key>` after the trailer, so the trailer is
# looked for near the end rather than required to be the last line.
_DUMP_TAIL_WINDOW = 4096

# pg_dump's default output writes table data as a COPY block: a header naming the
# columns in order, then one tab-separated row per line, terminated by a lone `\.`.
_COPY_HEADER = re.compile(
    r'^COPY\s+(?:"?\w+"?\.)?"?(?P<table>\w+)"?\s*\((?P<columns>[^)]*)\)\s+FROM\s+stdin;',
    re.IGNORECASE,
)
_COPY_END = "\\."
_SQL_NULL = "\\N"

# The two tables the dump is read for, and the column wanted from each.
_WANTED_COLUMNS = {"app_settings": "vault_key_hash", "alembic_version": "version_num"}


class SnapshotProblem(Exception):
    """A snapshot cannot be restored. The message is shown to the operator verbatim."""


class _DumpScanner:
    """Inspect ``db.sql.gz`` as it streams past, without decompressing it twice.

    Four things are read out of the one pass the checksum already makes:

    * whether the gzip stream is whole (a zlib error, or no end-of-stream marker);
    * whether the SQL is whole (pg_dump's header without its closing trailer);
    * ``app_settings.vault_key_hash`` — the SHA-256 of the key the database was
      encrypted with, which turns "vault.key is non-empty" into "vault.key is *this*
      database's key";
    * ``alembic_version.version_num`` — the schema revision the dump is at.

    A dump whose rows this cannot parse (``pg_dump --inserts``) yields no hash and no
    revision, and those cross-checks are skipped rather than guessed at: refusing an
    archive because the verifier could not read its dump would turn an unfamiliar format
    into a failed recovery. The integrity checks are not skipped — they do not depend on
    the dump's format.
    """

    def __init__(self) -> None:
        self._inflate = zlib.decompressobj(31)  # 31 = expect a gzip wrapper
        self._pending = b""
        self._parsing = True
        self._copy_table: str | None = None
        self._copy_index: int | None = None
        self._seen_tables: set[str] = set()
        self._head = b""
        self._tail = b""
        self.inflated_bytes = 0
        self.stream_error: str | None = None
        self.vault_key_hash: str | None = None
        self.schema_revisions: list[str] = []

    def feed(self, block: bytes) -> None:
        """Consume the next compressed block."""
        if self.stream_error is not None:
            return
        data = block
        while data:
            if self._inflate.eof:
                if not data.strip(b"\x00"):
                    return  # zero padding after the final member, which gzip tolerates
                self._inflate = zlib.decompressobj(31)  # a further gzip member
            try:
                out = self._inflate.decompress(data, _INFLATE_CHUNK)
            except zlib.error as exc:
                self.stream_error = str(exc)
                return
            self._absorb(out)
            data = self._inflate.unused_data if self._inflate.eof else self._inflate.unconsumed_tail

    def finish(self) -> None:
        """Record whether the stream ended where a whole gzip stream ends."""
        if self.stream_error is None and not self._inflate.eof:
            self.stream_error = "the compressed stream ends before its end-of-stream marker"

    @property
    def is_truncated_dump(self) -> bool:
        """True when pg_dump's header is present and its closing trailer is not."""
        return _DUMP_HEADER in self._head and _DUMP_TRAILER not in self._tail

    def _absorb(self, out: bytes) -> None:
        if not out:
            return
        self.inflated_bytes += len(out)
        if len(self._head) < _DUMP_HEAD_WINDOW:
            self._head += out[: _DUMP_HEAD_WINDOW - len(self._head)]
        self._tail = (self._tail + out)[-_DUMP_TAIL_WINDOW:]
        if not self._parsing:
            return
        self._pending += out
        *lines, self._pending = self._pending.split(b"\n")
        for line in lines:
            self._consume(line.decode("utf-8", "replace"))
            if self._seen_tables >= set(_WANTED_COLUMNS):
                self._parsing = False
                self._pending = b""
                return

    def _consume(self, line: str) -> None:
        if self._copy_table is None:
            match = _COPY_HEADER.match(line)
            if match is None:
                return
            table = match.group("table").lower()
            self._copy_table = table
            self._copy_index = None
            wanted = _WANTED_COLUMNS.get(table)
            if wanted is not None and table not in self._seen_tables:
                columns = [
                    column.strip().strip('"') for column in match.group("columns").split(",")
                ]
                if wanted in columns:
                    self._copy_index = columns.index(wanted)
            return
        if line == _COPY_END:
            if self._copy_table in _WANTED_COLUMNS:
                self._seen_tables.add(self._copy_table)
            self._copy_table = None
            return
        if self._copy_index is None:
            return  # a table this scanner is not reading, or one without the column
        fields = line.split("\t")
        value = fields[self._copy_index] if self._copy_index < len(fields) else _SQL_NULL
        if value == _SQL_NULL:
            return
        if self._copy_table == "app_settings" and self.vault_key_hash is None:
            # app_settings is a singleton row; the first is all there is to read.
            self.vault_key_hash = value
        elif self._copy_table == "alembic_version":
            self.schema_revisions.append(value)


@dataclass
class _ArchiveContents:
    """What one streaming pass over the archive found."""

    root: str | None = None
    member_names: set[str] = field(default_factory=set)
    relative_names: set[str] = field(default_factory=set)
    vault_bytes: bytes | None = None
    manifest_bytes: bytes | None = None
    db_checksum: str | None = None
    dump: _DumpScanner = field(default_factory=_DumpScanner)
    upload_files: int = 0
    config_files: set[str] = field(default_factory=set)


def _member_kind(member: tarfile.TarInfo) -> str:
    if member.issym():
        return "a symbolic link"
    if member.islnk():
        return "a hard link"
    if member.ischr() or member.isblk():
        return "a device node"
    if member.isfifo():
        return "a FIFO"
    return "a special file"


def _admit_member(archive: Path, member: tarfile.TarInfo, contents: _ArchiveContents) -> str:
    """Refuse a member no snapshot this product built could contain; return its path
    relative to the snapshot's top-level directory ("" for that directory itself)."""
    raw = member.name
    parts = [part for part in raw.split("/") if part not in ("", ".")]
    if raw.startswith("/") or ".." in parts or not parts:
        raise SnapshotProblem(
            f"{archive.name} contains an unsafe path ({raw!r}): an absolute path or a '..' "
            "component would be written outside the directory the restore unpacks into. "
            "Snapshots never contain one — this archive was not produced by `cb backup`. "
            "Nothing has been changed."
        )
    if not (member.isfile() or member.isdir()):
        raise SnapshotProblem(
            f"{archive.name} contains {_member_kind(member)} ({raw!r}). Snapshots hold only "
            "regular files and directories, and a link is how an archive makes a restore "
            "read or write outside its own tree. Nothing has been changed."
        )
    top = parts[0]
    if contents.root is None:
        contents.root = top
    elif top != contents.root:
        raise SnapshotProblem(
            f"{archive.name} has more than one top-level entry ({contents.root!r} and "
            f"{top!r}). A snapshot is one directory; the restore paths unpack exactly one. "
            "Nothing has been changed."
        )
    if len(parts) == 1 and not member.isdir():
        raise SnapshotProblem(
            f"{archive.name} has a file ({raw!r}) outside a snapshot directory. "
            "Nothing has been changed."
        )
    key = "/".join(parts)
    if key in contents.member_names:
        raise SnapshotProblem(
            f"{archive.name} contains {key!r} more than once. Unpacking keeps the last copy, "
            "so what was verified would not be what is restored. Nothing has been changed."
        )
    contents.member_names.add(key)
    return "/".join(parts[1:])


def _read_bounded(archive: Path, stream: IO[bytes], name: str, limit: int) -> bytes:
    payload = stream.read(limit + 1)
    if len(payload) > limit:
        raise SnapshotProblem(
            f"{name} inside {archive.name} is larger than {limit} bytes — it is not what a "
            "snapshot writes there. Nothing has been changed."
        )
    return payload


def _read_member(
    archive: Path,
    tf: tarfile.TarFile,
    member: tarfile.TarInfo,
    relative: str,
    contents: _ArchiveContents,
) -> None:
    stream = tf.extractfile(member)
    if stream is None:  # pragma: no cover - _admit_member lets only regular files reach here
        raise SnapshotProblem(f"{member.name} is not a regular file inside the archive")
    if relative == "db.sql.gz":
        digest = hashlib.sha256()
        for block in iter(lambda: stream.read(_STREAM_BLOCK), b""):
            digest.update(block)
            contents.dump.feed(block)
        contents.dump.finish()
        contents.db_checksum = digest.hexdigest()
    elif relative == "vault.key":
        contents.vault_bytes = _read_bounded(archive, stream, relative, _MAX_VAULT_KEY_BYTES)
    elif relative == "manifest.json":
        contents.manifest_bytes = _read_bounded(archive, stream, relative, _MAX_MANIFEST_BYTES)
    elif relative.startswith("uploads/"):
        contents.upload_files += 1
    elif relative.startswith("config/"):
        contents.config_files.add(relative)
    # Members not read here are still decompressed: a streaming tar skips forward by
    # reading, so every byte of the archive passes through the gzip CRC below.


def _read_archive(archive: Path) -> _ArchiveContents:
    """One streaming pass over the whole archive, integrity checked to the last byte."""
    contents = _ArchiveContents()
    try:
        # gzip.open, not tarfile's own "r:gz": GzipFile checks the CRC32 and length
        # trailer when it reaches the end of the stream, and the drain below makes sure
        # it gets there. tarfile stops reading at the end-of-archive marker and never
        # looks at the trailer, which is how a corrupt archive used to verify clean.
        with gzip.open(archive, "rb") as compressed:
            with tarfile.open(fileobj=compressed, mode="r|") as tf:
                for member in tf:
                    relative = _admit_member(archive, member, contents)
                    contents.relative_names.add(relative)
                    if member.isfile():
                        _read_member(archive, tf, member, relative, contents)
            while compressed.read(_STREAM_BLOCK):
                pass
    except PermissionError as exc:
        raise SnapshotProblem(
            f"{archive} cannot be read: permission denied ({exc.strerror}). Run the restore "
            "as a user that can read the snapshot, or fix its permissions. "
            "Nothing has been changed."
        ) from exc
    except EOFError as exc:
        raise SnapshotProblem(
            f"{archive.name} is truncated: the archive ends before its end-of-stream marker "
            "(an interrupted copy or backup, or a full disk while it was written). It cannot "
            "be restored. Nothing has been changed."
        ) from exc
    except (gzip.BadGzipFile, zlib.error, tarfile.TarError) as exc:
        raise SnapshotProblem(
            f"{archive.name} is corrupt or truncated and cannot be restored: {exc}. "
            "Nothing has been changed."
        ) from exc
    except OSError as exc:
        raise SnapshotProblem(
            f"{archive} could not be read: {exc}. Nothing has been changed."
        ) from exc
    return contents


def _require_members(archive: Path, contents: _ArchiveContents) -> None:
    missing = [name for name in _REQUIRED_MEMBERS if name not in contents.relative_names]
    if not missing:
        return
    if all(name in contents.relative_names for name in _LEGACY_CB_BACKUP_MEMBERS):
        raise SnapshotProblem(
            f"{archive.name} is an old `cb backup` archive (database.sql + manifest.txt). "
            "That format was never restorable: it carries no vault key, so encrypted "
            "columns could not be read back. Take a fresh backup with `cb backup`."
        )
    raise SnapshotProblem(f"{archive.name} is missing required member(s): {', '.join(missing)}")


def _checked_vault_key(archive: Path, vault_bytes: bytes) -> str:
    key = vault_bytes.decode("utf-8", errors="replace").strip()
    if not key:
        raise SnapshotProblem(
            f"vault.key inside {archive.name} is empty — this snapshot cannot restore "
            "credentials, and every encrypted column would be unreadable after restore."
        )
    try:
        Fernet(key.encode())
    except (ValueError, TypeError) as exc:
        raise SnapshotProblem(
            f"vault.key inside {archive.name} is not a vault key (a vault key is 32 url-safe "
            "base64-encoded bytes). Restoring it would replace the working key with one that "
            "decrypts nothing. Nothing has been changed."
        ) from exc
    return key


def _parsed_manifest(archive: Path, manifest_bytes: bytes) -> dict[str, Any]:
    try:
        manifest = json.loads(manifest_bytes)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise SnapshotProblem(f"manifest.json in {archive.name} is not valid JSON: {exc}") from exc
    if not isinstance(manifest, dict):
        raise SnapshotProblem(
            f"manifest.json in {archive.name} is not a JSON object — it is not a snapshot manifest."
        )
    return manifest


def _check_format_version(archive: Path, manifest: dict[str, Any]) -> None:
    """Archives predating the field read as version 0; a newer layout is refused."""
    declared = manifest.get("format_version", 0)
    if isinstance(declared, bool) or not isinstance(declared, int) or declared < 0:
        raise SnapshotProblem(
            f"manifest.json in {archive.name} declares format_version {declared!r}, which is "
            "not a snapshot format. Nothing has been changed."
        )
    if declared > SNAPSHOT_FORMAT_VERSION:
        raise SnapshotProblem(
            f"{archive.name} uses snapshot format {declared}; this build reads format "
            f"{SNAPSHOT_FORMAT_VERSION} and older. It was taken by a newer Circuit Breaker — "
            "upgrade this install first, then restore. Nothing has been changed."
        )


def _check_dump(archive: Path, manifest: dict[str, Any], contents: _ArchiveContents) -> None:
    expected = manifest.get("db_checksum_sha256")
    if not expected:
        raise SnapshotProblem("manifest.json carries no db_checksum_sha256")
    expected = str(expected)
    actual = contents.db_checksum or ""
    if not hmac.compare_digest(actual, expected):
        raise SnapshotProblem(
            f"db.sql.gz checksum mismatch in {archive.name}: manifest says {expected[:12]}…, "
            f"archive contains {actual[:12]}…. The archive is corrupt or was modified."
        )
    dump = contents.dump
    if dump.stream_error is not None:
        raise SnapshotProblem(
            f"db.sql.gz inside {archive.name} is not a complete gzip stream "
            f"({dump.stream_error}). This is a partial snapshot: the dump was cut short "
            "before its checksum was recorded. Nothing has been changed."
        )
    if dump.inflated_bytes == 0:
        raise SnapshotProblem(
            f"db.sql.gz inside {archive.name} is empty — there is no database in this "
            "snapshot to restore. Nothing has been changed."
        )
    if dump.is_truncated_dump:
        raise SnapshotProblem(
            f"The database dump inside {archive.name} is incomplete: it opens with pg_dump's "
            "header but never reaches '-- PostgreSQL database dump complete'. pg_dump was "
            "interrupted while this snapshot was taken, and replaying it would load a partial "
            "database. Nothing has been changed."
        )


def _check_vault_pairing(archive: Path, vault_key: str, recorded_key_hash: str | None) -> None:
    """The pairing check.

    A snapshot can carry a syntactically perfect vault.key that belongs to a different
    install — `cb backup` archived the container's creation-time key while the database
    was encrypted with the one OOBE generated — and a restore that accepted it wrote that
    key over the only surviving copy of the real one. There is no --force for this: the
    two halves of the archive contradict each other, and applying it destroys the key
    that could still open the database.
    """
    if not recorded_key_hash:
        return
    # compare_digest rather than !=, for the same reason vault_service uses it on this
    # same column: it is the one comparison in the file that decides whether a secret is
    # the right one.
    if not hmac.compare_digest(hashlib.sha256(vault_key.encode()).hexdigest(), recorded_key_hash):
        raise SnapshotProblem(
            f"vault.key inside {archive.name} does not match the database it was taken "
            f"with: app_settings.vault_key_hash in the dump is {recorded_key_hash[:12]}…, "
            "and the archived key hashes to something else. Restoring this would write "
            "the wrong key over the working one and leave every encrypted column "
            "unreadable. Take a fresh snapshot on the source install."
        )


def _check_file_counts(archive: Path, manifest: dict[str, Any], contents: _ArchiveContents) -> None:
    """A partial files snapshot: fewer uploads or config files than the manifest records.

    Both fields are optional so archives predating them still verify; when present they
    were written by the builder from the tree it had just packed.
    """
    expected_uploads = manifest.get("uploads_count")
    if (
        isinstance(expected_uploads, int)
        and not isinstance(expected_uploads, bool)
        and expected_uploads != contents.upload_files
    ):
        raise SnapshotProblem(
            f"{archive.name} is a partial snapshot: its manifest records {expected_uploads} "
            f"uploaded file(s) and the archive contains {contents.upload_files}. Restoring it "
            "would replace this install's uploads with an incomplete set. "
            "Nothing has been changed."
        )
    listed = manifest.get("config_files")
    if isinstance(listed, list):
        missing = [
            name for name in listed if isinstance(name, str) and name not in contents.config_files
        ]
        if missing:
            raise SnapshotProblem(
                f"{archive.name} is a partial snapshot: its manifest lists config file(s) "
                f"{', '.join(missing)} that the archive does not contain. "
                "Nothing has been changed."
            )


def _version_tuple(raw: str) -> tuple[int, ...]:
    """Compare only the numeric release part; `1.0.0-rc.3` sorts as `1.0.0`."""
    head = str(raw).split("-", 1)[0]
    parts: list[int] = []
    for chunk in head.split("."):
        if not chunk.isdigit():
            break
        parts.append(int(chunk))
    return tuple(parts)


def _check_schema(
    archive: Path,
    manifest: dict[str, Any],
    schema_revisions: list[str],
    installed_version: str | None,
    known_revisions: Collection[str] | None,
) -> None:
    if installed_version:
        archive_version = str(manifest.get("cb_version", ""))
        if _version_tuple(archive_version) > _version_tuple(installed_version):
            raise SnapshotProblem(
                f"This snapshot is from Circuit Breaker {archive_version}, which is newer "
                f"than the installed {installed_version}. Restoring a newer schema into an "
                "older build produces a corrupted install and the migration state cannot be "
                "repaired afterwards. Upgrade first, or re-run with --force."
            )
    # The schema itself, not the label on the archive. A version string can be "unknown"
    # (a dev build) or waived with --force; the revision in alembic_version cannot lie
    # about which migrations the data went through. A revision this build does not ship
    # is one its migrations cannot start from, so the restored install would not boot —
    # and --force does not waive it, because there is nothing to force past.
    if known_revisions is None or not schema_revisions:
        return
    unknown = [revision for revision in schema_revisions if revision not in known_revisions]
    if unknown:
        raise SnapshotProblem(
            f"The database in {archive.name} is at schema revision {', '.join(unknown)}, "
            "which this build of Circuit Breaker does not have. It was taken by a newer or "
            "divergent build, and this build can neither migrate nor run that schema. "
            "Restore it with the build that took it, or upgrade this install first. "
            "Nothing has been changed."
        )


def verify_archive(
    path: Path,
    installed_version: str | None = None,
    known_revisions: Collection[str] | None = None,
) -> dict[str, Any]:
    """Validate a snapshot tarball and return its manifest.

    Args:
        path: The snapshot ``.tar.gz``.
        installed_version: This build's version; a newer archive is refused. Empty or
            None skips that comparison (it is what ``cb restore --force`` sends).
        known_revisions: Every Alembic revision this build ships. When given, a dump
            whose ``alembic_version`` names a revision outside it is refused. None skips
            the check.

    Raises:
        SnapshotProblem: with a message naming the specific unmet condition, if the
            archive cannot be restored. Touches nothing.
    """
    if not path.is_file():
        raise SnapshotProblem(f"Snapshot file not found: {path}")

    contents = _read_archive(path)
    _require_members(path, contents)
    vault_key = _checked_vault_key(path, contents.vault_bytes or b"")
    manifest = _parsed_manifest(path, contents.manifest_bytes or b"")
    _check_format_version(path, manifest)
    _check_dump(path, manifest, contents)
    _check_vault_pairing(path, vault_key, contents.dump.vault_key_hash)
    _check_file_counts(path, manifest, contents)
    _check_schema(
        path, manifest, contents.dump.schema_revisions, installed_version, known_revisions
    )
    return manifest
