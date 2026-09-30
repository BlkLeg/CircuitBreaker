"""The two release-key tools: generating the key pair, and signing SHA256SUMS.

Every key here is generated inside the test's tmp_path and discarded with it;
no key material is committed (CLAUDE.md).
"""

from __future__ import annotations

import base64
import hashlib
import re
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KEYGEN = ROOT / "scripts" / "release_signing_key.sh"
SIGN = ROOT / "scripts" / "ci" / "sign_release_sums.sh"
SPKI_PREFIX = bytes.fromhex("302a300506032b6570032100")


def _keygen(tmp_path: Path, name: str = "k.pem") -> tuple[Path, str]:
    out = subprocess.run(
        ["bash", str(KEYGEN), str(tmp_path / name), "0.4.7", "test key"],
        capture_output=True, text=True, check=True,
    )
    return tmp_path / name, out.stdout.strip()


def test_keygen_writes_a_private_pem_and_prints_a_valid_key_line(tmp_path: Path) -> None:
    key, line = _keygen(tmp_path)
    assert stat.S_IMODE(key.stat().st_mode) == 0o600
    assert key.read_text().startswith("-----BEGIN PRIVATE KEY-----")
    key_id, pub, first, comment = line.split(" ", 3)
    raw = base64.b64decode(pub, validate=True)
    assert len(raw) == 32
    assert key_id == hashlib.sha256(raw).hexdigest()[:16]
    assert (first, comment) == ("0.4.7", "test key")
    assert re.fullmatch(r"[0-9a-f]{16} [A-Za-z0-9+/]{43}= \S+ .+", line)


def test_keygen_refuses_to_overwrite(tmp_path: Path) -> None:
    key, _ = _keygen(tmp_path)
    before = key.read_bytes()
    result = subprocess.run(
        ["bash", str(KEYGEN), str(key), "0.4.7"], capture_output=True, text=True
    )
    assert result.returncode != 0
    assert "refusing to overwrite" in result.stderr
    assert key.read_bytes() == before


def test_keygen_requires_a_first_version(tmp_path: Path) -> None:
    result = subprocess.run(["bash", str(KEYGEN), str(tmp_path / "k.pem")], capture_output=True, text=True)
    assert result.returncode != 0
    assert not (tmp_path / "k.pem").exists()


def test_sign_produces_a_signature_the_public_key_verifies(tmp_path: Path) -> None:
    key, line = _keygen(tmp_path)
    sums = tmp_path / "SHA256SUMS"
    sums.write_text("ab" * 32 + "  ./circuit-breaker_0.4.7_linux_amd64.tar.gz\n")
    sig = tmp_path / "SHA256SUMS.sig"
    subprocess.run(["bash", str(SIGN), str(key), str(sums), str(sig)], check=True)
    text = sig.read_text()
    assert text.endswith("\n") and text.count("\n") == 1
    raw_sig = base64.b64decode(text.strip(), validate=True)
    assert len(raw_sig) == 64
    der = tmp_path / "pub.der"
    der.write_bytes(SPKI_PREFIX + base64.b64decode(line.split()[1]))
    (tmp_path / "sig.bin").write_bytes(raw_sig)
    verify = subprocess.run(
        ["openssl", "pkeyutl", "-verify", "-pubin", "-inkey", str(der), "-keyform", "DER",
         "-rawin", "-in", str(sums), "-sigfile", str(tmp_path / "sig.bin")],
        capture_output=True, text=True,
    )
    assert verify.returncode == 0, verify.stderr


def test_sign_fails_loudly_on_a_bad_key(tmp_path: Path) -> None:
    bad = tmp_path / "bad.pem"
    bad.write_text("not a key\n")
    sums = tmp_path / "SHA256SUMS"
    sums.write_text("x\n")
    result = subprocess.run(
        ["bash", str(SIGN), str(bad), str(sums), str(tmp_path / "out.sig")],
        capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert not (tmp_path / "out.sig").exists()
