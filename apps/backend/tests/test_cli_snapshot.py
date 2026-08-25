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
