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


def test_openssl_before_3_refuses_a_signed_bundle_naming_pve_8(rel: Release) -> None:
    rel.fake_openssl("OpenSSL 1.1.1w  11 Sep 2023")
    r = rel.verify()
    _refused(r)
    assert "OpenSSL 3 is required" in r.stdout
    assert "1.1.1w" in r.stdout
    assert "Proxmox VE 8 or newer" in r.stdout
    assert "apt-get install openssl" not in r.stdout


def test_no_openssl_at_all_refuses_a_signed_bundle(rel: Release) -> None:
    rel.fake_openssl("")
    r = rel.verify()
    _refused(r)
    assert "OpenSSL 3 is required" in r.stdout


def test_openssl_1_1_still_installs_the_pinned_unsigned_v046(rel: Release) -> None:
    """PVE 7 ships OpenSSL 1.1.1; the unsigned v0.4.6 needs no signature check."""
    rel.fake_openssl("OpenSSL 1.1.1w  11 Sep 2023")
    rel.sig.unlink()
    r = rel.verify(pin_this_tarball=True, version="0.4.6")
    _ok(r)
    assert "predates bundle signing" in r.stdout
    assert "SHA256 checksum verified" in r.stdout


# ── Wiring: the real func_do_install, run against fake PVE tools ─────────────


def test_the_release_is_verified_before_anything_is_created() -> None:
    body = _function("func_do_install")
    download = body.index('download_release_files "$host_release_dir" "$release_json" "$tarball_name"')
    verify = body.index('verify_release_files "$host_release_dir" "$tarball_name" "$cb_version"')
    template = body.index("pveam update")
    create = body.index('"${PCT_CMD[@]}"')
    push = body.index('push_release_files "$CTID" "$host_release_dir"')
    assert body.index('"${CB_RELEASE_API}/latest"') < download < verify < template < create < push
    assert "pct " not in body[:verify], "nothing may touch a container before verification"
    assert "pveam " not in body[:verify], "no template is fetched for a release that will be refused"


class Pve:
    """Fake curl, pct and pveam on PATH, logging what the helper asked of them."""

    def __init__(self, rel: Release, tmp: Path, *, assets: tuple[str, ...] | None = None,
                 release_api_fails: bool = False, create_fails: bool = False,
                 no_template: bool = False) -> None:
        self.rel = rel
        self.assets = tmp / "assets"
        self.assets.mkdir()
        for f in rel.dir.iterdir():
            if assets is None or f.name in assets:
                (self.assets / f.name).write_bytes(f.read_bytes())
        release = {"tag_name": "v0.4.7", "assets": [
            {"name": f.name, "browser_download_url": f"https://dl.invalid/{f.name}"}
            for f in self.assets.iterdir()]}
        (tmp / "release.json").write_text(json.dumps(release))
        # No -o: the /latest release JSON. -o <file> <url>: the asset.
        rel._exe("curl", f"""#!/bin/sh
out=""; url=""
while [ $# -gt 0 ]; do
  case "$1" in -o) out="$2"; shift 2 ;; http*) url="$1"; shift ;; *) shift ;; esac
done
[ -n "$out" ] || {{ {"exit 22" if release_api_fails else f'cat "{tmp}/release.json"; exit 0'}; }}
cp "{self.assets}/$(basename "$url")" "$out"
""")
        self.log = tmp / "pve.log"
        self.container = tmp / "container"
        self.container.mkdir()
        # The apt-get step fails on purpose: it ends the run right after the
        # push and extraction, before anything writes outside tmp_path.
        rel._exe("pct", f"""#!/bin/sh
echo "pct $@" >> "{self.log}"
case "$1" in
  create) exit {1 if create_fails else 0} ;;
  exec) shift 3
        case "$*" in *apt-get*) exit 1 ;; esac
        [ "$1" = mkdir ] && mkdir -p "{self.container}$3" ;;
  push) cp "$3" "{self.container}$4" ;;
esac
exit 0
""")
        rel._exe("pveam", f"""#!/bin/sh
echo "pveam $@" >> "{self.log}"
[ "$1" = available ] && {{ {"exit 0" if no_template else "echo 'system debian-12-standard_12.7-1_amd64.tar.zst'"}; }}
exit 0
""")
        rel._exe("pvesm", f'#!/bin/sh\necho "pvesm $@" >> "{self.log}"\nexit 0\n')
        rel._exe("uname", '#!/bin/sh\n[ "$1" = -m ] && echo x86_64 || echo Linux\n')
        self.hostdirs = tmp / "hostdirs"
        self.hostdirs.mkdir()

    def run(self) -> subprocess.CompletedProcess[str]:
        rel = self.rel
        script = "\n".join([
            STUBS,
            "clear() { :; }",
            # Only the "Press Enter" prompts; the library's `while read` loops need the builtin.
            'read() { if [[ "$1" == -rp ]]; then return 0; fi; builtin read "$@"; }',
            "sleep() { :; }",
            "post_create_config() { :; }",
            "post_start_config() { :; }",
            'wait_for_ip() { CT_IP=192.0.2.10; }',
            _constant("CB_GITHUB_REPO"),
            'CB_RELEASE_API="https://api.invalid/releases"',
            _constant("CB_CT_RELEASE_DIR"),
            _library(),
            f'_cb_embedded_release_keys() {{ cat "{rel.keys}"; }}',
            *(_function(n) for n in (
                "detect_template", "build_pct_cmd", "download_release_files", "push_release_files",
                "drop_host_release_dir",
                "release_verify_fail", "verify_release_files", "build_installer_cmd", "func_do_install")),
            "CTID=101 CT_TYPE=1 HN=cb PW=secret CORES=2 RAM=4096 DISK=20 SWAP=512",
            'BRIDGE=vmbr0 IPV4_MODE=dhcp IPV6_MODE=none MTU=1500 STORAGE=local-lvm TEMPLATE_STORAGE=local',
            'CT_TAGS="cb" SSH_KEY_MODE=none ROOT_ACCESS=1 FUSE=0 TUN_TAP=0 NESTING=1 KEYCTL=0 MKNOD=0',
            'PROTECTION=0 VERBOSE=0 INSTALL_MODE=default CB_NO_TLS=true CB_FQDN="" CB_PORT=8088 CB_DOCKER=false',
            'CLEANUP_CTID="" CB_HOST_RELEASE_DIR=""',
            "func_do_install",
            'echo "RC=$? CLEANUP_CTID=$CLEANUP_CTID"',
        ])
        env = {**os.environ, "PATH": f"{rel.bin}:{os.environ['PATH']}", "TMPDIR": str(self.hostdirs)}
        return subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env, check=False)

    def calls(self) -> str:
        return self.log.read_text() if self.log.exists() else ""


def _nothing_created(pve: Pve, r: subprocess.CompletedProcess[str]) -> None:
    assert "RC=1" in r.stdout, r.stdout + r.stderr
    assert "pct " not in pve.calls(), "no container may be created or touched"
    assert "pveam " not in pve.calls(), "no template may be fetched"
    assert re.search(r"^RC=1 CLEANUP_CTID=$", r.stdout, re.MULTILINE), "no container is left for cleanup()"
    assert list(pve.hostdirs.iterdir()) == [], "the host temp dir is removed"


def test_a_tampered_bundle_creates_no_container(rel: Release, tmp_path: Path) -> None:
    rel.tarball.write_bytes(b"evil")
    pve = Pve(rel, tmp_path)
    r = pve.run()
    assert "SHA256 mismatch" in r.stdout
    _nothing_created(pve, r)


def test_an_unsigned_unpinned_release_creates_no_container(rel: Release, tmp_path: Path) -> None:
    pve = Pve(rel, tmp_path, assets=(TARBALL, "SHA256SUMS"))
    r = pve.run()
    assert "refusing an unsigned bundle" in r.stdout
    _nothing_created(pve, r)


def test_a_failed_download_creates_no_container(rel: Release, tmp_path: Path) -> None:
    pve = Pve(rel, tmp_path, assets=(TARBALL,))
    r = pve.run()
    assert "SHA256SUMS not found in the release" in r.stdout
    _nothing_created(pve, r)


def test_an_unreachable_release_api_creates_no_container(rel: Release, tmp_path: Path) -> None:
    pve = Pve(rel, tmp_path, release_api_fails=True)
    r = pve.run()
    assert "Failed to fetch latest release" in r.stdout
    _nothing_created(pve, r)


def test_a_verified_bundle_is_created_then_pushed_and_the_host_dir_removed(rel: Release, tmp_path: Path) -> None:
    pve = Pve(rel, tmp_path)
    r = pve.run()
    assert "Signature verified" in r.stdout, r.stdout + r.stderr
    calls = pve.calls()
    assert "pct create 101" in calls
    assert calls.index("pct create 101") < calls.index("pct push 101")
    assert sorted(p.name for p in (pve.container / "tmp" / "cb-release").iterdir()) == sorted(
        [TARBALL, "SHA256SUMS", "SHA256SUMS.sig"])
    assert "tar -xzf" in calls
    assert list(pve.hostdirs.iterdir()) == []


def test_a_failed_pct_create_still_removes_the_host_dir(rel: Release, tmp_path: Path) -> None:
    pve = Pve(rel, tmp_path, create_fails=True)
    r = pve.run()
    assert "pct create failed" in r.stdout, r.stdout + r.stderr
    assert "pct push" not in pve.calls()
    assert list(pve.hostdirs.iterdir()) == []


def test_a_missing_template_still_removes_the_host_dir(rel: Release, tmp_path: Path) -> None:
    pve = Pve(rel, tmp_path, no_template=True)
    r = pve.run()
    assert "No Debian 12 template found" in r.stdout, r.stdout + r.stderr
    assert "pct " not in pve.calls()
    assert list(pve.hostdirs.iterdir()) == []


def test_an_interrupt_removes_the_host_dir_too() -> None:
    """The EXIT/INT trap's cleanup() must know the host temp dir."""
    assert 'CB_HOST_RELEASE_DIR="$host_release_dir"' in _function("func_do_install")
    assert "drop_host_release_dir" in _function("cleanup")
    assert 'rm -rf -- "$CB_HOST_RELEASE_DIR"' in _function("drop_host_release_dir")
