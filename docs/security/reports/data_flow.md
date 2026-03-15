# Circuit Breaker — Data Flow Analysis

*Audited: 2026-03-12 | Scope: Backend API → Frontend consumption*

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│  Browser (React / Vite)                                         │
│                                                                 │
│  AuthContext ──► cookie-based session (cb_session)              │
│  SettingsContext ──► GET /api/v1/settings (on mount)            │
│                                                                 │
│  REST Layer                  │  Real-Time Layer                 │
│  ─────────────               │  ────────────────                │
│  client.jsx (axios)          │  useDiscoveryStream  ┐           │
│  22 named API modules        │  useTopologyStream   │ WebSocket │
│  baseURL: /api/v1            │  useTelemetryStream  ┘           │
│  withCredentials: true       │                                  │
│  timeout: 20 s               │  ──► mitt event buses           │
│  auto-retry (2×, backoff)    │  ──► setNodes / ReactFlow        │
└─────────────────────────────────────────────────────────────────┘
                 │ HTTP                │ WS
                 ▼                    ▼
┌─────────────────────────────────────────────────────────────────┐
│  FastAPI (Uvicorn)                                              │
│  52 API files under apps/backend/src/app/api/                   │
│  Middleware: CORS, SecurityHeaders, LegacyToken, Logging, Tenant│
│  Rate limiting: slowapi (per-IP, configurable profile)          │
│                                                                 │
│  WebSocket servers                                              │
│    ws_discovery.py ──► NATS + Redis fan-out                     │
│    ws_topology.py  ──► NATS bridge                             │
│    ws_telemetry.py ──► Redis pub/sub (per entity_id channel)    │
│    ws_status.py    ──► (no frontend consumer — see §4)          │
└─────────────────────────────────────────────────────────────────┘
                 │
                 ▼
      PostgreSQL + Redis + NATS
```

---

## 2. REST Data Flow — Path Tracing

### 2.1 Auth Flow
| Step | Actor | Mechanism |
|------|-------|-----------|
| 1. Mount | `AuthContext` | `GET /auth/me` — validates httpOnly cookie |
| 2. Login | `LoginPage` | `POST /auth/login` → sets `cb_session` cookie |
| 3. Expiry | `axios interceptor` | 401 fires `cb:session-expired` CustomEvent |
| 4. Re-auth | `AuthContext` listener | Clears user state, shows auth modal |

**Notes:** token is never stored in localStorage/sessionStorage. The WS hooks use `token === 'cookie'` sentinel to skip sending JWT over WS (they rely on the httpOnly cookie being validated server-side from the WS upgrade request only when available).

### 2.2 Topology Map Flow (core data path)
```
MapPage mount
  ├─ useMapDataLoad.fetchData()
  │    ├─ GET /graph/topology?environment_id=&include=...
  │    │     └─► returns {nodes[], edges[]}
  │    ├─ GET /graph/layout?name=default
  │    │     └─► merge saved positions
  │    └─► setNodes/setEdges → ReactFlow renders
  │
  ├─ useTopologyStream (WebSocket /api/v1/topology/stream)
  │    └─► topologyEmitter events → useMapRealTimeUpdates
  │          node_moved, cable_added/removed, node_status_changed
  │
  ├─ useTelemetryStream (WebSocket /api/v1/telemetry/stream)
  │    ├─► subscribe by hardware entity_id
  │    └─► telemetryEmitter → setNodes (live telemetry patches)
  │         Falls back to REST polling (30s/exp-backoff) when WS down
  │
  └─ useMapRealTimeUpdates
       ├─► monitor polling (GET /monitors, 60s interval)
       └─► discovery badge via GET /discovery/results?limit=1
```

### 2.3 Discovery Flow
```
DiscoveryPage or MapPage
  ├─ POST /discovery/jobs  (user-triggered scan)
  ├─ useDiscoveryStream (WebSocket /api/v1/discovery/stream)
  │    └─► discoveryEmitter events:
  │          job_update, job_progress, scan_log_entry,
  │          result_added, result_processed,
  │          proxmox_scan_started/progress/completed/failed
  └─► Badge: optimistic decrement + 30s reconcile window
```

### 2.4 Settings Flow
```
SettingsProvider (on mount)
  └─ GET /settings → React context (global, no cache invalidation)
     Consumers: SettingsPage, MapPage (graph_*, vendor_icon_mode, etc.)
```

---

## 3. Client API Module Coverage

| Backend Router | Frontend Module | Coverage |
|----------------|----------------|----------|
| hardware.py | `hardwareApi` | ✅ Full |
| compute_units.py | `computeUnitsApi` | ✅ Full |
| services.py | `servicesApi` | ✅ Full |
| networks.py | `networksApi` | ✅ Full (members, peers, hw-members) |
| storage.py | `storageApi` | ✅ Full |
| misc.py | `miscApi` | ✅ Full |
| docs.py | `docsApi` | ✅ Full (inc. import/export) |
| graph.py | `graphApi` | ✅ Full |
| auth.py | `authApi` (auth.js) | ✅ Full |
| auth_oauth.py | Inline in LoginPage | ✅ Covered |
| logs.py | `logsApi` | ✅ Full (inc. SSE stream) |
| discovery.py | `discoveryApi` (discovery.js) | ✅ Full |
| settings.py | `settingsApi` | ✅ Full |
| admin.py | `adminApi` | ✅ Full |
| admin_users.py | `adminUsersApi` | ✅ Full |
| clusters.py | `clustersApi` | ✅ Full |
| proxmox.py | `proxmoxApi` | ✅ Full |
| telemetry.py | `telemetryApi` | ✅ Full |
| categories.py | `categoriesApi` | ✅ Full |
| environments.py | `environmentsApi` | ✅ Full |
| external_nodes.py | `externalNodesApi` | ✅ Full |
| catalog.py | `catalogApi` | ✅ Full |
| cve.py | `cveApi` | ✅ Full |
| search.py | `searchApi` | ✅ Full |
| tags.py | `tagsApi` | ✅ Full |
| capabilities.py | `capabilitiesApi` | ✅ Full |
| assets.py | `assetsApi` | ⚠️ Partial (user-icon only; branding.py covered inline) |
| branding.py | Inline in SettingsPage | ⚠️ Inline calls, no named client export |
| webhooks.py | Inline in WebhooksManager.jsx | ⚠️ Inline calls, no named client export |
| notifications.py | Inline in NotificationsManager.jsx | ⚠️ Inline calls, no named client export |
| certificates.py | Inline in OOBEWizardPage | ⚠️ Inline only, limited to OOBE context |
| monitor.py | monitor.js (standalone) | ✅ Covered (separate file) |
| **ipam.py** | **None** | ❌ **MISSING** |
| **topologies.py** | **None** | ❌ **MISSING** |
| **status.py** | **None** | ❌ **MISSING** |
| **events.py** | **None** | ❌ **MISSING** |
| **rack.py** | **None** | ❌ **MISSING** |
| ws_status.py | **None** | ❌ **WS not consumed** |
| system.py | `systemApi` | ✅ Full |
| metrics.py | Inline | ⚠️ Partial (covered via settings) |
| security_status.py | `securityApi` | ✅ Full |
| vault.py | Inline in VaultResetPage | ✅ Covered |
| timezones.py | `timezonesApi` | ✅ Full |

---

## 4. Gaps & Missing Connections

### 🔴 P1 — Missing Frontend Entirely

**`/api/v1/ipam/*`** — IP Address Management endpoints
- `ipam_router`, `vlan_router`, `site_router`, `node_relations_router` are registered in `main.py`
- No frontend API client, no UI page, no hook exists
- Users cannot manage IP pools, VLANs, or sites from the UI
- **Impact:** Entire IPAM subsystem is backend-only dead code from the user's perspective

**`/api/v1/topologies/*`** — Multi-topology management
- The `topologies.py` router provides full CRUD for named topology objects
- No frontend consumer found
- Map always loads `default` layout; users cannot switch, create, or delete named topologies from UI
- **Impact:** Topology management API is fully unreachable from the frontend

**`/api/v1/status/*`** (status pages for public monitoring)
- Backend provides CRUD + public rendering of status pages
- No frontend CRUD UI exists; there is also a `ws_status.py` WebSocket (`/api/v1/status/stream`) that has no frontend consumer
- **Impact:** Status page management is inaccessible without direct API calls

**`/api/v1/events/*`** — SSE event feed
- Backend provides a Server-Sent Events endpoint for real-time log streaming
- No frontend hook or component subscribes to this endpoint
- **Impact:** Duplicate effort — discovery stream and log polling exist, but the dedicated events SSE feed is unused

**`/api/v1/racks/*`** — Rack unit management
- Rack endpoints exist and are registered, no frontend UI or API client
- Rack data *does* surface on the map (u_height, rack_unit in node data), but no dedicated management page exists
- **Impact:** Racks cannot be created, edited, or deleted from the UI

---

### 🟠 P2 — Bottlenecks / Architectural Concerns

**Settings Context: No Live Invalidation**
- `SettingsContext` fetches settings once on app mount
- If an admin changes settings (e.g., rate limit profile, CORS origins) elsewhere, other open sessions are stale until manual page refresh
- No WebSocket push or polling loop invalidates the settings cache
- **Recommendation:** Add a `settings_changed` NATS/WS event or periodic refetch (e.g., 5-min interval)

**Telemetry WS Falls Back to Per-Node REST Polling When Redis is Down**
- When Redis is unavailable, `useTelemetryStream` stays open but silent
- `useMapRealTimeUpdates` polling then fans out `GET /hardware/{id}/telemetry` individually per node (5s loop)
- With a large topology (50+ hardware nodes), this can produce dozens of concurrent requests every 30s
- **Recommendation:** Implement backend server-sent batch telemetry polling endpoint (e.g., `POST /telemetry/batch`) to reduce N+1 REST calls

**Graph Topology Load: N+1 Layout Fetch**
- `useMapDataLoad.fetchData()` always fetches topology AND layout in two sequential API calls
- With network latency, this causes visible loading delays
- **Recommendation:** Consider merging layout data into the topology response or using `Promise.all()` to parallelize

**Discovery Badge: Dual Sync Sources**
- Badge count comes from WS push (`result_added`, `result_processed`) plus a 30s reconcile REST poll (`GET /discovery/status`)
- In high-throughput scans, optimistic decrements can race with the server count
- **Recommendation:** Rely solely on server-authoritative count from WS events; remove the 30s polling when WS is connected

**Inline API Calls Without Standard Error Pipeline**
- Components for webhooks (`WebhooksManager.jsx`), notifications (`NotificationsManager.jsx`), and branding (inline in `SettingsPage.jsx`) make `axios` or `client` calls directly inside components without going through named `client.jsx` exports
- These bypass the centralized retry logic, 429 handling, and session expiry flow
- **Recommendation:** Consolidate these into named api modules in `client.jsx`

---

### 🟡 P3 — Minor / Informational

**`logsApi.stream()` Returns a URL String, Not a Fetch Promise**
- `logsApi.stream()` returns a URL string for consumers to build their own `EventSource`
- This is inconsistent with every other API module and easy to miss in code review
- **Recommendation:** Document this prominently in the code, or wrap in a helper that returns an `EventSource` instance

**`monitor.js` is a Standalone File Not Exported From `client.jsx`**
- Monitor API calls live in `src/api/monitor.js` as a separate file
- Creates an inconsistent pattern where some modules are in `client.jsx` and some are standalone
- **Recommendation:** Consolidate into `client.jsx` or establish a consistent split (e.g., all REST in `client.jsx`, WS hooks separate)

**WebSocket Auth: Cookie vs. JWT Token Sent as First Message**
- When auth is cookie-based (most browser sessions), `token === 'cookie'` and WS hooks skip sending a JWT message
- Server extracts the cookie from the WebSocket upgrade request headers
- However, ws_telemetry.py and ws_topology.py also accept a raw JWT as first message, creating two auth paths on the server with subtly different validation logic
- **Recommendation:** Document both auth paths; add a test for the cookie-based WS auth path

---

## 5. Summary Triage

| Priority | Finding | Severity |
|----------|---------|----------|
| P1 | IPAM endpoints have no frontend — entire subsystem unreachable | High |
| P1 | Topologies CRUD has no frontend — named topologies unmanageable | High |
| P1 | Status pages/WS stream not consumed by frontend | Medium |
| P1 | Events SSE feed unused | Low |
| P1 | Rack management has no frontend | Medium |
| P2 | Settings context not invalidated on remote change | Medium |
| P2 | Telemetry fallback polling creates N+1 REST calls | Medium |
| P2 | Topology + layout fetched sequentially (extra RTT) | Low |
| P2 | Inline API calls bypass centralized error/retry pipeline | Low |
| P3 | `logsApi.stream()` returns URL string (inconsistent pattern) | Low |
| P3 | `monitor.js` standalone file breaks module consistency | Low |
| P3 | Dual WS auth paths with different validation logic | Low |
