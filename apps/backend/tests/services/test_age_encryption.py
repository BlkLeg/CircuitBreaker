from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.services.backup.age_encryption import encrypt_for_upload, validate_age_recipient
from app.services.backup.snapshot import BackupError

RECIPIENT = "age1" + "q" * 58


def test_recipient_accepts_one_x25519_public_key_only() -> None:
    assert validate_age_recipient(RECIPIENT) == RECIPIENT
    for invalid in (None, "", "AGE-SECRET-KEY-1NOTPUBLIC", "age1short", RECIPIENT + "x"):
        with pytest.raises(BackupError, match="recipient"):
            validate_age_recipient(invalid)


def test_encrypt_for_upload_creates_mode_0600_age_derivative(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = tmp_path / "cb-snapshot-test.tar.gz"
    archive.write_bytes(b"plaintext snapshot")
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/age")

    def fake_run(argv, **kwargs):  # type: ignore[no-untyped-def]
        output = Path(argv[argv.index("--output") + 1])
        output.write_bytes(b"age-encryption.org/v1\nopaque")
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    encrypted = encrypt_for_upload(archive, RECIPIENT)
    assert encrypted.name.endswith(".tar.gz.age")
    assert encrypted.read_bytes().startswith(b"age-encryption.org/v1")
    assert encrypted.stat().st_mode & 0o777 == 0o600
    assert archive.read_bytes() == b"plaintext snapshot"


def test_encryption_failure_removes_partial_derivative(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = tmp_path / "cb-snapshot-test.tar.gz"
    archive.write_bytes(b"plaintext snapshot")
    partial = archive.with_name(archive.name + ".age")
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/age")

    def fail(argv, **kwargs):  # type: ignore[no-untyped-def]
        partial.write_bytes(b"partial")
        raise subprocess.CalledProcessError(1, argv, stderr=b"wrong recipient")

    monkeypatch.setattr(subprocess, "run", fail)
    with pytest.raises(BackupError, match="wrong recipient"):
        encrypt_for_upload(archive, RECIPIENT)
    assert not partial.exists()
