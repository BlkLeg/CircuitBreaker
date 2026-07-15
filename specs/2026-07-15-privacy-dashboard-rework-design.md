# Privacy Dashboard Rework — Design

**Date:** 2026-07-15
**Status:** Approved for planning
**Author:** Shawnji (with Claude)
**Builds on:** `specs/2026-07-15-windscribe-privacy-completion-design.md` (shipped in `e85e33d1`). That work delivered the data pipeline and a plain card-list Privacy page; this spec reworks the page into a full dashboard and adds the interactive pieces (ignore, category chart, in-page scan trigger).

## Problem

The Privacy page renders as vertically stacked plain cards: a score number with a hand-rolled bar sparkline, a chip strip for network checks, a flat findings list, and a device table, with remediation in a fixed overlay drawer. The target is a dashboard: gauge-based score and check cards, 30-day trend charts, a findings-by-category chart, actionable findings (remediate/ignore), and a docked remediation rail with a re-run-scan button.

## Decisions (settled during brainstorming)

1. **Scope:** full mockup — dashboard layout, gauges, both charts, rule categories, Ignore/Remediate actions, and a Re-run Discovery Scan button. Backend additions required and in scope.
2. **Ignore semantics:** suppress + restore points. Ignored findings stop deducting from the score, move to a collapsed "Ignored" section, and can be un-ignored. Persisted per `(rule_id, hardware_id)`.
3. **Re-run scan:** triggers a full discovery scan via the existing `POST /discovery/scan`; the existing scan-finalize hook recomputes privacy afterward. No privacy-only recompute button.
4. **Charts:** Recharts (already a declared dependency, currently unused) for line/area/bar charts; hand-rolled SVG for the circular gauges. The Privacy route is lazy-loaded so Recharts stays out of the initial bundle. (Rejected: all-hand-rolled SVG — too much fiddly axis/tooltip code to own; Plotly — megabyte-scale and fights the theme.)

## Frontend

### Layout (desktop, CSS grid)

- **Row 1 — Network Privacy Score card:** large SVG arc gauge showing score + grade, colored by grade band (A/B success, C/D warning, else danger), beside a Recharts line chart of the last 30 days of snapshot scores, with a "Last evaluated …" caption. **Network Status Check card:** three small radial gauges — Captive Portal, DNS Integrity, DNS Filtering — colored by check status with an OK/warning/critical label and a "More info" link that opens the check's evidence + remediation guide in the right rail.
- **Row 2 — Findings Overview:** Recharts stacked area chart of findings counts per day over the last 30 days, one series per severity (critical/warning/info), with a legend. **Findings by Category:** Recharts horizontal bar chart of current (non-ignored) findings bucketed by rule category.
- **Row 3 — Key Findings List:** findings grouped under severity headers; each row shows title + points badge and has a context menu (⋮ button and right-click): **View Details**, **Remediate**, **Ignore**. View Details and Remediate both open the right rail (Details focuses evidence, Remediate focuses the guide). Ignored findings collapse into an "Ignored (n)" section at the bottom, each row offering **Un-ignore**. **Flagged Devices table:** device name (links to the hardware page), OS icon (from the hardware OS field when known, generic device icon otherwise), finding, points, and per-row **Remediate** / **Ignore** buttons.
- **Right rail (docked):** replaces the overlay drawer on wide screens; persistent. Shows the selected finding's remediation guide (title, severity, points, steps, links) or its check evidence; empty state reads "Select a finding to see remediation steps." Pinned at its bottom: the **Re-run Discovery Scan** button — disabled with a spinner while a scan is in flight (existing discovery status surface). On narrow screens the rail collapses: remediation falls back to a slide-over drawer and the scan button moves to the page header.

### Component structure

`PrivacyPage.jsx` becomes composition + data fetching only. Each card is its own file under `components/security/privacy/`: `ScoreGauge`, `ScoreTrendChart`, `NetworkCheckGauge`, `FindingsOverviewChart`, `FindingsByCategoryChart`, `KeyFindingsList`, `FlaggedDevicesTable`, `RemediationRail`. Existing disabled / not-evaluated empty states are preserved. Remediation guides remain the static frontend content map keyed by `remediation_id`. Implementation applies the `dataviz` skill when building the charts.

### Data freshness

Page keeps the existing fetch-on-mount + 60 s interval for `/network/privacy-score`, plus a fetch of the new history endpoint on the same cadence. Ignore/un-ignore refetches immediately after the mutation returns (the backend recomputes synchronously; no optimistic update).

## Backend

### Rule categories

Each entry in `DEVICE_RULES` / `NETWORK_CHECK_RULES` (`app/services/privacy_rules.py`) gains a `category` field, and the Deduction shape gains `category`. Taxonomy: `dns` (dns_tamper, dns_filtering_absent), `network` (captive_portal), `services` (telnet_open, ftp_open), `protocols` (legacy_smb_netbios, upnp_exposed). Deductions missing a category (old snapshots) render as `other`; the frontend chart buckets whatever categories arrive, so future rules just declare theirs.

### Findings history endpoint

`GET /network/privacy-score/history?days=30` (authed read, same as siblings) →

```json
{"days": [{"date": "2026-07-15", "score": 87, "critical_count": 0, "warning_count": 1, "info_count": 1}]}
```

One point per calendar day — the latest snapshot of that day — aggregated server-side from `network_privacy_snapshots` (score column + severity counts computed from the `deductions` JSONB). `days` is clamped to a sane max (90). The existing `history` field on `/network/privacy-score` is unchanged (Map pill keeps using it).

### Ignores

New table `privacy_finding_ignores`: `id`, `rule_id text`, `hardware_id int nullable` (null = network-level finding), `created_by`, `created_at`, unique on `(rule_id, hardware_id)`. Per the fresh-install convention, the migration adds the table to `0001_init`'s `_EXCLUDED_TABLES` in the same commit, verified with a fresh-volume mono boot.

Endpoints (admin-only, matching the page's admin gating):

- `POST /network/privacy-ignores` `{"rule_id", "hardware_id"}` → created ignore row
- `DELETE /network/privacy-ignores/{id}`

Scoring: the orchestrator (`privacy_score.recompute_all`) loads the ignore set and passes it into the pure rules module. Ignored deductions are excluded from all score math (device scores, network aggregate, badges) but persisted in the snapshot under a new `ignored_deductions` key so the UI can render the collapsed section and offer un-ignore. `GET /network/privacy-score` adds `ignored_deductions` (with each ignore's row id so DELETE can target it) alongside `deductions`.

**Recompute on toggle:** both ignore endpoints trigger an immediate lightweight recompute before returning, so the score updates in one round trip. This recompute re-runs only the pure rules against existing scan data and **reuses the latest snapshot's network-check results** — no scan and no network I/O inside the request handler.

### Scan trigger

No new backend. The button calls the existing `POST /discovery/scan` (`startAdHocScan` in `src/api/discovery.js`); the existing scan-finalize hook recomputes privacy when the scan completes.

## Error Handling & Empty States

| Situation | Behavior |
| --- | --- |
| Privacy disabled / never evaluated | Existing empty-state cards; dashboard grid not rendered |
| Fewer than 2 days of snapshot history | Charts render available points + "still collecting history" caption |
| History endpoint fails | Gauge/findings still render from `/network/privacy-score`; chart areas show a muted "history unavailable" note |
| Ignore toggle fails | Toast error; list state unchanged (no optimistic update) |
| Scan trigger fails / scan already running | Button re-enables with toast; while running: disabled + spinner |
| All findings ignored | Score shows recomputed (higher) value; Key Findings shows "No active findings" plus the Ignored section |

## Testing

- **Backend units:** category tagging on every rule; ignore-aware scoring in `privacy_rules` (ignored deductions excluded from math, present in `ignored_deductions`; badges unaffected by ignored-only findings).
- **Endpoint contracts:** history aggregation (day bucketing, multiple snapshots per day picks latest, empty DB, `days` clamp); ignore POST/DELETE including the synchronous recompute side-effect, duplicate-ignore conflict, and admin gating; `ignored_deductions` in the score payload.
- **Migration:** fresh-boot check for the new table + 0001 exclusion via the fresh-volume mono boot procedure.
- **Frontend:** extend `privacy-components.test.jsx` — gauge grade colors, findings grouping + ignore/un-ignore flow, ignored section, flagged-device row actions, rail empty/selected states, chart empty-history captions. Recharts internals get shallow render smoke tests only.

## Out of Scope

- Automated remediation (guides only, as before).
- Passive traffic/DNS capture and feed-matched device badges (unchanged from prior spec).
- Snapshot retention/pruning policy (history endpoint reads whatever exists; pruning is a later concern).
- Ignore expiry ("snooze until date") — ignores are indefinite until un-ignored.

## Phasing

1. **Backend:** rule categories → history endpoint → ignores table/endpoints + ignore-aware scoring + recompute-on-toggle → migration + 0001 exclusion.
2. **Frontend:** dashboard grid + gauges + charts (lazy route, Recharts) → key findings list with actions + ignored section → flagged devices actions → remediation rail + scan button → responsive fallback.
