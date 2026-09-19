# Backend functions and helpers for the approved UI

Date: 2026-09-07  
Inspection baseline: working tree at `92039986`; concurrent frontend/refactor changes remain outside this work.  
Status: implementation planning only. No backend files, migrations, live services, or data were changed.

## Purpose

Power the [eight approved designs](../approved-ui/README.md) with accurate, bounded, authorized operations. These documents deepen the backend sections of the UI plans; they do not reopen visual approval or introduce unrelated features. Revalidate source drift before implementing a slice.

The navigator replaces the menu and command palette, but the server only needs to improve asset search/activation contracts—not store the frontend route tree or personal pins. Themes stay in the frontend: backend responses expose semantic state, reason codes, freshness, units, and provenance, never Gruvbox colors or CSS.

## Plan index

| Plan | Backend responsibility | Dependency |
| --- | --- | --- |
| [00 · Directory boundaries and shared contracts](00-boundaries-and-shared-contracts.md) | Preserve refactored structure, transaction ownership, errors, identity, security | First |
| [01 · Inventory and navigator search](01-inventory-and-search.md) | Bulk serialization, bounded list/selector/search queries, structured conflicts | 00 |
| [02 · Notification delivery](02-notification-delivery.md) | Shared delivery classification, retries, per-sink outcomes, message acknowledgement | 00; required by 07 |
| [03 · Docker discovery](03-docker-discovery.md) | Source identity, durable sync status, enumeration authority, parentage | 00/01 |
| [04 · Vulnerability assessment](04-vulnerability-assessment.md) | Feed completeness, product identity, applicability, honest assessment state | 00/01 |
| [05 · Dependency impact](05-dependency-impact.md) | Typed directed evidence, bounded traversal, bulk resolution | 00/01; stable map integration |
| [06 · Inventory transfer](06-inventory-transfer.md) | Versioned export, validation, conflict planning, safe atomic application | 00/01; verified relationship inventory |
| [07 · Metric alert rules](07-metric-alert-rules.md) | Rule validation, sample semantics, state transitions, reliable dispatch | 00/01/02 |
| [08 · Migrations, rollout, and verification](08-migrations-and-verification.md) | Data ownership, expand/contract changes, tests and release gates | Cross-cutting |

Each feature plan specifies existing entry points, proposed file ownership, callable boundaries, contracts, failure semantics, storage, and tests. Names marked “new” are proposed files, not work already performed. Do not create empty scaffolding ahead of its implementation slice.

## Confirmed implementation facts

| Current source | Fact and planning consequence |
| --- | --- |
| [api/routing.py](../../../apps/backend/src/app/api/routing.py) | Router table is already extracted. Register new routers here, not in main.py. |
| [startup/jobs.py](../../../apps/backend/src/app/startup/jobs.py), [startup/workers.py](../../../apps/backend/src/app/startup/workers.py) | Scheduled jobs and process-owned loops have separate lifecycle owners. Do not rebuild startup orchestration. |
| [db/models/__init__.py](../../../apps/backend/src/app/db/models/__init__.py) | Models are split by bounded context; the package imports/re-exports them for metadata discovery and compatibility. New tables must be registered here. |
| [services/entity_tags.py](../../../apps/backend/src/app/services/entity_tags.py) | Tag/document attachment logic is already shared. Add bulk reads here rather than another attachment abstraction. |
| [services/hardware_service.py](../../../apps/backend/src/app/services/hardware_service.py) | List serialization still calls tag/document reads per row and loads an unbounded result. IP conflicts use object-valued HTTP detail. |
| [api/search.py](../../../apps/backend/src/app/api/search.py) | Fetches all matches for each type before slicing to 20; results point to collection pages. |
| [services/docker_discovery.py](../../../apps/backend/src/app/services/docker_discovery.py) | Sync result is a process-global dictionary; identities/disappearance queries are not source-scoped; an empty seen set skips disappearance handling. |
| [services/discovery_safe.py](../../../apps/backend/src/app/services/discovery_safe.py) | Docker enumeration mixes containers and a topology sentinel; network enumeration errors are swallowed and failure can become an empty list. |
| [workers/notification_worker.py](../../../apps/backend/src/app/workers/notification_worker.py) | Webhook responses are discarded. Dispatch exceptions gathered by process_alert are logged without propagating an aggregate failure; run_worker subsequently acknowledges. Redis suppression is recorded before dispatch. |
| [services/cve_service.py](../../../apps/backend/src/app/services/cve_service.py), [db/cve_session.py](../../../apps/backend/src/app/db/cve_session.py) | Lexical version matching/first applicability only; CVE data actually lives in separate SQLite, despite sharing Base model metadata. Main Alembic changes alone cannot upgrade it. |
| [services/intelligence/dependency_graph.py](../../../apps/backend/src/app/services/intelligence/dependency_graph.py) | Subnet peers become mutual dependencies, physical connections become dependencies without evidence classification, and ServiceStorage is missing. |
| [api/admin.py](../../../apps/backend/src/app/api/admin.py) | Portable export serializers and import logic remain in the router; import uses db.merge on supplied primary keys. |
| [core/destructive_actions.py](../../../apps/backend/src/app/core/destructive_actions.py) | An Idempotency-Key header is required for destructive actions, but the helper does not implement a durable replay record. Header presence is not idempotent execution. |
| [services/monitoring/state.py](../../../apps/backend/src/app/services/monitoring/state.py) | Existing availability transitions demonstrate pure decision + locked application. Reuse that separation for metrics, not its up/down retry semantics. |

These are source observations, not new live reproductions, benchmarks, or claims that a deployed instance is affected in every configuration.

## Strategic implementation order

1. Establish contract tests, identity aliases, error metadata, and transaction rules.
2. Complete inventory bulk reads/paging/selectors and search. Notification correctness can proceed independently.
3. Correct Docker and impact contracts; implement CVE readiness before declaring matching complete.
4. Implement safe transfer once declared entity/relationship coverage and validators are settled.
5. Add metric rules only after notification acknowledgement/retry correctness is verified.
6. Finish migrations, recovery, scope, load, and end-to-end tests for each slice before release.

Do not delay a small correctness repair behind a whole domain reorganization. Extract only the responsibilities touched by the slice, retain compatibility entry points temporarily, and migrate callers with tests.

## Boundaries against scope creep

- No generic repository/service base classes, plugin framework, workflow engine, universal job table, new database, search cluster, or second graph engine.
- No backend route-navigation service, pin/recents API, or UI-theme endpoint just for these designs.
- No new Docker provider/daemon-management features, CVE triage/offline-feed UI, online full-state restore, or advanced alert policy.
- New persistence must buy correctness: source/runs, import replay/preview binding, assessment identity/feed metadata, alert transitions/delivery receipts. Do not store cosmetic state or raw secrets.
- Do not change historical migrations or invent revision numbers ahead of the current head. Preserve model imports and public service facades throughout staged refactoring.
