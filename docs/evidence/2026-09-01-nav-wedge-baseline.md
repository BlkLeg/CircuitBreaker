# Navigation wedge baseline — 2026-09-01

The before-baseline for H1's remediation (R1), which is **not shipped**. Reproduce
with `make nav-wedge`.

`2026-09-01-nav-wedge-baseline.json` is a distilled copy of the harness output.
The raw file lands in `apps/frontend/test-results/`, which is gitignored, so the
only copy of the release's headline quality number lived on one workstation and
would not survive a clean checkout.

## What the run measured

30 navigations, Chromium at 6× CPU throttle, `repeats: 6`.

| | |
|---|---|
| Wedges | 12 |
| Wedge rate over all navigations | 40% |
| Harness failures | 0 |
| Suspense fallbacks seen | 0 |
| Branch taken | `router-location-never-updated`, 12/12 |
| Wedges with a pending chunk | 0 |

## The number the rate understates

Every wedge rendered `/map`, and every one of the 12 navigations that left
`/map` wedged — targets `/monitors` ×6 and `/agents` ×6, at positions 1 and 3 of
each five-step repeat, in all six repeats.

So this is not a 40% flake. It is a **100% reproducible failure of navigation
away from `/map`**, diluted to 40% by the three navigations per repeat that
start elsewhere and never wedge. `known_bugs-v1.0.0-rc.1.md` item 1 says the
same thing from the other direction: leaving the React Flow canvas is what
wedges.

## Mechanism

The URL advances through a real `navigate()` and `useLocation` never updates, so
the route tree never re-renders and the lazy import is never requested — react-
router v7 wraps navigations in `React.startTransition`, and React withholds the
transition's location update until it can commit without a fallback. All 26
routes share one `Suspense` (`App.jsx:147`), which therefore never renders.

Note that §4.4's literal H1 test — "chunk fetch pending at wedge time" — reads
false here (`wedges_with_pending_chunk: 0`), because the import never starts.

## What a user sees

On a loaded machine, clicking away from the map does nothing for at least 5.5 s.
The URL bar changes. The map stays fully opaque and interactive: no spinner, no
skeleton, no dimming. Recovery is a manual reload. The nav ring buffer records
nothing for the attempt, so an operator downloading diagnostics sees a gap
rather than a failure.

## Scope limits, stated

- The harness runs against `stubApi(page)`, so backend contribution (H2) is
  excluded by construction. This is a pure-frontend number.
- 30 navigations, against §5's stated ambition of 500 and `known_bugs`' ~180.
