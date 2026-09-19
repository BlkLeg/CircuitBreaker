"""The design tool's content-hash manifest is excused by shape, not by path.

`.superdesign/resume.json` is editor state: a map of source path to the SHA-256
of that file's contents, rewritten every time a design session runs. Gitleaks'
`generic-api-key` rule scores those hashes as credentials, so `make verify`
went red on a file holding no secret at all.

The obvious fix is the wrong one. A global `[[allowlists]]` entry with `paths`
does not narrow anything: gitleaks skips a path-allowlisted file before any
rule runs, so pairing `paths` with `regexes` — with or without
`matchCondition = "AND"` — silently means "never scan this file". Verified
against gitleaks 8.30.1: a planted enrollment token in that file was found by
the unmodified config and disappeared under every `paths` variant.

So the allowlist matches the *line*, and the line has to look like a manifest
entry — a quoted source path with a file extension, a colon, and a quoted
64-hex value. The same hash written as `CB_VAULT_KEY = "<hex>"` is not that
shape and is still a finding, in that file as in any other.

This test pins all of it: the regex must cover what the manifest really holds
today, must not cover a credential assignment carrying the identical value, and
the entry must not regrow a `paths` key.
"""

from __future__ import annotations

import re
from pathlib import Path

import tomllib

REPO = Path(__file__).resolve().parents[2]
CONFIG = REPO / ".gitleaks.toml"
MANIFEST = REPO / ".superdesign/resume.json"

#: The allowlist entry this file is about.
ALLOWLIST_ID = "superdesign-content-hash-manifest"

#: A manifest line, as the design tool writes it.
_HASH_LINE = re.compile(r'"[^"]+": "[a-f0-9]{64}"')


def _allowlist() -> dict[str, object]:
    config = tomllib.loads(CONFIG.read_text())
    entries = [a for a in config.get("allowlists", []) if a.get("id") == ALLOWLIST_ID]
    assert entries, (
        f"{CONFIG.name} has no allowlist {ALLOWLIST_ID!r}; without it a design "
        "session's own state file fails the secret gate"
    )
    assert len(entries) == 1, f"{ALLOWLIST_ID!r} is declared {len(entries)} times"
    return entries[0]


def _allowlist_regex() -> re.Pattern[str]:
    entry = _allowlist()
    regexes = entry.get("regexes")
    assert isinstance(regexes, list) and len(regexes) == 1, (
        f"{ALLOWLIST_ID!r} should carry exactly one regex; it is the whole of "
        "what this excuse covers and a second one would widen it unread"
    )
    return re.compile(str(regexes[0]))


def test_the_excuse_is_a_line_shape_and_never_a_path() -> None:
    """`paths` would turn this into "never scan that file".

    Not a style preference: gitleaks drops a path-allowlisted file before any
    rule is applied, so a `paths` key here would stop the enrollment-token rule
    from firing inside the one file this entry names — the exact regression
    tests/build/test_enrollment_token_never_shipped.py exists to prevent.
    """
    entry = _allowlist()

    assert "paths" not in entry, (
        "a `paths` key makes gitleaks skip the whole file, so every rule — "
        "including the cbe_ enrollment-token rule — stops applying to it"
    )
    assert entry.get("regexTarget") == "line", (
        "the excuse is the manifest's line shape; matching the secret alone "
        "would allowlist a bare 64-hex value everywhere in the repo, which is "
        "exactly the shape of a hex-encoded key"
    )


def test_the_regex_covers_every_hash_the_manifest_actually_holds() -> None:
    """A pattern that no longer matches what the tool writes is a gate that
    goes red again on the next design session, which is how this started."""
    if not MANIFEST.exists():
        # The manifest is committed today. If it is ever removed, the allowlist
        # becomes dead config rather than a wrong one — the other two tests
        # still hold it to its shape.
        return

    pattern = _allowlist_regex()
    lines = [
        line for line in MANIFEST.read_text().splitlines() if _HASH_LINE.search(line)
    ]
    assert lines, "no content-hash lines in the manifest; the format changed"

    uncovered = [line.strip() for line in lines if not pattern.search(line)]
    assert not uncovered, (
        f"{len(uncovered)} manifest line(s) the allowlist no longer matches, "
        f"e.g. {uncovered[0]!r} — the secret gate will fail on them"
    )


def _sample_enrollment_token() -> str:
    """A token-shaped string, minted the way the service mints one.

    Never written out and never constant: a literal `cbe_` + 43 characters in a
    tracked file is exactly what `.gitleaks.toml`'s rule fires on and what
    test_enrollment_token_never_shipped.py refuses to let anyone commit — and
    concatenating literals is no better, because CPython folds them and the
    result lands in `__pycache__` as a literal anyway, where the scanner found
    it. Random bytes cannot be folded.
    """
    import base64
    import secrets

    return "cbe_" + base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip(
        "="
    )


def test_a_real_credential_carrying_the_same_value_is_still_a_finding() -> None:
    """The value is not what is excused; the shape around it is.

    Each line below carries a hex string taken straight from the manifest, in a
    shape that means something entirely different. If any of them matched, the
    excuse would have escaped the file it was written for.
    """
    pattern = _allowlist_regex()
    digest = "b30de745b3637e084220404373f405382f9c3481122bc5a7baee00c989e759cb"

    must_not_match = [
        f'CB_VAULT_KEY = "{digest}"',
        f'  "api_token": "{digest}",',
        f'  "authorization": "{digest}",',
        f"CB_JWT_SECRET={digest}",
        f'  "password": "{digest}",',
        f'  "enroll_token": "{_sample_enrollment_token()}",',
    ]
    escaped = [line for line in must_not_match if pattern.search(line)]
    assert not escaped, f"the allowlist excuses a real credential shape: {escaped}"
