"""Blocklist text parser: hosts-file, ABP (``||domain^``), and plain-domain lines."""

from __future__ import annotations

_HOSTS_PREFIXES = frozenset({"0.0.0.0", "127.0.0.1", "::", "::1"})
_IGNORED_DOMAINS = frozenset({"localhost", "localhost.localdomain", "broadcasthost"})
_COMMENT_PREFIXES = ("#", "!", "[")


def _domain_from_line(line: str) -> str | None:
    if line.startswith("||") and line.endswith("^"):
        return line[2:-1]
    tokens = line.split()
    if not tokens:
        return None
    if tokens[0] in _HOSTS_PREFIXES:
        return tokens[1] if len(tokens) > 1 else None
    return tokens[0]


def _is_valid_domain(candidate: str) -> bool:
    if not candidate or candidate in _IGNORED_DOMAINS:
        return False
    return "." in candidate and "/" not in candidate and ":" not in candidate


def parse_blocklist(text: str) -> set[str]:
    """Extract lowercase domains from a blocklist body; comments/junk are skipped."""
    domains: set[str] = set()
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(_COMMENT_PREFIXES):
            continue
        candidate = _domain_from_line(line)
        if candidate is None:
            continue
        candidate = candidate.lower().strip(".")
        if _is_valid_domain(candidate):
            domains.add(candidate)
    return domains
