"""Safe nmap argument validation to prevent command injection.

Only allowlisted flags and port specs are accepted. Forbidden shell
metacharacters are rejected.
"""

import re
import shlex

# Safe nmap flags (exact match). -O is allowed here; _sanitise_nmap_args_for_unpriv()
# strips it at runtime when CAP_NET_RAW is absent, so rejection at the allowlist level
# was redundant and prevented OS detection for privileged runs.
_NMAP_ALLOWED_FLAGS = frozenset(
    {
        "-sT",
        "-sV",
        "-F",
        "--open",
        "-T0",
        "-T1",
        "-T2",
        "-T3",
        "-T4",
        "-T5",
        "-O",
        "--osscan-limit",
        "--osscan-guess",
        "-A",
    }
)

# Forbidden in any token (command injection)
_FORBIDDEN_CHARS = re.compile(r"[;|$`()><&\\]")

# Port spec after -p: digits, commas, hyphens only (e.g. 80,443 or 1-1000)
_PORT_SPEC = re.compile(r"^[0-9,\-]+$")


def _validate_token(tok: str) -> None:
    if _FORBIDDEN_CHARS.search(tok):
        raise ValueError("nmap_arguments may not contain ; | $ ` ( ) > < & or backslash")


def _consume_tokens(tokens: list[str], i: int) -> tuple[list[str], int]:
    """Consume one or two tokens (-p + port spec or single flag). Returns (out_tokens, next_i)."""
    tok = tokens[i]
    _validate_token(tok)
    if tok in _NMAP_ALLOWED_FLAGS:
        return ([tok], i + 1)
    if tok == "-p":
        if i + 1 >= len(tokens):
            raise ValueError("nmap_arguments: -p requires a port list")
        next_tok = tokens[i + 1]
        _validate_token(next_tok)
        if not _PORT_SPEC.match(next_tok):
            raise ValueError(
                "nmap_arguments: port list after -p must be digits, commas, hyphens only"
            )
        return (["-p", next_tok], i + 2)
    raise ValueError(f"nmap_arguments: disallowed token {tok!r}")


def validate_nmap_arguments(args: str | None, max_length: int = 256) -> str:
    """Validate and return safe nmap arguments string.

    Raises ValueError if args contain forbidden characters or non-allowlisted
    tokens. Use for any user- or config-supplied nmap arguments before
    passing to nmap.
    """
    if not args or not args.strip():
        return "-T4 -F"
    s = args.strip()
    if len(s) > max_length:
        raise ValueError(f"nmap_arguments must be at most {max_length} characters")
    try:
        tokens = shlex.split(s)
    except ValueError as e:
        raise ValueError("Invalid nmap_arguments: unbalanced quotes or escapes") from e
    out: list[str] = []
    i = 0
    while i < len(tokens):
        part, i = _consume_tokens(tokens, i)
        out.extend(part)
    return " ".join(out)
