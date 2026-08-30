"""`cb backup` and `cb restore` reach the snapshot machinery through these subcommands.

The shell is the only caller that matters here, so what is pinned is the shell's
contract: `snapshot create` prints the tarball path and nothing else on stdout, and
`snapshot verify` turns a `SnapshotProblem` into a non-zero exit with the operator's
reason on stderr. Both are the third caller of `run_full_snapshot`/`verify_archive`,
never a second implementation — which is why the indirections below are the seams the
tests replace, rather than a database.
"""

from __future__ import annotations

from app.cli import build_parser, main
from app.services.backup.verify import SnapshotProblem


class _NullSession:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_parser_accepts_snapshot_create():
    args = build_parser().parse_args(["snapshot", "create", "--out", "/tmp/x"])

    assert args.group == "snapshot"
    assert args.action == "create"
    assert args.out == "/tmp/x"


def test_parser_accepts_snapshot_verify():
    args = build_parser().parse_args(["snapshot", "verify", "/tmp/snap.tar.gz"])

    assert args.group == "snapshot"
    assert args.action == "verify"
    assert args.archive == "/tmp/snap.tar.gz"


def test_verify_returns_zero_for_a_good_archive(monkeypatch, capsys):
    monkeypatch.setattr(
        "app.cli.verify_archive", lambda path, installed_version=None: {"cb_version": "1.0.0"}
    )

    assert main(["snapshot", "verify", "/tmp/snap.tar.gz"]) == 0
    assert "1.0.0" in capsys.readouterr().out


def test_verify_returns_nonzero_and_prints_the_reason(monkeypatch, capsys):
    def _boom(path, installed_version=None):
        raise SnapshotProblem("vault.key inside snap.tar.gz is empty")

    monkeypatch.setattr("app.cli.verify_archive", _boom)

    assert main(["snapshot", "verify", "/tmp/snap.tar.gz"]) == 1
    assert "vault.key" in capsys.readouterr().err


def test_create_prints_the_path(monkeypatch, capsys, tmp_path):
    made = tmp_path / "cb-snapshot-20260824-000000.tar.gz"
    made.write_bytes(b"")

    async def _fake(db):
        return made

    monkeypatch.setattr("app.cli._run_full_snapshot", _fake)
    monkeypatch.setattr("app.cli._cli_session", lambda: _NullSession())

    assert main(["snapshot", "create"]) == 0
    assert str(made) in capsys.readouterr().out


def test_create_reports_a_failure_instead_of_raising(monkeypatch, capsys):
    async def _boom(db):
        raise RuntimeError("pg_dump not found")

    monkeypatch.setattr("app.cli._run_full_snapshot", _boom)
    monkeypatch.setattr("app.cli._cli_session", lambda: _NullSession())

    assert main(["snapshot", "create"]) == 1
    assert "pg_dump not found" in capsys.readouterr().err


def test_create_out_directory_becomes_the_backup_dir(monkeypatch, tmp_path):
    """--out has to land before services.db_backup reads BACKUP_DIR at import time."""
    seen: dict[str, str] = {}

    async def _fake(db):
        import os

        seen["backup_dir"] = os.environ["BACKUP_DIR"]
        return tmp_path / "snap.tar.gz"

    monkeypatch.setattr("app.cli._run_full_snapshot", _fake)
    monkeypatch.setattr("app.cli._cli_session", lambda: _NullSession())

    assert main(["snapshot", "create", "--out", str(tmp_path)]) == 0
    assert seen["backup_dir"] == str(tmp_path)


def test_entrypoint_routes_snapshot_create_to_the_cli(monkeypatch):
    """Binary installs have no `python -m app.cli`.

    `cb backup` in binary mode runs the frozen entrypoint built from `start.py`
    (scripts/build_native_release.py:BACKEND_ENTRYPOINT), so the only way in is a
    flag that entrypoint understands — the same route `--config-validate` takes.
    """
    import app.cli
    from app import start

    seen: dict[str, list[str]] = {}

    def _fake_cli_main(argv: list[str]) -> int:
        seen["argv"] = argv
        return 0

    monkeypatch.setattr(app.cli, "main", _fake_cli_main)

    assert start.main(["--snapshot-create", "--out", "/var/backups"]) == 0
    assert seen["argv"] == ["snapshot", "create", "--out", "/var/backups"]


def test_entrypoint_snapshot_create_without_an_out_directory(monkeypatch):
    """No --out means the configured BACKUP_DIR, exactly as the CLI defaults."""
    import app.cli
    from app import start

    seen: dict[str, list[str]] = {}

    def _fake_cli_main(argv: list[str]) -> int:
        seen["argv"] = argv
        return 0

    monkeypatch.setattr(app.cli, "main", _fake_cli_main)

    assert start.main(["--snapshot-create"]) == 0
    assert seen["argv"] == ["snapshot", "create"]


def test_entrypoint_routes_snapshot_verify_to_the_cli(monkeypatch):
    """`cb restore` verifies before it stops anything — in binary mode too.

    There is no `python -m app.cli` on a packaged install, and `cb`'s binary branches run
    `$CB_BINARY --config-validate` / `--snapshot-create`. Verification takes the same route,
    so all three modes refuse an unrestorable archive with the same sentence.
    """
    import app.cli
    from app import start

    seen: dict[str, list[str]] = {}

    def _fake_cli_main(argv: list[str]) -> int:
        seen["argv"] = argv
        return 0

    monkeypatch.setattr(app.cli, "main", _fake_cli_main)

    assert start.main(["--snapshot-verify", "/var/backups/snap.tar.gz"]) == 0
    assert seen["argv"] == ["snapshot", "verify", "/var/backups/snap.tar.gz"]


# ── snapshot encrypt (B3) ────────────────────────────────────────────────────
#
# The subcommand exists so the encrypted-backup promise has a caller outside a
# configured S3 bucket: `cb backup --encrypt-to` and Tier 3's round trip both
# come through here. It is the third caller of `encrypt_for_upload`, never a
# second implementation — the same rule `create` and `verify` follow above.


def test_parser_accepts_snapshot_encrypt():
    args = build_parser().parse_args(
        ["snapshot", "encrypt", "/tmp/snap.tar.gz", "--recipient", "age1abc"]
    )

    assert args.group == "snapshot"
    assert args.action == "encrypt"
    assert args.archive == "/tmp/snap.tar.gz"
    assert args.recipient == "age1abc"


def test_parser_requires_a_recipient_to_encrypt():
    """An archive encrypted to a default recipient is one nobody holds the key to."""
    import pytest

    with pytest.raises(SystemExit):
        build_parser().parse_args(["snapshot", "encrypt", "/tmp/snap.tar.gz"])


def test_encrypt_prints_the_derivative_path_and_nothing_else(tmp_path, monkeypatch, capsys):
    archive = tmp_path / "cb-snapshot-20260830-020000.tar.gz"
    archive.write_bytes(b"snapshot")
    encrypted = archive.with_suffix(archive.suffix + ".age")

    def _fake_encrypt(path, recipient):
        assert path == archive
        assert recipient == "age1abc"
        encrypted.write_bytes(b"age-encryption.org/v1\nopaque")
        return encrypted

    monkeypatch.setattr("app.services.backup.age_encryption.encrypt_for_upload", _fake_encrypt)

    assert main(["snapshot", "encrypt", str(archive), "--recipient", "age1abc"]) == 0
    assert capsys.readouterr().out.strip() == str(encrypted)


def test_encrypt_reports_a_missing_archive_without_calling_the_encryptor(tmp_path, capsys):
    missing = tmp_path / "absent.tar.gz"

    assert main(["snapshot", "encrypt", str(missing), "--recipient", "age1abc"]) == 1
    assert "snapshot not found" in capsys.readouterr().err


def test_encrypt_turns_a_backup_error_into_the_operator_s_reason(tmp_path, monkeypatch, capsys):
    """A rejected recipient is an operator mistake, not a traceback."""
    from app.services.backup.snapshot import BackupError

    archive = tmp_path / "cb-snapshot-20260830-020000.tar.gz"
    archive.write_bytes(b"snapshot")

    def _refuse(path, recipient):
        raise BackupError("S3 backup requires one valid age X25519 recipient (age1...)")

    monkeypatch.setattr("app.services.backup.age_encryption.encrypt_for_upload", _refuse)

    assert main(["snapshot", "encrypt", str(archive), "--recipient", "nonsense"]) == 1
    assert "valid age X25519 recipient" in capsys.readouterr().err


def test_entrypoint_routes_snapshot_encrypt_to_the_cli(monkeypatch):
    """A packaged host has no `python -m app.cli`; this flag is the only route in."""
    import app.cli
    from app import start

    seen: dict[str, list[str]] = {}

    def _fake_cli_main(argv: list[str]) -> int:
        seen["argv"] = argv
        return 0

    monkeypatch.setattr(app.cli, "main", _fake_cli_main)

    archive = "/var/backups/snap.tar.gz"

    assert start.main(["--snapshot-encrypt", archive, "--recipient", "age1abc"]) == 0
    assert seen["argv"] == ["snapshot", "encrypt", "--recipient", "age1abc", archive]


def test_entrypoint_refuses_snapshot_encrypt_without_an_archive_or_recipient(capsys):
    """The two ways to mistype it, each named for what is missing.

    `--snapshot-encrypt --recipient age1…` in particular must not be read as a
    request to encrypt a file called "--recipient": that reports a missing
    snapshot, which names the wrong mistake.
    """
    from app import start

    assert start.main(["--snapshot-encrypt", "--recipient", "age1abc"]) == 2
    assert "requires the path to a snapshot archive" in capsys.readouterr().err

    assert start.main(["--snapshot-encrypt", "/var/backups/snap.tar.gz"]) == 2
    assert "requires --recipient" in capsys.readouterr().err
