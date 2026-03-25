# Circuit Breaker — Project State

**Date:** 2026-03-25
**Branch:** `hotfix/performance`
**Last tag:** `v0.2.5`
**Target release:** `v0.2.8`

---

## Architecture Overview

Circuit Breaker is a self-hosted homelab visualization and monitoring platform packaged as a single Docker image (`ghcr.io/blkleg/circuitbreaker`). The mono image runs all services (FastAPI backend, React/Vite frontend via Caddy, PostgreSQL, Redis, Caddy TLS proxy) inside one container under a non-root user (`breaker:1000`).

### Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI + SQLAlchemy (PostgreSQL), Pydantic v2, Alembic |
| Frontend | React + Vite, React Flow (topology), Tailwind CSS |
| Database | PostgreSQL (embedded in mono image), `/data` volume |
| Cache/RT | Redis (embedded), advisory locks for background jobs |
| Proxy | Caddy (TLS termination, reverse proxy) |
| Packaging | Docker mono image (`Dockerfile.mono`), native installer (`install.sh`) |
| CI | GitHub Actions — multi-arch build (amd64/arm64/armv7), SBOM, GPG signing |

### Dev Workflow

```
make services-up      # starts Postgres + Redis containers for dev
make migrate          # applies Alembic migrations
make backend          # uvicorn at :8000
make frontend         # Vite at :5173
make caddy-up         # Caddy dev proxy → https://circuitbreaker.lab
```

Python version: **3.12** (always use `python3.12 -m venv`).

---

## Migration Chain

Current head: **0066** (`0066_ipam_notes_network_site`)

| Migration | Description |
|---|---|
| 0050 | TimescaleDB hypertables |
| 0051 | Integrations table |
| 0052 | Slug on integrations |
| 0053 | Public status page + monitor events |
| 0054 | Status page integration_id FK |
| 0055 | Webhook DLQ |
| 0056 | Webhook body template |
| 0057 | Backup settings |
| 0058 | BI models — capacity_forecasts, resource_efficiency_recommendations, flap_incidents, retention settings |
| 0059 | Uptime Kuma enrichment — avg_response_ms, cert_expiry_days, linked_hardware_id, last_heartbeat_at on integration_monitors |
| 0060 | Hardware mounting fields — mounting_orientation, side_rail |
| 0061 | OAuth invite fields — accepted_at on user_invites, invite_token on oauth_states |
| 0062 | Native monitoring — probe_type/probe_target/probe_port/probe_interval_s, event annotations (reason/reason_by/reason_at), auto_monitor_on_discovery setting |
| 0063 | Proxmox sync health — last_sync_error, last_poll_error on integration_configs |
| 0064 | Integrations base_url nullable |
| 0065 | Multi-map — maps table (Topology rows) + TopologyNode entity membership |
| 0066 | IPAM notes field + network site association |

Auto-migration runs at startup when `CB_AUTO_MIGRATE=true` (default).

---

## Feature Inventory

### Committed to `hotfix/performance` (since v0.2.5)

| Feature | Commit | Status |
|---|---|---|
| Security hardening (weekly report fixes) | `8862e119`, `d05cf782` | ✅ Committed |
| Legacy auth token deprecation | `f6ab5516`, `61fd5af0` | ✅ Committed |
| Docker install automation (optional upgrade) | `cc7d60da` | ✅ Committed |
| Uptime Kuma integration — status page, webhooks, DLQ, integration engine, TimescaleDB metrics | `fc0f2783`, `f81d04da` | ✅ Committed |
| Debian 13 compatibility (installer) | `3e8d283a` | ✅ Committed |
| Disaster recovery — broader backup coverage, Proxmox node sync improvements, persistent map filters | `6807ac13` | ✅ Committed |
| Business Intelligence system — migration 0058, analytics/retention/blast-radius, `/api/v1/intel/` | `18906d01`, `b331b5b2` | ✅ Committed |
| Rack editor foundation — @dnd-kit deps, `unassignFromRack` hook | `0258dd8a` | ✅ Committed |
| Proxmox sync+poll health — design spec + implementation plan | `827e45d2`, `ac061ab7` | ✅ Committed (docs) |

### In-Flight (untracked / modified, not yet committed)

These are fully authored and staged in the working tree; awaiting commit after testing.

#### Multi-Map Support
- **New:** `apps/backend/src/app/api/maps.py` — CRUD for named maps (max 10), entity assignment, pin-to-all-maps
- **New:** `apps/backend/src/app/schemas/map.py` — MapOut, EntityAssign schemas
- **New:** `apps/frontend/src/api/maps.js` — API client for maps
- **New:** `apps/frontend/src/components/MapSwitcher.jsx` — dropdown pill in map toolbar
- **New:** `apps/frontend/src/components/details/MapAssignSection.jsx` — entity-drawer assign panel
- **New:** `apps/frontend/src/hooks/useMapTabs.js` — active map state management
- **Migration:** `0065_multi_map.py`

#### Interactive Rack Editor (Phase 1)
- **New:** `apps/frontend/src/components/racks/HardwareInventory.jsx` — unmounted hardware list, draggable items
- **New:** `apps/frontend/src/components/racks/RackCanvas.jsx` — U-slot grid, droppable slots, draggable mounted devices
- **New:** `apps/frontend/src/components/racks/RackInspector.jsx` — right panel: device details + remove
- **New:** `apps/frontend/src/components/racks/CableOverlay.jsx` — SVG cable visualization
- **Modified:** `apps/frontend/src/pages/RackPage.jsx` — 3-panel DnD layout
- **Migration:** `0060_hardware_mounting_fields.py` (mounting_orientation, side_rail)

#### Native Built-in Monitoring
- **New:** `apps/backend/src/app/integrations/native_probe.py` — ICMP/HTTP/TCP probe plugin
- **New:** `apps/frontend/src/components/settings/NativeMonitorModal.jsx` — probe configuration UI
- **Migration:** `0062_native_monitoring.py` (probe columns, event annotations, auto_monitor_on_discovery)

#### Uptime Kuma Socket.IO Enrichment
- **New:** `apps/backend/src/app/integrations/uptime_kuma_socket.py` — Socket.IO client (UptimeKuma 2.0), heartbeat history, cert expiry, response times
- **New:** `apps/backend/src/app/workers/integration_sync_worker.py` — background sync worker with advisory locking and status-change event emission
- **Migration:** `0059_uk_enrichment.py`

#### TLS Certificate Management
- **New:** `apps/frontend/src/pages/CertificatesPage.jsx` — full CRUD, expiry status badges (ShieldCheck/ShieldAlert/ShieldOff)
- **New:** `apps/frontend/src/components/details/CertificateDetail.jsx` — certificate detail drawer

#### Notifications Management
- **New:** `apps/frontend/src/pages/NotificationsPage.jsx` — notification sinks (Slack/Discord/Teams/Email) + routing rules

#### Tenant Management
- **New:** `apps/backend/src/app/api/tenants.py` — full CRUD (tenants + member management)
- **New:** `apps/frontend/src/pages/TenantsPage.jsx` — tenant management UI
- **New:** `apps/frontend/src/context/TenantContext.jsx` — active tenant context with localStorage persistence

#### User Management Enhancements
- **New:** `apps/frontend/src/components/MasqueradeBanner.jsx` — persistent amber banner for admin "login-as" sessions with "Return to Admin" button
- **Migration:** `0061_invite_oauth_fields.py` (accepted_at, invite_token for OAuth invite flow)

#### Proxmox Reliability & Observability
- **Migration:** `0063_proxmox_sync_health.py` (last_sync_error, last_poll_error on integration_configs)
- Implementation plan written; wiring into services pending

#### Integration base_url nullability
- **Migration:** `0064_integrations_base_url_nullable.py`

#### Map Topology — First-Scan Layout Fix
- **Modified:** `apps/frontend/src/hooks/useMapDataLoad.js` — Dagre is now always the default layout on first load; removed Proxmox-specific radial path that caused all nodes to spawn stacked at (0,0) when no edges exist on first scan

#### Installer Hardening (install.sh + deploy/setup.sh + cb-proxmox-deploy.sh)
- **Distro-agnostic preflight:** `stage0_preflight()` no longer blocks on a hardcoded version whitelist — detects distro family only (`ubuntu/debian → apt-get`, `fedora/rhel/rocky/almalinux/centos → dnf`, `arch/manjaro → pacman`). Any version of a supported family proceeds.
- **Dynamic PGDG repo URLs:** `stage2_dependencies()` — Fedora PGDG URL uses `$(uname -m)` for arch; RHEL/Rocky/Alma uses `${VERSION_ID%%.*}` for EL major version. No more hardcoded `EL-9` or `x86_64`.
- **Idempotency:** All four `stage3_configure_*` functions (postgres, pgbouncer, redis, nats) now return early with a skip message if the service is already initialized and running — safe to re-run a fresh install without downtime.
- **Inline debug hints:** `cb_fail()` in `install.sh` now prints a numbered "Debug steps:" block from the `CB_STAGE_HINTS[]` array. Each major stage in `main()` pre-loads 3-5 actionable hints (log path, service status command, port check, retry command) so novice users get specific next steps on failure.
- **Checksum hardening:** SHA256 mismatch in `install.sh` is now a hard `cb_fail` abort instead of a `cb_warn`; new `--skip-checksum` flag for air-gapped or local-bundle scenarios.
- **Proxmox — operation timeouts:** `pveam download` wrapped with `timeout 300` (5m); `pct create` with `timeout 120` (2m); `pct exec` install and upgrade with `timeout 600` (10m). Prevents indefinite hangs.
- **Proxmox — stale lock pre-clear:** Proactive `pct unlock` before both `pct create` and `pct start` to clear leftover locks from previous failed attempts.
- **Proxmox — IPv4 CIDR validation:** Static IP input now loops until the user enters a valid `x.x.x.x/prefix` format; invalid input re-prompts with a clear error message instead of passing garbage to `pct create`.
- **Proxmox — enhanced failure debug:** Install failure output now includes a 5-step debug block: `pct enter`, full log path, service status, all-logs command, and re-run command.

#### Tests
- **New:** `apps/frontend/src/__tests__/certificates-page.test.jsx`
- **New:** `apps/frontend/src/__tests__/notifications-page.test.jsx`
- **New:** `apps/frontend/src/__tests__/tenant-context.test.jsx`
- **New:** `apps/frontend/src/__tests__/tenants-page.test.jsx`
- **New:** `apps/backend/tests/integrations/`
- **New:** `apps/backend/tests/test_map_schemas.py`
- **New:** `tests/integration/test_certificates_notifications.py`
- **New:** `tests/integration/test_proxmox.py`

---

## Key Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Multi-map backend model | Activate existing `Topology`/`TopologyNode` tables | Already in schema from migration 0026; no new tables needed |
| Multi-map entity scope | Exclusive by default; pin to all maps as escape hatch | Clean separation without blocking "core" devices |
| Inactive map performance | Full React `key` unmount | No timers, polling, or animation frames from inactive maps |
| Native probe integration | Full `IntegrationPlugin` subclass | Consistent with UptimeKuma/Proxmox plugin model; uses same sync worker |
| BI analytics | PostgreSQL advisory locks for analytics jobs | No external scheduler; consistent with existing job_lock pattern |
| Rack editor drag-and-drop | `@dnd-kit/core` + `@dnd-kit/utilities` | Accessibility-first; no DOM hacks; CSS-variable styling throughout |
| Masquerade | Short-lived 15-min JWT with `is_masquerade` claim | Clear expiry; admin session preserved separately |
| Proxmox sync health | `last_sync_error`/`last_poll_error` columns on integration_configs | Zero new tables; surfaced in existing Proxmox tab UI |

---

## Known Gaps / Next Steps

- **Proxmox observability wiring:** Migration 0063 is written; `_record_sync_health()` and `_record_poll_health()` helpers in `main.py` still need to be authored and wired into `_proxmox_full_sync()` and poll wrappers (9-task plan at `docs/superpowers/plans/2026-03-24-proxmox-sync-poll-health.md`).
- **Rack Editor Phase 2:** Cable management (physics sim, port assignment), rear view toggle, PNG/PDF export — per design at `design-racks.md`.
- **User management Phase 2/3:** Admin password reset endpoints + frontend modals; session revocation UI — per design at `design-user-management.md`.
- **Multi-map full wiring:** MapSwitcher needs to be wired into the existing `MapPage.jsx` toolbar and all data-fetch hooks need `map_id` threading.
- **Notifications backend:** `NotificationsPage.jsx` exists; backend sink/route models assumed present from webhook DLQ work but routing logic needs verification.

---

## Environment Variables (Key)

| Variable | Purpose |
|---|---|
| `CB_VAULT_KEY` | Fernet key for credential encryption |
| `CB_AUTO_MIGRATE` | Auto-run Alembic at startup (default: `true`) |
| `CB_AIRGAP` | Disable outbound connections |
| `CB_REDIS_URL` | Redis connection string (includes auth password) |
| `DATABASE_URL` | PostgreSQL DSN |

---

## Deployment Paths

1. **Docker (mono image):** `ghcr.io/blkleg/circuitbreaker` — single image, `/data` volume, all services embedded.
2. **Native installer:** `install.sh` — installs services directly on Debian/Ubuntu/Fedora/Proxmox LXC. No Docker in LXC containers. Primary deployment path.
3. **Docker Compose:** `docker-compose.yml` — compose-based deployment for users preferring external orchestration.
