# Release bundle signing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

Date: 2026-09-30. Status: **Active — planned; no task started.**

**Goal:** Every release from 0.4.7 on carries an Ed25519 signature over `SHA256SUMS` plus GitHub build-provenance attestations. `install.sh` and `install.sh --local-bundle` verify the signature before trusting the hash, fully offline.

**Architecture:**
- **One shell library, `deploy/lib/bundle-signature.sh`, holds the trusted key list and the verification functions.** `release.yml` and `release-dry-run.yml` source it. `install.sh` carries a byte-identical inline copy between markers, kept in sync by the existing `scripts/ci/sync_installer_ui.py`, which is generalised to more than one block, and pinned by a test.
- **The Stage Draft Release job signs the final `SHA256SUMS`.** The private key comes from a new `release-signing` environment. Signing uses a small script shared with the dry run.
- **`promote-verify` and `post-publish` re-verify with the same library.**

**Tech Stack:** bash, OpenSSL 3 (`openssl pkeyutl -rawin`), coreutils, GitHub Actions, `actions/attest-build-provenance`, `gh attestation verify`, pytest (`tests/build`).

**Spec:** [docs/design/2026-09-30-release-bundle-signing-design.md](../docs/design/2026-09-30-release-bundle-signing-design.md), approved 2026-09-30.

## Global Constraints

- **Signature:** detached Ed25519 over `SHA256SUMS`, written as base64 of the raw 64-byte signature on one line, in `SHA256SUMS.sig`.
- **Order is always signature, then hash.** The hash list is trusted only once its signature verifies.
- **Trusted keys:** `deploy/keys/release-bundle-keys.txt`, one per line:
  - format: `<key-id> <base64 raw 32-byte public key> <first-version> <comment>`;
  - key id: the first 16 hex characters of the SHA-256 of the raw public key;
  - `#` lines and blank lines are ignored.
- **Verification tries each trusted key and reports which one verified.** A signature no trusted key verifies is a failure.
- **First signed release: `0.4.7`.** Earlier releases stay installable, with a warning.
- **Key custody:**
  - The private key is `RELEASE_BUNDLE_SIGNING_KEY`, a secret of the `release-signing` environment, whose deployment-branch rule allows `main` only.
  - Only the `release` job ("Stage Draft Release") declares `environment: release-signing`, and only `promote` declares `environment: release`.
  - It is a new key, never the agent update key.
- **Workflow rules that still hold:**
  - no `continue-on-error` and no `always()` on the new steps;
  - every `${{ }}` reaches shell through `env:`, quoted;
  - the key file is created under `umask 077` and deleted in the same step;
  - the key reaches the step only through `env:`.
- **No key material in the repo, tests, workflows or fixtures** (CLAUDE.md). Tests and the dry run generate throwaway keys at run time. Only public key lines are committed.
- **Air gap:** with `CB_AIRGAP=true` the installer makes no network request for verification. Attestation checks are skipped and the signature alone decides.
- **Installer messages** use `cb_fail "<what>" "<what to do>"` and name the file, the key ids tried and the fix.
- **Commits:** prefixes `feat:`/`fix:`/`chore:`/`docs:`/`test:`/`ci:`; attribution trailer only, never a claude.ai link.
- **Do not touch** `.superdesign/` (another agent's uncommitted work) or `CHANGELOG.md`. The changelog's 0.4.7 section arrives with the post-release follow-up PR, and the release captain adds the entry there.

## Review Focus

1. **A trusted key list with no keys.** Until the maintainer commits the first public key line, a ≥ 0.4.7 download must fail closed with "this installer trusts no release keys", not pass or crash. Pinned in Task 4.
2. **A renamed local bundle.** A browser save as `circuit-breaker_0.4.7_linux_amd64(1).tar.gz` must fail with a message naming the expected file name, not "SHA256 mismatch". Pinned in Task 4.
3. **`SHA256SUMS.sig` with CRLF or trailing whitespace.** A copy made through Windows or a mail client must still verify, because the base64 is whitespace-insensitive. Pinned in Task 2.
4. **An air-gapped local install with `gh` on the PATH.** It must never call `gh`. Pinned in Task 4.
5. **A signed `SHA256SUMS` whose tarball entry points at another release** (a real, validly signed `SHA256SUMS` from v0.4.8 next to a v0.4.7 tarball). This must fail, because the hash line is chosen by exact file name. Pinned in Task 4.

---

### Task 1: Release signing key tool

**Files:**
- Create: `scripts/release_signing_key.sh`
- Create: `scripts/ci/sign_release_sums.sh`
- Modify: `Makefile` (a `release-signing-key` target next to `agent-signing-key`, plus the `.PHONY` line)
- Test: `tests/build/test_release_signing_tools.py`

**Interfaces:**
- Produces: `scripts/release_signing_key.sh <private-key-out> <first-version> [comment]`. It writes a PKCS#8 PEM Ed25519 private key at mode 0600 and refuses to overwrite. It prints one trusted-key line on stdout: `<key-id> <b64-pub> <first-version> <comment>`.
- Produces: `scripts/ci/sign_release_sums.sh <private-key-pem> <SHA256SUMS> <out.sig>`. It writes base64 of the raw 64-byte signature plus a newline, and exits non-zero on any failure.

- [ ] **Step 1: Write the failing test**

`tests/build/test_release_signing_tools.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/build/test_release_signing_tools.py -q`
Expected: FAIL, because `scripts/release_signing_key.sh` does not exist.

- [ ] **Step 3: Write the tools**

`scripts/release_signing_key.sh` (`chmod 755`):

```bash
#!/usr/bin/env bash
# Generate the Ed25519 key pair that signs release bundles' SHA256SUMS.
#
#   scripts/release_signing_key.sh <private-key-out> <first-version> [comment]
#
# Writes the private key (PKCS#8 PEM, mode 0600, never overwritten) and prints
# the trusted-key line for deploy/keys/release-bundle-keys.txt:
#   <key-id> <base64 raw 32-byte public key> <first-version> <comment>
# The private key goes to the release-signing environment's
# RELEASE_BUNDLE_SIGNING_KEY secret and an offline backup, then off this disk.
# See docs/release/bundle-signing.md. Never commit it or paste it anywhere.
set -euo pipefail

out="${1:?usage: release_signing_key.sh <private-key-out> <first-version> [comment]}"
first="${2:?usage: release_signing_key.sh <private-key-out> <first-version> [comment]}"
comment="${3:-release bundle key}"

if [[ -e "$out" ]]; then
  echo "refusing to overwrite $out" >&2
  exit 1
fi

# umask before creation: the key must never exist with a wider mode.
(umask 077 && openssl genpkey -algorithm ed25519 -out "$out")
pub="$(openssl pkey -in "$out" -pubout -outform DER | tail -c 32 | base64 -w0)"
key_id="$(printf '%s' "$pub" | base64 -d | sha256sum | cut -c1-16)"
printf '%s %s %s %s\n' "$key_id" "$pub" "$first" "$comment"
```

`scripts/ci/sign_release_sums.sh` (`chmod 755`):

```bash
#!/usr/bin/env bash
# Sign SHA256SUMS with the release bundle key: base64 of the raw 64-byte
# Ed25519 signature, one line. Used by release.yml (real key, from the
# release-signing environment) and release-dry-run.yml (throwaway key).
#
#   scripts/ci/sign_release_sums.sh <private-key-pem> <SHA256SUMS> <out.sig>
set -euo pipefail

key="${1:?usage: sign_release_sums.sh <private-key-pem> <SHA256SUMS> <out.sig>}"
sums="${2:?usage: sign_release_sums.sh <private-key-pem> <SHA256SUMS> <out.sig>}"
out="${3:?usage: sign_release_sums.sh <private-key-pem> <SHA256SUMS> <out.sig>}"

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
openssl pkeyutl -sign -inkey "$key" -rawin -in "$sums" -out "$tmp"
if [[ "$(wc -c < "$tmp")" -ne 64 ]]; then
  echo "sign_release_sums: expected a 64-byte Ed25519 signature" >&2
  exit 1
fi
{ base64 -w0 < "$tmp"; printf '\n'; } > "$out"
```

`Makefile`: add `release-signing-key` to the `.PHONY` line that lists `agent-signing-key`. Add this after the `agent-signing-key` recipe:

```make
release-signing-key: ## Generate the release-bundle Ed25519 key pair (maintainer, once; see docs/release/bundle-signing.md)
	@[ -n "$(OUT)" ] || (echo "usage: make release-signing-key OUT=/path/outside/the/repo/release-bundle.pem FIRST=0.4.7"; exit 1)
	@[ -n "$(FIRST)" ] || (echo "usage: make release-signing-key OUT=... FIRST=<first version this key signs>"; exit 1)
	bash scripts/release_signing_key.sh "$(OUT)" "$(FIRST)" "release bundle key, created $$(date -u +%F)"
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/build/test_release_signing_tools.py -q`
Expected: PASS, 5 tests.

- [ ] **Step 5: Commit**

```bash
chmod 755 scripts/release_signing_key.sh scripts/ci/sign_release_sums.sh
git add scripts/release_signing_key.sh scripts/ci/sign_release_sums.sh Makefile tests/build/test_release_signing_tools.py
git commit -m "feat(release): tools to generate the bundle key and sign SHA256SUMS"
```

---

### Task 2: Verification library and trusted key list

**Files:**
- Create: `deploy/keys/release-bundle-keys.txt`
- Create: `deploy/lib/bundle-signature.sh`
- Test: `tests/build/test_bundle_signature_lib.py`

**Interfaces:**
- Consumes: `scripts/release_signing_key.sh` and `scripts/ci/sign_release_sums.sh` from Task 1, which the tests use to make throwaway keys and signatures.
- Produces, all from `deploy/lib/bundle-signature.sh`:
  - `CB_FIRST_SIGNED_RELEASE="0.4.7"`.
  - `_cb_embedded_release_keys` prints the embedded key file verbatim. It is a heredoc byte-identical to `deploy/keys/release-bundle-keys.txt`.
  - `cb_release_keys [keys-file]` prints `<key-id> <b64-pub>` for each well-formed line whose id matches its key. It reads the embedded list when no file is given.
  - `cb_verify_sums_signature <sums> <sig> [keys-file]` prints the verifying key id. Exit 0 means verified, 1 means no trusted key verifies, 2 means the signature is unreadable or there are no trusted keys.
  - `cb_verify_sums_entry <sums> <tarball>` checks the `./<basename>` line. Exit 0 means a match, 1 a mismatch, 3 that the tarball isn't listed.
  - `cb_release_requires_signature <version>` exits 0 when the version is at or above 0.4.7, and 1 otherwise.

- [ ] **Step 1: Write the key list**

`deploy/keys/release-bundle-keys.txt`. It has no key lines yet; the maintainer adds the first one in Task 8:

```
# Trusted Ed25519 keys for Circuit Breaker release bundles (SHA256SUMS.sig).
# Format: <key-id> <base64 raw 32-byte public key> <first-version> <comment>
# key-id: first 16 hex characters of sha256(raw public key).
# install.sh and deploy/lib/bundle-signature.sh embed this file verbatim.
# Rotation adds a line; a line is removed only on compromise.
# See docs/release/bundle-signing.md.
```

- [ ] **Step 2: Write the failing test**

`tests/build/test_bundle_signature_lib.py`:

```python
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
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/build/test_bundle_signature_lib.py -q`
Expected: FAIL, because `deploy/lib/bundle-signature.sh` does not exist.

- [ ] **Step 4: Write the library**

`deploy/lib/bundle-signature.sh`. The heredoc body must be the exact contents of `deploy/keys/release-bundle-keys.txt`:

```bash
# shellcheck shell=bash
# Release bundle signature verification.
#
# Shared by release.yml and release-dry-run.yml (sourced) and install.sh (an
# inlined copy, regenerated by scripts/ci/sync_installer_ui.py). Design:
# docs/design/2026-09-30-release-bundle-signing-design.md.
#
# Needs bash, coreutils and OpenSSL 3; no network.

CB_FIRST_SIGNED_RELEASE="0.4.7"

# DER SubjectPublicKeyInfo header for an Ed25519 key (RFC 8410). The raw
# 32-byte public key follows it; OpenSSL reads the pair as a DER public key.
_CB_ED25519_SPKI_PREFIX='\x30\x2a\x30\x05\x06\x03\x2b\x65\x70\x03\x21\x00'

# deploy/keys/release-bundle-keys.txt, verbatim.
_cb_embedded_release_keys() {
  cat <<'CB_RELEASE_KEYS'
# Trusted Ed25519 keys for Circuit Breaker release bundles (SHA256SUMS.sig).
# Format: <key-id> <base64 raw 32-byte public key> <first-version> <comment>
# key-id: first 16 hex characters of sha256(raw public key).
# install.sh and deploy/lib/bundle-signature.sh embed this file verbatim.
# Rotation adds a line; a line is removed only on compromise.
# See docs/release/bundle-signing.md.
CB_RELEASE_KEYS
}

# Print "<key-id> <base64 key>" for each trusted key whose id matches its key.
# $1: optional keys file; the embedded list otherwise. A malformed line is
# skipped: it can only ever fail to verify, never widen trust.
cb_release_keys() {
  local src line key_id key _rest raw_len actual
  if [[ -n "${1:-}" ]]; then
    src="$(cat -- "$1")" || return 1
  else
    src="$(_cb_embedded_release_keys)"
  fi
  while IFS= read -r line; do
    [[ -z "${line//[[:space:]]/}" || "$line" == \#* ]] && continue
    read -r key_id key _rest <<<"$line"
    [[ "$key_id" =~ ^[0-9a-f]{16}$ ]] || continue
    raw_len="$(printf '%s' "$key" | base64 -d 2>/dev/null | wc -c)" || continue
    [[ "$raw_len" -eq 32 ]] || continue
    actual="$(printf '%s' "$key" | base64 -d | sha256sum | cut -c1-16)"
    [[ "$actual" == "$key_id" ]] || continue
    printf '%s %s\n' "$key_id" "$key"
  done <<<"$src"
}

# Verify SHA256SUMS ($1) against SHA256SUMS.sig ($2) with the trusted keys
# ($3 optional keys file). Prints the id of the key that verified.
# 0: verified. 1: no trusted key verifies it. 2: the signature is unreadable,
# or there are no trusted keys at all.
cb_verify_sums_signature() {
  local sums="$1" sig="$2" keys_file="${3:-}" work key_id key tried=0 rc=1
  work="$(mktemp -d)" || return 2
  # Whitespace-insensitive: CRLF or trailing blanks from a copy must not
  # turn a good signature into "unreadable".
  if ! tr -d ' \t\r\n' <"$sig" | base64 -d >"$work/sig" 2>/dev/null \
    || [[ "$(wc -c <"$work/sig")" -ne 64 ]]; then
    rm -rf "$work"
    return 2
  fi
  while read -r key_id key; do
    tried=$((tried + 1))
    { printf '%b' "$_CB_ED25519_SPKI_PREFIX"; printf '%s' "$key" | base64 -d; } >"$work/pub.der"
    if openssl pkeyutl -verify -pubin -inkey "$work/pub.der" -keyform DER -rawin \
      -in "$sums" -sigfile "$work/sig" >/dev/null 2>&1; then
      printf '%s\n' "$key_id"
      rc=0
      break
    fi
  done < <(cb_release_keys "$keys_file")
  rm -rf "$work"
  if [[ "$tried" -eq 0 ]]; then
    return 2
  fi
  return "$rc"
}

# Check one tarball ($2) against its own line in SHA256SUMS ($1). The line is
# chosen by exact name (./<basename>), never with --ignore-missing, so a sums
# file that does not list this tarball cannot "verify" it.
# 0: match. 1: mismatch. 3: not listed.
cb_verify_sums_entry() {
  local sums="$1" tarball="$2" name expected actual
  name="$(basename -- "$tarball")"
  expected="$(awk -v want="./${name}" '$2 == want { print $1; exit }' "$sums")"
  [[ -n "$expected" ]] || return 3
  actual="$(sha256sum -- "$tarball" | cut -d' ' -f1)"
  [[ "$actual" == "$expected" ]] || return 1
}

# 0 when release $1 must carry a signature (it is CB_FIRST_SIGNED_RELEASE or
# later), 1 for earlier releases and for an empty version.
cb_release_requires_signature() {
  local v="${1#v}"
  [[ -n "$v" ]] || return 1
  [[ "$(printf '%s\n%s\n' "$CB_FIRST_SIGNED_RELEASE" "$v" | sort -V | head -n1)" == "$CB_FIRST_SIGNED_RELEASE" ]]
}
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/build/test_bundle_signature_lib.py -q`
Expected: PASS. If `0.4.7-rc.1` sorts before `0.4.7` on this host's `sort -V`, the test fails. Don't weaken it: stop and report, because candidates of a signed release must be treated as signed.

- [ ] **Step 6: Commit**

```bash
git add deploy/keys/release-bundle-keys.txt deploy/lib/bundle-signature.sh tests/build/test_bundle_signature_lib.py
git commit -m "feat(release): bundle signature library and trusted key list"
```

---

### Task 3: Inline the library into install.sh

**Files:**
- Modify: `scripts/ci/sync_installer_ui.py` (handle a list of blocks)
- Modify: `install.sh` (add a second marked block after the `ui.sh` block, before `# GitHub repo for release downloads`)
- Modify: `tests/build/test_installer_ui_inline_matches_library.py` (parametrise over both blocks)

**Interfaces:**
- Consumes: `deploy/lib/bundle-signature.sh` (Task 2).
- Produces: `install.sh` defines everything the library defines, between these markers:
  - `# --- BEGIN INLINED deploy/lib/bundle-signature.sh — regenerate with scripts/ci/sync_installer_ui.py ---`
  - `# --- END INLINED deploy/lib/bundle-signature.sh ---`

- [ ] **Step 1: Read the current sync script and its test**

Run: `sed -n 1,200p scripts/ci/sync_installer_ui.py tests/build/test_installer_ui_inline_matches_library.py`. Note how `BEGIN_MARKER`, `END_MARKER`, `_BLOCK_RE`, `--check` and the two tests fit together.

- [ ] **Step 2: Parametrise the test first (failing)**

Change `tests/build/test_installer_ui_inline_matches_library.py` so each existing test runs once per entry of `BLOCKS`, imported from the sync script. That is:

```python
from scripts.ci.sync_installer_ui import BLOCKS  # [(library_path, begin_marker, end_marker), ...]

@pytest.mark.parametrize(("library", "begin", "end"), BLOCKS, ids=lambda v: getattr(v, "name", None))
def test_the_inlining_markers_exist(library, begin, end) -> None: ...
```

Keep each test body's assertions and messages. Replace the module constants with the parameters. If the file imports the script differently today, keep its existing import style and import `BLOCKS` the same way.

Run: `.venv/bin/pytest tests/build/test_installer_ui_inline_matches_library.py -q`
Expected: FAIL, because `BLOCKS` is not defined.

- [ ] **Step 3: Generalise the sync script**

In `scripts/ci/sync_installer_ui.py`:
- Replace the single `UI_SH`/`BEGIN_MARKER`/`END_MARKER`/`_BLOCK_RE` with a `BLOCKS` list of `(Path, begin, end)` tuples.
- Keep the first entry's values exactly as they are today.
- Add the second entry:

```python
BLOCKS: list[tuple[Path, str, str]] = [
    (
        REPO_ROOT / "deploy" / "lib" / "ui.sh",
        "# --- BEGIN INLINED deploy/lib/ui.sh — regenerate with scripts/ci/sync_installer_ui.py ---",
        "# --- END INLINED deploy/lib/ui.sh ---",
    ),
    (
        REPO_ROOT / "deploy" / "lib" / "bundle-signature.sh",
        "# --- BEGIN INLINED deploy/lib/bundle-signature.sh — regenerate with scripts/ci/sync_installer_ui.py ---",
        "# --- END INLINED deploy/lib/bundle-signature.sh ---",
    ),
]
```

Make the rewrite and `--check` loop over `BLOCKS`, building each block's regex the way `_BLOCK_RE` is built today. Update the module docstring's first line to "Keep install.sh's inlined libraries byte-identical to deploy/lib/". Keep the file name, so the `ui.sh` workflow and every existing reference still work.

- [ ] **Step 4: Add the empty markers to install.sh, then sync**

Insert these two lines into `install.sh`, directly after `# --- END INLINED deploy/lib/ui.sh ---` and its following blank line:

```bash
# --- BEGIN INLINED deploy/lib/bundle-signature.sh — regenerate with scripts/ci/sync_installer_ui.py ---
# --- END INLINED deploy/lib/bundle-signature.sh ---
```

Run: `python3 scripts/ci/sync_installer_ui.py && python3 scripts/ci/sync_installer_ui.py --check && git diff --stat install.sh`
Expected: `--check` exits 0, and `install.sh` grows by the library's line count.

- [ ] **Step 5: Run the affected suites**

Run: `.venv/bin/pytest tests/build/test_installer_ui_inline_matches_library.py tests/build/test_installer_ui_inline_not_shadowed.py tests/build/test_installer_banner_unchanged.py -q && bash -n install.sh`
Expected: PASS. If `test_installer_ui_inline_not_shadowed.py` flags a name the new block defines, rename the library function (for example with a `_cb_` prefix) in both Task 2's library and test. Don't exempt it.

- [ ] **Step 6: Commit**

```bash
git add scripts/ci/sync_installer_ui.py install.sh tests/build/test_installer_ui_inline_matches_library.py
git commit -m "feat(install): inline the bundle signature library into install.sh"
```

---

### Task 4: install.sh verifies signature, then hash

**Files:**
- Modify: `install.sh`:
  - add `SKIP_SIGNATURE=false` beside `SKIP_CHECKSUM=false` (~line 629);
  - replace `cb_verify_bundle_checksum` (~lines 1505–1578) with `cb_fetch_release_asset`, `cb_check_bundle` and `cb_check_attestation`;
  - call them from `stage0_download_bundle` in both the local and the download branches;
  - add the `--skip-signature` option and its help line.
- Test: `tests/build/test_install_bundle_verification.py`

**Interfaces:**
- Consumes: the inlined library (Task 3).
- Produces:
  - `cb_check_bundle <tarball> <sums-path|""> <sig-path|""> <download|local> <version|"">` implements the spec's behaviour table and returns 0 or calls `cb_fail`.
  - `cb_fetch_release_asset <release-json> <asset-name>` downloads to `/tmp/cb-<asset-name>`. It returns 0 when downloaded, 1 when the release doesn't publish that asset, and calls `cb_fail` when the download fails.
  - `cb_check_attestation <tarball>` never fails the install.

- [ ] **Step 1: Write the failing test**

`tests/build/test_install_bundle_verification.py`:

```python
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
              airgap: bool = True, keys: Path | None = None) -> subprocess.CompletedProcess[str]:
        script = "\n".join([
            "set -euo pipefail",
            STUBS,
            _library(),
            f'_cb_embedded_release_keys() {{ cat "{keys or self.keys}"; }}',
            f"SKIP_CHECKSUM={'true' if skip_checksum else 'false'}",
            f"SKIP_SIGNATURE={'true' if skip_signature else 'false'}",
            f"CB_AIRGAP={'true' if airgap else 'false'}",
            'CB_GITHUB_REPO="BlkLeg/CircuitBreaker"',
            _function("cb_check_attestation"),
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/build/test_install_bundle_verification.py -q`
Expected: FAIL, because `cb_check_bundle() not found in install.sh`.

- [ ] **Step 3: Implement in install.sh**

Next to `SKIP_CHECKSUM=false`:

```bash
SKIP_SIGNATURE=false
```

Replace the whole `cb_verify_bundle_checksum` comment block and function with the following. Keep the old comment's history about `--ignore-missing` and the `.sha256` 404: it now lives above `cb_verify_sums_entry` in the library, so condense it here to a pointer.

```bash
# Download one release asset to /tmp/cb-<name>. 0: downloaded. 1: the release
# does not publish it (the caller decides whether that is fatal). A failed
# download stops the install: it is a network fault, not a verdict.
#
# The `|| true` keeps a truncated or proxy-mangled API body (jq exits 2) from
# ending the install silently under `set -euo pipefail`; it falls through to
# "not published", which cb_check_bundle then refuses out loud.
cb_fetch_release_asset() {
  local release_json="$1" name="$2" url
  url=$(printf '%s' "$release_json" | jq -r --arg n "$name" '.assets[] | select(.name==$n) | .browser_download_url' 2>/dev/null || true)
  if [[ -z "$url" ]] || [[ "$url" == "null" ]]; then
    return 1
  fi
  curl -fsSL --retry 5 --retry-delay 2 --retry-all-errors --connect-timeout 15 -o "/tmp/cb-${name}" "$url" \
    || cb_fail "Could not download ${name} for release v${CB_VERSION}" \
               "Check internet connectivity and re-run"
}

# Build provenance (GitHub attestation). Reported, never required: an
# air-gapped host cannot reach Sigstore, and the signature has already
# decided. Only called after a signature verified.
cb_check_attestation() {
  local tarball="$1"
  if [[ "$CB_AIRGAP" == "true" ]]; then
    cb_ok "Build provenance not checked (air-gapped)"
    return 0
  fi
  if ! command -v gh >/dev/null 2>&1 || ! gh auth status >/dev/null 2>&1; then
    cb_ok "Build provenance not checked (install and log in to the GitHub CLI to check it)"
    return 0
  fi
  if gh attestation verify "$tarball" --repo "${CB_GITHUB_REPO}" >/dev/null 2>&1; then
    cb_ok "Build provenance verified (GitHub attestation)"
  else
    cb_warn "Build provenance could not be verified with gh (offline, or this release has no attestation); the signature above still verified"
  fi
}

# Decide whether a bundle may be installed: signature first, then hash.
# $1 tarball, $2 SHA256SUMS path or "", $3 SHA256SUMS.sig path or "",
# $4 origin (download|local), $5 release version or "" (local).
# Implements the behaviour table in
# docs/design/2026-09-30-release-bundle-signing-design.md.
cb_check_bundle() {
  local tarball="$1" sums="$2" sig="$3" origin="$4" version="$5"
  local key_id rc name refetch tried signed=false
  name="$(basename -- "$tarball")"
  if [[ "$origin" == "download" ]]; then
    refetch="Download SHA256SUMS and SHA256SUMS.sig again from https://github.com/${CB_GITHUB_REPO}/releases/tag/v${version}"
  else
    refetch="Copy the release's SHA256SUMS and SHA256SUMS.sig next to the bundle"
  fi

  if [[ "$SKIP_CHECKSUM" == "true" ]]; then
    cb_warn "Skipping bundle verification (--skip-checksum): neither the signature nor the SHA256 of ${name} is checked"
    return 0
  fi

  if [[ -z "$sums" ]]; then
    if [[ "$origin" == "local" ]] && [[ -z "$sig" ]]; then
      cb_warn "No SHA256SUMS or SHA256SUMS.sig next to ${tarball}: installing an UNVERIFIED bundle"
      return 0
    fi
    cb_fail "No SHA256SUMS for ${name}" \
      "${refetch}, or pass --skip-checksum only for a bundle you already trust"
  fi

  if [[ -n "$sig" ]] && [[ "$SKIP_SIGNATURE" != "true" ]]; then
    cb_step "Verifying release signature"
    tried="$(cb_release_keys | cut -d' ' -f1 | paste -sd, -)"
    if key_id="$(cb_verify_sums_signature "$sums" "$sig")"; then
      cb_ok "Signature verified (key ${key_id})"
      signed=true
    else
      rc=$?
      if [[ -z "$tried" ]]; then
        cb_fail "This installer trusts no release keys" \
          "Use an install.sh from a release that ships its trusted key list, or pass --skip-signature only for a bundle you already trust"
      fi
      if (( rc == 2 )); then
        cb_fail "SHA256SUMS.sig is unreadable" "${refetch}. Keys tried: ${tried}"
      fi
      cb_fail "SHA256SUMS signature does not verify — the release files may have been tampered with" \
        "${refetch}. Keys tried: ${tried}. Pass --skip-signature only for a bundle you already trust"
    fi
  elif [[ "$SKIP_SIGNATURE" == "true" ]]; then
    cb_warn "Skipping signature verification (--skip-signature); the SHA256 is still checked"
  elif [[ "$origin" == "download" ]] && cb_release_requires_signature "$version"; then
    cb_fail "Release v${version} publishes no SHA256SUMS.sig" \
      "Every release from v${CB_FIRST_SIGNED_RELEASE} on is signed; refusing an unsigned one. Pass --skip-signature only for a bundle you already trust"
  elif [[ "$origin" == "download" ]]; then
    cb_warn "Release v${version} predates bundle signing (v${CB_FIRST_SIGNED_RELEASE}); checking its SHA256 only"
  else
    cb_warn "No SHA256SUMS.sig next to the bundle; checking its SHA256 only"
  fi

  cb_step "Verifying checksum"
  if cb_verify_sums_entry "$sums" "$tarball"; then
    cb_ok "SHA256 checksum verified"
  else
    rc=$?
    if (( rc == 3 )); then
      cb_fail "${name} is not listed in SHA256SUMS" \
        "The bundle must keep its release file name (circuit-breaker_<version>_linux_<arch>.tar.gz) and come from the same release as SHA256SUMS"
    fi
    cb_fail "SHA256 mismatch — ${name} may be corrupted or tampered with" \
      "Download it again, or pass --skip-checksum only for a bundle you already trust"
  fi

  if [[ "$signed" == "true" ]]; then
    cb_check_attestation "$tarball"
  fi
}
```

In `stage0_download_bundle`, the local branch (after `cb_ok "Local bundle: $CB_LOCAL_BUNDLE"`):

```bash
    local local_dir local_sums="" local_sig=""
    local_dir="$(dirname -- "$CB_LOCAL_BUNDLE")"
    [[ -f "${local_dir}/SHA256SUMS" ]] && local_sums="${local_dir}/SHA256SUMS"
    [[ -f "${local_dir}/SHA256SUMS.sig" ]] && local_sig="${local_dir}/SHA256SUMS.sig"
    cb_check_bundle "$CB_LOCAL_BUNDLE" "$local_sums" "$local_sig" local ""
```

In the download branch, replace `cb_verify_bundle_checksum "$release_json" "$tarball_name"` with:

```bash
    local sums_path="" sig_path=""
    rm -f /tmp/cb-SHA256SUMS /tmp/cb-SHA256SUMS.sig
    if [[ "$SKIP_CHECKSUM" != "true" ]]; then
      if cb_fetch_release_asset "$release_json" SHA256SUMS; then
        sums_path=/tmp/cb-SHA256SUMS
      fi
      if [[ "$SKIP_SIGNATURE" != "true" ]] && cb_fetch_release_asset "$release_json" SHA256SUMS.sig; then
        sig_path=/tmp/cb-SHA256SUMS.sig
      fi
    fi
    cb_check_bundle "/tmp/${tarball_name}" "$sums_path" "$sig_path" download "$CB_VERSION"
    rm -f /tmp/cb-SHA256SUMS /tmp/cb-SHA256SUMS.sig
```

In the argument parser, next to `--skip-checksum)`:

```bash
    --skip-signature)
      SKIP_SIGNATURE=true
      shift
      ;;
```

In the help text, directly after the `--skip-checksum` line:

```bash
  echo "  --skip-signature       Skip the release signature check (SHA256 is still checked)"
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/pytest tests/build/test_install_bundle_verification.py tests/build/test_install_release_selection.py tests/build/test_installer_unattended_contract.py tests/build/test_installer_ui_inline_matches_library.py -q && bash -n install.sh && shellcheck -S warning install.sh deploy/lib/bundle-signature.sh`
Expected: PASS, and shellcheck is clean at warning level. If `shellcheck` is not installed, say so in the report; don't skip silently. Then run the whole policy suite once with `.venv/bin/pytest tests/build -q`. The known `.superdesign` allowlist failure is not this task's; any other failure is.

- [ ] **Step 5: Commit**

```bash
git add install.sh tests/build/test_install_bundle_verification.py
git commit -m "feat(install): verify the release signature before trusting SHA256SUMS"
```

---

### Task 5: Sign and attest in the Stage Draft Release job

**Files:**
- Modify: `.github/workflows/release.yml`, in the `release` job (~lines 459–767)
- Modify: `tests/build/test_release_approval_gate.py`, in `test_only_promote_uses_the_release_environment` (~line 87)
- Create: `tests/build/test_release_bundle_signing_wiring.py`

**Interfaces:**
- Consumes: `scripts/ci/sign_release_sums.sh` (Task 1), plus `deploy/lib/bundle-signature.sh` and `deploy/keys/release-bundle-keys.txt` (Task 2).
- Produces: a staged draft carrying `SHA256SUMS.sig`, and GitHub attestations for every `circuit-breaker_<v>_linux_<arch>.tar.gz`. Task 6 verifies both.

- [ ] **Step 1: Write the failing wiring test**

`tests/build/test_release_bundle_signing_wiring.py`:

```python
"""Where release.yml signs, verifies and attests the bundles (spec: release pipeline)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
RELEASE = yaml.safe_load((ROOT / ".github" / "workflows" / "release.yml").read_text())
DRY_RUN = yaml.safe_load((ROOT / ".github" / "workflows" / "release-dry-run.yml").read_text())
JOBS: dict[str, Any] = RELEASE["jobs"]


def _steps(job: str, workflow: dict[str, Any] = RELEASE) -> list[dict[str, Any]]:
    return workflow["jobs"][job]["steps"]


def _index(job: str, predicate, workflow: dict[str, Any] = RELEASE) -> int:
    for i, step in enumerate(_steps(job, workflow)):
        if predicate(step):
            return i
    raise AssertionError(f"no matching step in {job}")


def _runs(step: dict[str, Any], needle: str) -> bool:
    return needle in step.get("run", "")


def test_only_the_stage_job_declares_the_signing_environment() -> None:
    declared = {name: job.get("environment") for name, job in JOBS.items() if job.get("environment")}
    assert declared == {"release": "release-signing", "promote": "release"}


def test_the_stage_job_can_attest() -> None:
    perms = JOBS["release"]["permissions"]
    assert perms == {
        "contents": "write", "packages": "write", "id-token": "write",
        "security-events": "write", "attestations": "write",
    }


def test_signing_happens_after_the_final_sums_and_before_the_draft() -> None:
    final = _index("release", lambda s: s.get("name") == "Write the final SHA256SUMS")
    sign = _index("release", lambda s: _runs(s, "scripts/ci/sign_release_sums.sh"))
    verify = _index("release", lambda s: _runs(s, "cb_verify_sums_signature"))
    attest = _index("release", lambda s: str(s.get("uses", "")).startswith("actions/attest-build-provenance@"))
    stage = _index("release", lambda s: _runs(s, "gh release create"))
    candidate = _index("release", lambda s: s.get("name") == "Write candidate.json")
    assert final < sign < verify < attest < candidate < stage


def test_the_key_reaches_only_the_signing_step_and_only_through_env() -> None:
    holders = [s for s in _steps("release") if "RELEASE_BUNDLE_SIGNING_KEY" in yaml.safe_dump(s)]
    assert len(holders) == 1
    step = holders[0]
    assert step["env"]["RELEASE_BUNDLE_SIGNING_KEY"] == "${{ secrets.RELEASE_BUNDLE_SIGNING_KEY }}"
    run = step["run"]
    assert "${{" not in run
    assert "umask 077" in run
    assert 'rm -f "${keyfile}"' in run
    assert "trap" in run
    assert "exit 1" in run  # an empty secret stops the release


def test_the_final_sums_exclude_the_signature_files() -> None:
    step = _steps("release")[_index("release", lambda s: s.get("name") == "Write the final SHA256SUMS")]
    assert "! -name 'SHA256SUMS*'" in step["run"]


def test_attestation_covers_the_bundle_tarballs() -> None:
    step = _steps("release")[_index("release", lambda s: str(s.get("uses", "")).startswith("actions/attest-build-provenance@"))]
    assert step["with"]["subject-path"] == "dist/release/circuit-breaker_*_linux_*.tar.gz"


def test_new_steps_never_soften_failure() -> None:
    for step in _steps("release"):
        text = yaml.safe_dump(step)
        if "sign_release_sums" in text or "cb_verify_sums" in text or "attest-build-provenance" in text:
            assert "continue-on-error" not in step
            assert "always()" not in str(step.get("if", ""))
```

In `tests/build/test_release_approval_gate.py`, change `test_only_promote_uses_the_release_environment` so it checks the environment named `release`, not any environment:

```python
def test_only_promote_uses_the_release_environment() -> None:
    """Approving must mean approving the publish, not some earlier step."""
    others = sorted(
        name
        for name, job in JOBS.items()
        if name != "promote" and _environment_name(job) == "release"
    )
    assert not others, f"jobs other than promote declare the release environment: {others}"
```

Add this helper, and use it in `test_promote_declares_the_release_environment` too, instead of its inline `isinstance` logic:

```python
def _environment_name(job: dict[str, Any]) -> str | None:
    environment = job.get("environment")
    return environment.get("name") if isinstance(environment, dict) else environment
```

Run: `.venv/bin/pytest tests/build/test_release_bundle_signing_wiring.py tests/build/test_release_approval_gate.py -q`
Expected: the new file FAILs, and the approval-gate file PASSes.

- [ ] **Step 2: Edit the Stage job**

Look up the current major version tag of `actions/attest-build-provenance` with `gh api repos/actions/attest-build-provenance/releases/latest --jq .tag_name`. Pin its major (for example `@v3`), matching how this workflow pins `actions/checkout@v5`.

1. On the `release:` job, under `runs-on: ubuntu-22.04`, add:

```yaml
    # The release-bundle key is a secret of this environment, whose deployment
    # branch rule allows main only (docs/release/bundle-signing.md). It has no
    # reviewers: approval happens once, on `release`, before promote.
    environment: release-signing
    permissions:
      contents: write
      packages: write
      id-token: write
      security-events: write
      attestations: write
```

2. In `GPG sign artifacts`, delete the last block, from `# Regenerate SHA256SUMS (now includes .asc + SBOM files) then sign it` through the `--armor --detach-sign SHA256SUMS` command. That step now signs individual files only.

3. Directly after `GPG sign artifacts`, insert:

```yaml
      # The one SHA256SUMS that is published and signed: every file attached
      # to the release, including the SBOMs and .asc files written above, and
      # never SHA256SUMS or its own signatures.
      - name: Write the final SHA256SUMS
        run: |
          set -euo pipefail
          cd dist/release/
          find . -maxdepth 1 -type f ! -name 'SHA256SUMS*' -exec sha256sum {} + > SHA256SUMS
          cat SHA256SUMS

      - name: GPG sign SHA256SUMS
        env:
          GPG_PRIVATE_KEY: ${{ secrets.GPG_PRIVATE_KEY }}
          GPG_PASSPHRASE: ${{ secrets.GPG_PASSPHRASE }}
        run: |
          if [ -z "${GPG_PRIVATE_KEY}" ]; then
            echo "GPG_PRIVATE_KEY not set — skipping the GPG signature of SHA256SUMS"
            exit 0
          fi
          cd dist/release/
          gpg --batch --yes --pinentry-mode loopback \
              --passphrase "${GPG_PASSPHRASE}" \
              --armor --detach-sign SHA256SUMS

      # Required: a release is never staged unsigned. The key exists only in
      # this step, in a 0600 file removed before the step ends.
      - name: Sign SHA256SUMS with the release bundle key
        env:
          RELEASE_BUNDLE_SIGNING_KEY: ${{ secrets.RELEASE_BUNDLE_SIGNING_KEY }}
        run: |
          set -euo pipefail
          if [ -z "${RELEASE_BUNDLE_SIGNING_KEY}" ]; then
            echo "::error::RELEASE_BUNDLE_SIGNING_KEY is empty. It is a secret of the release-signing environment (docs/release/bundle-signing.md); a release is never staged unsigned."
            exit 1
          fi
          umask 077
          keyfile="$(mktemp)"
          trap 'rm -f "${keyfile}"' EXIT
          printf '%s\n' "${RELEASE_BUNDLE_SIGNING_KEY}" > "${keyfile}"
          scripts/ci/sign_release_sums.sh "${keyfile}" dist/release/SHA256SUMS dist/release/SHA256SUMS.sig
          rm -f "${keyfile}"

      # Against the COMMITTED key list, so a secret that does not match the
      # public key install.sh trusts fails here, not on users' hosts.
      - name: Verify SHA256SUMS.sig against the trusted keys
        run: |
          set -euo pipefail
          source deploy/lib/bundle-signature.sh
          if ! key_id="$(cb_verify_sums_signature dist/release/SHA256SUMS dist/release/SHA256SUMS.sig deploy/keys/release-bundle-keys.txt)"; then
            echo "::error::the new SHA256SUMS.sig does not verify against deploy/keys/release-bundle-keys.txt: the release-signing secret and the committed public key do not match"
            exit 1
          fi
          echo "SHA256SUMS signed by trusted key ${key_id}"

      - name: Attest build provenance for the bundles
        uses: actions/attest-build-provenance@<major found above>
        with:
          subject-path: dist/release/circuit-breaker_*_linux_*.tar.gz
```

`Stage the draft release` uploads `dist/release/*`, so `SHA256SUMS.sig` is attached with no further change. `Write candidate.json` still parses `SHA256SUMS`, which is unchanged in format.

- [ ] **Step 3: Run the tests**

Run: `.venv/bin/pytest tests/build/test_release_bundle_signing_wiring.py tests/build/test_release_approval_gate.py tests/build/test_workflow_job_graph.py tests/build/test_release_publication_is_gated.py tests/build/test_release_promote_contract.py tests/build/test_release_artifact_patterns.py -q`
Expected: PASS. Then run `.venv/bin/pytest tests/build -q`. Any workflow-policy failure, such as action pinning or interpolation rules, is fixed in the workflow, never exempted.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/release.yml tests/build/test_release_bundle_signing_wiring.py tests/build/test_release_approval_gate.py
git commit -m "ci(release): sign SHA256SUMS and attest the bundles when staging a draft"
```

---

### Task 6: Verify before approval, after publish, and in the dry run

**Files:**
- Modify: `.github/workflows/release.yml`, in `promote-verify` (~813) and `post-publish` (~934)
- Modify: `.github/workflows/release-dry-run.yml` (after `Generate SHA256SUMS`, ~436)
- Modify: `tests/build/test_release_bundle_signing_wiring.py` (append tests)

**Interfaces:**
- Consumes: Task 5's staged draft, plus Task 1's and Task 2's scripts and library.

- [ ] **Step 1: Append the failing tests**

Add to `tests/build/test_release_bundle_signing_wiring.py`:

```python
def test_promote_verify_checks_signature_hashes_and_provenance_before_approval() -> None:
    step = _steps("promote-verify")[_index("promote-verify", lambda s: _runs(s, "cb_verify_sums_signature"))]
    run = step["run"]
    assert "--pattern 'SHA256SUMS.sig'" in run
    assert "deploy/keys/release-bundle-keys.txt" in run
    assert "cb_verify_sums_entry" in run
    assert 'gh attestation verify "${tarball}" --repo "${GITHUB_REPOSITORY}"' in run
    assert "${{" not in run
    assert JOBS["promote-verify"]["permissions"]["attestations"] == "read"


def test_post_publish_verifies_the_published_signature() -> None:
    download = _steps("post-publish")[_index("post-publish", lambda s: s.get("name") == "Download the published tarball and checksums")]
    assert '--pattern "SHA256SUMS.sig"' in download["run"]
    verify = _index("post-publish", lambda s: _runs(s, "cb_verify_sums_signature"))
    hashes = _index("post-publish", lambda s: s.get("name") == "Verify the published tarball against the published checksums")
    assert verify < hashes


def test_the_dry_run_rehearses_signing_with_a_throwaway_key() -> None:
    step = _steps("staged-publication", DRY_RUN)[_index("staged-publication", lambda s: _runs(s, "sign_release_sums.sh"), DRY_RUN)]
    run = step["run"]
    assert "openssl genpkey -algorithm ed25519" in run  # generated at run time, never stored
    assert "cb_verify_sums_signature" in run
    assert "tampered" in run  # the negative case must fail
    assert "secrets." not in yaml.safe_dump(step)
```

Run: `.venv/bin/pytest tests/build/test_release_bundle_signing_wiring.py -q`
Expected: the three new tests FAIL.

- [ ] **Step 2: Edit promote-verify**

Add `attestations: read` to its `permissions:` block. Append this step after `Assert the draft's assets still match candidate.json`:

```yaml
      # The signed path, proven against the real key and the real draft
      # assets before anyone is asked to approve.
      - name: Verify the draft's signature, bundle hashes and provenance
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          VERSION: ${{ needs.version.outputs.version }}
        run: |
          set -euo pipefail
          mkdir -p /tmp/signed && cd /tmp/signed
          gh release download "v${VERSION}" --repo "${GITHUB_REPOSITORY}" \
            --pattern 'SHA256SUMS' --pattern 'SHA256SUMS.sig' \
            --pattern "circuit-breaker_${VERSION}_linux_*.tar.gz"
          source "${GITHUB_WORKSPACE}/deploy/lib/bundle-signature.sh"
          key_id="$(cb_verify_sums_signature SHA256SUMS SHA256SUMS.sig "${GITHUB_WORKSPACE}/deploy/keys/release-bundle-keys.txt")" \
            || { echo "::error::the draft's SHA256SUMS.sig does not verify against deploy/keys/release-bundle-keys.txt"; exit 1; }
          echo "draft signed by trusted key ${key_id}"
          checked=0
          for tarball in circuit-breaker_"${VERSION}"_linux_*.tar.gz; do
            cb_verify_sums_entry SHA256SUMS "${tarball}" \
              || { echo "::error::${tarball} does not match the signed SHA256SUMS"; exit 1; }
            gh attestation verify "${tarball}" --repo "${GITHUB_REPOSITORY}"
            checked=$((checked + 1))
          done
          [ "${checked}" -ge 2 ] || { echo "::error::expected the amd64 and arm64 tarballs, verified ${checked}"; exit 1; }
```

- [ ] **Step 3: Edit post-publish**

In `Download the published tarball and checksums`, add `--pattern "SHA256SUMS.sig"` to the `gh release download` call. Insert this step before `Verify the published tarball against the published checksums`:

```yaml
      - name: Verify the published signature
        run: |
          set -euo pipefail
          source deploy/lib/bundle-signature.sh
          key_id="$(cb_verify_sums_signature published/SHA256SUMS published/SHA256SUMS.sig deploy/keys/release-bundle-keys.txt)" \
            || { echo "::error::the published SHA256SUMS.sig does not verify against deploy/keys/release-bundle-keys.txt"; exit 1; }
          echo "published release signed by trusted key ${key_id}"
```

- [ ] **Step 4: Edit the dry run**

After `Generate SHA256SUMS` in `release-dry-run.yml`, insert:

```yaml
      # The real key never reaches a dry run. This proves the signing script,
      # the library and the SHA256SUMS they read agree, with a key generated
      # here and discarded with the runner.
      - name: Rehearse bundle signing with a throwaway key
        run: |
          set -euo pipefail
          work="$(mktemp -d)"
          trap 'rm -rf "${work}"' EXIT
          (umask 077 && openssl genpkey -algorithm ed25519 -out "${work}/key.pem")
          pub="$(openssl pkey -in "${work}/key.pem" -pubout -outform DER | tail -c 32 | base64 -w0)"
          id="$(printf '%s' "${pub}" | base64 -d | sha256sum | cut -c1-16)"
          printf '%s %s 0.0.0 dry-run throwaway\n' "${id}" "${pub}" > "${work}/keys.txt"
          scripts/ci/sign_release_sums.sh "${work}/key.pem" dist/release/SHA256SUMS "${work}/SHA256SUMS.sig"
          source deploy/lib/bundle-signature.sh
          got="$(cb_verify_sums_signature dist/release/SHA256SUMS "${work}/SHA256SUMS.sig" "${work}/keys.txt")"
          [ "${got}" = "${id}" ] || { echo "::error::rehearsal signature verified by ${got}, expected ${id}"; exit 1; }
          cp dist/release/SHA256SUMS "${work}/tampered"
          printf 'tampered\n' >> "${work}/tampered"
          if cb_verify_sums_signature "${work}/tampered" "${work}/SHA256SUMS.sig" "${work}/keys.txt" >/dev/null; then
            echo "::error::a tampered SHA256SUMS verified"
            exit 1
          fi
          for tarball in dist/release/circuit-breaker_*_linux_*.tar.gz; do
            cb_verify_sums_entry dist/release/SHA256SUMS "${tarball}" \
              || { echo "::error::${tarball} does not match the staged SHA256SUMS"; exit 1; }
          done
          echo "bundle signing rehearsed with throwaway key ${id}"
```

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/pytest tests/build/test_release_bundle_signing_wiring.py tests/build/test_release_approval_gate.py tests/build/test_workflow_job_graph.py tests/build/test_release_dry_run_asset_discovery.py tests/build/test_release_paths_run_before_the_tag.py -q`, then `.venv/bin/pytest tests/build -q`.
Expected: PASS, apart from the known `.superdesign` allowlist failure.

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/release.yml .github/workflows/release-dry-run.yml tests/build/test_release_bundle_signing_wiring.py
git commit -m "ci(release): verify the bundle signature before approval, after publish and in the dry run"
```

---

### Task 7: Documentation and release-control progress

**Files:**
- Create: `docs/release/bundle-signing.md` (the maintainer runbook: setup, rotation, compromise)
- Modify: `mkdocs.yml` (nav entry beside the other `release/` pages, ~line 69)
- Modify: `docs/installation/security-verification.md` (a section on verifying the Ed25519 signature)
- Modify: `docs/installation/upgrading.md` (~line 104: copy the tarball, `SHA256SUMS` and `SHA256SUMS.sig`)
- Modify: `Makefile` (the `release-candidate` soak hint also downloads `SHA256SUMS*`)
- Modify: `.claude/skills/cb-release/SKILL.md` (one line on the `release-signing` environment)
- Modify: `specs/1.0.0/release-control/requirement-ledger.csv` (NPM-03 and NPM-12 notes only)

- [ ] **Step 1: Write the runbook**

`docs/release/bundle-signing.md`:

````markdown
# Release bundle signing

Every release from 0.4.7 on publishes `SHA256SUMS.sig`: an Ed25519 signature over
`SHA256SUMS`, made by the Stage Draft Release job with a key only that job can read.
`install.sh` checks it before it trusts any hash. The design is
[the bundle signing design](../design/2026-09-30-release-bundle-signing-design.md).

## One-time setup

1. Generate the key pair on a trusted machine, outside the repository:

   ```bash
   make release-signing-key OUT=$HOME/secure/release-bundle.pem FIRST=0.4.7
   ```

   It prints one line, `<key-id> <public key> 0.4.7 <comment>`. The private key is
   written with mode 0600.

2. Append that line to `deploy/keys/release-bundle-keys.txt`. Then copy the file's
   exact contents into the heredoc in `_cb_embedded_release_keys` in
   `deploy/lib/bundle-signature.sh`. Then run `python3 scripts/ci/sync_installer_ui.py`,
   so `install.sh` carries the same list. `tests/build` fails if the three differ.

3. Create the environment, allowing deployments from `main` only:

   ```bash
   gh api -X PUT repos/BlkLeg/CircuitBreaker/environments/release-signing \
     -F 'deployment_branch_policy[protected_branches]=false' \
     -F 'deployment_branch_policy[custom_branch_policies]=true'
   gh api -X POST repos/BlkLeg/CircuitBreaker/environments/release-signing/deployment-branch-policies \
     -f name=main -f type=branch
   ```

4. Store the private key as the environment's secret, read from the file so it
   never appears on a command line or in shell history:

   ```bash
   gh secret set RELEASE_BUNDLE_SIGNING_KEY --env release-signing < $HOME/secure/release-bundle.pem
   ```

5. Keep an offline backup, for example on an encrypted USB key. Then remove the
   working copy with `shred -u $HOME/secure/release-bundle.pem`. Never commit the
   private key or paste it anywhere.

The first candidate after this proves the setup: the Stage job verifies its own
signature against the committed key list, and `promote-verify` checks it again
before asking for approval.

## Rotation

Generate a new key the same way, with `FIRST=<the next version>`. Add its line and
keep the old one, so older releases still verify. Replace the environment secret.

## Compromise

1. Remove the compromised key's line from `deploy/keys/release-bundle-keys.txt`,
   the library heredoc and `install.sh` (sync script), and from the npm CLI's copy
   once it ships.
2. Add a new key (rotation, above).
3. Re-sign each affected release's `SHA256SUMS` with the new key:
   `scripts/ci/sign_release_sums.sh <new.pem> SHA256SUMS SHA256SUMS.sig`. Then
   replace the asset with `gh release upload v<version> SHA256SUMS.sig --clobber`.
4. Publish an advisory naming the removed key id. Any release still carrying only
   the old signature now fails verification, by design.

## Verifying by hand

See [security verification](../installation/security-verification.md#release-bundle-signature).
````

- [ ] **Step 2: Add the user-facing verification section**

Append to `docs/installation/security-verification.md`:

````markdown
## Release bundle signature

From 0.4.7, every release publishes `SHA256SUMS.sig`, an Ed25519 signature over
`SHA256SUMS`. `install.sh` checks it automatically, including with `--local-bundle`
when `SHA256SUMS` and `SHA256SUMS.sig` sit next to the tarball. To check a download
by hand with OpenSSL 3, take the public key (the second field) from
[`deploy/keys/release-bundle-keys.txt`](https://github.com/BlkLeg/CircuitBreaker/blob/main/deploy/keys/release-bundle-keys.txt):

```bash
PUB='<public key from the key file>'
{ printf '\x30\x2a\x30\x05\x06\x03\x2b\x65\x70\x03\x21\x00'; printf '%s' "$PUB" | base64 -d; } > release-key.der
base64 -d SHA256SUMS.sig > SHA256SUMS.sig.bin
openssl pkeyutl -verify -pubin -inkey release-key.der -keyform DER -rawin \
  -in SHA256SUMS -sigfile SHA256SUMS.sig.bin
sha256sum -c --ignore-missing SHA256SUMS
```

`Signature Verified Successfully` followed by `OK` for your tarball means the files
are the ones the release pipeline signed. Releases before 0.4.7 have no signature.
````

- [ ] **Step 3: Update the upgrade page, the Makefile hint and the skill**

- **`docs/installation/upgrading.md`:** in the paragraph at ~line 104 that tells air-gapped users what to copy, name `SHA256SUMS.sig` alongside the tarball and `SHA256SUMS`. Say that the installer verifies the pair when both are next to the tarball.
- **`Makefile`:** in `release-candidate`, change the soak hint to:
  `gh release download v$$(cat VERSION) --pattern '*linux_amd64.tar.gz' --pattern 'SHA256SUMS*' && install.sh --local-bundle ...`
- **`.claude/skills/cb-release/SKILL.md`:** add one line where the environments are described: "The Stage job declares `environment: release-signing` (the bundle key; `main` only, no reviewers); `release` stays promote-only. Setup and rotation: `docs/release/bundle-signing.md`."

- [ ] **Step 4: mkdocs nav**

Add `      - Bundle Signing: release/bundle-signing.md` to the nav block in `mkdocs.yml` that lists the `release/` pages (~line 69). Run `mkdocs build --strict`, using `.venv/bin/mkdocs` or a scratch venv with `mkdocs-material` if it isn't installed.
Expected: exit 0. Also run `.venv/bin/pytest tests/build/test_npm_is_not_a_distribution_channel.py -q`, since `docs/release/` is a scanned surface. It must PASS.

- [ ] **Step 5: Ledger notes**

In `specs/1.0.0/release-control/requirement-ledger.csv`, append to the `notes` field of NPM-03 and NPM-12 only. The file uses CRLF endings. Edit textually, one row at a time, and never round-trip it through a CSV library.
- **NPM-03:** ` Server-artifact half implemented on dev: Ed25519 SHA256SUMS.sig + build-provenance attestations (docs/release/bundle-signing.md); evidenced by the first signed release (0.4.7).`
- **NPM-12:** ` The @blkleg npm organization was created on 2026-09-30.`

If a note contains a comma, the field must be double-quoted. Status stays unchanged.

Run: `python3 scripts/validate_v1_release_control.py && git diff --stat specs/`
Expected: the validator is OK, and exactly 2 lines changed.

- [ ] **Step 6: Commit**

```bash
git add docs/release/bundle-signing.md docs/installation/security-verification.md docs/installation/upgrading.md mkdocs.yml Makefile .claude/skills/cb-release/SKILL.md specs/1.0.0/release-control/requirement-ledger.csv
git commit -m "docs(release): bundle signing runbook, verification steps and ledger notes"
```

When the plan is done, update its row in `plans/README.md` to say so.

---

### Task 8: Maintainer actions and acceptance (human, not an agent)

These steps use the real private key, so the maintainer runs them. An agent must not generate, handle or print it.

- [ ] **Step 1: Create the key and the environment** — key generated and trusted (`5f2aa2afdb764f86`, aee0c20c + ef267cbb); environment, secret and offline backup outstanding

Follow *One-time setup* in `docs/release/bundle-signing.md`: `make release-signing-key`, then append the public line, update the heredoc and run the sync. Then create the environment and branch policy, set the secret, back the key up offline and shred the working copy. Commit only the public line and its two synced copies:

```bash
git add deploy/keys/release-bundle-keys.txt deploy/lib/bundle-signature.sh install.sh
git commit -m "chore(release): trust the first release bundle key"
.venv/bin/pytest tests/build/test_bundle_signature_lib.py tests/build/test_installer_ui_inline_matches_library.py -q
```

- [x] **Step 2: Local installer acceptance on a fresh LXC** — run 2026-09-30 on `cb-test1` (Ubuntu 26.04.1, Proxmox LXC) with `install.sh` from `ef267cbb`+fixes (trusting key `5f2aa2afdb764f86`) and a bundle built by `make build-in-release-image`: case c refused at the signature ("does not verify … Keys tried: 5f2aa2afdb764f86"), case d refused at the hash ("SHA256 mismatch"), both before any change to the host; case b verified the hash and installed. Case a (no files, warn-and-continue) not run.

Build a bundle with `make build-in-release-image`. Copy `dist/native/circuit-breaker_*_linux_amd64.tar.gz`, `install.sh` and (per case) the files below to a fresh LXC, then run `sudo bash install.sh --local-bundle <tarball> --unattended --no-tls` for each case:

| Case | Next to the tarball | Expected |
|---|---|---|
| a | nothing | warns `UNVERIFIED`, installs |
| b | `SHA256SUMS` from `dist/native/*.sha256`, rewritten as `<hash>  ./<name>` | warns no signature, checks the hash, installs |
| c | that `SHA256SUMS` plus a `SHA256SUMS.sig` made with a throwaway key (`scripts/release_signing_key.sh /tmp/t.pem 0.4.7` then `scripts/ci/sign_release_sums.sh /tmp/t.pem SHA256SUMS SHA256SUMS.sig`) | refuses: signature does not verify, and names the trusted key id |
| d | case b with one byte of the tarball changed | refuses: SHA256 mismatch |

Case c is the fail-closed proof on a real host. The accept path with the real key is proven by the release run.

- [ ] **Step 3: The first signed candidate**

After `dev` is merged to `main`, run `make release-candidate` from `main`. In the run:
- **Stage Draft Release** shows "SHA256SUMS signed by trusted key <id>".
- **Verify the candidate before promoting** shows the draft signature, both tarball hashes and both `gh attestation verify` results.
- After approval, **Verify the published release** shows "published release signed by trusted key <id>".

Then run `curl -fsSL https://raw.githubusercontent.com/BlkLeg/CircuitBreaker/main/install.sh | sudo bash` on a fresh LXC. It must print "Signature verified (key <id>)".

## Self-review record

- **Spec coverage.** Each part of the spec maps to a task:

  | Spec item | Task |
  |---|---|
  | Decisions 1–5 | 1, 2, 5, 8 |
  | Trust model: key file format and id, embedded list and parity, rotation, try-each-key | 2, 3, 7 |
  | Release pipeline: Stage environment, umask'd key file, verify against committed list, attest, upload | 5 |
  | promote-verify with signature, hashes and `gh attestation verify` | 6 |
  | post-publish | 6 |
  | Installer: OpenSSL 3 check, signature then hash, every row of the table, `--skip-signature`, attestation when `gh` is present | 4 |
  | Air-gap and upgrade docs | 7 |
  | Key setup and compromise | 7, 8 |
  | Testing (throwaway keys, parity, release graph, end to end) | 1–6, 8 |
  | Rollout, including the NPM-12 note | 7, 8 |
  | npm CLI contract | Out of scope; CLI sub-plan 02 implements it |

- **Deviation from the spec: attestation in `install.sh` uses `gh` only.** The spec says "`gh` or `cosign`", but cosign cannot fetch a GitHub attestation without the GitHub API bundle that `gh` downloads, so the `cosign` branch would need `gh` anyway. Recorded here for the reviewer; the spec's "never required" rule is unchanged.
- **Placeholder scan.** Every code step carries its code. One lookup is left for execution time, with the command that answers it: the current `attest-build-provenance` major version.
- **Name consistency.** Each is defined once and used with the same signature everywhere:
  - `cb_release_keys`, `cb_verify_sums_signature`, `cb_verify_sums_entry`, `cb_release_requires_signature`, `_cb_embedded_release_keys` and `CB_FIRST_SIGNED_RELEASE` (Task 2);
  - `cb_check_bundle`, `cb_fetch_release_asset` and `cb_check_attestation` (Task 4);
  - `scripts/ci/sign_release_sums.sh` and `scripts/release_signing_key.sh` (Task 1).
- **Review Focus.** Each item has its test:
  1. `test_an_installer_that_trusts_no_keys_fails_closed` (Task 4);
  2. `test_a_renamed_local_bundle_names_the_expected_file` (Task 4);
  3. `test_crlf_and_whitespace_around_the_signature_are_tolerated` (Task 2);
  4. `test_air_gap_never_calls_gh` (Task 4);
  5. `test_sums_signed_for_another_release_do_not_cover_this_tarball` (Task 4).
