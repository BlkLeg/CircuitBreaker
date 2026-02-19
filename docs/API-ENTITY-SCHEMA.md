# API & Entity Schema

## 1. Entities Overview

| Entity       | Table             | Description                              |
|--------------|-------------------|------------------------------------------|
| Hardware     | `hardware`        | Physical nodes (servers, routers, NAS)   |
| ComputeUnit  | `compute_units`   | VMs or containers running on hardware    |
| Service      | `services`        | Apps/daemons running in a compute unit   |
| Storage      | `storage`         | Disks, pools, datasets, shares           |
| Network      | `networks`        | VLANs / subnets                          |
| MiscItem     | `misc_items`      | External SaaS, tools, accounts, etc.     |
| Doc          | `docs`            | Markdown notes attachable to any entity  |
| Tag          | `tags`            | Labels, shared via `entity_tags`         |

All timestamps are ISO 8601 (`YYYY-MM-DDTHH:MM:SSZ`). IDs are auto-increment integers.

---

## 2. Database Schema (SQLite DDL)

### Common Tables

```sql
CREATE TABLE tags (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE
);

CREATE TABLE docs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    body_md     TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

-- Polymorphic tag linking
CREATE TABLE entity_tags (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL, -- 'hardware', 'compute', 'service', 'storage', 'network', 'misc'
    entity_id   INTEGER NOT NULL,
    tag_id      INTEGER NOT NULL,
    UNIQUE (entity_type, entity_id, tag_id),
    FOREIGN KEY (tag_id) REFERENCES tags(id)
);

-- Polymorphic doc attachment
CREATE TABLE entity_docs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,
    entity_id   INTEGER NOT NULL,
    doc_id      INTEGER NOT NULL,
    UNIQUE (entity_type, entity_id, doc_id),
    FOREIGN KEY (doc_id) REFERENCES docs(id)
);
```

### Hardware

```sql
CREATE TABLE hardware (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    role        TEXT,               -- 'hypervisor', 'router', 'nas', etc.
    vendor      TEXT,
    model       TEXT,
    cpu         TEXT,
    memory_gb   INTEGER,
    location    TEXT,               -- 'rack-1', 'closet', etc.
    notes       TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
```

### Compute Units

```sql
CREATE TABLE compute_units (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    kind            TEXT NOT NULL,        -- 'vm' or 'container'
    hardware_id     INTEGER NOT NULL,
    os              TEXT,
    CPU_cores       INTEGER,
    memory_mb       INTEGER,
    disk_gb         INTEGER,
    ip_address      TEXT,
    environment     TEXT,                 -- 'prod', 'lab', etc.
    notes           TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    FOREIGN KEY (hardware_id) REFERENCES hardware(id)
);
```

### Services

```sql
CREATE TABLE services (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    slug            TEXT NOT NULL UNIQUE,
    compute_id      INTEGER NOT NULL,
    category        TEXT,                 -- 'media', 'monitoring', 'infra', etc.
    url             TEXT,
    ports           TEXT,                 -- '80/tcp,443/tcp'
    description     TEXT,
    environment     TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    FOREIGN KEY (compute_id) REFERENCES compute_units(id)
);

CREATE TABLE service_dependencies (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    service_id      INTEGER NOT NULL,
    depends_on_id   INTEGER NOT NULL,
    UNIQUE (service_id, depends_on_id),
    FOREIGN KEY (service_id) REFERENCES services(id),
    FOREIGN KEY (depends_on_id) REFERENCES services(id)
);
```

### Storage

```sql
CREATE TABLE storage (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    kind            TEXT NOT NULL,        -- 'disk', 'pool', 'dataset', 'share'
    hardware_id     INTEGER,
    capacity_gb     INTEGER,
    path            TEXT,
    protocol        TEXT,                 -- 'zfs', 'nfs', 'smb', etc.
    notes           TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    FOREIGN KEY (hardware_id) REFERENCES hardware(id)
);

CREATE TABLE service_storage (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    service_id  INTEGER NOT NULL,
    storage_id  INTEGER NOT NULL,
    purpose     TEXT,                     -- 'config', 'data', 'backups'
    UNIQUE (service_id, storage_id),
    FOREIGN KEY (service_id) REFERENCES services(id),
    FOREIGN KEY (storage_id) REFERENCES storage(id)
);
```

### Networks

```sql
CREATE TABLE networks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    cidr            TEXT,
    vlan_id         INTEGER,
    gateway         TEXT,
    description     TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE compute_networks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    compute_id      INTEGER NOT NULL,
    network_id      INTEGER NOT NULL,
    ip_address      TEXT,
    UNIQUE (compute_id, network_id),
    FOREIGN KEY (compute_id) REFERENCES compute_units(id),
    FOREIGN KEY (network_id) REFERENCES networks(id)
);
```

### Misc

```sql
CREATE TABLE misc_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    kind            TEXT,         -- 'external_saas', 'tool', 'account', etc.
    url             TEXT,
    description     TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE service_misc (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    service_id      INTEGER NOT NULL,
    misc_id         INTEGER NOT NULL,
    purpose         TEXT,
    UNIQUE (service_id, misc_id),
    FOREIGN KEY (service_id) REFERENCES services(id),
    FOREIGN KEY (misc_id) REFERENCES misc_items(id)
);
```

---

## 3. REST API Surface (v1)

Base URL: `/api/v1`

### Hardware

| Method   | Path                    | Description              |
|----------|-------------------------|--------------------------|
| `GET`    | `/hardware`             | List (filters: `tag`, `role`, `q`) |
| `POST`   | `/hardware`             | Create                   |
| `GET`    | `/hardware/{id}`        | Get by ID                |
| `PUT`    | `/hardware/{id}`        | Replace                  |
| `PATCH`  | `/hardware/{id}`        | Partial update           |
| `DELETE` | `/hardware/{id}`        | Delete                   |

### Compute Units

| Method   | Path                         | Query params                         |
|----------|------------------------------|--------------------------------------|
| `GET`    | `/compute-units`             | `kind`, `hardware_id`, `environment`, `tag`, `q` |
| `POST`   | `/compute-units`             |                                      |
| `GET`    | `/compute-units/{id}`        |                                      |
| `PATCH`  | `/compute-units/{id}`        |                                      |
| `DELETE` | `/compute-units/{id}`        |                                      |

### Services

| Method   | Path                                        | Description               |
|----------|---------------------------------------------|---------------------------|
| `GET`    | `/services`                                 | List                      |
| `POST`   | `/services`                                 | Create                    |
| `GET`    | `/services/{id}`                            | Get                       |
| `PATCH`  | `/services/{id}`                            | Update                    |
| `DELETE` | `/services/{id}`                            | Delete                    |
| `GET`    | `/services/{id}/dependencies`               | List deps                 |
| `POST`   | `/services/{id}/dependencies`               | Add dep `{depends_on_id}` |
| `DELETE` | `/services/{id}/dependencies/{dep_id}`      | Remove dep                |
| `GET`    | `/services/{id}/storage`                    | List storage links        |
| `POST`   | `/services/{id}/storage`                    | Add storage link          |
| `DELETE` | `/services/{id}/storage/{storage_id}`       | Remove storage link       |

### Storage, Networks, Misc

Same CRUD pattern as Hardware. Networks additionally has:

- `GET /networks/{id}/members` — compute units on this network
- `POST /networks/{id}/members` — attach `{compute_id, ip_address}`
- `DELETE /networks/{id}/members/{compute_id}`

### Docs

| Method   | Path                        | Description                           |
|----------|-----------------------------|---------------------------------------|
| `GET`    | `/docs`                     | List all docs                         |
| `POST`   | `/docs`                     | Create doc                            |
| `GET`    | `/docs/{id}`                | Get doc                               |
| `PATCH`  | `/docs/{id}`                | Update doc                            |
| `DELETE` | `/docs/{id}`                | Delete doc                            |
| `POST`   | `/docs/attach`              | Attach doc to entity                  |
| `DELETE` | `/docs/attach`              | Detach doc from entity                |
| `GET`    | `/docs/by-entity`           | `?entity_type=service&entity_id=123`  |

### Graph / Map

```
GET /graph/topology?environment=prod&include=hardware,compute,services,storage,networks
```

Response:

```json
{
  "nodes": [
    { "id": "hw-1", "type": "hardware", "ref_id": 1, "label": "Node-1", "tags": [] },
    { "id": "svc-42", "type": "service", "ref_id": 42, "label": "Plex", "tags": ["media"] }
  ],
  "edges": [
    { "id": "e-hw-cu-10", "source": "hw-1", "target": "cu-10", "relation": "hosts" },
    { "id": "e-cu-svc-42", "source": "cu-10", "target": "svc-42", "relation": "runs" },
    { "id": "e-ss-1", "source": "svc-42", "target": "st-5", "relation": "uses" }
  ]
}
```
