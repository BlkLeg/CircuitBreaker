# Changelog

All notable changes to Circuit Breaker are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
while pre-1.0 (a `0.MINOR.PATCH` bump can still carry a breaking change).

**Policy:** starting with 0.4.2, entries here are generated from each release's
notes going forward. Releases before 0.4.2 have narrative write-ups under
[`docs/updates/`](docs/updates/) instead of an entry here.

## [Unreleased]

## [0.4.2] - 2026-09-07

`v0.4.0` (tagged 2026-08-31) is the last version actually cut and shipped on
`main`. A large agent/production-readiness effort has been landing on `dev`
since then, but the project's own tracking
(`docs/evidence/2026-08-30-production-readiness-route.md`) carries much of it
as "fixed in working tree, release evidence pending" or "gated, not fixed",
and aims its own next milestone at 0.5.0 — so it is not listed here to avoid
claiming a shipped state that isn't backed by release evidence yet. This entry
covers only the commits below, which are complete, self-contained, and
directly verifiable in this tree.

### Fixed

- The Sigma map renderer requested a `format: 'sigma'` payload the backend has
  never supported, so it silently rendered nothing (`45a49a66`).
- Map node deletion was restored: the delete-target lookup indexed a `Map`
  with bracket syntax, which always read `undefined` and silently disabled
  delete for every node (`abd59cc6`).
- Map tag and hardware-role filters are now composed as a single predicate;
  previously the hardware-role filter's effect ran after the tag filter's and
  overwrote its result for hardware nodes (`c60d2698`).
- `useMapDataLoad` now rejects a topology response superseded by a newer
  request instead of letting a slower, older response overwrite the canvas
  with stale nodes and edges (`97570315`).
- The Cloud View toggle no longer races the map's own topology re-fetch,
  which could apply the toggle's node transform twice with no ordering
  guarantee (`3a8c9213`).
- The Sigma map renderer is now scoped to the active map and its include
  tokens; it previously fetched an unscoped graph and built its type filter
  from the wrong keys, so it could show entities from other maps (`ab575787`).
- The UI no longer loads its web fonts from Google Fonts — they are
  self-hosted, so a `CB_AIRGAP=true` install no longer makes an outbound font
  request (`e0223e8b`, `9d7651c2`).

### Changed

- Saved map layouts are now versioned behind a `layoutCodec`
  (`schemaVersion: 2`). It reads both older on-disk shapes and writes view
  options nested and flat, so a self-hoster running a rebuilt frontend against
  an unrestarted server, or rolling back a release, keeps reading a layout it
  understands (`454f70c6`).
- `scripts/check_version_parity.py` gained `--write`, and `make version-sync`
  now propagates a `VERSION` bump to every registered file mechanically
  instead of by hand (`ef729552`).
