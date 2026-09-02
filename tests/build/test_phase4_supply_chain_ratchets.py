"""Phase 4 repo-policy ratchets (route findings F4, F3).

These are Tier 0 gates: they read source text, never run the app, and they
exist because each finding they cover is a *class* of defect that came back
after being fixed once.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT_SRC = REPO_ROOT / "apps" / "agent"

# The only files allowed to name cfg.TLSPin: the config struct that declares
# it, and the one resolver that turns it into a trust policy. Every dial site
# must go through link.ResolveTrust instead.
_TLS_PIN_ALLOWLIST = {
    Path("internal/config/config.go"),
    Path("internal/link/trust.go"),
}


def _go_sources() -> list[Path]:
    return [
        p
        for p in AGENT_SRC.rglob("*.go")
        if not p.name.endswith("_test.go") and "/vendor/" not in p.as_posix()
    ]


def test_no_go_source_reads_tls_pin_directly() -> None:
    """F4: cfg.TLSPin fed four dial sites — enrollment, the /link socket, its
    re-dial, and the update binary download — and nothing ever rewrote it, so
    a certificate change stranded the agent on every path at once, including
    the one that would have delivered a fix.

    One resolver (link.ResolveTrust) now owns that translation. A new
    reference to cfg.TLSPin outside the allowlist means a fifth dial site
    that will not see an advertised successor.
    """
    offenders: list[str] = []
    pattern = re.compile(r"\bTLSPin\b")
    for path in _go_sources():
        rel = path.relative_to(AGENT_SRC)
        if rel in _TLS_PIN_ALLOWLIST:
            continue
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("//"):
                continue
            if pattern.search(line):
                offenders.append(f"{rel}:{lineno}: {stripped}")
    assert not offenders, (
        "TLSPin must only be read by internal/config (which declares it) and "
        "internal/link/trust.go (which resolves it into a tlsdial.Trust). "
        "Every dial site goes through link.ResolveTrust so an advertised "
        "successor policy reaches all of them:\n  " + "\n  ".join(offenders)
    )


def test_every_dialer_and_transport_call_takes_a_resolved_trust() -> None:
    """The companion to the check above: a call site could construct a
    tlsdial.Trust literal inline and bypass the resolver without ever naming
    TLSPin. Every NewDialer/NewTransport call must be handed either
    ResolveTrust(...) or a variable, never a Trust literal."""
    offenders: list[str] = []
    call = re.compile(r"tlsdial\.New(?:Dialer|Transport)\(\s*tlsdial\.Trust\{")
    for path in _go_sources():
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            if call.search(line):
                offenders.append(f"{path.relative_to(AGENT_SRC)}:{lineno}: {line.strip()}")
    assert not offenders, (
        "Build the trust policy with link.ResolveTrust rather than an inline "
        "tlsdial.Trust literal — a literal cannot pick up an advertised "
        "successor:\n  " + "\n  ".join(offenders)
    )
