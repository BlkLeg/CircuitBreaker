"""The snapshot must archive the key the database is actually encrypted with.

`cb backup` runs `docker exec … python -m app.cli snapshot create`, which is a *fresh*
process: it sees the container's creation environment, not the exports the entrypoint
made and not the key the server resolved at boot. On a standard install those differ —
install.sh generates key A into the container environment, OOBE generates key B and
writes it to `$CB_DATA_DIR/.env`, and every credential is encrypted with B. Reading
`os.environ["CB_VAULT_KEY"]` archives A, the archive verifies clean because vault.key is
merely non-empty, and the restore then writes A over B and destroys the only copy of the
real key.

Two properties close that: the builder resolves the key through the same chain the server
uses (`vault_service.load_vault_key`), and the verifier cross-checks vault.key against the
`app_settings.vault_key_hash` carried in the dump, so a mismatched pair is refused rather
than silently applied.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import subprocess
import tarfile
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from app.services.backup.verify import SnapshotProblem, verify_archive


def _fake_pg_dump(monkeypatch: pytest.MonkeyPatch, payload: bytes = b"-- fake dump\n") -> None:
    """Stand in for the pg_dump binary; the key under test is independent of the dump."""
    original_run = subprocess.run

    def fake_run(cmd: list, **kwargs):  # type: ignore[no-untyped-def]
        if cmd and "pg_dump" in cmd[0]:
            return subprocess.CompletedProcess(cmd, 0, stdout=payload, stderr=b"")
        return original_run(cmd, **kwargs)

    monkeypatch.setattr(subprocess, "run", fake_run)


def _vault_key_in(archive: Path) -> str:
    with tarfile.open(archive, "r:gz") as tf:
        member = next(m for m in tf.getmembers() if m.name.endswith("vault.key"))
        payload = tf.extractfile(member)
        assert payload is not None
        return payload.read().decode().strip()


@pytest.mark.asyncio
async def test_snapshot_archives_the_key_the_database_is_encrypted_with(
    db_session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stale CB_VAULT_KEY in the process environment must not reach the archive."""
    from app.services import db_backup, vault_service
    from app.services.settings_service import get_or_create_settings

    stale_key = Fernet.generate_key().decode()  # what the container was created with
    real_key = Fernet.generate_key().decode()  # what OOBE generated and encrypted with

    cfg = get_or_create_settings(db_session)
    cfg.vault_key_hash = hashlib.sha256(real_key.encode()).hexdigest()
    cfg.vault_key = None
    db_session.flush()

    data_env = tmp_path / "data" / ".env"
    data_env.parent.mkdir(parents=True)
    data_env.write_text(f"CB_VAULT_KEY={real_key}\n", encoding="utf-8")
    monkeypatch.setattr(vault_service, "_DATA_ENV_PATH", data_env)
    monkeypatch.setenv("CB_VAULT_KEY", stale_key)

    monkeypatch.setattr(db_backup, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(db_backup, "_data_dir", tmp_path / "data")
    _fake_pg_dump(monkeypatch)

    archive = await db_backup.run_full_snapshot(db_session)

    assert _vault_key_in(archive) == real_key, (
        "the snapshot archived the container's creation-environment key, not the key the "
        "database is encrypted with"
    )


# ── The verifier's half: refuse a vault.key the dump disagrees with ──────────────────


def _dump_with_app_settings(vault_key_hash: str | None) -> bytes:
    """A plain pg_dump-shaped COPY block for app_settings."""
    value = vault_key_hash if vault_key_hash is not None else r"\N"
    return (
        "--\n-- PostgreSQL database dump\n--\n\n"
        "COPY public.app_settings (id, vault_key_hash, vault_key_rotated_at) FROM stdin;\n"
        f"1\t{value}\t\\N\n"
        "\\.\n\n\n"
    ).encode()


def _archive(tmp_path: Path, *, dump: bytes, vault: str) -> Path:
    inner = tmp_path / "cb-snapshot-test"
    inner.mkdir(parents=True, exist_ok=True)
    gz = gzip.compress(dump)
    (inner / "db.sql.gz").write_bytes(gz)
    (inner / "vault.key").write_text(vault, encoding="utf-8")
    (inner / "manifest.json").write_text(
        json.dumps(
            {
                "format_version": 1,
                "install_mode": "docker",
                "cb_version": "1.0.0",
                "created_at": "2026-08-24T00:00:00+00:00",
                "db_name": "circuitbreaker",
                "uploads_count": 0,
                "db_checksum_sha256": hashlib.sha256(gz).hexdigest(),
                "config_files": [],
            }
        ),
        encoding="utf-8",
    )
    dest = tmp_path / "snap.tar.gz"
    with tarfile.open(dest, "w:gz") as tf:
        tf.add(inner, arcname=inner.name)
    return dest


def test_verify_refuses_a_vault_key_the_dump_disagrees_with(tmp_path: Path) -> None:
    """The exact INC shape: key A in vault.key, a database encrypted with key B."""
    real_key = Fernet.generate_key().decode()
    stale_key = Fernet.generate_key().decode()
    archive = _archive(
        tmp_path,
        dump=_dump_with_app_settings(hashlib.sha256(real_key.encode()).hexdigest()),
        vault=stale_key,
    )

    with pytest.raises(SnapshotProblem) as excinfo:
        verify_archive(archive)

    message = str(excinfo.value).lower()
    assert "vault" in message
    assert "vault_key_hash" in message or "does not match" in message


def test_verify_accepts_a_vault_key_the_dump_agrees_with(tmp_path: Path) -> None:
    key = Fernet.generate_key().decode()
    archive = _archive(
        tmp_path,
        dump=_dump_with_app_settings(hashlib.sha256(key.encode()).hexdigest()),
        vault=key,
    )

    assert verify_archive(archive)["db_name"] == "circuitbreaker"


def test_verify_accepts_a_dump_that_records_no_hash(tmp_path: Path) -> None:
    """A pre-hash install has nothing to cross-check against; that is not a refusal."""
    archive = _archive(tmp_path, dump=_dump_with_app_settings(None), vault="any-key")

    assert verify_archive(archive)["db_name"] == "circuitbreaker"
