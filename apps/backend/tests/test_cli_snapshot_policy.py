"""SRV-06 / RC-04: `cb restore` and the documented version window.

`cb restore` verifies before it stops anything, in every install mode, and both
routes into the verifier — `python -m app.cli snapshot verify` in a container
and the frozen binary's `--snapshot-verify` — land in `app.cli`. So this is
where the compatibility policy is applied to an archive, and where it is
tested.

The two directions are not symmetrical, because the policy is not:

* An archive *newer* than the installed build is **Rejected** — "database
  schema ahead of the 1.0 binary" — and `verify_archive` refuses it.
* An archive older than the minimum supported source version is **Upgrade-only
  until proven**, which is a warning and not a refusal. Refusing it would turn
  a recoverable outage into an unrecoverable one over a migration path that is
  merely unproven; saying nothing would let the operator find out afterwards.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import re
import tarfile
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from app.cli import _MINIMUM_RESTORABLE_SOURCE_VERSION, main

_POLICY_DOC = (
    Path(__file__).resolve().parents[3] / "docs" / "release" / "1.0.0-compatibility-policy.md"
)


def _snapshot(tmp_path: Path, *, cb_version: str) -> Path:
    """A structurally valid snapshot: the shape services/backup/snapshot.py builds."""
    dump = gzip.compress(b"-- an empty but well-formed dump\n")
    vault_key = Fernet.generate_key()
    manifest = json.dumps(
        {
            "cb_version": cb_version,
            "db_checksum_sha256": hashlib.sha256(dump).hexdigest(),
        }
    ).encode()

    archive = tmp_path / f"cb-snapshot-{cb_version}.tar.gz"
    with tarfile.open(archive, "w:gz") as tf:
        for name, payload in (
            ("db.sql.gz", dump),
            ("vault.key", vault_key),
            ("manifest.json", manifest),
        ):
            info = tarfile.TarInfo(f"snapshot/{name}")
            info.size = len(payload)
            tf.addfile(info, io.BytesIO(payload))
    return archive


def test_the_floor_matches_the_published_compatibility_policy():
    """The constant in the container must be the number in the document.

    The policy table is the source of truth and does not ship inside the
    image, so the code carries the value and this test carries the link. A
    floor that drifted from the published one would enforce a window nobody
    agreed to.
    """
    text = _POLICY_DOC.read_text()
    match = re.search(r"Minimum directly supported source version for 1\.0\.0 is `([^`]+)`", text)
    assert match, "the compatibility policy no longer states a minimum source version"
    assert match.group(1) == _MINIMUM_RESTORABLE_SOURCE_VERSION


def test_an_archive_below_the_floor_is_verified_but_warned_about(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CB_VERSION", "1.0.0")
    archive = _snapshot(tmp_path, cb_version="0.2.9")

    assert main(["snapshot", "verify", str(archive)]) == 0
    captured = capsys.readouterr()
    assert "minimum directly supported source version" in captured.err
    assert json.loads(captured.out)["cb_version"] == "0.2.9"


def test_an_archive_at_the_floor_passes_without_a_warning(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CB_VERSION", "1.0.0")
    archive = _snapshot(tmp_path, cb_version=_MINIMUM_RESTORABLE_SOURCE_VERSION)

    assert main(["snapshot", "verify", str(archive)]) == 0
    assert "minimum directly supported" not in capsys.readouterr().err


def test_a_newer_archive_is_refused_not_warned(tmp_path, monkeypatch, capsys):
    """The other direction: rejected, before the restore stops anything."""
    monkeypatch.setenv("CB_VERSION", "1.0.0")
    archive = _snapshot(tmp_path, cb_version="1.1.0")

    assert main(["snapshot", "verify", str(archive)]) == 1
    assert "newer than the installed" in capsys.readouterr().err


def test_force_clears_both_version_gates_and_not_only_one(tmp_path, monkeypatch, capsys):
    """`cb restore --force` sends one signal — an empty CB_VERSION — to both."""
    monkeypatch.setenv("CB_VERSION", "")
    old_archive = _snapshot(tmp_path, cb_version="0.2.9")
    new_archive = _snapshot(tmp_path, cb_version="1.1.0")

    assert main(["snapshot", "verify", str(old_archive)]) == 0
    assert main(["snapshot", "verify", str(new_archive)]) == 0
    assert "minimum directly supported" not in capsys.readouterr().err


def test_a_corrupt_dump_is_refused_before_anything_is_stopped(tmp_path, capsys):
    """The checksum half of the restore refusal, through the CLI the wrappers call."""
    archive = tmp_path / "tampered.tar.gz"
    dump = gzip.compress(b"the dump that was archived\n")
    manifest = json.dumps(
        {"cb_version": "1.0.0", "db_checksum_sha256": hashlib.sha256(b"something else").hexdigest()}
    ).encode()
    with tarfile.open(archive, "w:gz") as tf:
        for name, payload in (
            ("db.sql.gz", dump),
            ("vault.key", Fernet.generate_key()),
            ("manifest.json", manifest),
        ):
            info = tarfile.TarInfo(f"snapshot/{name}")
            info.size = len(payload)
            tf.addfile(info, io.BytesIO(payload))

    assert main(["snapshot", "verify", str(archive)]) == 1
    assert "checksum mismatch" in capsys.readouterr().err


def test_a_missing_vault_key_is_refused(tmp_path, capsys):
    archive = tmp_path / "keyless.tar.gz"
    dump = gzip.compress(b"dump\n")
    manifest = json.dumps(
        {"cb_version": "1.0.0", "db_checksum_sha256": hashlib.sha256(dump).hexdigest()}
    ).encode()
    with tarfile.open(archive, "w:gz") as tf:
        for name, payload in (
            ("db.sql.gz", dump),
            ("vault.key", b"   \n"),
            ("manifest.json", manifest),
        ):
            info = tarfile.TarInfo(f"snapshot/{name}")
            info.size = len(payload)
            tf.addfile(info, io.BytesIO(payload))

    assert main(["snapshot", "verify", str(archive)]) == 1
    assert "vault.key" in capsys.readouterr().err


@pytest.mark.parametrize("argv", [["snapshot", "verify", "/nonexistent/archive.tar.gz"]])
def test_a_missing_archive_is_a_sentence_not_a_traceback(argv, capsys):
    assert main(argv) == 1
    captured = capsys.readouterr()
    assert "Snapshot file not found" in captured.err
    assert "Traceback" not in captured.err
