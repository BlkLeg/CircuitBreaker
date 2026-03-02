# Circuit Breaker CORTEX Backend Intelligence Upgrade Prompt

You are a senior FastAPI/SQLAlchemy engineer tasked with implementing the 32 findings from **CORTEX.md** (v0.1.4-beta audit). Focus on rack-impacting fixes first (CB-RACK-*-*), then P1/P2 correctness/intelligence gaps. Prioritize atomicity, derived state, and relationships without breaking existing APIs/UX.

## Project Context
- **Repo**: `BlkLeg/circuitbreaker` (v0.1.4-beta, rack sim v1.1 pre-foundation)
- **Stack**: FastAPI (Python 3.12), SQLAlchemy (SQLite), React/Vite frontend
- **Key files**: `backend/app/db/models.py`, `services/*.py`, `api/*.py`, `graph.py`
- **Deployment**: Single Docker image (`ghcr.io/blkleg/circuitbreaker`)
- **Principles**:
  - Freeform-first (no gating)
  - Derived state via hooks/signals (not cron)
  - SQLite migrations via `run_migrations()` guards (ALTER IF NOT EXISTS)
  - No regressions to CRUD/topology/rack sim

## Implementation Priority (32 Findings)
**Phase 1: Rack Foundation (P1, Rack=Yes) — Ship first**
1. **CB-RACK-001**: Add `Rack` model/table (`id`, `name`, `height_u`, `location`). `Hardware.rack_id` FK (nullable). Migrate via guard.
2. **CB-RACK-002**: `services/hardware_service.py` → `check_rack_overlap(rack_id, rack_unit, u_height)` query. Reject 422 on create/update.
3. **CB-REL-002**: Denormalize `Service.hardware_id` (populated from `compute.hardware_id` on save). Use in `graph.py` for direct edges.

**Phase 2: Correctness (P1 Cascade/State)**
4. **CB-STATE-003**: IP conflict re-eval → `services/ip_conflict_check(ip, exclude_id)`. Call on `Hardware.update` → loop children.
5. **CB-STATE-006**: Port conflict → `services/port_conflict_check(compute_id, ports_json, exclude_id)`.
6. **CB-CASCADE-005**: Wrap `discovery_service.merge_scan_result` in `db.begin_nested()`.
7. **CB-PATTERN-001**: Unique index `mac_address` on Hardware (migration). Soft alert on dupes.

**Phase 3: Intelligence/Derived State (P2)**
8. **CB-STATE-001**: `hardware_service.recalculate_status(hardware_id)` → telemetry worst-child. Call on telemetry/update.
9. **CB-STATE-002**: Add `ComputeUnit.status` derived from services.
10. **CB-STATE-005**: Update `Hardware.last_seen` on telemetry success/API touch.
11. **CB-PATTERN-003**: `hardware_service.find_orphans()` → no services/compute/storage.
12. **CB-PATTERN-004**: `GET /api/v1/hardware/groups` → GROUP BY vendor+model COUNT.
13. **CB-LEARN-002**: On Hardware save, catalog lookup → auto-fill `u_height/role` if null.
14. **CB-REL-001**: `Hardware.source_scan_result_id` FK → ScanResult. Populate on merge.

**Phase 4: Future-Proof (P3, Rack Enhancements)**
15-32: Remaining (e.g., CB-RACK-003 orientation enum, CB-STATE-004 net util, CB-LEARN-001 port→category).

## Technical Guidelines
- **Migrations**: `run_migrations()` → raw SQL `ALTER TABLE IF NOT EXISTS ADD COLUMN`.
- **Derived State**: Use SQLAlchemy events (`@event.listens_for(Hardware, 'after_update')`) or service hooks.
- **API Changes**:
  - New: `/api/v1/racks`, `/hardware/groups`, `/hardware/orphans`.
  - Extend: `HardwareOut` (+`rack_name`, `status_derived`), `ServiceOut` (+`hardware_id`).
- **Rack Hooks**:
  - `RackService`: CRUD + overlap validation.
  - `graph.py`: `rackGroup` nodes → `rackMember` edges.
  - Frontend: RackPage (DnD), map integration (?rack=ID).
- **Transactions**: All multi-step ops (merge, cascade) → `db.begin()`.
- **No Breaking Changes**: Existing endpoints idempotent/backward-compatible.
- **Tests**: `backend/tests/test_cortex.py` → 1 test per finding.

## Output Format
1. **Migration Script** (`run_migrations()` additions).
2. **New/Changed Models** (Rack, FKs).
3. **Service Hooks** (recalc_status, validators).
4. **API Extensions** (endpoints, schemas).
5. **Rack Integration** (RackService, graph nodes).
6. **Test Suite** (key assertions).
7. **Docker Notes** (if schema changes).

**Exit Criteria**:
- Rack sim validates overlaps, links Hardware→Rack.
- `curl /api/v1/hardware/1?include=derived` → new fields populated.
- No regressions (CRUD, graph, discovery).
- `docker build && docker run` → works.

Implement Phase 1-3 fully. Defer P3 to follow-up. Commit as "feat(cortex): intelligence audit fixes".
