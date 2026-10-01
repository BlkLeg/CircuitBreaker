"""deploy/lib/bundle-signature.sh, driven through bash with throwaway keys.

Keys are generated per test with scripts/release_signing_key.sh inside
tmp_path; nothing here is committed key material (CLAUDE.md).
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / "deploy" / "lib" / "bundle-signature.sh"
KEYS = ROOT / "deploy" / "keys" / "release-bundle-keys.txt"
KEYGEN = ROOT / "scripts" / "release_signing_key.sh"
SIGN = ROOT / "scripts" / "ci" / "sign_release_sums.sh"
TARBALL = "circuit-breaker_0.4.7_linux_amd64.tar.gz"


def bash(script: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", f'set -euo pipefail\nsource "{LIB}"\n{script}', "bash", *args],
        capture_output=True, text=True,
    )


class Release:
    """A tarball, its SHA256SUMS and a signature, in one tmp directory."""

    def __init__(self, tmp: Path, name: str = "a") -> None:
        self.dir = tmp
        self.key = tmp / f"{name}.pem"
        line = subprocess.run(
            ["bash", str(KEYGEN), str(self.key), "0.4.7", f"key {name}"],
            capture_output=True, text=True, check=True,
        ).stdout
        self.key_id = line.split()[0]
        self.keys = tmp / f"{name}-keys.txt"
        self.keys.write_text("# comment\n\n" + line)
        self.tarball = tmp / TARBALL
        self.tarball.write_bytes(b"bundle bytes")
        self.sums = tmp / "SHA256SUMS"
        digest = hashlib.sha256(self.tarball.read_bytes()).hexdigest()
        self.sums.write_text(
            f"{digest}  ./{TARBALL}\n" + "0" * 64 + f"  ./{TARBALL}.asc\n"
        )
        self.sig = tmp / "SHA256SUMS.sig"
        self.sign()

    def sign(self, key: Path | None = None) -> None:
        subprocess.run(["bash", str(SIGN), str(key or self.key), str(self.sums), str(self.sig)], check=True)


@pytest.fixture
def rel(tmp_path: Path) -> Release:
    return Release(tmp_path)


def test_a_good_signature_verifies_and_names_its_key(rel: Release) -> None:
    r = bash('cb_verify_sums_signature "$1" "$2" "$3"', str(rel.sums), str(rel.sig), str(rel.keys))
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == rel.key_id


def test_a_tampered_sums_file_fails(rel: Release) -> None:
    rel.sums.write_text(rel.sums.read_text().replace("0" * 64, "1" * 64))
    r = bash('cb_verify_sums_signature "$1" "$2" "$3"', str(rel.sums), str(rel.sig), str(rel.keys))
    assert r.returncode == 1


def test_a_signature_from_an_untrusted_key_fails(tmp_path: Path, rel: Release) -> None:
    (tmp_path / "o").mkdir()
    other = Release(tmp_path / "o", "b")
    rel.sign(other.key)
    r = bash('cb_verify_sums_signature "$1" "$2" "$3"', str(rel.sums), str(rel.sig), str(rel.keys))
    assert r.returncode == 1


def test_the_second_of_two_trusted_keys_is_found(tmp_path: Path, rel: Release) -> None:
    (tmp_path / "o").mkdir()
    other = Release(tmp_path / "o", "b")
    both = tmp_path / "both.txt"
    both.write_text(other.keys.read_text() + rel.keys.read_text())
    r = bash('cb_verify_sums_signature "$1" "$2" "$3"', str(rel.sums), str(rel.sig), str(both))
    assert (r.returncode, r.stdout.strip()) == (0, rel.key_id)


def test_no_trusted_keys_is_its_own_failure(tmp_path: Path, rel: Release) -> None:
    empty = tmp_path / "empty.txt"
    empty.write_text("# nothing trusted yet\n")
    r = bash('cb_verify_sums_signature "$1" "$2" "$3"', str(rel.sums), str(rel.sig), str(empty))
    assert r.returncode == 2


@pytest.mark.parametrize("garbage", ["not base64 !!!\n", "c2hvcnQ=\n", ""])
def test_an_unreadable_signature_is_its_own_failure(rel: Release, garbage: str) -> None:
    rel.sig.write_text(garbage)
    r = bash('cb_verify_sums_signature "$1" "$2" "$3"', str(rel.sums), str(rel.sig), str(rel.keys))
    assert r.returncode == 2


def test_crlf_and_whitespace_around_the_signature_are_tolerated(rel: Release) -> None:
    rel.sig.write_text("  " + rel.sig.read_text().strip() + "\r\n\r\n")
    r = bash('cb_verify_sums_signature "$1" "$2" "$3"', str(rel.sums), str(rel.sig), str(rel.keys))
    assert r.returncode == 0, r.stderr


def test_a_key_line_whose_id_does_not_match_its_key_is_ignored(tmp_path: Path, rel: Release) -> None:
    key_id, rest = rel.keys.read_text().splitlines()[-1].split(" ", 1)
    forged = tmp_path / "forged.txt"
    forged.write_text(f"{'0' * 16} {rest}\n")
    r = bash('cb_release_keys "$1"', str(forged))
    assert r.stdout == ""
    r = bash('cb_verify_sums_signature "$1" "$2" "$3"', str(rel.sums), str(rel.sig), str(forged))
    assert r.returncode == 2


def test_the_hash_entry_is_chosen_by_exact_name(rel: Release) -> None:
    r = bash('cb_verify_sums_entry "$1" "$2"', str(rel.sums), str(rel.tarball))
    assert r.returncode == 0
    rel.tarball.write_bytes(b"tampered")
    assert bash('cb_verify_sums_entry "$1" "$2"', str(rel.sums), str(rel.tarball)).returncode == 1


def test_an_unlisted_tarball_is_its_own_failure(rel: Release) -> None:
    renamed = rel.dir / f"{TARBALL}(1)"
    renamed.write_bytes(rel.tarball.read_bytes())
    assert bash('cb_verify_sums_entry "$1" "$2"', str(rel.sums), str(renamed)).returncode == 3


def test_an_asc_entry_does_not_stand_in_for_the_tarball(rel: Release) -> None:
    """`./x.tar.gz.asc` contains `./x.tar.gz`; a substring match would pass."""
    digest = hashlib.sha256(rel.tarball.read_bytes()).hexdigest()
    rel.sums.write_text(f"{digest}  ./{TARBALL}.asc\n")
    assert bash('cb_verify_sums_entry "$1" "$2"', str(rel.sums), str(rel.tarball)).returncode == 3


def test_a_bare_name_entry_written_by_sha256sum_star_is_found(rel: Release) -> None:
    """`make sign` and users run `sha256sum * > SHA256SUMS`: no ./ prefix."""
    digest = hashlib.sha256(rel.tarball.read_bytes()).hexdigest()
    rel.sums.write_text("0" * 64 + f"  {TARBALL}.asc\n" + f"{digest}  {TARBALL}\n")
    assert bash('cb_verify_sums_entry "$1" "$2"', str(rel.sums), str(rel.tarball)).returncode == 0
    rel.tarball.write_bytes(b"tampered")
    assert bash('cb_verify_sums_entry "$1" "$2"', str(rel.sums), str(rel.tarball)).returncode == 1


def test_a_bare_name_asc_entry_does_not_stand_in_for_the_tarball(rel: Release) -> None:
    digest = hashlib.sha256(rel.tarball.read_bytes()).hexdigest()
    rel.sums.write_text(f"{digest}  {TARBALL}.asc\n{digest}  sub/{TARBALL}\n")
    assert bash('cb_verify_sums_entry "$1" "$2"', str(rel.sums), str(rel.tarball)).returncode == 3


@pytest.mark.parametrize(
    ("version", "required"),
    [("0.4.6", False), ("0.4.6-rc.1", False), ("0.3.9", False), ("", False),
     ("0.4.7", True), ("v0.4.7", True), ("0.4.7-rc.1", True), ("0.4.10", True),
     ("0.5.0", True), ("1.0.0-rc.4", True)],
)
def test_which_releases_must_be_signed(version: str, required: bool) -> None:
    r = bash('cb_release_requires_signature "$1"', version)
    assert (r.returncode == 0) is required


def test_the_embedded_list_is_the_key_file_byte_for_byte() -> None:
    r = bash("_cb_embedded_release_keys")
    assert r.returncode == 0
    assert r.stdout == KEYS.read_text()


def test_cb_verify_sums_entry_returns_3_when_sums_file_is_missing_under_set_e(rel: Release) -> None:
    # Under set -euo pipefail, missing sums file should return 3, not awk's error code 2
    r = bash('cb_verify_sums_entry "$1" "$2"', "/nonexistent/SHA256SUMS", str(rel.tarball))
    assert r.returncode == 3, f"Expected rc=3 for missing sums, got rc={r.returncode}\nstderr: {r.stderr}"


def test_cb_verify_sums_entry_returns_1_when_tarball_is_missing_under_set_e(rel: Release) -> None:
    # Remove the tarball file but keep its entry in sums; should return 1 (mismatch)
    rel.tarball.unlink()
    r = bash('cb_verify_sums_entry "$1" "$2"', str(rel.sums), str(rel.tarball))
    assert r.returncode == 1, f"Expected rc=1 for missing tarball, got rc={r.returncode}\nstderr: {r.stderr}"


def test_cb_release_keys_tolerates_crlf_key_lines(tmp_path: Path, rel: Release) -> None:
    # A key line with CRLF should be parsed correctly
    key_id, rest = rel.keys.read_text().splitlines()[-1].split(" ", 1)
    crlf_keys = tmp_path / "crlf.txt"
    # Write a key line with CRLF line ending
    crlf_keys.write_bytes((f"{key_id} {rest}\r\n").encode())
    r = bash('cb_release_keys "$1"', str(crlf_keys))
    assert r.returncode == 0
    assert f"{key_id} " in r.stdout
    # Now verify that a signature from this key verifies even with CRLF key lines
    r = bash('cb_verify_sums_signature "$1" "$2" "$3"', str(rel.sums), str(rel.sig), str(crlf_keys))
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == key_id


def test_every_committed_key_line_is_well_formed() -> None:
    import base64

    for line in KEYS.read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        key_id, pub, first, _comment = line.split(" ", 3)
        raw = base64.b64decode(pub, validate=True)
        assert len(raw) == 32, line
        assert key_id == hashlib.sha256(raw).hexdigest()[:16], line
        assert re.fullmatch(r"\d+\.\d+\.\d+", first), line
