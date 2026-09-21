"""Every external fetch on the install path must retry.

The v0.4.3 release build died on

    curl: (35) Recv failure: Connection reset by peer
    gpg: no valid OpenPGP data found.

fetching a GPG key from postgresql.org — a single unretried curl to a
third-party host, after Derive Version and the Tier 0 gate had already passed.

Auditing the installer for the same shape found seven such fetches and zero
retries, including the ~200MB bundle tarball itself, the SHA256SUMS the bundle
is verified against, and the identical postgresql.org key URL. The installer
version was worse than the release build's: both curl and gpg were redirected to
/dev/null, so a reset wrote an EMPTY keyring and the failure surfaced later as an
apt signature error naming nothing about the real cause.

A homelab user on a domestic connection pulling 200MB is exactly who loses this
coin flip. So the rule is mechanical: a curl that names an http(s) URL, or reads
one from a variable, retries.

Localhost polls are exempt: they already sit in until-loops whose whole purpose
is to retry, and adding curl-level retries there would multiply the timeout.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = (REPO_ROOT / "install.sh", REPO_ROOT / "deploy" / "setup.sh")

# A curl invocation that actually fetches something remote.
_CURL = re.compile(r"\bcurl\b[^\n|]*?(https?://|\$\{?[A-Za-z_][A-Za-z0-9_]*(_URL|_url)\b)")
_LOCALHOST = re.compile(r"https?://(127\.0\.0\.1|localhost)\b")
_RETRY = re.compile(r"--retry\b")


def _fetches(path: Path) -> list[tuple[int, str]]:
    """(line number, text) for each line making a remote curl fetch."""
    found: list[tuple[int, str]] = []
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = raw.strip()
        if stripped.startswith("#"):
            continue
        if not _CURL.search(raw):
            continue
        if _LOCALHOST.search(raw):
            continue
        # A curl inside a human-facing message or a CB_STAGE_DIAGS entry is text
        # for the operator to read, not a fetch this script performs.
        if re.search(r"\bcb_(fail|warn|note|detail|ok|step)\b", raw):
            continue
        if stripped.startswith('"') or "::" in stripped:
            continue
        found.append((number, stripped))
    return found


def test_the_audit_finds_fetches_at_all() -> None:
    """Guards against every assertion below passing because the regex broke."""
    total = sum(len(_fetches(p)) for p in SCRIPTS)
    assert total >= 5, (
        f"only {total} remote curl fetches detected across {[p.name for p in SCRIPTS]}; "
        "the installer makes more than that, so this matcher has drifted and the "
        "check below would pass vacuously."
    )


def test_every_external_fetch_retries() -> None:
    offenders: list[str] = []
    for path in SCRIPTS:
        for number, text in _fetches(path):
            if not _RETRY.search(text):
                offenders.append(f"{path.name}:{number}: {text[:100]}")
    assert not offenders, (
        "These fetch over the network without --retry:\n  "
        + "\n  ".join(offenders)
        + "\n\nA transient reset on a third-party host should cost seconds, not the "
        "whole install. Use: --retry 5 --retry-delay 2 --retry-all-errors "
        "--connect-timeout 15 (--retry-all-errors is what covers a connection "
        "torn down mid-transfer; plain --retry does not)."
    )


def test_the_postgres_key_fetch_is_not_silenced() -> None:
    """A swallowed key fetch writes an empty keyring and fails much later."""
    setup = (REPO_ROOT / "deploy" / "setup.sh").read_text(encoding="utf-8")
    match = re.search(r"^.*postgresql\.org/media/keys.*$", setup, re.MULTILINE)
    assert match, "the PGDG key fetch is gone — update this test if that is deliberate"
    line = match.group(0)
    assert "2>/dev/null" not in line, (
        "the PostgreSQL key fetch sends curl's stderr to /dev/null again. A reset "
        "then writes an empty keyring silently and the install fails later at "
        f"apt-get update with an unrelated-looking signature error:\n  {line.strip()}"
    )
