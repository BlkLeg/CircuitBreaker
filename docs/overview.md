# Service Layout Mapper – OVERVIEW.md

This document defines the goals, scope, and high-level design for a lightweight **Service Layout Mapper** that documents a homelab/infra stack and visualizes relationships between components.

## 1. Goal and Scope

The app’s purpose is to centralize documentation of:

- Hardware (nodes, switches, firewalls, etc.).
- Virtualization (VMs, LXCs, containers).
- Services/Apps (self-hosted software, databases, supporting daemons).
- Storage (pools, datasets, disks, shares).
- Misc infrastructure (DNS, VPNs, networks, external SaaS dependencies).
- A visual map layout showing how all of the above connect.
- Attached free-form documentation for each object.

Non-goals (for v1):

- Automated discovery, scanning, or config import.
- Real-time monitoring/metrics.
- Multi-tenant or RBAC-heavy features.

The v1 target is a single-user, self-hosted documentation tool that you can run on a homelab node and iterate on quickly.

## 2. Core Concepts and Data Model

Top-level entities:

- Hardware: Physical hosts, switches, firewalls, UPS, NAS, etc. Each has name, role, specs, tags.
- Compute Units:  
  - VMs: Guest name, host, resources, purpose.  
  - LXCs/Containers: Name, host, image/base, purpose.
- Services/Apps: Logical services (e.g., “Plex”, “IPAM”, “Home Assistant”), with URLs, ports, owning VM/LXC, and category.
- Storage: Disks, pools, volumes, and shares, each with capacity, type, and where they are attached.
- Networks: VLANs, subnets, gateways, key firewall rules at a descriptive level.
- Misc: Anything that does not fit cleanly above (external APIs, SaaS services, etc.).
- Docs: Markdown notes linked to any entity (or globally), for procedures, runbooks, or rationales.

Relationships:

- Hardware hosts Compute Units.
- Compute Units run Services/Apps.
- Services/Apps depend on other Services, Storage, and Networks.
- Hardware and Storage are linked (e.g., “ZFS pool on Node A”).

All entities should support:

- Stable IDs.
- Tags for flexible grouping (e.g., “prod”, “lab”, “media”).
- Links to external docs (wiki, git repo, runbook).

## 3. High-Level Architecture

Stack:

- Backend: Python (FastAPI or Flask) providing a JSON REST API for CRUD on all entities and relationships.
- Frontend: JavaScript SPA (React or minimal vanilla + a graph library) consuming the API and rendering lists, detail pages, and a topology/map view.
- Storage:  
  - v1: SQLite for simplicity.  
  - Future: Optional Postgres migration.

Backend responsibilities:

- CRUD endpoints for Hardware, Compute Units, Services, Storage, Networks, Misc, and Docs.
- Relationship management (e.g., assign service to VM, VM to node).
- Simple search/filter by name, tag, type.
- JSON export/import for easy backups and migration.

Frontend responsibilities:

- Entity lists with filters and quick search.
- Entity detail views with fields, relationships, and attached docs.
- Map view:  
  - Nodes representing entities (hardware, VMs/LXCs, services).  
  - Edges for “runs on”, “depends on”, “connected to” relationships.
- Inline Markdown rendering for docs.

## 4. Map Layout View

The map is the main “at-a-glance” visualization:

- Layout:  
  - Hardware as the outer layer (e.g., grouped per physical node or rack).  
  - Compute Units inside or attached to their hardware.  
  - Services/Apps as a higher layer attached to their compute unit.  
  - Storage and Networks shown as shared resources that multiple services connect to.
- Interaction:  
  - Pan/zoom, basic node highlighting.  
  - Click node → open side panel or detail page.  
  - Filter by tag, type, or environment (e.g., show only “prod” and “media”).

v1 layout engine can be:

- Client-side only, using a graph library (e.g., simple force-directed layout), with precomputed groupings from the API.

## 5. UX and Workflows

Primary workflows:

- “Document my lab”: manually create hardware, add VMs/LXCs, then add services to each.
- “Understand where a service lives”: search a service, see its hosting VM/LXC and backing hardware, plus storage and network dependencies.
- “Add notes for future me”: attach docs to any entity and link out to external tooling (NetBox, BookStack, Obsidian, etc.).

Navigation:

- Sidebar: Sections for Hardware, Compute Units, Services, Storage, Networks, Misc, Map, Docs.
- Global search bar.
- Persistent “Map” entry as the default landing page after setup.

## 6. Security and Deployment

Security (v1):

- Single-user or small trusted group in a homelab context.
- HTTP behind reverse proxy (nginx/Traefik/Caddy) with TLS termination.
- Optional basic auth or simple token auth on the API.

Deployment:

- Simple Python app packaged as:  
  - Docker container.  
  - Or venv + systemd service.
- Single configuration file (YAML/TOML) for database path, listen address, and basic auth/token settings.

## 7. Roadmap (High-Level)

Phase 0 – Skeleton:

- Define data models and migrations (SQLite).
- Implement basic CRUD API for all entities.
- Set up minimal JS frontend with list/detail views for one entity type.

Phase 1 – Full CRUD + Docs:

- CRUD for all entity types via UI.
- Markdown docs support and linking.
- Tagging and basic search.

Phase 2 – Map View:

- Graph API endpoints for relationships.
- Initial interactive map with hardware → compute → services layering.

Phase 3 – Quality of Life:

- JSON export/import.
- Simple auth.
- Basic “recent changes” view.

Phase 4 – Optional Enhancements (future ideas):

- Basic integration hooks (e.g., ingest a static JSON from Proxmox API, NetBox, or other tools without full sync).
- Snapshot/versioned docs.
- Multi-user with roles.