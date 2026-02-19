**Prompt: Implement Comprehensive Logs Page for Circuit Breaker (Real Implementation, No Placeholders)**

You are a senior Vite/React + FastAPI engineer.  
The project is **Circuit Breaker**.  
Phases 0–3 and QOL features (vendor icons, settings) are complete.

**Your task**: Implement a **fully functional Logs page** that captures **all user actions** from top to bottom with **real data logging** (no placeholder/mock data). This is an audit trail for enterprise-grade homelab management.

***

## Goals

1. Log **every user action** that modifies data or changes app state.
2. Display logs in a **Logs HUD** with filtering, search, and export.
3. Integrate with **HUD/Dock** and **command palette**.
4. Persist logs in SQLite with **real timestamps** and **action details**.
5. Make it **production-ready** (no mock data, handles edge cases).

***

## Backend: Logging System

### 1. Logs schema

Create a `logs` table to capture all actions:

```sql
CREATE TABLE logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT NOT NULL,        -- ISO 8601
    level       TEXT NOT NULL,        -- "info", "warn", "error"
    category    TEXT NOT NULL,        -- "crud", "auth", "settings", "graph", "export"
    action      TEXT NOT NULL,        -- "create_hardware", "update_service", "delete_compute"
    actor       TEXT,                 -- "user" or future user ID
    entity_type TEXT,                 -- "hardware", "service", "compute", etc.
    entity_id   INTEGER,              -- DB ID of affected entity
    old_value   TEXT,                 -- JSON string of before state (if applicable)
    new_value   TEXT,                 -- JSON string of after state (if applicable)
    user_agent  TEXT,                 -- HTTP User-Agent header
    ip_address  TEXT,                 -- client IP (if available)
    details     TEXT                  -- additional context
);
```

### 2. Logging middleware

Implement **automatic logging** for all CRUD operations using FastAPI middleware or dependency:

**Automatic logging triggers** (log every single one):
- `POST /api/v1/*` → `action: "create_{entity}"`
- `PATCH /api/v1/*` → `action: "update_{entity}"`
- `DELETE /api/v1/*` → `action: "delete_{entity}"`
- `PUT /api/v1/settings` → `action: "update_settings"`
- `POST /api/v1/export` → `action: "export_data"` (when Phase 4 is implemented)
- `POST /api/v1/docs/attach` → `action: "attach_doc"`
- `DELETE /api/v1/docs/attach` → `action: "detach_doc"`
- `POST /api/v1/services/{id}/dependencies` → `action: "add_service_dependency"`
- `DELETE /api/v1/services/{id}/dependencies/{depends_on_id}` → `action: "remove_service_dependency"`
- And all other relationship endpoints from Phase 2.

**Log content**:
- `category`: `"crud"` for CRUD, `"settings"` for settings, `"relationships"` for relationship changes.
- `level`: `"info"` for all user actions (no errors here).
- `entity_type` and `entity_id`: extract from URL path.
- `old_value`/`new_value`: for updates, capture the Pydantic model before/after (JSON stringified).
- `actor`: `"user"` for now (future: user ID).
- `user_agent`: from request headers.
- `ip_address`: from `request.client.host` (if available).
- `details`: structured JSON with request body or other context.

### 3. Logs API

```
GET /api/v1/logs
  Query params:
  - limit: number (default 100, max 1000)
  - offset: number (for pagination)
  - start_time: ISO date (e.g., "2026-02-19T00:00:00Z")
  - end_time: ISO date
  - category: string (e.g., "crud")
  - action: string (e.g., "create_hardware")
  - entity_type: string (e.g., "service")
  - entity_id: number
  - level: string ("info"|"warn"|"error")
  - search: string (search across action, details, entity_type)

Response:
{
  "logs": [LogEntry[]],
  "total_count": number,
  "has_more": boolean
}
```

**LogEntry shape**:
```json
{
  "id": 123,
  "timestamp": "2026-02-19T12:34:56.789Z",
  "level": "info",
  "category": "crud",
  "action": "create_hardware",
  "actor": "user",
  "entity_type": "hardware",
  "entity_id": 42,
  "old_value": null,
  "new_value": "{\"name\": \"Node-1\", \"vendor\": \"dell\"}",
  "user_agent": "Mozilla/5.0...",
  "ip_address": "192.168.1.100",
  "details": "{\"role\": \"hypervisor\"}"
}
```

***

## Frontend: Logs HUD Panel

### 1. HUD/Dock integration

- **Dock**: Add **"Logs"** icon/button (clock/history icon) next to Map/Settings.
- **Command palette**:
  - `Open: Logs`
  - `Logs: Filter by CRUD`
  - `Logs: Filter by service`
  - `Logs: Export logs`
  - `Logs: Clear logs` (with confirmation)

### 2. Logs HUD layout

The Logs HUD should be a **table-focused panel** with:

#### a) **Main table** (80% of space)
Columns (left to right):
1. **Time** (timestamp, relative like "2m ago" + tooltip with full ISO).
2. **Action** (e.g., `create_hardware`, `add_service_dependency`).
3. **Entity** (e.g., `hardware #42`, `service #123`; clickable to open entity HUD).
4. **Details** (truncated JSON or key-value pairs).
5. **Actor/IP** (combined, e.g., `user @ 192.168.1.100`).

#### b) **Filters/controls** (top bar)
- **Time range**: `Last 1h`, `Today`, `Last 24h`, `Last 7d`, `Custom` (date pickers).
- **Category** dropdown: `All`, `CRUD`, `Settings`, `Relationships`, `Docs`.
- **Action** dropdown/search: free text autocomplete (e.g., "create_", "update_").
- **Entity type** dropdown: `All`, `Hardware`, `Services`, `Compute`, etc.
- **Search** free text (searches action, details, entity_type).
- **Refresh** button.
- **Export** button (CSV or JSON download).
- **Clear logs** button (dangerous, confirmation required).

#### c) **Pagination** (bottom)
- Show `Showing 1-50 of 1,234 logs`.
- Next/Prev buttons.
- Jump to first/last.

### 3. Features

1. **Real-time updates**:
   - Use **Server-Sent Events (SSE)** or **long polling** to show new logs as they happen.
   - SSE endpoint: `GET /api/v1/logs/stream?since={timestamp}`.
   - New logs appear at the top with smooth animation.

2. **Entity linking**:
   - Click any `entity_type #entity_id` → open that entity’s HUD.
   - If entity was deleted, show "Entity deleted".

3. **Details expansion**:
   - Click row → expand to show full `old_value`/`new_value` as formatted JSON.
   - Or use a details drawer.

4. **Export**:
   - Download visible logs as CSV:
     ```
     timestamp,action,entity_type,entity_id,details
     2026-02-19T12:34:56Z,create_hardware,hardware,42,"{"name": "Node-1"}"
     ```
   - Or JSON array.

5. **Clear logs**:
   - `DELETE /api/v1/logs` endpoint.
   - Confirmation dialog: “Clear all logs? This cannot be undone.”

### 4. Data fetching

- **Initial load**: `GET /api/v1/logs?limit=50`.
- **Filters change**: refetch with params.
- **Scroll to load more**: `GET /api/v1/logs?offset={last_id}&limit=50`.
- **SSE stream**: `GET /api/v1/logs/stream?since={last_timestamp}` for real-time.

***

## Integration with existing features

1. **Settings**:
   - `default_logs_limit` (if added to settings).
   - `log_retention_days` (optional, implement if settings schema allows).

2. **Vendor icons**:
   - Show vendor icons in log entries where relevant (e.g., hardware logs).

3. **HUD consistency**:
   - Use same dark theme, typography, button styles.
   - Match the resolution/layout of attached screenshots.

***

## Backend endpoints to implement

```
GET /api/v1/logs
  ?limit=100&offset=0&start_time=...&end_time=...&category=...&action=...&entity_type=...&entity_id=...&search=...
DELETE /api/v1/logs  # clear all
GET /api/v1/logs/stream?since=2026-02-19T12:34:56Z  # SSE
```

***

## Exit criteria (MUST PASS)

1. **Every CRUD action** (create/update/delete any entity) appears in logs with:
   - Correct timestamp.
   - `action: "create_hardware"`, etc.
   - `old_value`/`new_value` JSON.
   - Entity type/ID.

2. **Logs HUD**:
   - Shows real logs (no placeholders).
   - Filters work (category, entity type, time range, search).
   - Pagination works.
   - Click entity ID → opens entity HUD.

3. **Real-time**: New actions appear automatically without manual refresh.

4. **Export**: Downloads CSV with all visible logs.

5. **Command palette**: `Open: Logs` works.

6. **Dock**: Logs button opens the HUD.

***

## Output format

When you are done, respond with:

1. **Backend**: logs table schema + key middleware/route code.
2. **Frontend**: Logs HUD layout diagram (text-based).
3. **Log entry example**: show a real log from create_hardware + update_service.
4. **Test workflow**: 5-step test proving it works end-to-end.
5. **New endpoints**: full spec with example requests/responses.

**NO PLACEHOLDER DATA**. Everything must log and display real actions from the existing CRUD.