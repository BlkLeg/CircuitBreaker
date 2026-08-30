"""Fail-closed age encryption for off-host snapshot copies."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from app.services.backup.snapshot import BackupError

_AGE_X25519_RECIPIENT = re.compile(r"^age1[023456789acdefghjklmnpqrstuvwxyz]{58}$")


def validate_age_recipient(value: str | None) -> str:
    recipient = (value or "").strip()
    if not _AGE_X25519_RECIPIENT.fullmatch(recipient):
        raise BackupError(
            "S3 backup requires one valid age X25519 recipient (age1...). "
            "The private identity must remain with the operator."
        )
    return recipient


def encrypt_for_upload(archive: Path, recipient: str | None) -> Path:
    """Encrypt *archive* beside it and return the mode-0600 temporary copy."""
    recipient = validate_age_recipient(recipient)
    age = shutil.which("age")
    if not age:
        raise BackupError("The age executable is required for encrypted S3 backups")
    encrypted = archive.with_name(archive.name + ".age")
    encrypted.unlink(missing_ok=True)
    try:
        subprocess.run(  # noqa: S603
            [age, "--encrypt", "--recipient", recipient, "--output", str(encrypted), str(archive)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        encrypted.chmod(0o600)
        return encrypted
    except (OSError, subprocess.CalledProcessError) as exc:
        encrypted.unlink(missing_ok=True)
        detail = ""
        if isinstance(exc, subprocess.CalledProcessError) and exc.stderr:
            detail = f": {exc.stderr.decode(errors='replace').strip()}"
        raise BackupError(f"age encryption failed{detail}") from exc
