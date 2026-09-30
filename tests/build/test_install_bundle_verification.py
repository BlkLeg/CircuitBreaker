"""install.sh's bundle verification, row by row of the design's behaviour table.

install.sh runs `main` at import time, so the verification functions and the
inlined library are extracted and eval'd in a clean bash, with the UI helpers
stubbed to plain lines. Keys are throwaway, generated per test.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
INSTALL_SH = ROOT / "install.sh"
KEYGEN = ROOT / "scripts" / "release_signing_key.sh"
SIGN = ROOT / "scripts" / "ci" / "sign_release_sums.sh"
TARBALL = "circuit-breaker_0.4.7_linux_amd64.tar.gz"
BEGIN = "# --- BEGIN INLINED deploy/lib/bundle-signature.sh"
END = "# --- END INLINED deploy/lib/bundle-signature.sh ---"


def _function(name: str) -> str:
    body = re.search(rf"^{name}\(\) \{{\n.*?^\}}$", INSTALL_SH.read_text(), re.MULTILINE | re.DOTALL)
    assert body, f"{name}() not found in install.sh"
    return body.group(0)


def _last_unsigned() -> str:
    line = re.search(r'^CB_LAST_UNSIGNED_RELEASE="[^"]*"$', INSTALL_SH.read_text(), re.MULTILINE)
    assert line, "CB_LAST_UNSIGNED_RELEASE assignment not found in install.sh"
    return line.group(0)


def _library() -> str:
    text = INSTALL_SH.read_text()
    return text[text.index(BEGIN) : text.index(END)]


STUBS = """
cb_fail() { echo "FAIL: $1 | ${2:-}"; exit 1; }
cb_warn() { echo "WARN: $1"; }
cb_ok()   { echo "OK: $1"; }
cb_step() { :; }
"""


class Setup:
    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.key = tmp / "k.pem"
        line = subprocess.run(["bash", str(KEYGEN), str(self.key), "0.4.7", "t"],
                              capture_output=True, text=True, check=True).stdout
        self.key_id = line.split()[0]
        self.keys = tmp / "keys.txt"
        self.keys.write_text(line)
        self.tarball = tmp / TARBALL
        self.tarball.write_bytes(b"bundle")
        self.sums = tmp / "SHA256SUMS"
        self.sums.write_text(f"{hashlib.sha256(b'bundle').hexdigest()}  ./{TARBALL}\n")
        self.sig = tmp / "SHA256SUMS.sig"
        subprocess.run(["bash", str(SIGN), str(self.key), str(self.sums), str(self.sig)], check=True)
        self.bin = tmp / "bin"
        self.bin.mkdir()

    def fake_gh(self, verify_exit: int) -> Path:
        log = self.tmp / "gh.log"
        gh = self.bin / "gh"
        gh.write_text(f'#!/bin/sh\necho "$@" >> "{log}"\n'
                      f'case "$1" in auth) exit 0 ;; attestation) exit {verify_exit} ;; esac\n')
        gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
        return log

    def check(self, sums: str, sig: str, origin: str, version: str, *,
              skip_checksum: bool = False, skip_signature: bool = False,
              airgap: bool = True, keys: Path | None = None, explicit: bool = False) -> subprocess.CompletedProcess[str]:
        script = "\n".join([
            "set -euo pipefail",
            STUBS,
            _library(),
            f'_cb_embedded_release_keys() {{ cat "{keys or self.keys}"; }}',
            f"SKIP_CHECKSUM={'true' if skip_checksum else 'false'}",
            f"SKIP_SIGNATURE={'true' if skip_signature else 'false'}",
            _last_unsigned(),
            f"CB_VERSION_EXPLICIT={'true' if explicit else 'false'}",
            f"CB_AIRGAP={'true' if airgap else 'false'}",
            'CB_GITHUB_REPO="BlkLeg/CircuitBreaker"',
            _function("cb_check_attestation"),
            _function("cb_unsigned_release_allowed"),
            _function("cb_check_bundle"),
            'cb_check_bundle "$1" "$2" "$3" "$4" "$5"',
        ])
        env = {**os.environ, "PATH": f"{self.bin}:{os.environ['PATH']}"}
        return subprocess.run(["bash", "-c", script, "bash", str(self.tarball), sums, sig, origin, version],
                              capture_output=True, text=True, env=env)


@pytest.fixture
def s(tmp_path: Path) -> Setup:
    return Setup(tmp_path)


def test_download_signed_release_verifies_signature_then_hash(s: Setup) -> None:
    r = s.check(str(s.sums), str(s.sig), "download", "0.4.7")
    assert r.returncode == 0, r.stdout + r.stderr
    assert f"Signature verified (key {s.key_id})" in r.stdout
    assert r.stdout.index("Signature verified") < r.stdout.index("SHA256 checksum verified")


def test_download_signed_release_without_a_signature_fails_closed(s: Setup) -> None:
    r = s.check(str(s.sums), "", "download", "0.4.7")
    assert r.returncode == 1
    assert "publishes no SHA256SUMS.sig" in r.stdout


def test_download_with_a_tampered_sums_file_fails(s: Setup) -> None:
    s.sums.write_text(s.sums.read_text() + "0" * 64 + "  ./extra\n")
    r = s.check(str(s.sums), str(s.sig), "download", "0.4.7")
    assert r.returncode == 1
    assert "signature does not verify" in r.stdout
    assert s.key_id in r.stdout


def test_download_with_a_tampered_tarball_fails_after_the_signature(s: Setup) -> None:
    s.tarball.write_bytes(b"evil")
    r = s.check(str(s.sums), str(s.sig), "download", "0.4.7")
    assert r.returncode == 1
    assert "Signature verified" in r.stdout
    assert "SHA256 mismatch" in r.stdout


def test_a_signature_by_an_unknown_key_fails(s: Setup, tmp_path: Path) -> None:
    other = tmp_path / "other.pem"
    subprocess.run(["bash", str(KEYGEN), str(other), "0.4.7"], capture_output=True, check=True)
    subprocess.run(["bash", str(SIGN), str(other), str(s.sums), str(s.sig)], check=True)
    r = s.check(str(s.sums), str(s.sig), "download", "0.4.7")
    assert r.returncode == 1
    assert "signature does not verify" in r.stdout


def test_an_installer_that_trusts_no_keys_fails_closed(s: Setup, tmp_path: Path) -> None:
    empty = tmp_path / "empty.txt"
    empty.write_text("# no keys yet\n")
    r = s.check(str(s.sums), str(s.sig), "download", "0.4.7", keys=empty)
    assert r.returncode == 1
    assert "trusts no release keys" in r.stdout


def test_an_unreadable_signature_file_fails(s: Setup) -> None:
    s.sig.write_text("garbage\n")
    r = s.check(str(s.sums), str(s.sig), "download", "0.4.7")
    assert r.returncode == 1
    assert "SHA256SUMS.sig is unreadable" in r.stdout


def test_a_release_before_signing_warns_and_checks_the_hash(s: Setup) -> None:
    r = s.check(str(s.sums), "", "download", "0.4.6")
    assert r.returncode == 0, r.stdout
    assert "predates bundle signing" in r.stdout
    assert "SHA256 checksum verified" in r.stdout


def test_a_download_without_sums_fails(s: Setup) -> None:
    r = s.check("", "", "download", "0.4.6")
    assert r.returncode == 1
    assert "No SHA256SUMS" in r.stdout


def test_local_bundle_with_both_files_must_verify(s: Setup) -> None:
    assert s.check(str(s.sums), str(s.sig), "local", "").returncode == 0
    s.sums.write_text(s.sums.read_text() + "\n")
    assert s.check(str(s.sums), str(s.sig), "local", "").returncode == 1


def test_local_bundle_with_only_sums_warns_and_checks_the_hash(s: Setup) -> None:
    r = s.check(str(s.sums), "", "local", "")
    assert r.returncode == 0
    assert "No SHA256SUMS.sig next to the bundle" in r.stdout
    assert "SHA256 checksum verified" in r.stdout


def test_local_bundle_with_neither_file_warns_and_continues(s: Setup) -> None:
    r = s.check("", "", "local", "")
    assert r.returncode == 0
    assert "UNVERIFIED" in r.stdout


def test_local_bundle_with_a_signature_but_no_sums_fails(s: Setup) -> None:
    r = s.check("", str(s.sig), "local", "")
    assert r.returncode == 1


def test_skip_signature_still_checks_the_hash(s: Setup) -> None:
    s.sig.write_text("garbage\n")
    r = s.check(str(s.sums), str(s.sig), "download", "0.4.7", skip_signature=True)
    assert r.returncode == 0
    assert "--skip-signature" in r.stdout
    s.tarball.write_bytes(b"evil")
    assert s.check(str(s.sums), str(s.sig), "download", "0.4.7", skip_signature=True).returncode == 1


def test_skip_checksum_skips_both_with_a_warning(s: Setup) -> None:
    s.tarball.write_bytes(b"evil")
    r = s.check(str(s.sums), str(s.sig), "download", "0.4.7", skip_checksum=True)
    assert r.returncode == 0
    assert "--skip-checksum" in r.stdout


def test_a_renamed_local_bundle_names_the_expected_file(s: Setup) -> None:
    renamed = s.tmp / f"{TARBALL[:-7]}(1).tar.gz"
    s.tarball.rename(renamed)
    s.tarball = renamed
    r = s.check(str(s.sums), str(s.sig), "local", "")
    assert r.returncode == 1
    assert "not listed" in r.stdout
    assert renamed.name in r.stdout


def test_sums_signed_for_another_release_do_not_cover_this_tarball(s: Setup) -> None:
    other = "circuit-breaker_0.4.8_linux_amd64.tar.gz"
    s.sums.write_text(f"{hashlib.sha256(b'bundle').hexdigest()}  ./{other}\n")
    subprocess.run(["bash", str(SIGN), str(s.key), str(s.sums), str(s.sig)], check=True)
    r = s.check(str(s.sums), str(s.sig), "download", "0.4.7")
    assert r.returncode == 1
    assert "not listed" in r.stdout


def test_attestation_is_checked_online_when_gh_is_available(s: Setup) -> None:
    log = s.fake_gh(verify_exit=0)
    r = s.check(str(s.sums), str(s.sig), "download", "0.4.7", airgap=False)
    assert r.returncode == 0
    assert "Build provenance verified" in r.stdout
    assert "attestation verify" in log.read_text()
    assert "--repo BlkLeg/CircuitBreaker" in log.read_text()


def test_a_failed_attestation_warns_but_does_not_block(s: Setup) -> None:
    s.fake_gh(verify_exit=1)
    r = s.check(str(s.sums), str(s.sig), "download", "0.4.7", airgap=False)
    assert r.returncode == 0
    assert "Build provenance could not be verified" in r.stdout


def test_air_gap_never_calls_gh(s: Setup) -> None:
    log = s.fake_gh(verify_exit=0)
    r = s.check(str(s.sums), str(s.sig), "local", "", airgap=True)
    assert r.returncode == 0
    assert "not checked (air-gapped)" in r.stdout
    assert not log.exists()


def test_the_option_is_parsed_and_documented() -> None:
    text = INSTALL_SH.read_text()
    assert re.search(r"^\s+--skip-signature\)\n\s+SKIP_SIGNATURE=true", text, re.MULTILINE)
    assert "--skip-signature" in _function("show_help")
    assert re.search(r"^SKIP_SIGNATURE=false$", text, re.MULTILINE)


def test_default_path_accepts_only_the_last_unsigned_release(s: Setup) -> None:
    r = s.check(str(s.sums), "", "download", "0.4.3")
    assert r.returncode == 1
    assert "publishes no SHA256SUMS.sig" in r.stdout
    assert "--version" in r.stdout and "--skip-signature" in r.stdout


def test_explicit_version_below_the_first_signed_release_may_be_unsigned(s: Setup) -> None:
    r = s.check(str(s.sums), "", "download", "0.4.3", explicit=True)
    assert r.returncode == 0, r.stdout
    assert "predates bundle signing" in r.stdout
    assert "SHA256 checksum verified" in r.stdout


@pytest.mark.parametrize("version", ["0.4.6.1", "00.4.7", "0.4.6-rc.1", ""])
@pytest.mark.parametrize("explicit", [False, True])
def test_a_non_canonical_version_is_never_accepted_unsigned(s: Setup, version: str, explicit: bool) -> None:
    r = s.check(str(s.sums), "", "download", version, explicit=explicit)
    assert r.returncode == 1
    assert "publishes no SHA256SUMS.sig" in r.stdout


def test_explicit_version_at_or_above_the_first_signed_release_still_needs_a_signature(s: Setup) -> None:
    assert s.check(str(s.sums), "", "download", "0.4.7", explicit=True).returncode == 1


def test_openssl_before_3_fails_with_the_found_version(s: Setup) -> None:
    openssl = s.bin / "openssl"
    openssl.write_text('#!/bin/sh\n[ "$1" = version ] && echo "OpenSSL 1.1.1w  11 Sep 2023"\nexit 1\n')
    openssl.chmod(openssl.stat().st_mode | stat.S_IEXEC)
    r = s.check(str(s.sums), str(s.sig), "download", "0.4.7")
    assert r.returncode == 1
    assert "OpenSSL 3 is required to verify the release signature" in r.stdout
    assert "1.1.1w" in r.stdout


def test_an_unreachable_sums_download_stops_the_install(s: Setup) -> None:
    curl = s.bin / "curl"
    curl.write_text("#!/bin/sh\nexit 22\n")
    curl.chmod(curl.stat().st_mode | stat.S_IEXEC)
    release = '{"assets":[{"name":"SHA256SUMS","browser_download_url":"https://example.invalid/SHA256SUMS"}]}'
    script = "\n".join([
        "set -euo pipefail", STUBS, 'CB_VERSION=0.4.7',
        _function("cb_fetch_release_asset"),
        f"cb_fetch_release_asset '{release}' SHA256SUMS \"{s.tmp}\"",
        'echo REACHED',
    ])
    env = {**os.environ, "PATH": f"{s.bin}:{os.environ['PATH']}"}
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env)
    assert r.returncode != 0
    assert "FAIL: Could not download SHA256SUMS" in r.stdout
    assert "REACHED" not in r.stdout


def test_a_release_not_publishing_the_asset_returns_1_without_failing(s: Setup) -> None:
    script = "\n".join([
        "set -euo pipefail", STUBS, 'CB_VERSION=0.4.7', _function("cb_fetch_release_asset"),
        "rc=0", f"cb_fetch_release_asset '{{\"assets\":[]}}' SHA256SUMS \"{s.tmp}\" || rc=$?", 'echo "RC=$rc"',
    ])
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    assert "RC=1" in r.stdout


def test_a_double_v_tag_is_not_read_as_the_last_unsigned_release(s: Setup) -> None:
    """Tag vv0.4.6 leaves CB_VERSION=v0.4.6 after the installer's single strip."""
    assert s.check(str(s.sums), "", "download", "v0.4.6").returncode == 1
    assert s.check(str(s.sums), "", "download", "v0.4.3", explicit=True).returncode == 1
    assert s.check(str(s.sums), "", "download", "0.4.6").returncode == 0
