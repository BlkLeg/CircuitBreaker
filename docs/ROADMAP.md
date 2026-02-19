```markdown
# ROADMAP.md

This roadmap describes the v1 delivery of the Service Layout Mapper. It is organized into phases that can be executed sequentially. Each phase should be shippable, with data migration kept minimal.

---

## Phase 0 – Foundation and Skeleton

**Objectives**

- Establish project structure for backend and frontend.
- Define core entity models, migrations, and minimal API.
- Enable basic manual data entry through API only.

**Deliverables**

- Repo layout:
  - `backend/` FastAPI app with modular routers.
  - `frontend/` JS SPA scaffold (React or vanilla).
  - `docs/` with `OVERVIEW.md`, `API-ENTITY-SCHEMA.md`, `ROADMAP.md`.
- Configuration:
  - Single config file (YAML/TOML) for:
    - SQLite database path.
    - HTTP listen address/port.
    - Optional API token (reserved for Phase 3).
- Database:
  - SQLite schema for:
    - `hardware`
    - `compute_units`
    - `services`
    - `storage`
    - `networks`
    - `misc_items`
    - `tags`
    - `docs`
    - link tables (`entity_tags`, `entity_docs`, `service_dependencies`, `service_storage`, `compute_networks`, `service_misc`)
- Backend:
  - FastAPI app entrypoint (`main.py`) with:
    - Health check: `GET /api/v1/health`
    - Root metadata: `GET /api/v1/meta` (app version, build info).
  - SQLAlchemy setup (or equivalent):
    - Engine/session factory for SQLite.
    - Base model registration and migration script generation (“create-all” for v1).
- Frontend:
  - SPA scaffold with:
    - Basic layout (sidebar + topbar).
    - Routing between empty pages: Hardware, Compute Units, Services, Storage, Networks, Misc, Docs, Map.

**Exit Criteria**

- App starts locally (dev mode) with:
  - Backend serving `/api/v1/health`.
  - Frontend served via `npm run dev` or similar, with navigation between empty pages.
- Database file created and tables successfully initialized.

---

## Phase 1 – CRUD for Core Entities + Tags

**Objectives**

- Make the app usable for basic inventory: hardware, compute units, services, storage, networks, misc.
- Implement tags and filtering.
- Provide simple UI for create/read/update/delete.

**Deliverables**

### Backend

CRUD endpoints (JSON):

- Hardware:
  - `GET /api/v1/hardware`
  - `POST /api/v1/hardware`
  - `GET /api/v1/hardware/{id}`
  - `PATCH /api/v1/hardware/{id}`
  - `DELETE /api/v1/hardware/{id}`
- Compute Units:
  - `GET /api/v1/compute-units`
  - `POST /api/v1/compute-units`
  - `GET /api/v1/compute-units/{id}`
  - `PATCH /api/v1/compute-units/{id}`
  - `DELETE /api/v1/compute-units/{id}`
- Services:
  - `GET /api/v1/services`
  - `POST /api/v1/services`
  - `GET /api/v1/services/{id}`
  - `PATCH /api/v1/services/{id}`
  - `DELETE /api/v1/services/{id}`
- Storage:
  - `GET /api/v1/storage`
  - `POST /api/v1/storage`
  - `GET /api/v1/storage/{id}`
  - `PATCH /api/v1/storage/{id}`
  - `DELETE /api/v1/storage/{id}`
- Networks:
  - `GET /api/v1/networks`
  - `POST /api/v1/networks`
  - `GET /api/v1/networks/{id}`
  - `PATCH /api/v1/networks/{id}`
  - `DELETE /api/v1/networks/{id}`
- Misc Items:
  - `GET /api/v1/misc`
  - `POST /api/v1/misc`
  - `GET /api/v1/misc/{id}`
  - `PATCH /api/v1/misc/{id}`
  - `DELETE /api/v1/misc/{id}`

Filtering/query:

- All list endpoints accept:
  - `tag` (single tag filter).
  - `q` (search by name/description/notes).
- Specific filters:
  - Compute units: `kind`, `hardware_id`, `environment`.
  - Services: `compute_id`, `environment`, `category`.
  - Storage: `kind`, `hardware_id`.
  - Networks: `vlan_id`, `cidr`.
  - Misc: `kind`.

Tags handling:

- Entities accept `tags: string[]` in create/update.
- Implementation uses `tags` table + `entity_tags` linking.
- Listing endpoints return `tags` array on each object.

### Frontend

Per-entity pages:

- HardwarePage:
  - Table: name, role, location, tags.
  - Create/edit form modal.
  - Delete with confirmation.
  - Filter by tag and free-text search.
- ComputeUnitsPage:
  - Table: name, kind, host hardware, environment, IP, tags.
  - Create/edit form with hardware dropdown.
  - Filters: tag, environment, kind.
- ServicesPage:
  - Table: name, slug, compute unit, category, environment, tags.
  - Create/edit form with compute dropdown.
  - Filters: tag, environment, category.
- StoragePage:
  - Table: name, kind, capacity, host hardware, path, tags.
  - Create/edit form with optional hardware association.
- NetworksPage:
  - Table: name, CIDR, VLAN, gateway, tags.
  - Create/edit form.
- MiscPage:
  - Table: name, kind, URL, tags.
  - Create/edit form.

Global UX:

- Sidebar navigation with active section highlight.
- Basic error display for failed API calls.
- Loading indicators on list fetch.

**Exit Criteria**

- A new environment can be fully documented (hardware → compute → services → storage → networks → misc) using only the UI.
- Tagging and basic filtering work across all core lists.

---

## Phase 2 – Relationships and Docs

**Objectives**

- Model how entities relate: hosts, runs on, uses, connects to.
- Add first-class docs in Markdown and attach them to entities.
- Provide “follow the chain” visibility per service.

**Deliverables**

### Backend

Relationship endpoints:

- Service dependencies:
  - `GET /api/v1/services/{id}/dependencies`
  - `POST /api/v1/services/{id}/dependencies`
  - `DELETE /api/v1/services/{id}/dependencies/{depends_on_id}`
- Service–storage:
  - `GET /api/v1/services/{id}/storage`
  - `POST /api/v1/services/{id}/storage`
  - `DELETE /api/v1/services/{id}/storage/{storage_id}`
- Service–misc:
  - `GET /api/v1/services/{id}/misc`
  - `POST /api/v1/services/{id}/misc`
  - `DELETE /api/v1/services/{id}/misc/{misc_id}`
- Compute–networks:
  - `GET /api/v1/networks/{id}/members`
  - `POST /api/v1/networks/{id}/members`
  - `DELETE /api/v1/networks/{id}/members/{compute_id}`

Docs endpoints:

- `GET /api/v1/docs`
- `POST /api/v1/docs`
- `GET /api/v1/docs/{id}`
- `PATCH /api/v1/docs/{id}`
- `DELETE /api/v1/docs/{id}`
- Attach:
  - `POST /api/v1/docs/attach`
  - `DELETE /api/v1/docs/attach`
  - `GET /api/v1/docs/by-entity?entity_type=service&entity_id=123`

### Frontend

Docs:

- DocsPage:
  - List of docs with title and updated timestamp.
  - Create/edit Markdown doc with live preview.
- Entity detail pages (or side pane on table row click) for:
  - Hardware
  - Compute units
  - Services
  - Storage
  - Networks
  - Misc
- Each detail view:
  - Shows core fields.
  - Lists attached tags.
  - Lists attached docs.
  - “Attach doc” workflow:
    - Choose existing doc or create new.
    - Attach to current entity.

Relationships:

- Service detail:
  - Shows:
    - Hosting compute unit and hardware chain.
    - Dependencies: list of other services.
    - Storage used with “purpose”.
    - Linked misc items.
  - UI actions:
    - Add/remove dependency.
    - Add/remove storage link.
    - Add/remove misc link.
- Compute unit detail:
  - Shows:
    - Host hardware.
    - Networks it belongs to (with IP).
    - Services running on it.
- Network detail:
  - Shows member compute units and their IPs.

**Exit Criteria**

- From any service, you can see:
  - Which VM/container and hardware it runs on.
  - Which storage it uses.
  - Which services it depends on.
- From any hardware node, you can see:
  - Its compute units and their services.
- Docs can be created, attached, edited, and viewed in Markdown across entities.

---

## Phase 3 – Map View (Topology)

**Objectives**

- Provide an interactive map visualizing hardware → compute → services plus shared infrastructure.
- Allow filtering by environment and tags.

**Deliverables**

### Backend

Graph endpoint:

- `GET /api/v1/graph/topology`
  - Query:
    - `environment` (optional).
    - `include` csv: `hardware,compute,services,storage,networks,misc`.
- Returns:
  - `nodes[]` with fields: `id`, `type`, `ref_id`, `label`, `tags`.
  - `edges[]` with fields: `id`, `source`, `target`, `relation`.

Implementation:

- Nodes:
  - Hardware → `type: "hardware"`.
  - Compute_units → `type: "compute"`.
  - Services → `type: "service"`.
  - Storage → `type: "storage"`.
  - Networks → `type: "network"`.
  - Misc → `type: "misc"`.
- Edges:
  - Hardware → compute: `relation: "hosts"`.
  - Compute → service: `relation: "runs"`.
  - Service → storage: `relation: "uses"`.
  - Service → service: `relation: "depends_on"`.
  - Compute → network: `relation: "connects_to"`.
  - Service → misc: `relation: "integrates_with"`.

### Frontend

MapPage:

- Fetches graph data from `/graph/topology`.
- Uses a JS graph layout library (force-directed or layered).
- Features:
  - Pan/zoom.
  - Node hover for quick info (name, type, tags).
  - Click node:
    - Highlights connected edges.
    - Shows side panel with details and deep-link to entity detail page.
  - Filters:
    - Environment dropdown.
    - Tag filter.
    - Toggles for node types (hardware, compute, services, storage, networks, misc).

Global UX:

- “Map” is promoted in sidebar as a primary entry point.
- Optional setting: “Open map after login / on initial load”.

**Exit Criteria**

- The map renders all nodes/edges for a documented environment.
- You can trace from a service node back to its compute and hardware, and out to its storage and dependencies, visually.
- Filters update the map without full page reload.

---

## Phase 4 – Export/Import, Basic Auth, Quality-of-Life

**Objectives**

- Make it safe to adopt long-term: backup/restore via JSON.
- Add basic protection suitable for a private homelab.
- Improve day-to-day usability and observability.

**Deliverables**

### Backend

Export/import:

- `GET /api/v1/export`
  - Returns JSON snapshot including:
    - All entities.
    - All tags and docs.
    - All relationships.
- `POST /api/v1/import`
  - Accepts JSON snapshot.
  - Strategy: “import-as-new IDs” with simple collision handling.
  - Option to “wipe before import” via query param or explicit flag.

Auth (simple for v1):

- Optional static API token configured via config file.
- If enabled:
  - All modifying endpoints require `Authorization: Bearer <token>`.
  - Read endpoints remain open by default (configurable).
- Middleware enforcing token where applicable.

Observability:

- Basic request logging (method, path, response status, duration).
- Health endpoint extended with:
  - DB connectivity check.
  - Migration/schema version number.

### Frontend

Export/import UI:

- In a small “Admin” section or settings dialog:
  - Export:
    - Button to download JSON snapshot.
  - Import:
    - File upload control.
    - “Wipe first” checkbox.
    - Confirmation warnings.

Auth handling:

- Optional token field in frontend settings (stored locally in browser, not in backend).
- If token is set, included as `Authorization: Bearer` header on all API calls.

Quality-of-life enhancements:

- “Recent changes” view:
  - Simple chronological list (last N updates/creates).
  - Basic backend support via timestamps and a “recent activity” endpoint, or implemented via `updated_at` sorted queries per entity.
- Inline validation and clearer form errors.

**Exit Criteria**

- A fully populated environment can be exported and imported into a fresh instance.
- Optional API token can be turned on without code changes.
- Day-to-day use feels safe (backups) and reasonably secure for a private homelab.

---

## Phase 5 – Future (Post-v1, Optional)

_Not required for v1, but useful to keep in mind:_

- Multi-user and roles (read-only vs editor).
- More advanced auth: OIDC/OAuth2 integration.
- “As-code” import/export (e.g., YAML definitions).
- Integrations / partial discovery:
  - Read-only ingest from Proxmox, NetBox, or similar.
- Versioned docs and change history per entity.

```