# 00 · Boundaries, directory strategy, and shared contracts

## Architectural rule

Keep the current layered structure:

```text
api/                   HTTP parsing, dependencies, status codes, response models
schemas/               public request/response contracts, no database or network work
services/              domain orchestration, SQL queries, focused pure helpers
  intelligence/        impact and vulnerability reasoning
  monitoring/          existing checks plus narrowly scoped metric-rule logic
  inventory_transfer/  new package: portable-format planning/application only
db/models/             existing domain-split ORM models; __init__ re-exports
workers/               transport consumption or scheduled batch execution
startup/               registration, ownership, shutdown; not domain algorithms
core/                  existing shared security, time, locks, errors, egress
```

Only inventory transfer gets a new service package: format parsing, export, planning, and application are distinct substantial responsibilities currently crowded into admin.py. Smaller additions remain adjacent modules in the existing service layout. Intelligence and monitoring already have appropriate packages.

### Shared-file integration discipline

Each feature owns its domain files; integrate edits to routing.py, startup/jobs.py, models/__init__.py, shared schemas, and migration heads deliberately. These files are registries or shared contracts, not places to collect feature implementation. Add a router/model/job only when its service and tests land; do not register placeholder workers or empty routes. A domain test must not require importing every new feature through a large convenience barrel.

Do not relocate all existing flat services merely to make the tree uniform. Keep docker_discovery.py and cve_service.py as small compatibility facades while their immediate callers migrate; retain the split entity model modules and existing monitoring/intelligence packages. Remove temporary forwarding wrappers only after imports and scheduled/manual callers are verified.

### Import and ownership rules

- API → service → schemas/domain types + models/core. Workers → service. Pure decision modules do not import routers, startup, SessionLocal, or network clients.
- Never import API functions from a worker or service to reuse business logic; extract that logic downward.
- Use sync SQLAlchemy Sessions consistently with current services. Async HTTP/worker orchestration must not perform large synchronous query/serialization work directly on the event loop.
- Query/serializer/planner helpers take caller-owned sessions and do not commit. The use-case boundary owns commit/rollback; background entry points create/close their own sessions.
- Never send HTTP notifications or hold remote enumeration inside a mutation transaction. Read/claim briefly, do bounded I/O outside it, then revalidate and persist.
- Existing service functions may commit internally. Do not compose those into an allegedly atomic import. Extract only required validate/prepare/flush operations with no commit, retaining wrappers for old callers.
- Audit helpers must be checked for transaction behavior too: log_service contains commit paths and cannot be assumed transaction-neutral. Keep operation results correct even if post-commit diagnostic publication fails.
- No model-module import side effects that start workers or connect to external services.

## Shared files: change or reuse, not duplicate

| File under app/ | Plan |
| --- | --- |
| core/errors.py | Extend AppError/ConflictError with optional safe structured metadata/fields. Keep existing message/status/code compatibility. |
| schemas/errors.py | Extend ErrorResponse with typed/allowlisted context; retain a human-readable detail string. |
| main.py | Only adjust existing exception-handler projection if necessary; no new domain logic or router/job tables. |
| core/rbac.py, core/security.py | Reuse role/scope/token policies. Add a small public read-context adapter only if aggregate queries cannot use current dependencies; no alternate role hierarchy. |
| schemas/inventory.py (new) | Shared bounded query envelope and EntityRef used by inventory/search/selection; avoid a universal entity ORM schema. |
| services/inventory_queries.py (new) | Concrete query-spec helpers and bounded metadata resolution, not generic CRUD. |
| services/entity_tags.py | Add bulk tag/document reads while preserving existing single-entity entry points. |
| services/ip_reservation.py | Retain IP/port/host-chain conflict authority. Do not create another collision checker. |
| core/time.py | Use injected/current UTC timestamps; do not compare naive/local time to sample timestamps. |
| core/job_lock.py, core/scheduler.py | Use current distributed-lock and SingleOwnerScheduler mechanisms; no process-local lock as cross-replica protection. |
| core/url_validation.py, core/egress.py | Retain outbound security and client construction; no direct arbitrary HTTP clients from new helpers. |
| api/routing.py | New-router mounting and the existing authentication dependencies. |
| startup/jobs.py | Exactly one stable registration per scheduled job, with shared lock identity across manual/scheduled paths where necessary. |
| db/models/__init__.py | Explicit imports and __all__ for new domain model classes; keep legacy imports working. |
| security/endpoint_policy.json, security/endpoint_inventory.json | Review policy; regenerate inventory through the existing generator/tests for changed endpoints. |

## Error and identity contracts

Proposed compatible error extension:

```json
{
  "detail": "This IP address conflicts with an existing asset.",
  "error_code": "ip_conflict",
  "fields": {"ip_address": "Choose an available address."},
  "context": {"conflicts": [{"entity_type": "hardware", "entity_id": 42}]}
}
```

The human-readable detail is always safe text. Context is allowlisted per error type; unauthorized names/IDs, secrets, raw provider bodies, uploaded documents, and credentials must not be reflected. Preserve established code spellings on existing paths; a repository-wide error-code rename is not needed.

Current RequestValidationError handling can echo the input body, and Pydantic error entries can contain input/context. When adding secret/file-bearing contracts, remove sensitive reflection through the shared handler/projection and add regression tests. Do not merely sanitize the final toast.

Use EntityRef with a documented canonical type + numeric ID at new contract boundaries. Existing names differ: compute attachment rows use `compute`, impact/CVE use `compute_unit`, and navigation/search have their own labels. Define explicit aliases for each consumer in a small fixed mapping beside inventory query specs. Do not rewrite stored entity_type values or silently migrate polymorphic relationships as a naming cleanup. Preserve existing JSON identifiers while adding canonical fields during compatibility.

## Principal, limits, and truthfulness

- Resolve an authenticated request's effective scope including narrowed API-token scopes, not just the associated user's role. Aggregated queries cannot bypass a restriction present on a type-specific endpoint.
- Apply existing visibility before querying/counting/paginating; never fetch secret-rich rows and filter in the browser. The product is single-tenant per current support scope; do not introduce a new tenancy model from dormant columns.
- Propose shared list defaults of 25 and maximum 100, search maximum 20, and explicit maximum query lengths; validate final values against existing callers. Bound SQL materialization, not just the final response.
- Public responses use semantic enums (accepted, partial, stale, unknown), timestamps, completeness, and reason codes. Zero counts are not proof of successful execution.
- Optional caches need explicit identity/freshness/invalidation keys; neither Redis nor a process dictionary is durable operational truth.

## Foundation implementation checklist

- [ ] Record route/type/scoping and alias tests before changes.
- [ ] Add compatible error metadata projection and secret-redaction tests.
- [ ] Introduce only the shared query types/helpers immediately consumed by plan 01.
- [ ] Add import-boundary tests where they protect refactored model/startup/facade contracts.
- [ ] For each new function document caller, inputs, output, transaction ownership, and failure behavior in its feature module.
- [ ] Keep new field defaults/backward compatibility safe for existing rows and API clients.
