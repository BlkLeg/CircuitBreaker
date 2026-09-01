"""Every lazily-loaded chunk must be instrumented.

Route §4.2 lists per-chunk fetch telemetry as instrumentation the navigation
investigation depends on, and §4.4's decision tree branches on it directly: its
first YES branch is "chunk fetch pending/failed at wedge time → H1 CONFIRMED".
While the app used bare `React.lazy`, no such record existed anywhere, so H1
could only ever be reached by eliminating the other branches — which is why a
recorded wedge was once described as "taking the H1 branch" on evidence that did
not contain a single chunk entry.

A bare `React.lazy` reintroduced anywhere puts that hole back for one route, and
it would be invisible until the next investigation needed exactly that route's
record. Hence a static check rather than a convention.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "apps/frontend/src"

#: The one module allowed to call `React.lazy` — it is the wrapper every other
#: call site is required to go through.
LAZY_WRAPPER = SRC / "lib/lazyRoute.js"

#: `React.lazy(` as code. Prose mentions in comments and docstrings are not
#: call sites, and this suite would otherwise fail on the comments that explain
#: the rule.
_LAZY_CALL = re.compile(r"React\.lazy\s*\(")


def _source_files() -> list[Path]:
    return [
        path
        for path in sorted(SRC.rglob("*.js*"))
        if path.suffix in {".js", ".jsx"} and "__tests__" not in path.parts
    ]


def _strip_comments(text: str) -> str:
    """Remove `//` and `/* */` comments so prose cannot look like a call."""
    without_block = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return re.sub(r"^\s*//.*$", "", without_block, flags=re.MULTILINE)


def test_react_lazy_is_only_called_through_the_instrumented_wrapper() -> None:
    offenders: list[str] = []
    for path in _source_files():
        if path == LAZY_WRAPPER:
            continue
        source = _strip_comments(path.read_text(encoding="utf-8"))
        if _LAZY_CALL.search(source):
            offenders.append(str(path.relative_to(ROOT)))

    assert not offenders, (
        "bare React.lazy() call sites, which produce no chunk-fetch record: "
        f"{offenders}. Use `lazyRoute(name, () => import(...))` from "
        "src/lib/lazyRoute.js so §4.4's decision tree can distinguish a stalled "
        "chunk (H1) from a blocked main thread (H4)."
    )


def test_the_wrapper_still_wraps_react_lazy() -> None:
    """Guards the exemption above from becoming vacuous.

    If `lazyRoute` stopped calling `React.lazy`, the rule would still pass
    while every route loaded eagerly.
    """
    source = LAZY_WRAPPER.read_text(encoding="utf-8")
    assert _LAZY_CALL.search(_strip_comments(source)), (
        "src/lib/lazyRoute.js no longer calls React.lazy; it is the only module "
        "permitted to, and the rest of the app routes through it."
    )


def test_every_route_chunk_is_declared_through_the_wrapper() -> None:
    """`App.jsx` holds the route table; none of it may load uninstrumented."""
    app = _strip_comments((SRC / "App.jsx").read_text(encoding="utf-8"))
    lazy_route_declarations = re.findall(r"=\s*lazyRoute\(", app)
    assert len(lazy_route_declarations) >= 25, (
        "App.jsx declares fewer instrumented lazy routes than expected "
        f"({len(lazy_route_declarations)}); a route was either un-lazied or "
        "converted back to a bare import without updating this floor."
    )


def test_the_chunk_record_reaches_the_diagnostics_buffer() -> None:
    """The wrapper's telemetry has to land somewhere a harness can read."""
    wrapper = LAZY_WRAPPER.read_text(encoding="utf-8")
    assert "recordChunk" in wrapper and "closeChunk" in wrapper, (
        "lazyRoute no longer opens and settles a diagnostics entry per chunk."
    )
    buffer_source = (SRC / "lib/diagnosticsBuffer.js").read_text(encoding="utf-8")
    for symbol in ("export function recordChunk", "export function closeChunk"):
        assert symbol in buffer_source, f"diagnosticsBuffer.js no longer exports {symbol}"
    assert "chunkRing.entries()" in buffer_source, (
        "chunk entries are recorded but not returned by getEntries(), so the "
        "Playwright wedge harness cannot read them back."
    )
