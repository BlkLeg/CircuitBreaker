"""cb-proxmox-deploy.sh must verify the release bundle on the host.

The helper extracts the downloaded tarball inside the container and runs the
install.sh *from that tarball*. Verification done only by that install.sh is
verification by the thing being verified: a tampered tarball brings its own
installer and checks nothing. So the helper verifies SHA256SUMS.sig, then the
tarball's SHA256SUMS entry, with its own inlined copy of
deploy/lib/bundle-signature.sh, before any file reaches the container.

cb-proxmox-deploy.sh runs `main` at import time, so the functions under test
are extracted and eval'd in a clean bash with the UI stubbed to plain lines.
Keys are throwaway, generated per test in tmp_path, and injected by
redefining _cb_embedded_release_keys after the inlined library.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "cb-proxmox-deploy.sh"
KEYGEN = ROOT / "scripts" / "release_signing_key.sh"
SIGN = ROOT / "scripts" / "ci" / "sign_release_sums.sh"
TARBALL = "circuit-breaker_0.4.7_linux_amd64.tar.gz"
BEGIN = "# --- BEGIN INLINED deploy/lib/bundle-signature.sh"
END = "# --- END INLINED deploy/lib/bundle-signature.sh ---"

STUBS = """
msg_ok()   { echo "OK: $1"; }
msg_info() { echo "INFO: $1"; }
msg_warn() { echo "WARN: $1"; }
msg_err()  { echo "ERR: $1"; }
die()      { echo "DIE: $1"; return 1; }
whiptail() { echo "WHIPTAIL $*"; }
"""


def _text() -> str:
    return HELPER.read_text()


def _function(name: str) -> str:
    body = re.search(rf"^{name}\(\) \{{\n.*?^\}}$", _text(), re.MULTILINE | re.DOTALL)
    assert body, f"{name}() not found in cb-proxmox-deploy.sh"
    return body.group(0)


def _constant(name: str) -> str:
    line = re.search(rf'^{name}="[^"]*"$', _text(), re.MULTILINE)
    assert line, f"{name} not found in cb-proxmox-deploy.sh"
    return line.group(0)


def _library() -> str:
    text = _text()
    return text[text.index(BEGIN) : text.index(END)]


class Release:
    """A release directory on the "host": tarball, SHA256SUMS, SHA256SUMS.sig."""

    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.key = tmp / "k.pem"
        line = subprocess.run(
            ["bash", str(KEYGEN), str(self.key), "0.4.7", "t"],
            capture_output=True, text=True, check=True,
        ).stdout
        self.key_id = line.split()[0]
        self.keys = tmp / "keys.txt"
        self.keys.write_text(line)
        self.dir = tmp / "release"
        self.dir.mkdir()
        self.name = TARBALL
        self.tarball = self.dir / TARBALL
        self.tarball.write_bytes(b"bundle")
        self.sums = self.dir / "SHA256SUMS"
        self.sums.write_text(f"{hashlib.sha256(b'bundle').hexdigest()}  ./{TARBALL}\n")
        self.sig = self.dir / "SHA256SUMS.sig"
        self.sign()
        self.bin = tmp / "bin"
        self.bin.mkdir()
        # Verification makes no network calls; a curl that logs proves it.
        self.curl_log = tmp / "curl.log"
        self._exe("curl", f'#!/bin/sh\necho "$@" >> "{self.curl_log}"\nexit 7\n')

    def sign(self, key: Path | None = None) -> None:
        subprocess.run(["bash", str(SIGN), str(key or self.key), str(self.sums), str(self.sig)], check=True)

    def _exe(self, name: str, body: str) -> None:
        f = self.bin / name
        f.write_text(body)
        f.chmod(0o755)

    def fake_openssl(self, version_line: str) -> None:
        self._exe("openssl", f'#!/bin/sh\n[ "$1" = version ] && echo "{version_line}"\nexit 1\n')

    def verify(self, *, keys: Path | None = None, pin_this_tarball: bool = False,
               version: str = "0.4.7") -> subprocess.CompletedProcess[str]:
        # The real pins name the v0.4.6 bundles; a test that needs a pinned
        # tarball repoints one pin at its own throwaway tarball, after the
        # library's assignments.
        own_pin = (f'CB_UNSIGNED_PIN_AMD64="{hashlib.sha256(self.tarball.read_bytes()).hexdigest()}'
                   f'  {self.name}"') if pin_this_tarball else ""
        script = "\n".join([
            STUBS,
            _constant("CB_GITHUB_REPO"),
            _library(),
            f'_cb_embedded_release_keys() {{ cat "{keys or self.keys}"; }}',
            own_pin,
            _function("release_verify_fail"),
            _function("verify_release_files"),
            'verify_release_files "$1" "$2" "$3"',
            'echo "RC=$?"',
        ])
        env = {**os.environ, "PATH": f"{self.bin}:{os.environ['PATH']}"}
        return subprocess.run(["bash", "-c", script, "bash", str(self.dir), self.name, version],
                              capture_output=True, text=True, env=env, check=False)


@pytest.fixture
def rel(tmp_path: Path) -> Release:
    return Release(tmp_path)


def _ok(r: subprocess.CompletedProcess[str]) -> None:
    assert "RC=0" in r.stdout, r.stdout + r.stderr
    assert "DIE:" not in r.stdout


def _refused(r: subprocess.CompletedProcess[str]) -> None:
    assert "RC=1" in r.stdout, r.stdout + r.stderr
    assert "DIE:" in r.stdout


def test_a_signed_release_verifies_and_names_its_key(rel: Release) -> None:
    r = rel.verify()
    _ok(r)
    assert f"Signature verified (key {rel.key_id})" in r.stdout
    assert "SHA256 checksum verified" in r.stdout
    assert r.stdout.index("Signature verified") < r.stdout.index("SHA256 checksum verified")
    assert not rel.curl_log.exists(), "verification must not touch the network"


def test_a_signature_by_an_untrusted_key_is_refused(rel: Release, tmp_path: Path) -> None:
    other = tmp_path / "other.pem"
    subprocess.run(["bash", str(KEYGEN), str(other), "0.4.7"], capture_output=True, check=True)
    rel.sign(other)
    r = rel.verify()
    _refused(r)
    assert "signature does not verify" in r.stdout
    assert f"Keys tried: {rel.key_id}" in r.stdout
    assert "SHA256 checksum verified" not in r.stdout


def test_a_tampered_sums_file_is_refused(rel: Release) -> None:
    rel.sums.write_text(rel.sums.read_text() + "0" * 64 + "  ./extra\n")
    r = rel.verify()
    _refused(r)
    assert "signature does not verify" in r.stdout


def test_a_tampered_tarball_is_refused_after_the_signature(rel: Release) -> None:
    rel.tarball.write_bytes(b"evil")
    r = rel.verify()
    _refused(r)
    assert "Signature verified" in r.stdout
    assert "SHA256 mismatch" in r.stdout


def test_an_unlisted_tarball_is_refused_as_not_listed(rel: Release) -> None:
    renamed = "circuit-breaker_0.4.8_linux_amd64.tar.gz"
    rel.tarball.rename(rel.dir / renamed)
    rel.tarball = rel.dir / renamed
    rel.name = renamed
    r = rel.verify(version="0.4.8")
    _refused(r)
    assert f"{renamed} is not listed in SHA256SUMS" in r.stdout


def test_an_unreadable_signature_has_its_own_message(rel: Release) -> None:
    rel.sig.write_text("garbage\n")
    r = rel.verify()
    _refused(r)
    assert "SHA256SUMS.sig is unreadable" in r.stdout
    assert f"Keys tried: {rel.key_id}" in r.stdout


def test_a_helper_that_trusts_no_keys_is_refused(rel: Release, tmp_path: Path) -> None:
    empty = tmp_path / "empty.txt"
    empty.write_text("# no keys\n")
    r = rel.verify(keys=empty)
    _refused(r)
    assert "trusts no release keys" in r.stdout


def test_the_unsigned_pinned_v046_bundle_is_accepted_with_a_warning(rel: Release) -> None:
    rel.sig.unlink()
    r = rel.verify(pin_this_tarball=True, version="0.4.6")
    _ok(r)
    assert "WARN:" in r.stdout and "predates bundle signing" in r.stdout
    assert "SHA256 checksum verified" in r.stdout


def test_an_unsigned_pinned_bundle_still_needs_its_hash_entry(rel: Release) -> None:
    rel.sig.unlink()
    rel.sums.write_text(f"{'0' * 64}  ./{TARBALL}\n")
    r = rel.verify(pin_this_tarball=True, version="0.4.6")
    _refused(r)
    assert "SHA256 mismatch" in r.stdout


def test_an_unsigned_bundle_that_is_not_pinned_is_refused(rel: Release) -> None:
    rel.sig.unlink()
    r = rel.verify(version="0.4.6")
    _refused(r)
    assert "releases from v0.4.7 on are signed; refusing an unsigned bundle" in r.stdout
    assert "SHA256 checksum verified" not in r.stdout


def test_a_release_without_sums_is_refused(rel: Release) -> None:
    rel.sums.unlink()
    r = rel.verify()
    _refused(r)
    assert "No SHA256SUMS" in r.stdout


def test_openssl_before_3_is_refused_with_the_found_version(rel: Release) -> None:
    rel.fake_openssl("OpenSSL 1.1.1w  11 Sep 2023")
    r = rel.verify()
    _refused(r)
    assert "OpenSSL 3 is required" in r.stdout
    assert "1.1.1w" in r.stdout


def test_no_openssl_at_all_is_refused(rel: Release) -> None:
    rel.fake_openssl("")
    r = rel.verify()
    _refused(r)
    assert "OpenSSL 3 is required" in r.stdout


# ── Wiring: the real func_do_install lines, run against fake curl and pct ────


def _install_segment() -> str:
    """func_do_install from the host temp dir to the in-container extraction."""
    body = _function("func_do_install")
    seg = re.search(r"^  local host_release_dir\n.*?^  pct exec \"\$CTID\" -- bash -c \"mkdir -p /tmp/cb-bundle[^\n]*\n",
                    body, re.MULTILINE | re.DOTALL)
    assert seg, "release download/push segment not found in func_do_install"
    return seg.group(0)


def test_verification_sits_between_download_and_push() -> None:
    body = _function("func_do_install")
    download = body.index('download_release_files "$host_release_dir" "$release_json" "$tarball_name"')
    verify = body.index('verify_release_files "$host_release_dir" "$tarball_name" "$cb_version"')
    push = body.index('push_release_files "$CTID" "$host_release_dir"')
    assert download < verify < push
    assert "pct " not in body[download:verify], "nothing may reach the container before verification"


def _run_install_segment(rel: Release, tmp: Path) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
    assets = tmp / "assets"
    assets.mkdir()
    for f in rel.dir.iterdir():
        (assets / f.name).write_bytes(f.read_bytes())
    release = {"tag_name": "v0.4.7", "assets": [
        {"name": f.name, "browser_download_url": f"https://dl.invalid/{f.name}"} for f in assets.iterdir()]}
    rel._exe("curl", f"""#!/bin/sh
out=""; url=""
while [ $# -gt 0 ]; do
  case "$1" in -o) out="$2"; shift 2 ;; http*) url="$1"; shift ;; *) shift ;; esac
done
cp "{assets}/$(basename "$url")" "$out"
""")
    pct_log = tmp / "pct.log"
    container = tmp / "container"
    container.mkdir()
    rel._exe("pct", f"""#!/bin/sh
echo "$@" >> "{pct_log}"
case "$1" in
  exec) shift 3; [ "$1" = mkdir ] && mkdir -p "{container}$3" ;;
  push) cp "$3" "{container}$4" ;;
esac
exit 0
""")
    hostdirs = tmp / "hostdirs"
    hostdirs.mkdir()
    script = "\n".join([
        STUBS,
        _constant("CB_GITHUB_REPO"),
        _constant("CB_CT_RELEASE_DIR"),
        _library(),
        f'_cb_embedded_release_keys() {{ cat "{rel.keys}"; }}',
        _function("download_release_files"),
        _function("push_release_files"),
        _function("release_verify_fail"),
        _function("verify_release_files"),
        "segment() {",
        f"  local release_json='{json.dumps(release)}'",
        f'  local tarball_name="{TARBALL}" cb_version="0.4.7" CTID=101',
        _install_segment(),
        "  echo EXTRACT_REACHED",
        "}",
        "segment",
        'echo "RC=$?"',
    ])
    env = {**os.environ, "PATH": f"{rel.bin}:{os.environ['PATH']}", "TMPDIR": str(hostdirs)}
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env, check=False)
    return r, pct_log, hostdirs


def test_a_verified_bundle_is_pushed_and_extracted(rel: Release, tmp_path: Path) -> None:
    r, pct_log, hostdirs = _run_install_segment(rel, tmp_path)
    assert "RC=0" in r.stdout, r.stdout + r.stderr
    assert "EXTRACT_REACHED" in r.stdout
    assert "push 101" in pct_log.read_text()
    assert list(hostdirs.iterdir()) == [], "the host temp dir is removed"


def test_a_tampered_bundle_never_reaches_the_container(rel: Release, tmp_path: Path) -> None:
    rel.tarball.write_bytes(b"evil")
    r, pct_log, hostdirs = _run_install_segment(rel, tmp_path)
    assert "RC=1" in r.stdout, r.stdout + r.stderr
    assert "SHA256 mismatch" in r.stdout
    assert "EXTRACT_REACHED" not in r.stdout
    assert not pct_log.exists(), "pct must not run for a bundle that failed verification"
    assert list(hostdirs.iterdir()) == [], "the host temp dir is removed on failure too"
