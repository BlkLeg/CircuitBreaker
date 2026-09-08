# 08 · Migration, rollout, and backend verification plan

## Planned storage ownership

| Change | Store/model owner | Migration and recovery requirement |
| --- | --- | --- |
| Inventory pagination/search | Existing entity tables | Add only justified indexes after query-plan review; no table for route navigation or pins |
| Structured errors | No storage | Additive response metadata; legacy string/object compatibility tests |
| Delivery receipts/claims | PostgreSQL, db/models/notifications.py | Event/sink uniqueness, lease/retry indexes, terminal retention beyond replay horizon |
| Docker sources/runs | PostgreSQL, db/models/discovery.py | Durable source identity/run state, lease expiry, backfill existing configured source |
| Docker object provenance | PostgreSQL, db/models/services.py and networks.py | Nullable additive source fields first; duplicate review before source-scoped uniqueness |
| Assessment identity overrides | PostgreSQL, db/models/intel.py | Unique canonical entity reference, revision/provenance, cleanup for deleted polymorphic targets |
| Normalized CVE feed/generations | Existing SQLite cve.db, new db/cve_models.py | Separate cache metadata/schema versioning via cve_session; not a main-database Alembic-only change |
| Import previews/replay results | PostgreSQL, db/models/transfers.py | Actor-bound preview, hash/revision/expiry, unique replay key and atomic result |
| Metric rules/state/events | PostgreSQL, db/models/monitors.py | Constraint-checked rules, unique state/transition identities, pending-publish and active-incident retention |

New PostgreSQL models are explicitly imported/re-exported in db/models/__init__.py so both migration metadata and create_all test fixtures see them. Cache-only models are the deliberate exception: they must not appear as new unused tables in primary metadata. Preserve the existing legacy CVEEntry import until compatibility consumers are migrated.

Do not preallocate Alembic revision numbers; select the current single head when implementation begins. Existing migration history stays immutable. Cache schema upgrade is separately tested against a copy of an old cache; no production cache mutation during planning.

## Expand → migrate → switch → contract

1. **Expand:** add new nullable/default-safe columns and new contracts behind explicit endpoint/response negotiation. Keep legacy import paths and Python facade exports working.
2. **Migrate/backfill:** process bounded batches, record unresolved ownership/identity rather than guess. A legacy Docker row without proven source is not eligible for disappearance reconciliation. Legacy flattened CVE data is not magically complete.
3. **Switch callers:** migrate one real UI/API slice at a time and update scheduled/manual callers together. Ensure static subresource paths precede dynamic ID routes.
4. **Observe:** collect real failure, queue, query, migration and latency evidence. A feature returns unavailable/degraded honestly if its dependency or contract is not ready.
5. **Contract:** remove deprecated endpoint shapes/facades only after caller tests, support docs, and rollback window permit. Do not keep two authoritative services or two scheduled owners indefinitely.

Rollback should first disable the new job/feature and restore compatible code while retaining additive data. Dropping new operational tables can lose active alerts, import replay protection, or source attribution; any destructive downgrade requires explicit operator planning and recovery. Do not promise zero-data-loss automatic downgrade.

## Transaction and lifecycle test matrix

| Workflow | Required fault boundary | Expected invariant |
| --- | --- | --- |
| Inventory bulk reads | Large page / many attached rows | Query growth bounded by type/chunk; no accidental full-dataset truncation |
| Search/options | Narrow token, unsupported type, query limit | No scope bypass, bounded SQL, stable entity identity |
| Notifications | One sink accepted, another fails, redelivery | Accepted receipt retained; only eligible failed target retried |
| Notifications | Acceptance followed by crash before receipt | Ambiguous outcome documented; no fabricated exactly-once guarantee |
| Docker | Mid-enumeration failure or process exit | No authoritative absence; prior inventory/last-success preserved |
| Docker | Manual and scheduled sync race | One source owner/current revision wins; stale result cannot overwrite |
| CVE | Partial feed pages then failure | Previous complete generation remains identifiable; no fresh/clean claim |
| CVE | Cache upgrade/rebuild failure | Honest unavailable/stale status; no primary DB damage |
| Impact | Cycle, large shared subnet, removed root | Bounded traversal; no subnet clique; missing root not a fabricated asset |
| Import | Mid-write constraint failure | Whole mutation rolls back; replay/result contract remains truthful |
| Import | Commit succeeded, response lost | Same operation result recoverable; no duplicate merge |
| Metric rules | Duplicate sample/old revision/concurrent evaluator | State and event identity remain deterministic |
| Metric events | Commit before NATS outage | Pending event persisted; retry publisher eventually handles it |
| All background work | Shutdown/restart/second replica | Existing lock/lifecycle owner respected; leases expire predictably |

## Test location strategy

Keep tests beside the repo's current suites, not in a new test framework:

- `apps/backend/tests/services/`: inventory queries/attachments/search, delivery policy/receipts, Docker enumeration/source/reconcile, CVE orchestration/cache migration, transfer format/plan/apply, metric catalog/evaluator/rules.
- `apps/backend/tests/intelligence/`: dependency graph classification, traversal and evidence.
- `apps/backend/tests/api/`: contract shapes, explicit bounds, scopes, error redaction, compatibility and endpoint authorization.
- `apps/backend/tests/unit/`: pure helpers where that is already the matching convention, metadata/import registration, migration and startup ownership tests.
- `tests/integration/`: complete workflow/API/database/bus coverage using the existing integration harness.
- Existing frontend tests/Playwright consume the same response fixtures for each approved screen; test semantic behavior as well as screenshots.

The services suite's conftest starts disposable PostgreSQL/Timescale and redirects data/uploads before importing the app. Pure import paths should stay free of DB initialization so lightweight tests need not inadvertently create cve.db or touch a real data directory. Honor the existing suite environment setup and generate ephemeral secrets; do not import application modules in ad hoc “read-only” probes that initialize storage.

## Verification ladder and evidence

- [ ] Static Python typing/lint, API schema and error compatibility tests.
- [ ] Model import/metadata tests and a single Alembic head; actual upgrade against an old disposable database, not only create_all.
- [ ] Separate old-cache/new-cache initialization and interruption tests for CVE.
- [ ] Unit/service/API tests for each feature plus existing regression suites.
- [ ] Existing endpoint policy/generator checks. Define policy entries for new reads/writes, test unauthenticated/viewer/editor/admin/demo and narrowed-token behavior.
- [ ] Repository `make verify` plus `make verify-full` for changed backend behavior; the shorter gate omits backend tests. Run relevant integration/E2E jobs separately where not covered.
- [ ] Existing `scripts/loadgen/` measurements for query count, bounded memory, DB pool occupancy, impact graph growth, evaluator backlog and delivery latency. Report fixture size/hardware/context; avoid unmeasured capacity claims.
- [ ] Fake Docker/provider/feed endpoints and disposable inventory in automated verification. No live scans, notifications, feed downloads, imports or restores without a deliberate test environment.
- [ ] Retention, cleanup, migration rollback, pending-work recovery and multi-replica ownership tests.
- [ ] Update API/user docs and release support boundaries with implemented guarantees and known limitations.

## Decisions to settle at each implementation gate

These are engineering decisions, not reasons to re-approve the UI:

- Final bounded page/search/import/feed/evaluator limits, selected from measured existing deployments/fixtures.
- The explicit legacy API negotiation/deprecation window and canonical entity deep-link agreement with frontend.
- Docker legacy-source backfill confidence and any unresolved-record repair policy.
- Supported CVE version schemes and feed completeness/retention policy; unsupported remains unknown.
- Portable merge identity/update policy and any later destructive replacement mode. Replacement is not implicitly authorized by this plan.
- Initial metric/target/source catalog, freshness/gap durations, rule edit permissions, and retry/receipt retention.
- Whether measured long import execution needs durable background processing; do not create that subsystem preemptively.

Record final choices in the feature plan before implementation and record test evidence when complete. Any broader provider, deployment, storage, or destructive-scope change requires explicit direction.

## Planning verification record

This plan set was produced by read-only source inspection and document edits. Backend tests, benchmarks, migrations, provider calls, database writes, and worker execution were not run. Documentation link/path checks are not evidence of implemented behavior.
