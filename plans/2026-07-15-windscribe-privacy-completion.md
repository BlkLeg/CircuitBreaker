# Windscribe Privacy & Threat Completion — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the mock Windscribe skeleton with a real privacy pipeline: public-blocklist threat feed, hostile-network checks, pure scoring rules, snapshot-backed endpoints, scan/periodic triggers, and a Privacy page.

**Architecture:** Five backend units (`threat_feed`, `network_checks`, `privacy_rules`, `privacy_score` orchestrator, triggers) writing `network_privacy_snapshots`; endpoints serve snapshots only. Frontend gets a `/privacy` page, slimmed Map overlays, and a Settings card.

**Tech Stack:** FastAPI + SQLAlchemy + Alembic, Redis (feed cache), httpx, APScheduler, React (jsx) frontend, pytest + testcontainers, vitest.

**Spec:** `specs/2026-07-15-windscribe-privacy-completion-design.md`

## Global Constraints

- Deduction shape everywhere: `{"rule_id", "title", "points", "severity": "critical"|"warning"|"info", "remediation_id", "hardware_id": int|null}`
- Scores start at 100, clamp 0–100. Grades: A ≥90, B ≥80, C ≥70, D ≥60, F <60.
- Network score = 100 − check points − device aggregate (10 largest device deductions, capped −40). Any `critical` check clamps score ≤55.
- Endpoints: 200 with `{"enabled": false}` / empty state when disabled or no snapshot — never errors for "not evaluated".
- Checks that error report `unknown`, never hostile. Feed fetch failure serves last cache with `stale: true`. `CB_AIRGAP` ⇒ feed `unavailable`, feed rules skipped.
- New table must be added to `0001_init._EXCLUDED_TABLES` in the same commit (fresh-install convention).
- cb-code-quality: named constants in `core/constants.py`, specific-exception handling on all I/O, small focused files/functions.
- cb-security-hardening: feed URLs HTTPS-only + `reject_ssrf_url`-style validation, timeout + response-size cap.
- No terminal-command config: settings changes ship through app-settings GET/PUT (in-app principle).
- Periodic job is **pinned to the API-process APScheduler** (same rails as `cve_sync` / `integration_sync_job`), not a new unified-worker type — no supervisord/compose changes needed; job checks `windscribe_enabled` and feed age at runtime so toggles apply without restart.

---

### Task 0: Branch
- [ ] `git checkout -b feat/windscribe-privacy-completion` (off `dev`, clean tree)

### Task 1: `privacy_rules.py` — pure ruleset (TDD)
**Files:** Create `apps/backend/src/app/services/privacy_rules.py`, `apps/backend/tests/services/test_privacy_rules.py`. Add rule constants to `app/core/constants.py`.

**Produces:**
- `DEVICE_RULES` / `NETWORK_CHECK_RULES` catalogs (rule_id → title, points, severity, remediation_id)
- `evaluate_device(hardware_id: int | None, role: str | None, open_ports: set[int]) -> list[dict]` (Deduction list)
- `evaluate_network(device_deductions: list[dict], check_results: list[dict]) -> dict` → `{"score": int, "grade": str, "deductions": [Deduction], "checks": [check]}`
- `grade_for(score: int) -> str`, `score_device(deductions) -> int`

**Rules v1:** `telnet_open` −15 critical (port 23); `ftp_open` −8 warning (21); `legacy_smb_netbios` −8 warning (137/138/139); `upnp_exposed` −10 warning (1900/5000). Gateway roles {router, firewall, gateway} escalate severity one level and points ×1.5 (ceil). Network checks: `captive_portal` −10 warning, `dns_tamper` −30 critical, `dns_filtering_absent` −5 info; `unknown`/`ok` checks contribute no deduction.

**Tests:** per-rule hit/miss, gateway escalation, device score floor 0, aggregate top-10/−40 cap, critical clamp ≤55, grade bands, empty inputs → 100/A.

### Task 2: `threat_feed.py` — pluggable feed + Redis cache (TDD)
**Files:** Create `apps/backend/src/app/services/threat_feed.py`, `tests/services/test_threat_feed.py`, fixture blocklist files under `tests/services/fixtures/`. Constants in `core/constants.py` (`FEED_CACHE_KEY`, `FEED_FETCH_TIMEOUT_S = 15`, `FEED_MAX_RESPONSE_BYTES = 5_000_000`, default URLs).

**Produces:**
- `ThreatFeed` dataclass: `malware/trackers/botnets: set[str]`, `fetched_at: str | None`, `source: str`, `stale: bool`, `available: bool`
- `FeedProvider` protocol: `async fetch() -> ThreatFeed`
- `PublicBlocklistProvider(urls: dict[str, list[str]])` — parses hosts-file (`0.0.0.0 domain`), plain-domain, and ABP (`||domain^`) lines; ignores comments/localhost
- `async get_feed(refresh_hours: int) -> ThreatFeed` — Redis-cached (JSON), refetch only when older than `refresh_hours`; fetch failure ⇒ cached feed with `stale=True`; no cache + failure ⇒ `available=False`; `CB_AIRGAP`/`airgap` config ⇒ `available=False`, no outbound attempt
- URL guard: `https` scheme required + `reject_ssrf_url`; streaming download with byte cap

**Tests:** parser fixtures (all three formats), https-only rejection, cache hit/stale/refresh flows with fake Redis (`AsyncMock`), airgap short-circuit, size cap.

### Task 3: `network_checks.py` — hostile-network detection (TDD)
**Files:** Create `apps/backend/src/app/services/network_checks.py`, `tests/services/test_network_checks.py`. Constants: `CAPTIVE_PORTAL_URL`, `DNS_CANARIES` (e.g. `one.one.one.one → {1.1.1.1, 1.0.0.1}`, `dns.google → {8.8.8.8, 8.8.4.4}`), `DNS_SAMPLE_SIZE = 3`.

**Produces:** each check returns `{"check_id", "status": "ok"|"warning"|"critical"|"unknown", "evidence": str, "detected_at": iso}`.
- `check_captive_portal()` — GET generate_204, no redirects; 204 ⇒ ok, other/redirect ⇒ warning, error ⇒ unknown
- `check_dns_tamper()` — resolve canaries via `asyncio.get_running_loop().getaddrinfo`; any mismatch ⇒ critical, resolution errors ⇒ unknown
- `check_dns_filtering(feed)` — skip (`unknown`, evidence "feed unavailable") when feed unavailable; sample malware domains; any resolve ⇒ warning-severity rule fires as `info` finding (status `warning` maps to rule severity info); none resolve ⇒ ok
- `run_all_checks(feed) -> list[dict]`
- Absorbs `check_connectivity` role from `windscribe_intel.py` (which Task 6 deletes).

**Tests:** mocked httpx/resolver per status incl. unknown-on-error and feed-unavailable skip.

### Task 4: snapshot model + migration
**Files:** Modify `app/db/models.py` (add `NetworkPrivacySnapshot`), `migrations/versions/0001_init.py` (add `network_privacy_snapshots` to `_EXCLUDED_TABLES`), create new alembic revision `xxxx_network_privacy_snapshots.py` (down_revision = `21f5eaea0483`).

Columns: `id` PK, `score int not null`, `grade varchar(1) not null`, `deductions JSONB`, `checks JSONB`, `created_at timestamptz default now`.

**Verify:** alembic upgrade on a fresh Postgres testcontainer succeeds from empty (fresh-install convention), plus normal test suite.

### Task 5: `privacy_score.py` — orchestrator rewrite (TDD)
**Files:** Rewrite `app/services/privacy_score.py`, create `tests/services/test_privacy_score.py`.

**Produces:**
- `async recompute_all(db: Session) -> dict | None` — None when `windscribe_enabled` is false. Loads hardware + latest matched `scan_results` ports per device → `evaluate_device` → persist `hardware.privacy_score`, `hardware.threat_profile` (Deduction list), `privacy_score_history` rows → `get_feed` → `run_all_checks` → `evaluate_network` → insert one `network_privacy_snapshots` row. Returns snapshot dict.
- `async run_privacy_periodic_job() -> None` — APScheduler entrypoint: opens session, honors `windscribe_enabled`, refreshes feed per `windscribe_feed_refresh_hours`, runs checks, writes snapshot (device scores only refreshed on scan hook).
- Kills the dict-vs-tuple unpack bug by returning/storing one standardized shape.

**Tests:** recompute persists device + snapshot rows with standardized shape; disabled ⇒ no-op; rule engine fed from scan_result ports.

### Task 6: endpoint rewrite + settings exposure + retire mock
**Files:** Rewrite `app/api/windscribe.py`; modify `app/schemas/settings.py` (add `windscribe_enabled: bool = True`, `windscribe_feed_refresh_hours: int = 1` to Read + Update models); delete `app/services/windscribe_intel.py`; create `tests/api/test_windscribe_api.py`.

**Contracts (all authed, snapshot-served, never compute on request):**
- `GET /network/privacy-score` → `{"enabled", "score", "grade", "deductions", "checked_at", "history": [{"score","at"}]}`; no snapshot/disabled ⇒ `{"enabled": false}`-style empty state (200)
- `GET /network/threat-alerts` → `{"status": "safe"|"warning"|"critical"|"unknown", "alerts": [{"check_id","severity","detail","detected_at"}]}`; status = worst check status (all ok ⇒ safe; else critical > warning > unknown); disabled/no snapshot ⇒ `{"status": "unknown", "alerts": [], "enabled": false}`
- `GET /devices/{id}/threat-profile` → `{"hardware_id", "score", "deductions"}` from stored columns; 404 only for missing hardware

**Tests:** three shapes + disabled/empty states + auth required.

### Task 7: triggers
**Files:** Modify `app/services/discovery_service.py` (helper `_schedule_privacy_recompute()`, called after both "completed" finalize sites — fire-and-forget task, own try/except, scoring bug can never fail a scan); modify `app/main.py` scheduler block (add `privacy_periodic` IntervalTrigger job, 15-min cadence, runtime-gated). Create `tests/services/test_privacy_triggers.py` (hook failure isolation; periodic job honors disabled flag).

### Task 8: frontend — API client, remediation guides, Privacy page, nav
**Files:** Modify `apps/frontend/src/api/windscribe.js`; create `src/data/remediationGuides.js` (map `remediation_id → {title, steps[], links[]}` for: `disable_telnet`, `disable_ftp`, `disable_legacy_smb`, `disable_upnp`, `captive_portal_info`, `dns_tamper_response`, `setup_dns_filtering` (ControlD/Windscribe R.O.B.E.R.T.)); create `src/pages/PrivacyPage.jsx` (score card + grade + trend, severity-grouped deduction list w/ remediation drawer, network-check strip, flagged-devices table → HardwareDetail); add `/privacy` route in `App.jsx`, Security nav group entry + NAV_MAP + DEFAULT_ORDER in `src/data/navigation.js`; 60 s refetch interval on the page.

### Task 9: frontend — slim overlays, HardwareDetail, Settings card
**Files:** Rewrite `components/security/PrivacyScoreWidget.jsx` (compact pill: score + grade, click → `/privacy`, refetch on scan-completion events already surfaced in MapPage); rewrite `components/security/HostileNetworkBanner.jsx` (renders only when `status` is `warning`/`critical`, styled by severity); update `components/details/HardwareDetail.jsx` threat section to Deduction shape (`deductions`, not `profile`); add Privacy/Windscribe card to Settings (toggle + refresh hours via app-settings PUT).

### Task 10: frontend tests + verification
**Files:** Create/extend `src/__tests__/` — banner safe/warning/critical, score pill render, existing map-page test updates.

**Final verification:**
- `pytest` backend suite (postgres-test skill procedure)
- Fresh-DB alembic upgrade check
- `npx vitest run` frontend
- Lint/complexity gates per cb-code-quality
