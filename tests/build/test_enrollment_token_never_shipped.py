"""No enrollment token may be committed, and the scanner must be able to find one.

Slice B mints a short-lived bearer credential that enrols an agent with no human
present. The `cbe_` prefix exists precisely so this is checkable — a rule that
does not match the format the code actually mints is a rule that will never
fire, and nobody would notice until a token was already in history.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

#: A minted token: the prefix plus 32 random bytes, base64url, unpadded.
_TOKEN_RE = re.compile(r"cbe_[A-Za-z0-9_-]{43}")


def test_no_minted_token_is_committed() -> None:
    """A real token in a tracked file outlives its TTL in every clone."""
    tracked = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split("\0")

    offenders = []
    for name in filter(None, tracked):
        path = REPO / name
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if _TOKEN_RE.search(text):
            offenders.append(name)

    assert not offenders, f"an enrollment token is committed in: {offenders}"


def _minting_constants() -> tuple[str, int]:
    """`(TOKEN_PREFIX, _TOKEN_BYTES)`, read out of the service by AST.

    Not imported: `app.services` pulls in `app.db.session`, which refuses to
    load without a database URL, and the build tier deliberately runs without
    one. Reading the literals is enough — they are what decide the format.
    """
    import ast

    source = (
        REPO
        / "apps"
        / "backend"
        / "src"
        / "app"
        / "services"
        / "agent_enrollment_tokens.py"
    ).read_text()
    found: dict[str, object] = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in ("TOKEN_PREFIX", "_TOKEN_BYTES"):
                found[name] = ast.literal_eval(node.value)
    assert "TOKEN_PREFIX" in found, "TOKEN_PREFIX is no longer a module-level literal"
    assert "_TOKEN_BYTES" in found, "_TOKEN_BYTES is no longer a module-level literal"
    return str(found["TOKEN_PREFIX"]), int(found["_TOKEN_BYTES"])


def test_the_scanner_rule_matches_the_format_the_code_mints() -> None:
    """Pins `.gitleaks.toml`'s regex against the minting code.

    The two live in different files in different languages, which is exactly
    the arrangement that drifts in silence: each looks correct on its own, and
    a mismatch shows up only as a scan that quietly passes.
    """
    import base64
    import secrets

    prefix, token_bytes = _minting_constants()
    config = (REPO / ".gitleaks.toml").read_text()

    assert prefix in config, (
        f"gitleaks has no rule mentioning {prefix!r}; a minted token would not "
        "be caught on its way into a commit"
    )

    rule = re.search(r"regex = '''(cbe_[^']+)'''", config)
    assert rule, "the cbe_ rule's regex is not in the shape this test can read"
    compiled = re.compile(rule.group(1))

    # A prefix match is not enough: a length or alphabet the rule does not
    # cover would still let every real token through. Tokens are generated the
    # way the service generates them, from the service's own constants.
    for _ in range(50):
        token = prefix + base64.urlsafe_b64encode(
            secrets.token_bytes(token_bytes)
        ).decode().rstrip("=")
        assert compiled.fullmatch(token), f"the gitleaks rule does not match {token!r}"
