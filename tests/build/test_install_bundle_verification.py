"""install.sh's bundle verification, row by row of the design's behaviour table.

install.sh runs `main` at import time, so the verification functions and the
inlined library are extracted and eval'd in a clean bash, with the UI helpers
stubbed to plain lines. Keys are throwaway, generated per test.
"""

from __future__ import annotations

import hashlib
import json
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


PINNED_V046 = {
    "CB_UNSIGNED_PIN_AMD64": "377a62236a792df994e63c54fef38aca2ab76b38246fd4de33b913514f7a35d5"
                             "  circuit-breaker_0.4.6_linux_amd64.tar.gz",
    "CB_UNSIGNED_PIN_ARM64": "1c93f507cbac803da6dc6fd0ef3da62083ef87b09bcba3531b7bd61a1624c93f"
                             "  circuit-breaker_0.4.6_linux_arm64.tar.gz",
}


def _unsigned_pins() -> str:
    """install.sh's CB_UNSIGNED_PIN_* assignments, verbatim."""
    lines = re.findall(r'^CB_UNSIGNED_PIN_[A-Z0-9]+="[^"]*"$', INSTALL_SH.read_text(), re.MULTILINE)
    assert lines, "CB_UNSIGNED_PIN_* assignments not found in install.sh"
    return "\n".join(lines)


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
              airgap: bool = True, keys: Path | None = None, explicit: bool = False,
              pin_this_tarball: bool = False) -> subprocess.CompletedProcess[str]:
        # The real pins name the v0.4.6 bundles; a test that needs a pinned
        # tarball repoints one pin at its own throwaway tarball, after the
        # real assignments, so they are still exercised everywhere else.
        own_pin = (f'CB_UNSIGNED_PIN_AMD64="{hashlib.sha256(self.tarball.read_bytes()).hexdigest()}'
                   f'  {self.tarball.name}"') if pin_this_tarball else ""
        script = "\n".join([
            "set -euo pipefail",
            STUBS,
            _library(),
            f'_cb_embedded_release_keys() {{ cat "{keys or self.keys}"; }}',
            f"SKIP_CHECKSUM={'true' if skip_checksum else 'false'}",
            f"SKIP_SIGNATURE={'true' if skip_signature else 'false'}",
            _unsigned_pins(),
            own_pin,
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


def test_the_pinned_v046_bundle_is_accepted_unsigned_and_its_hash_checked(s: Setup) -> None:
    r = s.check(str(s.sums), "", "download", "0.4.6", pin_this_tarball=True)
    assert r.returncode == 0, r.stdout
    assert "predates bundle signing" in r.stdout
    assert "SHA256 checksum verified" in r.stdout


def test_a_pinned_bundle_still_fails_a_mismatching_sums_entry(s: Setup) -> None:
    r = s.check(str(s.sums), "", "download", "0.4.6", pin_this_tarball=True)
    assert r.returncode == 0, r.stdout
    s.sums.write_text(f"{'0' * 64}  ./{TARBALL}\n")
    r = s.check(str(s.sums), "", "download", "0.4.6", pin_this_tarball=True)
    assert r.returncode == 1
    assert "SHA256 mismatch" in r.stdout


def test_a_forged_unsigned_v046_is_refused_on_the_default_path(s: Setup) -> None:
    """The tag says 0.4.6 but the bytes are not the published v0.4.6 bundle."""
    r = s.check(str(s.sums), "", "download", "0.4.6")
    assert r.returncode == 1
    assert "publishes no SHA256SUMS.sig" in r.stdout
    assert "genuine v0.4.6 bundle" in r.stdout


def test_the_pins_are_the_published_v046_hashes() -> None:
    """Copied from v0.4.6's SHA256SUMS; one per architecture the installer supports."""
    text = INSTALL_SH.read_text()
    for name, value in PINNED_V046.items():
        assert f'{name}="{value}"' in text
    assert "CB_LAST_UNSIGNED_RELEASE" not in text, "the version-string exception must not come back"
    assert '"$CB_UNSIGNED_PIN_AMD64" "$CB_UNSIGNED_PIN_ARM64"' in _function("cb_unsigned_release_allowed")


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


def test_default_path_refuses_an_older_unsigned_release(s: Setup) -> None:
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


def test_v_prefixed_versions_are_never_accepted_unsigned_by_version(s: Setup) -> None:
    """Tag vv0.4.6 (or --version vv0.4.3) leaves a v after the single strip."""
    assert s.check(str(s.sums), "", "download", "v0.4.6").returncode == 1
    assert s.check(str(s.sums), "", "download", "v0.4.3", explicit=True).returncode == 1
    assert s.check(str(s.sums), "", "download", "0.4.6").returncode == 1
    assert s.check(str(s.sums), "", "download", "0.4.6", pin_this_tarball=True).returncode == 0


def test_explicit_version_with_a_v_is_normalised_at_parse() -> None:
    """`--version v0.4.5` must query tags/v0.4.5, not tags/vv0.4.5."""
    arm = re.search(r"^    --version\)\n(.*?)^      ;;$", INSTALL_SH.read_text(), re.MULTILINE | re.DOTALL)
    assert arm, "--version) arm not found in install.sh's parser"
    script = "\n".join([
        "set -euo pipefail", 'CB_VERSION=""', "CB_VERSION_EXPLICIT=false",
        'while [[ $# -gt 0 ]]; do', 'case "$1" in', "--version)", arm.group(1), ";;", "esac", "done",
        'echo "V=$CB_VERSION E=$CB_VERSION_EXPLICIT"',
    ])
    for given, want in (("v0.4.5", "0.4.5"), ("0.4.5", "0.4.5"), ("vv0.4.5", "v0.4.5")):
        r = subprocess.run(["bash", "-c", script, "bash", "--version", given], capture_output=True, text=True)
        assert r.stdout.strip() == f"V={want} E=true", r.stdout + r.stderr


def _bundle_tarball(path: Path) -> None:
    """A minimal PBS-layout bundle: the two executables the extractor checks."""
    src = path.parent / "src"
    for rel in ("bin/circuit-breaker", "python/bin/python3"):
        f = src / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("#!/bin/sh\n")
        f.chmod(0o755)
    subprocess.run(["tar", "-czf", str(path), "-C", str(src), "."], check=True)


DOWNLOAD_STUBS = STUBS + """
cb_section() { :; }
cb_progress() { :; }
cb_check_bundle() { echo "CHECK $1 | $2 | $3 | $4 | $5"; }
"""


def _run_download_stage(tmp: Path, local_bundle: str, curl_body: str) -> subprocess.CompletedProcess[str]:
    bindir = tmp / "bin"
    bindir.mkdir(exist_ok=True)
    curl = bindir / "curl"
    curl.write_text(curl_body)
    curl.chmod(0o755)
    script = "\n".join([
        "set -euo pipefail", DOWNLOAD_STUBS,
        f'TMPDIR="{tmp / "tmp"}"', "export TMPDIR",
        'CB_VERSION="0.4.7"', f'CB_LOCAL_BUNDLE="{local_bundle}"', 'ARCH="amd64"',
        'CB_RELEASE_API="https://api.invalid/releases"', 'CB_GITHUB_REPO="BlkLeg/CircuitBreaker"',
        "SKIP_CHECKSUM=false", "SKIP_SIGNATURE=false", 'CB_PRIVATE_TMP=""',
        'CB_BUNDLE_TARBALL=""', 'CB_BUNDLE_DIR=""',
        _function("cb_fetch_release_asset"),
        _function("stage0_download_bundle"),
        "stage0_download_bundle",
        'echo "PRIVATE=$CB_PRIVATE_TMP"', 'echo "DIR=$CB_BUNDLE_DIR"', 'echo "TARBALL=$CB_BUNDLE_TARBALL"',
        'stat -c "MODE=%a" "$CB_PRIVATE_TMP"',
        'ls "$CB_BUNDLE_DIR/bin/circuit-breaker" >/dev/null && echo EXTRACTED',
    ])
    (tmp / "tmp").mkdir(exist_ok=True)
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}"}
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env)


def _vars(stdout: str) -> dict[str, str]:
    return dict(line.split("=", 1) for line in stdout.splitlines() if "=" in line and not line.startswith("CHECK"))


def test_a_downloaded_bundle_lives_and_is_extracted_in_a_private_dir(tmp_path: Path) -> None:
    assets = tmp_path / "assets"
    assets.mkdir()
    _bundle_tarball(assets / TARBALL)
    (assets / "SHA256SUMS").write_text("sums\n")
    (assets / "SHA256SUMS.sig").write_text("sig\n")
    release = {"tag_name": "v0.4.7", "assets": [
        {"name": n, "size": (assets / n).stat().st_size, "browser_download_url": f"https://dl.invalid/{n}"}
        for n in (TARBALL, "SHA256SUMS", "SHA256SUMS.sig")]}
    (assets / "release.json").write_text(json.dumps(release))
    # Fake curl: `-o <file> <url>` copies the asset named by the URL; no -o
    # prints the release JSON.
    curl = f"""#!/bin/sh
out=""; url=""
while [ $# -gt 0 ]; do
  case "$1" in -o) out="$2"; shift 2 ;; http*) url="$1"; shift ;; *) shift ;; esac
done
if [ -n "$out" ]; then cp "{assets}/$(basename "$url")" "$out"; else cat "{assets}/release.json"; fi
"""
    r = _run_download_stage(tmp_path, "", curl)
    assert r.returncode == 0, r.stdout + r.stderr
    v = _vars(r.stdout)
    private = v["PRIVATE"]
    assert private.startswith(str(tmp_path / "tmp") + "/"), private
    assert v["MODE"] == "700"
    assert v["TARBALL"] == f"{private}/{TARBALL}"
    assert v["DIR"] == f"{private}/bundle"
    assert "EXTRACTED" in r.stdout
    assert f"CHECK {private}/{TARBALL} | {private}/SHA256SUMS | {private}/SHA256SUMS.sig | download | 0.4.7" in r.stdout


def test_a_local_bundle_is_extracted_in_a_private_dir_and_left_in_place(tmp_path: Path) -> None:
    local = tmp_path / "operator" / TARBALL
    local.parent.mkdir()
    _bundle_tarball(local)
    r = _run_download_stage(tmp_path, str(local), "#!/bin/sh\nexit 99\n")
    assert r.returncode == 0, r.stdout + r.stderr
    v = _vars(r.stdout)
    assert v["PRIVATE"].startswith(str(tmp_path / "tmp") + "/")
    assert v["MODE"] == "700"
    assert v["DIR"] == f"{v['PRIVATE']}/bundle"
    assert v["TARBALL"] == str(local)
    assert "EXTRACTED" in r.stdout


def test_no_fixed_tmp_bundle_paths_remain_and_install_removes_the_private_dir() -> None:
    for name in ("stage0_download_bundle", "stage0_install_bundle"):
        body = _function(name)
        assert "/tmp/cb-bundle" not in body
        assert "/tmp/${tarball_name}" not in body
    install = _function("stage0_install_bundle")
    assert 'rm -rf -- "$CB_PRIVATE_TMP"' in install
    assert 'rm -f "$CB_BUNDLE_TARBALL"' not in install, "a --local-bundle tarball is the operator's file"
    # The check must not drop the directory the tarball and tree live in.
    download = _function("stage0_download_bundle")
    assert 'rm -rf -- "$CB_PRIVATE_TMP"' not in download
