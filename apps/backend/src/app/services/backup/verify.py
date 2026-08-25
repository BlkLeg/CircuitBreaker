"""Snapshot archive verification.

Everything here runs before a restore touches anything. INC-15 was two backup artifacts and
one restore script that accepted only one of them; the first job of a restore is therefore
to say precisely which artifact it has been handed.

No function in this module writes, extracts to a persistent location, or mutates state.
"""

from __future__ import annotations

import hashlib
import json
import tarfile
from pathlib import Path
from typing import IO

_REQUIRED_MEMBERS = ("db.sql.gz", "vault.key", "manifest.json")

# The shape `cb backup` produced before this batch. Named specifically so an operator
# holding one is told it never was restorable, rather than that db.sql.gz is missing.
_LEGACY_CB_BACKUP_MEMBERS = ("database.sql", "manifest.txt")


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
        stream = _open_member(tf, "db.sql.gz")
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
        actual = digest.hexdigest()

    if actual != expected:
        raise SnapshotProblem(
            f"db.sql.gz checksum mismatch in {path.name}: manifest says {expected[:12]}…, "
            f"archive contains {actual[:12]}…. The archive is corrupt or was modified."
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
