# Architecture Overview

## Purpose

`service-layout-mapper` documents a homelab infrastructure topology. It replaces ad-hoc spreadsheets and wikis with a structured inventory and an interactive graph that shows how nodes, VMs, services, storage, and networks are connected.

## Three-Tier Design

```
[ React SPA ]  ←HTTP→  [ FastAPI REST ]  ←SQLAlchemy→  [ SQLite ]
   frontend               backend/app                    data/app.db
```

- **Frontend**: React SPA with a page per entity type and a `MapPage` that renders the topology as an interactive graph using ReactFlow.
- **Backend**: FastAPI with a layered architecture — `api/` (routers), `services/` (business logic), `db/` (ORM models), `schemas/` (Pydantic request/response), `core/` (config).
- **Database**: SQLite in v1 for zero-dependency deployment. The `DATABASE_URL` setting can be swapped to a PostgreSQL URL in v2 without changing application code.

## Entity Relationships

```
Hardware (physical node)
  └── ComputeUnit (VM or container)   [hardware_id FK]
        └── Service (app/daemon)      [compute_id FK]
              ├── ServiceDependency   [service → service]
              ├── ServiceStorage      [service → storage]
              └── ServiceMisc        [service → misc_item]

Storage                               [hardware_id FK optional]
Network
  └── ComputeNetwork                  [compute_id + network_id]

Tag  (polymorphic via entity_tags)
Doc  (polymorphic via entity_docs)
```

## Polymorphic Tag & Doc Design

Both `entity_tags` and `entity_docs` use a discriminator column (`entity_type TEXT`) and a numeric `entity_id` rather than per-entity join tables. This keeps the schema flat and makes it trivial to add a new entity type without schema migration.

The trade-off is that foreign key constraints cannot be enforced by SQLite for the polymorphic columns — application-level validation is used instead.

## Graph Endpoint

`GET /api/v1/graph/topology` aggregates all entities into a `{ nodes, edges }` payload that the React frontend feeds directly into ReactFlow. Node IDs are prefixed by type (`hw-1`, `cu-10`, `svc-42`) to ensure global uniqueness across entity types.
