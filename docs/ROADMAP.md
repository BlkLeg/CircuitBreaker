# Roadmap

## v1 (current)

- Full CRUD for all 7 entity types: Hardware, ComputeUnit, Service, Storage, Network, MiscItem, Doc
- Polymorphic tagging via `entity_tags`
- Polymorphic doc attachments via `entity_docs`
- Service dependency graph (service → service)
- Service–storage and service–misc associations
- Network membership for compute units
- `GET /graph/topology` endpoint for map view
- React SPA with sidebar navigation, entity tables, create/edit forms, Markdown viewer, ReactFlow map
- Docker Compose deployment with healthcheck-gated startup
- In-memory SQLite fixture for fast unit tests

## v2 Ideas

- **Auth**: JWT-based authentication with API key management (`core/security.py` is pre-stubbed)
- **PostgreSQL**: Swap `DATABASE_URL`; add Alembic migration workflow (already in deps)
- **Pagination**: `limit`/`offset` or cursor-based pagination on list endpoints
- **Change tracking**: Immutable audit log table; diff view for entity updates
- **Prometheus metrics**: `/metrics` endpoint for request counts, latency histograms
- **Export**: PNG/SVG topology diagram export from the map view
- **Force-directed layout**: Replace the simple grid layout in MapPage with `d3-force`
- **Bulk import**: CSV/YAML import endpoint for seeding an inventory from existing data

## Known Limitations (v1)

- SQLite does not enforce foreign keys on the polymorphic `entity_tags` / `entity_docs` columns — `entity_type` and `entity_id` are application-validated only.
- SQLite write concurrency is serialized; not suitable for multi-user write-heavy workloads.
- List endpoints return all records without pagination — acceptable for typical homelab scale (< 1000 entities).
- ReactFlow node positions are computed with a simple grid; overlapping nodes are mitigated by `fitView` but not eliminated.
