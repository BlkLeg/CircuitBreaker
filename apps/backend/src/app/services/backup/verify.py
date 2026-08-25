"""Snapshot archive verification.

Everything here runs before a restore touches anything. INC-15 was two backup artifacts and
one restore script that accepted only one of them; the first job of a restore is therefore
to say precisely which artifact it has been handed.

No function in this module writes, extracts to a persistent location, or mutates state.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import tarfile
import zlib
from pathlib import Path
from typing import IO

_REQUIRED_MEMBERS = ("db.sql.gz", "vault.key", "manifest.json")

# The shape `cb backup` produced before this batch. Named specifically so an operator
# holding one is told it never was restorable, rather than that db.sql.gz is missing.
_LEGACY_CB_BACKUP_MEMBERS = ("database.sql", "manifest.txt")

# pg_dump's default output writes table data as a COPY block: a header naming the
# columns in order, then one tab-separated row per line, terminated by a lone `\.`.
_APP_SETTINGS_COPY = re.compile(
    r'^COPY\s+(?:[\w"]+\.)?"?app_settings"?\s*\((?P<columns>[^)]*)\)\s+FROM\s+stdin;',
    re.IGNORECASE,
)


class _VaultKeyHashScanner:
    """Recover ``app_settings.vault_key_hash`` from a plain dump as it streams past.

    The archive pairs one ``vault.key`` with one database, and the database records the
    SHA-256 of the key it was encrypted with.  Reading that hash back out is what turns
    "vault.key is non-empty" — which a snapshot holding the wrong key passes — into
    "vault.key is *this* database's key".

    Fed the same blocks the checksum pass already reads, so nothing is decompressed
    twice.  A dump this cannot parse (``pg_dump --inserts``, a custom-format dump, a
    truncated stream) yields no hash at all and the cross-check is skipped rather than
    guessed at: refusing an archive because the verifier could not read its dump would
    turn an unfamiliar format into a failed recovery.
    """

    def __init__(self) -> None:
        self._inflate = zlib.decompressobj(31)  # 31 = expect a gzip wrapper
        self._pending = b""
        self._columns: list[str] | None = None
        self._done = False
        self.vault_key_hash: str | None = None

    def feed(self, block: bytes) -> None:
        if self._done:
            return
        try:
            text = self._inflate.decompress(block)
        except zlib.error:
            self._done = True
            return
        self._pending += text
        *lines, self._pending = self._pending.split(b"\n")
        for line in lines:
            if self._consume(line.decode("utf-8", "replace")):
                self._done = True
                return

    def _consume(self, line: str) -> bool:
        """Read one dump line; True once there is nothing further worth looking for."""
        if self._columns is None:
            match = _APP_SETTINGS_COPY.match(line)
            if match:
                self._columns = [
                    column.strip().strip('"') for column in match.group("columns").split(",")
                ]
            return False
        if line == "\\.":  # the COPY block ended; the table held no rows
            return True
        try:
            index = self._columns.index("vault_key_hash")
        except ValueError:
            # A schema without the column — nothing to cross-check against.
            return True
        fields = line.split("\t")
        if index < len(fields) and fields[index] != "\\N":
            self.vault_key_hash = fields[index]
        # app_settings is a singleton row; one is all there is to read.
        return True


class SnapshotProblem(Exception):
    """A snapshot cannot be restored. The message is shown to the operator verbatim."""


def _member_named(tf: tarfile.TarFile, name: str) -> tarfile.TarInfo | None:
    for member in tf.getmembers():
        if member.name.rsplit("/", 1)[-1] == name:
            return member
    return None


def _open_member(tf: tarfile.TarFile, name: str) -> IO[bytes]:
    """Open a member the required-member check has already proven present."""
    member = _member_named(tf, name)
    if member is None:  # pragma: no cover - guarded by the required-member check
        raise SnapshotProblem(f"{name} vanished from the archive while it was being read")
    stream = tf.extractfile(member)
    if stream is None:  # pragma: no cover - required members are always regular files
        raise SnapshotProblem(f"{name} is not a regular file inside the archive")
    return stream


def _version_tuple(raw: str) -> tuple[int, ...]:
    """Compare only the numeric release part; `1.0.0-rc.3` sorts as `1.0.0`."""
    head = str(raw).split("-", 1)[0]
    parts: list[int] = []
    for chunk in head.split("."):
        if not chunk.isdigit():
            break
        parts.append(int(chunk))
    return tuple(parts)


def verify_archive(path: Path, installed_version: str | None = None) -> dict:
    """Validate a snapshot tarball and return its manifest.

    Raises SnapshotProblem, with a message naming the specific unmet condition, if the
    archive cannot be restored. Touches nothing.
    """
    if not path.is_file():
        raise SnapshotProblem(f"Snapshot file not found: {path}")

    try:
        tf = tarfile.open(path, "r:gz")
    except (tarfile.TarError, OSError) as exc:
        raise SnapshotProblem(f"{path} is not a readable gzip tarball: {exc}") from exc

    with tf:
        missing = [name for name in _REQUIRED_MEMBERS if _member_named(tf, name) is None]
        if missing:
            if all(_member_named(tf, name) is not None for name in _LEGACY_CB_BACKUP_MEMBERS):
                raise SnapshotProblem(
                    f"{path.name} is an old `cb backup` archive (database.sql + manifest.txt). "
                    "That format was never restorable: it carries no vault key, so encrypted "
                    "columns could not be read back. Take a fresh backup with `cb backup`."
                )
            raise SnapshotProblem(
                f"{path.name} is missing required member(s): {', '.join(missing)}"
            )

        vault_bytes = _open_member(tf, "vault.key").read()
        if not vault_bytes.strip():
            raise SnapshotProblem(
                f"vault.key inside {path.name} is empty — this snapshot cannot restore "
                "credentials, and every encrypted column would be unreadable after restore."
            )

        try:
            manifest: dict = json.loads(_open_member(tf, "manifest.json").read())
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise SnapshotProblem(f"manifest.json in {path.name} is not valid JSON: {exc}") from exc

        expected = manifest.get("db_checksum_sha256")
        if not expected:
            raise SnapshotProblem("manifest.json carries no db_checksum_sha256")

        digest = hashlib.sha256()
        scanner = _VaultKeyHashScanner()
        stream = _open_member(tf, "db.sql.gz")
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
            scanner.feed(block)
        actual = digest.hexdigest()
        recorded_key_hash = scanner.vault_key_hash

    if actual != expected:
        raise SnapshotProblem(
            f"db.sql.gz checksum mismatch in {path.name}: manifest says {expected[:12]}…, "
            f"archive contains {actual[:12]}…. The archive is corrupt or was modified."
        )

    # The pairing check.  A snapshot can carry a syntactically perfect vault.key that
    # belongs to a different install — `cb backup` archived the container's creation-time
    # key while the database was encrypted with the one OOBE generated — and a restore
    # that accepted it wrote that key over the only surviving copy of the real one.
    # There is no --force for this: the two halves of the archive contradict each other,
    # and applying it destroys the key that could still open the database.
    if recorded_key_hash:
        archived_key = vault_bytes.decode("utf-8", errors="replace").strip()
        # compare_digest rather than !=, for the same reason vault_service uses it on
        # this same column: it is the one comparison in the file that decides whether a
        # secret is the right one.
        if not hmac.compare_digest(
            hashlib.sha256(archived_key.encode()).hexdigest(), recorded_key_hash
        ):
            raise SnapshotProblem(
                f"vault.key inside {path.name} does not match the database it was taken "
                f"with: app_settings.vault_key_hash in the dump is {recorded_key_hash[:12]}…, "
                "and the archived key hashes to something else. Restoring this would write "
                "the wrong key over the working one and leave every encrypted column "
                "unreadable. Take a fresh snapshot on the source install."
            )

    if installed_version:
        archive_version = str(manifest.get("cb_version", ""))
        if _version_tuple(archive_version) > _version_tuple(installed_version):
            raise SnapshotProblem(
                f"This snapshot is from Circuit Breaker {archive_version}, which is newer "
                f"than the installed {installed_version}. Restoring a newer schema into an "
                "older build produces a corrupted install and the migration state cannot be "
                "repaired afterwards. Upgrade first, or re-run with --force."
            )

    return manifest
