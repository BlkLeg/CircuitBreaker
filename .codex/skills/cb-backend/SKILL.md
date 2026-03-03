---
name: cb-backend
description: FastAPI/SQLAlchemy backend development for Circuit Breaker — the self-hosted homelab visualization platform. Use when working on API routes (backend/app/api/), service layer (backend/app/services/), SQLAlchemy ORM models (backend/app/db/models.py), Pydantic schemas (backend/app/schemas/), telemetry integrations (backend/app/integrations/), or backend tests (backend/tests/). Covers entity CRUD, relationship management, discovery pipeline, audit logging, authentication (JWT), telemetry polling, IP conflict detection, and rate-limiting.
---

# Circuit Breaker — Backend Skill

## Stack

- **Python 3.11+**, FastAPI, SQLAlchemy 2.0 (mapped columns), Pydantic v2, SQLite
- **Auth**: PyJWT + bcrypt, optional (toggled by `AppSettings.auth_enabled`)
- **Rate limiting**: slowapi — disabled during tests via `limiter.enabled = False`
- **Scheduler**: APScheduler (telemetry polling, discovery schedules)
- **Discovery**: python-nmap, scapy (ARP), pysnmp, httpx
- **Telemetry integrations**: iDRAC (`app/integrations/idrac.py`), iLO (`ilo.py`), APC UPS (`apc_ups.py`), generic SNMP (`snmp_generic.py`)

## Repo layout

```
backend/app/
├── api/          # FastAPI routers — one file per entity/domain
├── core/         # config.py (Settings), rate_limit.py, errors.py, time.py
├── db/
│   ├── models.py # All SQLAlchemy ORM models (single file)
│   └── session.py
├── integrations/ # Telemetry drivers (idrac, ilo, apc_ups, snmp_generic, dispatcher)
├── middleware/   # logging_middleware.py, security_headers.py
├── schemas/      # Pydantic request/response schemas
├── services/     # Business logic — service layer between API and DB
└── main.py       # App factory, lifespan, middleware wiring
```

## Key conventions

### Adding an entity

1. Add ORM class to `db/models.py` (single-file, all models in one place).
2. Add Pydantic schemas (`Base`, `Create`, `Update`, `Read`) to `schemas/<entity>.py`.
3. Add CRUD service to `services/<entity>_service.py`.
4. Add FastAPI router to `api/<entity>.py`; register it in `main.py`.
5. Add audit log calls via `log_service.write_log(db, ...)` on create/update/delete.
6. Add tests in `tests/test_<entity>.py` using the `client` fixture (see below).

### ORM patterns

- Use `Mapped[T]` + `mapped_column()` (SQLAlchemy 2.0 style) — no `Column()`.
- Timestamps: `created_at` and `updated_at` via `default=_now` / `onupdate=_now` (`app.core.time.utcnow`).
- JSON stored as `Text` (SQLite has no native JSON) — serialize/deserialize manually.
- FK columns are nullable where an entity can exist without a parent.

### Service layer pattern

```python
# services/hardware_service.py example pattern
def get_hardware(db: Session, hardware_id: int) -> Hardware | None:
    return db.get(Hardware, hardware_id)

def create_hardware(db: Session, data: HardwareCreate) -> Hardware:
    obj = Hardware(**data.model_dump(exclude_unset=True))
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj
```

### Telemetry

- Config stored as JSON in `Hardware.telemetry_config` (Text column).
- Credentials encrypted via `credential_vault.py` (Fernet, key from `CB_VAULT_KEY` env var).
- Dispatcher (`integrations/dispatcher.py`) routes to the correct driver by `protocol` field.
- Poll results written back to `Hardware.telemetry_data` + `telemetry_status` + `telemetry_last_polled`.

### Discovery pipeline

`services/discovery_service.py` orchestrates: ARP scan → nmap → SNMP → HTTP probe.  
Results land in `ScanResult` rows; merge into `Hardware` via `discovery_profiles_service.py`.  
WebSocket progress stream: `api/ws_discovery.py`.

### IP conflict detection

`services/ip_reservation.py` — checks for IP collisions across Hardware, ComputeUnit, Service, ExternalNode. Result written to `Service.ip_conflict` + `Service.ip_conflict_json`.

### Auth

- `api/auth.py` — login, logout, token refresh endpoints.
- `core/config.py` `Settings` — `jwt_secret`, `session_timeout_hours` sourced from `AppSettings` DB row.
- Protected routes use `Depends(get_current_user)` from `services/auth_service.py`.

## Testing

- **Fixture**: `client` in `tests/conftest.py` — spins up an in-memory SQLite DB and patches `SessionLocal` globally (including middleware).
- **Pattern**: Use `client.post("/api/v1/hardware", json={...})` — no async needed, `TestClient` is sync.
- Tests live in `backend/tests/`; run with `pytest` from repo root via `make test`.

```python
def test_create_hardware(client):
    r = client.post("/api/v1/hardware", json={"name": "my-server", "role": "hypervisor"})
    assert r.status_code == 200
    assert r.json()["name"] == "my-server"
```

## Reference files

- **`references/schema.md`** — full field-level DB schema for all entities; read when adding/modifying models or writing queries.
