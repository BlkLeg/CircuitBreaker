# Phase 0 – Repository Restructure & Dev Flow Optimization

**Pre‑requisite phase** to establish industry‑standard monorepo layout, tooling, and CI/CD hygiene before any tech shift. Optimizes performance, DX, and maintainability.

**Status**: ✅ Complete (March 2026)

## Backend

- **Monorepo Structure** (root‑level):

    ```text
    circuitbreaker/
    ├── backend/                  # FastAPI app
    │   ├── src/                  # Python package: app/
    │   │   ├── app/
    │   │   │   ├── __init__.py
    │   │   │   ├── main.py
    │   │   │   ├── core/         # scheduler, vault, nats_client
    │   │   │   ├── api/          # routers: hardware.py, discovery.py
    │   │   │   ├── services/     # business logic
    │   │   │   ├── db/           # models, engine, migrations
    │   │   │   ├── schemas/      # pydantic models
    │   │   │   └── integrations/ # idrac.py, ilo.py, snmp.py
    │   ├── tests/                # pytest
    │   ├── pyproject.toml        # ruff, pytest, poetry
    │   └── requirements.txt      # pinned deps
    ├── frontend/                 # React + Vite
    │   ├── src/
    │   │   ├── components/       # Header, Dock, Node
    │   │   ├── pages/            # MapPage, Settings, Discovery
    │   │   ├── hooks/            # useApi, useRealtime
    │   │   ├── lib/              # api_client, nats.js
    │   │   └── config/           # rackComponents.js
    │   ├── tests/                # vitest
    │   ├── vite.config.ts
    │   └── package.json
    ├── packaging/                # installers, systemd units
    ├── docs/                     # API spec, architecture.md
    ├── .github/workflows/        # CI/CD
    ├── docker-compose.yml        # dev/prod
    └── Makefile                  # dev tasks
    ```

- **Performance**:
    - Backend: `uvicorn --workers 2` default, async DB sessions.
    - Frontend: Vite code‑splitting, lazy‑load heavy pages (Discovery, Racks).

### Database

- **Migration Hygiene**:
    - Central `backend/src/app/db/migrations/` with timestamped SQL files.
    - `run_migrations()` reads/executes in order, idempotent (`IF NOT EXISTS`).
- **Multi‑DB Abstraction**:
    - `db_client.py`: Switch between SQLite (primary), DuckDB (analytics).

### Frontend

- **Performance Bundle**:
    - `vite.config.ts`: `build.rollupOptions.output.manualChunks` for vendor/core.
    - Tree‑shaking enforced, analyze bundle with `vite-bundle-visualizer`.
- **TypeScript Strict**:
    - `tsconfig.json`: `"strict": true`, API responses fully typed.

### Settings / Toggles

- **Dev Mode Toggle** (`.env` + settings):
    ```
    dev_mode: true  # Disables auth, enables hot reload, verbose logs
    ```
    

### Testing & Tooling

| Tool | Backend | Frontend | Purpose |
| --- | --- | --- | --- |
| **Formatter** | `ruff format` | `prettier` | Code style |
| **Linter** | `ruff check` | `eslint --fix` | Static analysis |
| **Tests** | `pytest -v --cov` | `vitest --coverage` | Unit/integration |
| **Type Check** | `mypy src/` | `tsc --noEmit` | Type safety |
| **Bundle Analyzer** | - | `vite build --profile` | Perf |

**Makefile**:

```makefile
dev:
  docker-compose up -d
lint:
  ruff check backend/src && npm run lint --prefix frontend
test:
  pytest backend/tests && npm run test --prefix frontend
typecheck:
  mypy backend/src && tsc --noEmit frontend
ci: lint test typecheck
```

**`.github/workflows/dev.yml`** (pre‑commit):

```yaml
name: Dev Lint/Test
on: [push, pull_request]
jobs:
  backend:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v4
    - run: make lint test typecheck
```

### CI/CD Upgrades (`.github/workflows/`)

1. **lint-test.yml**: Parallel backend/frontend lint + test + typecheck.
2. **security.yml**: `snyk test`, `trivy fs .`.
3. **docker-build.yml**: Multi‑arch build/push on tags.
4. **release.yml**: Auto‑changelog + GitHub release.

**Husky + lint‑staged** (pre‑commit hooks):

```json
// package.json (frontend)
"lint-staged": {
  "*.{ts,tsx}": ["eslint --fix", "prettier --write"],
  "*.py": ["ruff check --fix", "ruff format"]
}
```

### Verification Plan

- **Restructure**:
    - `git mv` all files to new layout, update imports.
    - `make dev` → full stack running with hot reload.
- **DX Audit**:
    - New dev: `git clone && make dev` → working in <2min.
    - `make ci` → green on clean repo.
- **Perf Baseline**:
    - Lighthouse score >90 (frontend).
    - Backend: 200 req/s on CRUD endpoints.

**Benefits**: Industry monorepo (like Supabase/Turso), 50% faster dev cycle, zero‑config lint/test, bundle <1MB gzipped. **Estimated**: 1 day restructure + 1 day tooling.
Improved Tech Stack for Circuit Breaker

- API Gateway - Caddy: Single Go binary. Automatic HTTPS. Minimal RAM overhead. CDN + Mobile Sync - [https://circuitbreaker.local](https://circuitbreaker.local/)
- Message Queue - NATS: 15MB binary. Lightweight message queue
- Rate Limiting - Slowapi
- USer Mgmt - FastAPI-Users: High customizability, less bloat than PostgreSQL.
- DuckDB - Alternative DB for when catalog entries
- Notifications - **Server-Sent Events** (SSE): Alerts, logs, status updates. **WebSockets**: Live 3D cabling, interactive DnD. **OR** NATS Core + JetStream
- Ensure Audit Logs are in seperate SQLite table to make them searchable via API
- Scan Engine Upgrade: Scapy, Custom ARP Ping. NATS + Masscan. mDNS & SSDP. Banner Grabbing via Python asyncio.
    - Needs improvement on OS Detection with heavier TCP/IP probing. sV scan, External API for vendor lookup
- Vuln Scanning with CVE-Search approach with separate SQLite DB of the NVD

## TECH_SHIFT.md - Phase Plan for Pre-v1 Stack Upgrades

This document outlines phased technical work to adopt the improved stack (Caddy, NATS, SlowAPI, FastAPI‑Users, DuckDB, upgraded scan engine, SSE/WebSockets, container runtime security) before feature freeze. It is organized by backend, database, frontend, settings/toggles, testing, and verification.

---

## Phase 1 – Foundations: Gateway, Auth, Rate Limiting

**Status**: ✅ Complete (March 2026)

### Backend

- **Caddy** added as a TLS sidecar in `docker/docker-compose.yml` with a `docker/Caddyfile`.
    - Reverse proxies to the existing frontend container on `:8080` with auto-HTTPS for `circuitbreaker.local`.
    - Security headers: HSTS, X-Content-Type-Options, X-Frame-Options, Referrer-Policy. gzip enabled.
    - Caddy exposes ports 80/443; the frontend service is now `expose`-only.
- **SlowAPI** rate limiting upgraded to configurable profiles (relaxed / normal / strict) in `core/rate_limit.py`.
    - Profile read from `AppSettings.rate_limit_profile` at call time via `get_limit(category)`.
    - Auth endpoints use `get_limit("auth")`, discovery/scan triggers use `get_limit("scan")`.
- **FastAPI‑Users** integrated alongside existing auth for dual-path support:
    - `core/users.py`: `UserManager`, `BearerTransport`, `JWTStrategy`, `AuthenticationBackend`, `FastAPIUsers[User, int]`.
    - New routers: `/api/v1/auth/jwt` (OAuth2 login/logout), `/api/v1/auth` (forgot/reset-password), `/api/v1/users` (me, patch me).
    - Backward-compat legacy routes preserved: `POST /auth/login` (JSON), `GET /auth/me`, `POST /auth/register`, `POST /auth/logout`.
    - Async SQLAlchemy session (`db/async_session.py` with `aiosqlite`) used exclusively by FastAPI-Users; all other code stays sync.
- **Legacy CB_API_TOKEN** support preserved via `middleware/legacy_token.py` running before auth.
    - `core/security.py` checks legacy admin flag → FastAPI-Users JWT (`sub` claim) → legacy JWT (`user_id` claim).
- **NATS client scaffold** added in `core/nats_client.py` with `connect()`, `publish()`, `subscribe()`, graceful no-op mode. No flows rewired—prep for Phase 3.

### Database

- **User model** extended: renamed `password_hash` → `hashed_password`, added `is_active`, `is_superuser`, `updated_at`.
    - Migration `0002_fastapi_users.sql` with backfill: `UPDATE users SET is_superuser = 1 WHERE is_admin = 1`.
- **AppSettings** activated five dormant columns: `registration_open`, `rate_limit_profile`, `dev_mode`, `audit_log_retention_days`, `audit_log_hide_ip`.

### Frontend

- **Login** sends `application/x-www-form-urlencoded` to `/auth/jwt/login`; extracts `access_token`; fetches `/auth/me` for user profile.
- **429 interceptor** added to Axios client with retry-after messaging.
- **AuthModal** updated for new flow; "Forgot Password?" link added. **ForgotPasswordModal** skeleton created.
- **LoginPage** and **OOBEWizardPage** updated to handle `access_token` response format.

### Settings / Toggles

- **SettingsPage** Authentication section expanded:
    - `registration_open` toggle, `rate_limit_profile` dropdown (Relaxed / Normal / Strict), existing `auth_enabled` and `session_timeout_hours`.
- All five new AppSettings fields readable/writable via the settings API.

### Testing

- **Backend** (`tests/test_phase1_auth.py`): bootstrap flow, legacy login + `/me`, API token bypass, password validation, AppSettings fields, rate-limit profiles.
- **Frontend** (`__tests__/AuthModal.test.jsx`): login rendering, forgot password link, form-encoded submission, 429 handling.

### Verification Plan

- Deploy behind Caddy on a staging domain, confirm TLS, SPA, and `/api/v1/health`.
- Fresh OOBE creates admin account; login/logout works cleanly.
- Audit logs record bootstrap, auth changes, and admin settings changes.
- Rate limiting returns user-friendly 429 without 5xx.

---

## Phase 2 – Data Tier Upgrades: DuckDB, Log Separation, CVE DB

### Backend

- Introduce a **secondary DuckDB** engine for analytical/catalog workloads:
    - Abstract access via a `duckdb_client` module so the rest of the app doesn’t know about the engine details.
    - Use DuckDB for heavy read‑only queries (device catalog search, metrics aggregation) to offload from SQLite.
- Create a CVE ingestion job:
    - Fetch NVD/CVE feeds periodically and store into a dedicated local DB (SQLite or DuckDB) for offline querying.
    - Provide a service function that, given OS fingerprint and software banners, returns relevant CVEs.

### Database

- Add:
    - `audit_logs` table in main SQLite (if not already), indexed on timestamp and user_id.
    - Separate SQLite or DuckDB file for **CVE database** (schema for cve_id, vendor, product, version_range, severity, summary).
- Ensure migrations are additive and guarded (`ALTER TABLE ... IF NOT EXISTS`, `CREATE TABLE IF NOT EXISTS`) as in existing plans.
### Frontend

- Expose searchable audit log view:
    - Filters by user, entity, action, and time window; backed by the dedicated audit_logs table.
- Add a basic **vulnerability insights** panel on entity detail pages:
    - Slot to show “Known CVEs” once the backend returns mappings (even if initial implementation is stubbed).

### Settings / Toggles

- Add settings for:
    - `cve_sync_enabled` (bool), `cve_sync_interval_hours` (int).
    - `audit_log_retention_days` (int) with a background cleanup task.
- UI controls under an “Advanced / Security” section:
    - Toggle to enable/disable CVE pulling and a field for retention days.

### Testing

- Unit tests:
    - Insertion/query paths for audit_logs (filter by entity, user, time).
    - CVE lookup function with mocked CVE data.
- Migration tests:
    - Fresh DB vs upgrade of existing DB, confirming audit_logs table and CVE DB are created correctly.

### Verification Plan

- Run a seeded environment with fake CVE entries:
    - Confirm entity pages surface the expected “X potential vulnerabilities” summary.
- Verify audit log API supports pagination and filtering without noticeable performance degradation on a moderate dataset.

---

## Phase 3 – Messaging & Realtime: NATS, SSE, WebSockets

### Backend

- Stand up **NATS** as the internal message bus:
    - Connect a background worker process to NATS, subscribe to subjects for scans, discovery, telemetry, and notifications.
- Define subjects and payload contracts:
    - `discovery.scan.request`, `discovery.scan.result`, `telemetry.update`, `notifications.event`.
- **Notifications & realtime transport**:
    - Implement **SSE** endpoints for:
        - Alerts, logs, status badges, discovery job progress.
    - Implement **WebSockets** for:
        - Live 3D cabling/rack updates, interactive drag‑and‑drop operations that need low latency.
- Optionally prototype NATS JetStream if durable message streams are needed (replay of logs/alerts).

### Database

- Audit/log tables already exist; tie them into NATS:
    - When high‑value events are written (alert, scan complete, new device discovered), publish a NATS message as well.

### Frontend

- SSE client:
    - A singleton event source module that subscribes to alert/log streams, updates:
        - Toast notifications.
        - Status indicators on topology and discovery views.
- WebSocket client:
    - Connect from map/rack pages to a dedicated WS endpoint:
        - Receive node position updates, cable addition/removal events, and apply them live.
- Ensure clean reconnection logic and backoff for both SSE and WebSockets.

### Settings / Toggles

- Admin toggles:
    - `realtime_notifications_enabled` (bool).
    - `realtime_transport` (enum: `sse`, `websocket`, `auto`) for future flexibility.
- UI:
    - Switch for “Live updates on this device” on telemetry/3D views, backed by a per‑user preference.

### Testing

- Backend:
    - Unit tests for NATS publisher/subscriber layers using test connections.
    - SSE endpoint tests that stream events and close gracefully.
- Frontend:
    - Tests that:
        - SSE messages update UI stores.
        - WebSocket reconnection logic works when server drops.

### Verification Plan

- In staging:
    - Trigger a discovery scan and confirm:
        - NATS receives and broadcasts events, SSE pushes progress into the UI, WebSockets update relevant views.
- Simulate NATS outage:
    - Confirm app degrades gracefully (no crashes, UI shows “realtime unavailable”).

---

## Phase 4 – Discovery Engine 2.0 & Always‑On Listener

### Backend

- Expand the scan engine as a multi‑stage pipeline:
    - **Listener (Always On)**:
        - Run a background asyncio task using **zeroconf** to listen for mDNS/SSDP advertisements and push new devices into a “discovered” queue.
    - **The Prober**:
        - NATS‑triggered task that runs **Scapy‑based ARP** scans of local subnets every 15 minutes, filling IP/MAC tables.
    - **Deep Dive**:
        - Explicit scans that leverage **masscan** + TCP service probes with asyncio:
            - Banner grabbing, protocol detection, version extraction.
        - Integrate improved OS detection (more aggressive TCP/IP probing, `sV`‑style scans) and call an external vendor lookup API when needed.
- Ensure **libpcap** is present in deployment images so Scapy and related libraries function.

### Database

- Extend existing discovery schema (scan jobs, scan results) from the v1 push plan:
    - Add fields for:
        - `banner`, `version`, `os_accuracy`, `tcp_probe_profile`, and `mdns_ssdp_signature`.
- Create a separate SQLite DB for:
    - **NVD/CVE data** (already planned in Phase 2) but link scan results to CVEs via join tables or a computed mapping table.

### Frontend

- Discovery UI upgrades:
    - Distinguish between:
        - Listener‑sourced findings (mDNS/SSDP).
        - Prober ARP sweeps (periodic).
        - Deep Dive scans (on‑demand).
    - Show OS detection confidence, banner text, and “View possible vulnerabilities” badges.
- Provide a dedicated “Live listeners” panel:
    - List active zeroconf services and their associated entities.

### Settings / Toggles

- Discovery settings:
    - `listener_enabled` (bool) for zeroconf listener.
    - `prober_interval_minutes` (int, default 15).
    - `deep_dive_max_parallel_hosts` (int) and `scan_aggressiveness` profile.
    - Toggles for each protocol: `mdns_enabled`, `ssdp_enabled`, `arp_enabled`, `tcp_probe_enabled`.

### Testing

- Backend:
    - Unit tests for:
        - Parsing mDNS and SSDP packets into structured host/service data.
        - ARP probing functions (mocked network responses).
        - Deep Dive banner and OS detection parsers.
- Functional tests in a controlled test network (or with recorded pcaps):
    - Feed known captures into the pipeline, confirm device and OS classification.

### Verification Plan

- On a test subnet:
    - Confirm:
        - Listener discovers mDNS/SSDP devices without manual triggers.
        - Prober runs at the configured interval and updates “Last Seen” timestamps.
        - Deep Dive correctly identifies banner versions and ties into the CVE database to surface candidate issues.

---

## Phase 5 – Container Runtime Security: Docker Socket Scanning

This phase activates Docker socket scanning with explicit controls, and validates that security/error events are logged consistently without leaking sensitive client IP information when masking is enabled.

### Backend

- Add a container runtime security module to scan Docker socket exposure and risky mounts:
    - Validate `/var/run/docker.sock` ownership, permissions, and active bind mounts.
    - Detect containers started with socket mounts and elevated flags (`--privileged`, broad capabilities).
    - Expose scanner service methods that return normalized findings (severity, resource, remediation hint).
- Add API endpoints for:
    - On-demand Docker socket scan trigger.
    - Recent scan result retrieval and scanner health.
- Ensure robust exception mapping for scanner paths:
    - Permission/runtime failures return controlled 4xx/5xx responses with stable error codes.
    - Every scanner failure path emits an audit event with structured metadata (error_code, stage, component).

### Database

- Add tables for runtime security scan history:
    - `container_runtime_scans` (id, started_at, finished_at, status, triggered_by, summary JSON).
    - `container_runtime_findings` (scan_id, severity, finding_type, resource, details JSON).
- Extend `audit_logs` metadata conventions:
    - Include `source=container_runtime_scanner`, `operation`, `result`, and `error_code` for failures.

### Frontend

- Add a minimal “Container Security” card/page section:
    - “Run Docker Socket Scan” action.
    - Table/list of recent findings with severity and remediation notes.
    - Clear empty/error states for environments where Docker socket is unavailable.

### Settings / Toggles

- Add security toggles:
    - `docker_socket_scanning_enabled` (bool, master switch).
    - `docker_socket_scan_interval_minutes` (int, `0` = manual only).
    - `docker_socket_scan_fail_open` (bool; if false, hard-fail critical workflows when scanner is unhealthy).
- Add audit log privacy toggle:
    - `audit_log_hide_ip` (bool, default `false`).
    - When enabled, API responses and UI views mask IPs in audit logs (for example, `192.168.1.0/24` or hashed token), while preserving internal correlation IDs.

### Error Handling & Audit Logging Thoroughness Audit

- Define a cross-cutting audit checklist covering scanner + core APIs:
    - Every non-2xx response path maps to a documented error code.
    - Every critical action and failure path writes exactly one structured audit entry.
    - Retries/timeouts/cancellations are distinguishable in both API responses and audit metadata.
    - Sensitive fields (raw secrets, full IP when `audit_log_hide_ip=true`) never appear in user-visible logs.
- Add periodic audit job/report:
    - Sample recent requests/events and report missing/duplicate audit entries.
    - Flag unclassified exceptions and endpoints with inconsistent error schemas.

### Testing

- Unit tests:
    - Docker socket scanner logic for exposed socket, safe config, and permission-denied scenarios.
    - IP masking behavior in audit log serializers when `audit_log_hide_ip` is on/off.
    - Error-to-audit mapping to ensure handled exceptions always produce expected audit records.
- Integration tests:
    - Trigger scans end-to-end and confirm findings persisted and retrievable.
    - Validate standardized error payloads and matching audit entries for forced failures.

### Verification Plan

- In staging:
    - Run scan against a known safe host and a host with intentional socket exposure.
    - Confirm severity classification and remediation notes are accurate.
- Privacy and observability checks:
    - Toggle `audit_log_hide_ip` on/off and verify API/UI output changes accordingly.
    - Confirm correlation still works via request/audit IDs without exposing raw IPs.
- Thoroughness checks:
    - Execute negative-path API tests (timeouts, permission denied, dependency unavailable) and verify complete error/audit coverage.

---

## Phase 6 – Frontend & Settings Cohesion, Perf & UX

### Backend

- Add lightweight “capability” endpoints:
    - Report which optional subsystems are enabled/configured (NATS, CVE DB, realtime, listener).
    - Let the frontend gate UI features on actual availability.

### Database

- Ensure:
    - All new settings fields (auth, realtime, discovery, security) live in the existing singleton app_settings row with guarded migrations.
- Create indexes on:
    - Audit and discovery tables based on common query patterns (time, severity, entity_id).

### Frontend

- Central **Settings HUD** rework:
    - Group toggles into logical tabs: General, Discovery, Realtime, Security, Integrations.
    - Each toggle wired to backend settings, with inline validation.
- Performance improvements:
    - Lazy‑load heavy views (Discovery, Racks, Log Insights) only when needed.
    - Use virtualization for large tables (scan results, logs).

### Topology Options Expansion

- Expand topology rendering options so operators can switch views based on task context:
    - Layout modes: `force-directed`, `hierarchical`, `rack-grid`.
    - Link rendering modes: straight, orthogonal, and bundled (for dense environments).
    - Density controls: node spacing, edge label visibility, and overlap reduction.
- Add interaction options:
    - Group by site/rack/environment, collapse/expand clusters, and pin/unpin critical nodes.
    - Quick filters for offline, degraded, and recently discovered assets.
- Bonus additions for topology map editing:
    - Draw boundaries/zones on the topology map (for site/rack/floor segmentation).
    - Draw lines/paths to represent logical links, fiber/cable runs, or custom relationship overlays.
- Persist user preferences:
    - Save selected topology mode and visualization controls per user profile.
    - Apply safe defaults for first-time users with an easy reset to defaults.
- Keep topology options capability-aware:
    - Disable or hide unsupported modes when realtime/discovery data is unavailable.
    - Show a clear reason when an option is unavailable.

### Settings / Toggles

- Finalize all new toggles into a coherent UX:
    - Provide clear descriptions and warnings (especially for scanning and realtime features).
- Add per‑user preferences for:
    - Language (if implemented), theme, and realtime enablement.

### Testing

- End‑to‑end regression suite:
    - OOBE → basic CRUD → enable auth → enable discovery → run scan → receive realtime events → review results.
- Cross‑matrix:
    - Discovery/realtime on vs off, auth on vs off (where allowed), ensuring no 500s or UI dead‑ends.

### Verification Plan

- Pre‑v1 “tech shift” release candidate:
    - Full smoke across all major flows using the existing OOBE/OE test checklist plus new coverage for:
        - Realtime events.
        - New discovery pipeline modes.
        - CVE insights and audit log search.
- Capture baseline performance metrics:
    - Time to first paint, scan job throughput, and typical memory usage with NATS/Caddy enabled.

### TECH_SHIFT.md – Phase Plan for Pre‑v1 Stack Upgrades

## Phase 7 – Password Reset Infrastructure

This phase implements secure, production-grade password reset aligned with the new FastAPI-Users + JWT + audit logging stack.

### Backend

- **Primary Strategy**: **Magic Link** (JWT‑based, stateless):
    - `POST /api/v1/auth/forgot-password` (email input):
        - Validate user exists (don't leak existence).
        - Generate one-time JWT with `{"sub": user_id, "type": "reset", "exp": +15min}`.
        - Email single clickable link: `https://circuitbreaker.local/reset?token=eyJ...`.
        - Audit log: `user_id: reset_token_issued`.
    - `POST /api/v1/auth/reset-password` (token + new_password):
        - Decode/validate JWT, ensure `type=="reset"` and not expired.
        - Validate new password strength (`zxcvbn` score >=4).
        - Update user password hash, invalidate token.
        - Audit log: `user_id: password_reset_completed`.
- **Fallback**: Admin‑only reset (`PATCH /api/v1/admin/users/:id/reset-password`):
    - Superuser generates temp password (`CbTemp2026!`), emails/forces change on login.
- **Rate Limiting**: SlowAPI: 5 attempts/10min per email/IP.
- **Email**: `emails` lib or SMTP config, HTML templates branded via settings.

### Database

```sql
-- FastAPI-Users extensions (guarded migration)
ALTER TABLE users ADD COLUMN IF NOT EXISTS force_password_change BOOLEAN DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_password_change DATETIME;
-- Optional for code fallback (not used in magic link)
ALTER TABLE users ADD COLUMN IF NOT EXISTS reset_code TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS reset_expires DATETIME;
```

### Frontend

- **Forgot Password Flow**:
    - Login page → "Forgot Password?" → email input → success toast: "Check your inbox".
    - `/reset?token=...` → auto‑decode → "Set New Password" form → success → redirect to login.
- **Admin Panel**:
    - Superuser table with "Reset Password" button → confirm → copy temp password.
- **UX Polish**:
    - Password strength meter (inline `zxcvbn` feedback).
    - Rate limit toast: "Too many attempts, try again later".
    - QR code fallback: Scan token with mobile if email fails.

### Settings / Toggles

```yaml
auth:
  reset_enabled: true                    # Master toggle
  reset_method: "magic-link"             # "magic-link" | "code" | "admin-only"
  reset_email_smtp_host: ""              # SMTP config (optional for magic link)
  reset_email_smtp_port: 587
  reset_email_from: "noreply@circuitbreaker.local"
  force_password_change_on_temp: true    # Temp passwords require immediate change
  min_password_strength: 4               # zxcvbn score (0-4)
```

- **UI**: "Security" tab → toggles + SMTP config form (test connection button).

### Testing

- **Backend Unit Tests**:
    - `forgot-password` → token generated + email called + audit logged.
    - `reset-password` → valid token updates hash + invalidates + audit logged.
    - Invalid/expired tokens → 400 + no password change.
    - Rate limit → 429 after 5 attempts.
- **Frontend E2E**:
    - Full flow: forgot → email → reset link → new password → login success.
    - Admin reset → temp password works → forced change prompt.
- **Edge Cases**:
    - Non‑existent email → no leak ("check inbox if exists").
    - Weak passwords → validation error.

### Verification Plan

- **Staging**:
    - Self‑service reset: enter email → click link → set password → login works.
    - Admin reset: superuser resets another → temp login → forced change.
    - Audit logs show full chain: `reset_token_issued` → `password_reset_completed`.
- **Security Audit**:
    - Tokens don't leak secrets, expiry enforced, no rainbow table vulns on temp passwords.
    - Email templates branded correctly, rate limits prevent brute force.
- **Offline Test**:
    - SMTP disabled → graceful fallback to admin reset or QR code.

**Magic Link** is stateless/JWT‑native (no DB codes), aligns with FastAPI-Users, and provides best UX. Rollout: admin‑only first → full magic link. **Estimated**: 1‑2 days backend + 1 day frontend.

## Phase 8 – End‑to‑End Encryption & Security Hardening

This phase implements **zero‑trust encryption** across data at rest/transit, credential vaults, and API payloads. Only user‑explicitly allowed data flows in; everything else is blocked or encrypted.

### Backend

- **Data‑at‑Rest Encryption**:
    - **Fernet (AES‑256)** vault for all secrets:
        - SNMP communities, iDRAC/iLO/SSH credentials, SMTP passwords, API keys.
        - Vault key derived from `CB_VAULT_KEY` env var or appsettings.vault_key (Fernet‑generated on OOBE).
    - Transparent encryption/decryption in services:
        
        ```python
        class EncryptedSecretsService:
            def decrypt_snmp_community(self, encrypted_value: str) -> str:
                return self.vault.decrypt(encrypted_value)
        ```
        
- **API Payload Encryption** (optional for paranoid users):
    - Support **JWE (JSON Web Encryption)** for sensitive payloads using `pyjwt`.
    - Toggle: `api_payload_encryption_enabled`.
- **Network Hardening**:
    - Caddy: HSTS, CSP headers, referrer‑policy strict‑origin.
    - FastAPI: CORS origin whitelist from appsettings.allowed_origins.
    - All endpoints require explicit auth (no anonymous writes).
- **Input Sanitization**:
    - All user inputs (names, notes, docs) sanitized with `bleach` (XSS prevention).
    - CIDRs/IPs validated with `ipaddress`/`netaddr` before scans.

### Database

```sql
-- Vault key management (singleton appsettings)
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS vault_key TEXT UNIQUE;  -- Fernet key

-- Credential tables (encrypted fields)
CREATE TABLE IF NOT EXISTS credentials (
    id INTEGER PRIMARY KEY,
    user_id INTEGER,
    target_entity_id INTEGER,   -- hardware/service FK
    credential_type TEXT,        -- snmp, ssh, ipmi, smtp
    encrypted_value TEXT NOT NULL,  -- Fernet-encrypted
    created_at DATETIME
);

-- Explicit data allowlist (blocks unknown fields)
-- Enforced in Pydantic models: extra='forbid'
```

### Frontend

- **Secure Storage**:
    - JWTs: httpOnly cookies (Caddy sets `Secure; HttpOnly; SameSite=Strict`).
    - Local prefs: IndexedDB with encryption shim (`crypto.subtle`).
- **Client‑Side Hardening**:
    - CSP via meta tag: `script-src 'self'; img-src 'self' data: https:;`.
    - Sanitize all user‑generated content before render (`DOMPurify`).
- **UI Controls**:
    - Credential vault form: encrypt before upload (user sees "- - - - - - - ").
    - Explicit toggles for "Allow unencrypted logs?" and "Enable payload encryption?".

### Settings / Toggles

```yaml
security:
  vault_enabled: true                    # Master encryption toggle
  vault_key_auto_generate: true          # Generate on OOBE
  api_payload_encryption: false          # JWE for sensitive APIs
  cors_allowed_origins: ["<https://circuitbreaker.local>"]  # Whitelist
  csp_strict_mode: true                  # Enforce CSP headers
  input_auto_sanitize: true              # Bleach everything
  allow_unencrypted_logs: false          # Block plaintext secrets in logs
```

- **UI**: "Security" tab → toggles + vault key rotation button (generates new key, re‑encrypts all data).

### Testing

- **Backend**:
    - Roundtrip encryption/decryption for SNMP/SSH creds.
    - Pydantic `extra='forbid'` rejects unknown fields.
    - CSP header validation in test responses.
- **Frontend**:
    - No localStorage for tokens, CSP blocks inline scripts.
    - Sanitization prevents XSS in notes/docs.
- **E2E**:
    - Upload credential → stored encrypted → poll/decrypt works → re‑encrypt on vault key rotation.

### Verification Plan

- **Staging**:
    - Store SNMP community → confirm DB shows encrypted blob → successful poll.
    - Rotate vault key → all existing creds still decrypt → new creds encrypt with new key.
    - Inject XSS payload in notes → sanitized on render.
- **Security Audit**:
    - `grep -r "password\\|secret\\|key" data/` → no plaintext.
    - Wireshark capture: TLS everywhere, no secrets in transit.
    - CSP test: inline `<script>alert(1)</script>` blocked.

**Zero‑trust principle**: Encrypt everything by default, expose only what user explicitly allows via toggles. Fernet ensures forward secrecy on key rotation. **Estimated**: 2 days backend + 1 day frontend.