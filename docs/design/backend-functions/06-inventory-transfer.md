# 06 · Portable inventory export, planning, and safe application

UI consumer: Inventory transfer / Data Management; distinct from full-state backup and offline recovery.

## Why this needs a focused package

api/admin.py currently owns many serializers, import ordering, wipe operations, and primary-key merge. Separate the portable-format implementation while leaving admin controls/HTTP policy in their owners. Full-state snapshot code already lives in services/backup/ and db_backup.py; it must not be repurposed into online database restore.

## File plan

| File under app/ | Action / responsibility |
| --- | --- |
| schemas/inventory_transfer.py | New: portable manifest, allowlisted records/relationships, resolution requests, preview/apply results; explicit format/version. |
| services/inventory_transfer/__init__.py | Small public exports only; no side effects or implementation dump. |
| services/inventory_transfer/format.py | Parse/validate bounded portable input, legacy v2 adapter, declared coverage and safe serializable records. |
| services/inventory_transfer/export.py | Consistent snapshot reads and explicit field projection; relationship coverage; no hidden mutation. |
| services/inventory_transfer/plan.py | Identity matching, reference validation, conflict resolution, topological ordering, deterministic preview/digest. |
| services/inventory_transfer/apply.py | Transactional execution, source-to-target remapping, replay record, result counts. |
| db/models/transfers.py | New: InventoryTransferPlan/operation record for actor-bound preview, expiry, apply status and idempotent result. |
| api/inventory_transfer.py | New: authorized preview/apply/result/export routes, registered in api/routing.py. |
| api/admin.py | Delegate portable export/import compatibility only; retain unrelated Clear Lab/reset/recent-changes behavior. |
| Existing entity service validators | Extract no-commit validators as needed; keep existing CRUD wrappers and external side-effect ownership. |
| core/destructive_actions.py, services/backup/ | Reuse destructive guards/offline snapshot semantics unchanged. |

This package is warranted by four substantial responsibilities. Do not additionally create repository, manager, handler, and executor layers for the same operation.

## Functions and transaction ownership

| Callable | Responsibility / effects |
| --- | --- |
| parse_inventory_document(bytes, limits) -> PortableInventory | Strict version/type/size/depth/count validation; allowlisted fields; no ORM construction from arbitrary keys |
| normalize_legacy_v2(data) -> PortableInventory | Explicit legacy field/relationship mapping; report unsupported omissions, never silently guess |
| export_inventory(db, options) -> PortableInventory | Consistent read snapshot; explicit serializers and excluded-field manifest |
| resolve_import_identities(db, document, resolutions) -> IdentityPlan | Source refs map to create, explicit existing match, or unresolved conflict; PK equality is never identity |
| validate_references(document, identity_plan) -> ValidationReport | All FK/polymorphic relations, host chains, uniqueness, IP/port rules, custom/icon/document references |
| build_import_plan(db, document, resolutions, actor) -> ImportPlan | Counts and operations, evidence/read-set digests, format/file digest, policy revision; no inventory mutations |
| save_preview(db, plan, actor, expires_at) -> plan_id | Persist minimal bounded plan/document material or approved staging reference; own explicit preview transaction |
| apply_import(db, plan_id, expected_digest, idempotency_key, actor) -> ImportResult | Revalidate same plan/actor/input/context; execute allowlisted writes in one transaction; atomic result/replay record |
| read_import_result(db, operation_id, actor) | Safe result projection; authorization and expiry semantics |
| expire_transfer_plans(db, now, limit) | Bounded cleanup of expired, non-running records/staging only |

The API or apply use case explicitly owns commit/rollback. Lower-level functions flush but do not commit. Any called existing CRUD/log helper that can commit must be adapted or kept outside the mutation transaction.

## Portable contract and fidelity

Introduce a named portable format/schema version; retain an explicit legacy v2 reader. Keep the old export contract stable until callers migrate. The portable manifest is not “all database rows.”

Declare coverage for hardware, compute, services, storage, networks, misc, external nodes, tags, documents, clusters, and their supported relationships. Include HardwareConnection, ServiceStorage, service dependencies, network memberships, external associations, and tag/document joins. Audit category/environment/registry references and every exported FK; either include/remap their registry or explicitly represent a safe portable value.

Exclude users/sessions/tokens, secrets/vault material, operational runs/history, live telemetry, instance settings, and map layouts unless separately selected. References to uploaded icons/files require declared behavior; do not export local filesystem paths as portable assets. Document text can be portable, but rendering continues through existing sanitization. No arbitrary SQL or dynamic model construction.

Merge creates new local IDs and rewrites all references. Explicit user-approved updates match a target with validated identity/revision; same-name collisions are not automatic identity proof. Cyclic service dependencies require entity creation first and relationship linking second—not a naive single FK sort.

## Preview, apply, and crash safety

1. Parse and validate; store a bounded actor-bound preview with file hash, selected mode/resolutions, scope/read-set fingerprint, expiry and format/policy version.
2. Preview returns actual proposed creates/updates/skips and relationship changes; unresolved conflicts block apply.
3. Apply claims/locks the preview and durable idempotency key. Same key + different payload is a conflict; same completed operation returns its stored result.
4. Revalidate current identity matches and constraints under a transaction strategy that handles concurrent inserts as well as modified rows (e.g. appropriate serializable checks plus constraints). A stored hash alone does not prevent a time-of-check/time-of-use race.
5. Reject changed preview with a safe re-review response. Do not silently re-plan and apply a different set after confirmation.
6. Insert/update entities with remapped IDs, then relationships/attachments, validating IP and uniqueness rules; use no-commit domain operations.
7. Commit inventory changes and completed operation result together. Connection loss after commit is resolved by result lookup/replay, not a blind second import.
8. On rollback, report no inventory changes. Persist failure diagnostics in a separate safe transaction if needed. Post-commit audit/event failure must not turn committed import into an apparent rollback.

Initial recommendation: safe merge/create with explicit matched updates. Do not expose wipe/replace as a new portable mode until its preview, backup and confirmation contract is independently satisfied. Existing destructive endpoints retain safeguards and must not remain a hidden way to perform unsafe foreign-PK merges; migrate/deprecate/reject ambiguous legacy requests deliberately with compatibility documentation.

## Persistence, admission, and tests

Preview storage contains sensitive inventory descriptions even without credentials: restrict by actor/admin policy, bound count/bytes/age, avoid public uploads, and define cleanup. Never stage under an assumed large /tmp—the mono deployment can use a small tmpfs. If files are needed, use the existing data-root staging policy and validated generated paths, not uploaded filenames.

An accepted apply must have a durable outcome or explicit interruption recovery. For the initial bounded operation prefer a transaction completed within the request budget; if measurement requires background apply, use an explicit durable worker owner, not fire-and-forget BackgroundTasks pretending to be a job system.

- [ ] New schema/format, planner, apply and API tests; include all declared relation kinds and foreign-ID collisions.
- [ ] Constraint/concurrent-insert/preview-expiry/idempotency/actor mismatch tests.
- [ ] Fault injection before write, mid-relationship write, after commit before response, and post-commit audit failure.
- [ ] Main PostgreSQL migration includes operation uniqueness, expiry indexes and model registration; cleanup never removes running/replay-needed operations.
- [ ] Full-state services/backup and offline restore tests remain unchanged/green.
- [ ] Legacy clients receive an explicit migration path, not silently different merge semantics.
