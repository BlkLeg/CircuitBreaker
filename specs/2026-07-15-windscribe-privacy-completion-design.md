# Windscribe Integration — Privacy & Threat Completion Design

**Date:** 2026-07-15
**Status:** Approved for planning
**Author:** Shawnji (with Claude)
**Supersedes / completes:** `specs/2026-07-14-windscribe-integration-design.md` (original draft). The deprecations (racks/status/webhooks) and DB schema from that draft already shipped in `da7b0ed5`; this spec designs the remaining work.

## Problem

The Windscribe WIP shipped the skeleton — endpoints, DB columns, dashboard widgets — but the substance is missing or wrong:

- The threat feed is a hardcoded mock ("we don't have an API key").
- `windscribe_enabled` / `windscribe_feed_refresh_hours` settings exist in the DB but nothing reads them.
- `/network/threat-alerts` returns the raw (mock) feed, so the Hostile Network banner **always** shows.
- None of the hostile-network detections exist (captive portal check exists but is never called; DNS-tamper detection is unwritten).
- The scoring ruleset is a placeholder ("MAC visible" −10) and only runs on-demand per device; the network score is an average of whatever history rows happen to exist.
- `/devices/{id}/threat-profile` mis-unpacks the service's dict return (`score, profile = res` yields the key strings).
- No deductions, no remediation, no feed caching, no recompute triggers.

## Decisions (settled during brainstorming)

1. **Data source:** free public blocklists (Hagezi threat list, OISD, ControlD free malware list; URLs configurable) behind a pluggable `FeedProvider` interface. No API key required; a keyed Windscribe/ControlD provider can be added later without touching consumers.
2. **Device badges:** scan-derived risk only. We badge what scans prove (risky services, gateway posture). No passive traffic/DNS capture in this design; the feed's device-level role is deferred.
3. **Compute cadence:** recompute on discovery-scan completion + a periodic worker job for lightweight network checks and feed refresh.
4. **Remediation:** guided in-app instructions (static content keyed by `remediation_id`), not fake 1-click fixes.
5. **UI surface:** new Privacy page under the Security nav group; Map keeps a compact score pill and a banner that appears only on real alerts.
6. **Pipeline architecture:** scan-finalize hook + periodic job on the existing unified-worker rails; Redis-cached feed; pure rules module. (Rejected: on-demand-only computation — stale alerts, spotty history; NATS event-driven — unneeded machinery for millisecond-scale scoring.)

## Backend Architecture

Five units, one responsibility each:

### 1. `app/services/threat_feed.py` — pluggable intel source

- `FeedProvider` protocol: `async fetch() -> ThreatFeed`. `ThreatFeed` carries category sets (`malware`, `trackers`, `botnets`) plus `fetched_at` and `source` metadata.
- `PublicBlocklistProvider`: downloads the configured blocklist URLs, parses domain lists into the category sets. Defaults: Hagezi threat feed, OISD small list, ControlD free malware list. URLs are configuration, not code.
- **Caching:** parsed feed stored in Redis; refreshed only when older than `windscribe_feed_refresh_hours`. Fetch failure ⇒ serve last cached feed flagged `stale: true`; never a hard error.
- **Security:** outbound URLs validated through the existing `url_validation` guard; HTTPS only; request timeout and response-size cap enforced.
- **Airgap:** when `CB_AIRGAP` is set, no outbound fetch is attempted; the feed reports `unavailable` and feed-dependent rules are skipped (not scored as failures).
- Retires `windscribe_intel.py` (mock feed removed; `check_connectivity` moves to `network_checks.py`).

### 2. `app/services/network_checks.py` — hostile-network detection

Each check returns `{check_id, status: ok|warning|critical|unknown, evidence, detected_at}`. A check that itself errors (no connectivity) reports `unknown` — we never fabricate "hostile".

- `captive_portal`: GET a generate_204 endpoint; non-204 or redirect ⇒ `warning`.
- `dns_tamper`: resolve canary domains with known-stable answers; mismatch ⇒ `critical`.
- `dns_filtering_absent` (feed-powered): resolve a small sample from the feed's malware set; if they resolve normally, the network has no DNS-level malware blocking ⇒ informational finding whose remediation guide is the Windscribe/ControlD R.O.B.E.R.T. setup. Skipped when the feed is unavailable.

### 3. `app/services/privacy_rules.py` — pure ruleset

No I/O. Rules are catalog entries (stable `rule_id`, title, points, severity, `remediation_id`) plus pure functions:

- `evaluate_device(device, scan_data, feed) -> list[Deduction]`
- `evaluate_network(device_results, check_results) -> NetworkScore`

**Deduction shape (used verbatim everywhere — DB, API, frontend):**
`{"rule_id": str, "title": str, "points": int, "severity": "critical"|"warning"|"info", "remediation_id": str, "hardware_id": int|null}`

**v1 device rules** (provable from stored scan results/services):

| rule_id | points | severity |
|---|---|---|
| `telnet_open` | −15 | critical |
| `ftp_open` | −8 | warning |
| `legacy_smb_netbios` | −8 | warning |
| `upnp_exposed` | −10 | warning |

Devices with a gateway/router hardware role escalate severity/points (a router with telnet open is worse than a printer).

**v1 network checks:** `captive_portal` (−10, warning), `dns_tamper` (−30, critical), `dns_filtering_absent` (−5, info).

**Scoring math:** device and network scores start at 100, subtract points, clamp 0–100. Grades: A ≥90, B ≥80, C ≥70, D ≥60, F <60. Network score = 100 − network-check points − device aggregate, where the device aggregate is the sum of the **10 largest** device deductions capped at **−40 total** (volume alone cannot zero the score). If any network check is `critical`, the network score is additionally clamped to at most 55 (F band) regardless of the rest.

**Badges:** a device's badge severity = max severity among its deductions. `hardware.threat_profile` stores the device's deduction list.

### 4. `app/services/privacy_score.py` — orchestrator (rewritten)

`recompute_all(db)`: load devices + latest scan/service data → run rules → persist per-device `hardware.privacy_score` / `threat_profile` + `privacy_score_history` rows → run/collect network checks → write one `network_privacy_snapshots` row. Fixes the dict-vs-tuple return bug by construction (single standardized shape).

### 5. Triggers

- **Scan-finalize hook** in `discovery_service` (success path): fire-and-forget recompute wrapped in its own try/except — a scoring bug must never fail a discovery scan.
- **Periodic job** in the existing unified-worker framework: network checks + feed refresh honoring `windscribe_feed_refresh_hours`. (The implementation plan pins which worker type hosts it.)
- `windscribe_enabled = false` disables both triggers; endpoints return their `disabled` state.

## Data Model

- **New table `network_privacy_snapshots`:** `id`, `score int`, `grade char(1)`, `deductions JSONB`, `checks JSONB`, `created_at timestamptz`. Migration **must** add the table to `0001_init`'s `_EXCLUDED_TABLES` in the same commit (fresh-install convention).
- `privacy_score_history` unchanged. `hardware.threat_profile` standardizes to the Deduction list shape.

## API Contracts

All under authed `/api/v1` (standard auth for reads; settings mutation admin-only). When disabled or no snapshot exists, endpoints return 200 with `{"enabled": false}` / empty state — the UI renders "not evaluated", not an error.

- `GET /network/privacy-score` → `{"enabled", "score", "grade", "deductions": [Deduction], "checked_at", "history": [{"score", "at"}]}` — served from the latest snapshot, never computed on request.
- `GET /network/threat-alerts` → `{"status": "safe"|"warning"|"critical"|"unknown", "alerts": [{"check_id", "severity", "detail", "detected_at"}]}` — banner binds to `status`, fixing the always-on banner.
- `GET /devices/{id}/threat-profile` → `{"hardware_id", "score", "deductions": [Deduction]}`.
- `windscribe_enabled`, `windscribe_feed_refresh_hours` exposed through the existing app-settings GET/PATCH (in-app toggle; no terminal commands).

## Frontend

- **Privacy page** (`/privacy`, Security nav group, admin-gated like its siblings): score card with grade + trend from snapshot history; deduction list grouped by severity, each opening a remediation drawer; hostile-network status strip; flagged-devices table linking to HardwareDetail.
- **Remediation guides:** static frontend content map `remediation_id → {title, steps[], links[]}` (ControlD/Windscribe setup, router hardening, service disabling). i18n-ready; no backend round-trip.
- **Map overlays slim down:** compact score pill (score + grade, click → `/privacy`); `HostileNetworkBanner` renders only when `status !== "safe"`, styled by severity.
- **HardwareDetail:** threat section renders the standardized Deduction shape.
- **Settings:** Privacy/Windscribe card (enable toggle + refresh hours) via app-settings PATCH.
- **Freshness:** Privacy page refetches on mount + 60 s interval; Map pill refetches on the existing scan-completion events. No new WebSocket channel.

## Error Handling Summary

| Failure | Behavior |
|---|---|
| Feed fetch fails | Serve cached feed, `stale: true` info line |
| No cache + airgap/disabled | `{"enabled": false}` / empty state, UI "not evaluated" |
| Network check errors | `status: "unknown"`, never "hostile" |
| Scoring raises during scan hook | Caught + logged; scan completes normally |

## Testing

- `privacy_rules`: pure unit tests, exhaustive per rule (including the gateway escalation and score caps/floors).
- `threat_feed`: parser tests against fixture blocklist files; no network in tests; cache/staleness behavior.
- `network_checks`: mocked httpx/resolver for each status including `unknown`.
- Endpoint contract tests for the three GET shapes and the disabled/empty states.
- One worker-job test (periodic path) + scan-hook test (failure isolation).
- Fresh-boot migration check (new table + 0001 exclusion) via the fresh-volume mono boot procedure.
- Frontend: banner safe/warning/critical states; score widget; existing test patterns.

## Out of Scope

- Passive DNS/traffic capture and feed-matched "device X talked to malware" badges (possible later phase; the Deduction shape and feed provider already accommodate it).
- Keyed Windscribe/ControlD API providers (drop-in later via `FeedProvider`).
- Automated remediation (router reconfiguration) — guides only.

## Phasing

1. **Backend core:** threat_feed + network_checks + privacy_rules + orchestrator + snapshot table + endpoint rewrites (kills the mock, the always-on banner data, and the unpack bug).
2. **Triggers:** scan-finalize hook + periodic worker job + settings enforcement.
3. **Frontend:** Privacy page + remediation guides + slimmed overlays + Settings card.
