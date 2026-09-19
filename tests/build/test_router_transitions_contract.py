"""The app's router must keep location updates out of `React.startTransition`.

This is the static half of the fix for known_bugs item 1, the sticky-navigation
wedge: the URL advances, the rendered page does not, and only a manual reload
recovers.

react-router v7 wraps every location update in `React.startTransition` unless
told not to, while `history.pushState` has already moved the URL synchronously.
A transition is interruptible and non-urgent, so React may render it late,
discard the render, or never commit it — and the address bar and the rendered
route then disagree, with no fallback, no error boundary and nothing in the
console to say so.

Measured on this app under 6x CPU throttle, dock-click navigations: 16/40
wedges as shipped, 0/80 with `useTransitions={false}`. Removing
`AnimatePresence` entirely (16/40) and importing the routes eagerly instead of
through `React.lazy` (16/40) each changed nothing, which is why the guard is
here on the router and not on either of those.

The prop is one token. It is invisible in review, it is exactly the kind of
thing a router upgrade or a copy-paste of `<BrowserRouter>` drops, and losing it
reopens a high-severity bug that took eight months to localise the first time —
so this is a static check rather than a convention. The e2e half lives in
`apps/frontend/e2e/navigation.spec.ts`.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "apps/frontend/src"

#: Router components that own a location and therefore schedule the update this
#: rule is about. `<Routes>`/`<Route>` are not routers and are not listed.
_ROUTER_COMPONENTS = ("BrowserRouter", "HashRouter", "HistoryRouter", "MemoryRouter")

#: An opening router element, captured up to its closing `>`. Non-greedy so a
#: later `>` in the file cannot swallow unrelated markup into one match.
_ROUTER_ELEMENT = re.compile(
    r"<(" + "|".join(_ROUTER_COMPONENTS) + r")\b(?P<props>[^>]*)>",
    re.DOTALL,
)

#: `useTransitions={false}`, tolerating the whitespace a formatter may add.
_OPT_OUT = re.compile(r"useTransitions\s*=\s*\{\s*false\s*\}")


def _source_files() -> list[Path]:
    """App source only.

    Test files mount their own routers, almost always `MemoryRouter`, and they
    run in jsdom where this bug provably does not reproduce — the jsdom suites
    passed throughout the eight months item 1 was open. Holding them to the
    rule would be noise that teaches nothing.
    """
    return [
        path
        for path in sorted(SRC.rglob("*.js*"))
        if path.suffix in {".js", ".jsx"} and "__tests__" not in path.parts
    ]


def _strip_comments(text: str) -> str:
    """Remove `//` and `/* */` comments so prose cannot look like an element."""
    without_block = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return re.sub(r"^\s*//.*$", "", without_block, flags=re.MULTILINE)


def test_every_router_opts_out_of_transitions() -> None:
    offenders: list[str] = []
    for path in _source_files():
        source = _strip_comments(path.read_text(encoding="utf-8"))
        for match in _ROUTER_ELEMENT.finditer(source):
            if _OPT_OUT.search(match.group("props")):
                continue
            line = source.count("\n", 0, match.start()) + 1
            offenders.append(f"{path.relative_to(ROOT)}:{line} <{match.group(1)}>")

    assert not offenders, (
        "router(s) rendered without `useTransitions={false}`: "
        f"{offenders}. react-router v7 puts the location update inside "
        "React.startTransition by default, which reopens known_bugs item 1 — "
        "the URL advances and the page does not until a manual reload. See the "
        "comment on <BrowserRouter> in apps/frontend/src/App.jsx."
    )


def test_the_app_actually_renders_a_router() -> None:
    """Guards the rule above from passing because it found nothing to check.

    A refactor that moved the router out of `src/`, or renamed it to something
    outside `_ROUTER_COMPONENTS`, would leave the assertion above trivially
    satisfied while the app navigated with transitions back on.
    """
    routers = [
        path.relative_to(ROOT)
        for path in _source_files()
        if _ROUTER_ELEMENT.search(_strip_comments(path.read_text(encoding="utf-8")))
    ]
    assert routers, (
        "no router element found anywhere in apps/frontend/src — "
        f"test_every_router_opts_out_of_transitions has nothing to check. If the "
        f"router moved or was renamed, update _ROUTER_COMPONENTS in {Path(__file__).name}."
    )
