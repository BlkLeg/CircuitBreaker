# 03 · Docker source, enumeration, and reconciliation helpers

UI consumer: Docker discovery source state, source/host assignment, container reconciliation.

## Current entry points and constraints

`api/discovery.py` owns /docker/status, /docker/sync and Docker inventory endpoints; `api/services.py` fetches container details. `services/docker_discovery.py` is called by manual BackgroundTasks and scheduled sync. The scheduler owns the scheduled wrapper's lock, but the manual path must use the same source-level exclusion.

Current connectivity logic is inconsistent: get_docker_status honors CB_DOCKER_HOST without a local socket, while sync_docker_topology rejects early if that socket is absent. Enumeration already uses docker_client's context manager; preserve tested cleanup.

Do not reuse discovery_reconciler as a generic inventory reconciler: it owns readiness, while agent_discovery_reconcile owns agent leases. Docker needs its own authoritative source semantics without changing those recently separated owners.

## File and storage plan

| File under app/ | Action / responsibility |
| --- | --- |
| schemas/docker.py | New: source/run summaries, enumeration completeness, parent assignment request, reconciliation result. |
| services/docker_enumeration.py | New: extract Docker SDK enumeration from discovery_safe; normalize records with native daemon/network/container identity. No DB writes. |
| services/docker_sources.py | New: existing configured source identity, durable run/lease state, safe parent assignment and display projection. |
| services/docker_reconcile.py | New: build/apply source-scoped delta from structured enumeration; no SDK calls. |
| services/docker_discovery.py | Retain thin public orchestration facade/status/detail entry points; remove process-global result as authoritative storage. |
| services/discovery_safe.py | Retain docker_client/socket policy and compatibility adapter for old enumeration callers until migrated. |
| db/models/discovery.py | Extend: DockerSource and DockerSyncRun. Keep domain registrations in models/__init__.py. |
| db/models/services.py, db/models/networks.py | Add source/provenance references and native identity constraints to Docker-managed rows. |
| api/discovery.py | Initially delegate existing routes; if adding source/run CRUD substantially grows it, extract only Docker handlers to api/docker.py and mount the same URL prefix in api/routing.py. |
| startup/jobs.py | Keep one scheduled owner; add bounded abandoned-run cleanup only if not covered by source-run execution. |

Initial source configuration reflects the existing local socket or explicitly configured proxy. Multi-source-safe identity is required for reconciliation, but an arbitrary remote-daemon onboarding product is not.

## Proposed functions

| Callable | Inputs → output / ownership |
| --- | --- |
| resolve_source_config(settings, environment) | Effective socket/proxy choice → validated connection config; never expose raw URLs/paths to ordinary operators |
| enumerate_docker(config, scope) | Bounded SDK I/O → DockerEnumeration with containers, native network IDs, daemon ID, completeness by resource class, timestamps and safe errors |
| get_or_create_configured_source(db, identity) | Existing configured daemon identity → source row; caller owns transaction |
| start_sync(db, source_id, actor) | Source/version → durable queued/running run with stable ID and conflict on active lease |
| plan_reconciliation(existing, enumeration, policy) | Pure normalized records → creates/updates/disappearances/conflicts, with coverage proof |
| apply_reconciliation(db, source, run, delta) | Revalidate run/source revision; flush inventory changes and terminal summary atomically |
| assign_source_parent(db, source_id, parent_ref, actor, expected_revision) | Validate allowed hardware/compute parent → stored manual provenance, caller commits |
| run_source_sync(source_id, run_id) | Own session lifecycle/lease; enumerate outside DB transaction; apply complete delta or retain observations on failure |
| read_source_status(db, source_id) | Durable latest attempt/success and run result; no daemon call required for ordinary history/status read |

Enumeration returns explicit success/partial/failure, never ambiguous `[]`. Separate container completeness from network completeness; only a complete resource scope can establish absence in that scope. Network filters changing are not evidence that excluded networks disappeared.

## Correctness policy

- Native network ID is preserved; name/driver is a label, not identity. Key Docker objects by source + native ID.
- Restrict recreation adoption to a source and demonstrable stable workload identity (such as complete Compose labels), with ambiguity reported. Do not adopt solely by display name across all Docker services.
- Resolve the daemon's parent explicitly; a proxy/container running Circuit Breaker is not automatically the managed host.
- Manual assignments win over discovery-derived associations. Distinguish unresolved/automatic/manual provenance and prevent stale sync from overwriting a newer user choice.
- Only a complete successful container enumeration may mark unseen containers stopped; this includes zero containers. Failure/partial outcomes preserve previous observations and last-success timestamp.
- A worker crash cannot leave “running” forever. Durable run lease expiry marks interruption without reconciling absence; a subsequent safe retry gets a new attempt.
- Lock and revision checks cover manual and scheduled entry points, source config changes, out-of-order runs, and repeated triggers.
- Preserve Docker networks/container memberships needed by the map; changes publish/invalidate after successful commit. Never derive network relations by global name lookup.

## Migration and endpoint plan

Add source/provenance columns nullable first. Backfill only unambiguous legacy configured-source rows; quarantine unresolved legacy ownership from disappearance reconciliation until reviewed. Existing globally unique docker_container_id constraints must be deliberately replaced with source-scoped uniqueness if source support requires it; do not drop identity protections without backfill/duplicate checks.

Add source/run reads and parent patch operations under the existing discovery/Docker URL family. Manual sync returns `202 + run_id`; fetching that run works across API replicas/restarts. Existing status/sync clients receive a coordinated compatibility adapter. Do not return “sync_started” before durable admission succeeds.

## Tests / done

Extend test_docker_client_lifecycle.py; add services/test_docker_enumeration.py, test_docker_reconcile.py, test_docker_sources.py, API and migration fixtures.

- [ ] Socket absent with valid configured proxy succeeds through the correct path; unauthorized/unapproved endpoints are rejected.
- [ ] Populated, empty, partial-network, partial-container, failed, timeout, and crash states are distinct.
- [ ] Same network/container name on different sources cannot collide.
- [ ] Last-container disappearance works; no unrelated source or excluded scope is reconciled.
- [ ] Parent assignment, source changes, concurrent manual/scheduled execution, and old-run completion preserve current data.
- [ ] Run status survives process restart and yields identical results on another API replica.
