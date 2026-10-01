"""The npm CLI and the shell installers must reach the same verdict on the same files.

Keys are throwaway, generated per test with scripts/release_signing_key.sh.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / "deploy" / "lib" / "bundle-signature.sh"
KEYGEN = ROOT / "scripts" / "release_signing_key.sh"
SIGN = ROOT / "scripts" / "ci" / "sign_release_sums.sh"
TRUST_JS = ROOT / "packages" / "cli" / "src" / "release-trust.js"
NAME = "circuit-breaker_0.4.7_linux_amd64.tar.gz"


def test_packaged_key_list_is_the_repo_key_list() -> None:
    assert (ROOT / "packages" / "cli" / "trust" / "release-bundle-keys.txt").read_bytes() == (
        ROOT / "deploy" / "keys" / "release-bundle-keys.txt"
    ).read_bytes()


def test_unsigned_pins_match_the_installer() -> None:
    shell = dict(
        (name, digest)
        for digest, name in re.findall(
            r'^CB_UNSIGNED_PIN_\w+="([0-9a-f]{64})  (\S+)"$', (ROOT / "install.sh").read_text(), re.MULTILINE
        )
    )
    js = dict(
        (name, digest)
        for digest, name in re.findall(r"sha256: '([0-9a-f]{64})', name: '([^']+)'", TRUST_JS.read_text())
    )
    assert shell and js == shell


def _node(script: str, *args: str) -> dict:
    out = subprocess.run(
        ["node", "--input-type=module", "-e", script, *args], capture_output=True, text=True, check=True
    )
    return json.loads(out.stdout)


def _js_verdict(sums: Path, sig: Path, keys: Path) -> str:
    script = (
        f"import {{ readFileSync }} from 'node:fs';"
        f"import {{ parseTrustedKeys, verifySumsSignature }} from '{TRUST_JS.as_uri()}';"
        "const [s, g, k] = process.argv.slice(1);"
        "const r = verifySumsSignature(readFileSync(s), readFileSync(g, 'utf8'), parseTrustedKeys(readFileSync(k, 'utf8')));"
        "console.log(JSON.stringify(r.ok ? 'ok' : r.reason));"
    )
    return _node(script, str(sums), str(sig), str(keys))


def _shell_verdict(sums: Path, sig: Path, keys: Path) -> str:
    rc = subprocess.run(
        ["bash", "-c", f'source "{LIB}"; cb_verify_sums_signature "$1" "$2" "$3" >/dev/null', "bash", str(sums), str(sig), str(keys)]
    ).returncode
    return {0: "ok", 1: "mismatch", 2: "unreadable-or-no-keys"}[rc]


@pytest.mark.parametrize("case", ["good", "tampered", "untrusted", "crlf", "garbage", "no-keys"])
def test_both_implementations_agree(tmp_path: Path, case: str) -> None:
    line = subprocess.run(
        ["bash", str(KEYGEN), str(tmp_path / "k.pem"), "0.4.7", "t"], capture_output=True, text=True, check=True
    ).stdout
    keys = tmp_path / "keys.txt"
    keys.write_text(line if case != "no-keys" else "# none\n")
    sums = tmp_path / "SHA256SUMS"
    sums.write_text(f"{hashlib.sha256(b'b').hexdigest()}  ./{NAME}\n")
    sig = tmp_path / "SHA256SUMS.sig"
    signer = tmp_path / "k.pem"
    if case == "untrusted":
        subprocess.run(["bash", str(KEYGEN), str(tmp_path / "o.pem"), "0.4.7"], capture_output=True, check=True)
        signer = tmp_path / "o.pem"
    subprocess.run(["bash", str(SIGN), str(signer), str(sums), str(sig)], check=True)
    if case == "tampered":
        sums.write_text(sums.read_text() + "x\n")
    if case == "crlf":
        sig.write_text(sig.read_text().strip() + "\r\n")
    if case == "garbage":
        sig.write_text("garbage\n")
    js, sh = _js_verdict(sums, sig, keys), _shell_verdict(sums, sig, keys)
    expected = {"good": "ok", "crlf": "ok", "tampered": "mismatch", "untrusted": "mismatch",
                "garbage": "unreadable", "no-keys": "no-keys"}[case]
    assert js == expected
    assert sh == ("unreadable-or-no-keys" if expected in {"unreadable", "no-keys"} else expected)
