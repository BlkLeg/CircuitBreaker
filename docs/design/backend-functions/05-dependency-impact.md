# 05 · Dependency graph evidence and impact traversal

UI consumer: selected-asset impact list, focused graph, confirmed/inferred evidence.

## Current service boundary

Retain `services/intelligence/dependency_graph.py:calculate_blast_radius` as the public orchestration entry during migration. api/intel.py currently declares its response models inline and serializes dataclasses. Existing BFS terminates cycles, but edge meaning and metadata loading need correction.

Do not move this work into api/graph.py or reopen the map layout refactor. Display connectivity and operational dependency are related data, not interchangeable graphs.

## File plan

| File under app/ | Action |
| --- | --- |
| schemas/intelligence.py | New: move existing impact DTOs and add typed edge/path/completeness fields. Keep unrelated intelligence DTOs together only if small/cohesive. |
| services/intelligence/dependency_edges.py | New: load and classify source relationship rows; stable edge identity/provenance; pure normalized graph construction. |
| services/intelligence/dependency_graph.py | Modify: bounded traversal, deduplication, explainable paths, bulk entity projection; retain public facade. |
| services/inventory_queries.py | Reuse bulk identity/name/status reads from plan 01; do not call detail serializers per node. |
| api/intel.py | Adapt query/response and permissions; no traversal logic. |
| Existing relationship models | Reuse; no new edge table just to duplicate existing hosting/dependency facts. |

## Function and edge contract

- `load_dependency_edges(db, scope, access) -> EdgeSet`: bounded bulk relationship reads. Each edge carries provider, dependent, type, source table/record reference, provenance, confidence category, and optional observed timestamp.
- `classify_relationship(record) -> DependencyEdge | ConnectivityEdge | Unsupported`: pure rules, not inferred from line style or subnet proximity.
- `build_impact_adjacency(edges, include_inferred=False)`: normalized **provider → dependent** direction, matching current impact traversal. Keep domain “A depends on B” storage semantics explicit when reversing ServiceDependency.
- `traverse_impact(root, adjacency, limits) -> TraversalResult`: deterministic BFS, unique impacted refs, predecessor/evidence records, cycle termination, depth/node/path bounds, and truncation reason.
- `resolve_impact_assets(db, refs, access)`: call bounded bulk resolver; missing/hidden endpoints are not fabricated named assets.
- `calculate_blast_radius(db, root, options, access)`: verify root exists and is readable, assemble evidence, return read-only potential impact.

| Existing source | Operational mapping |
| --- | --- |
| ComputeUnit.hardware_id | Hardware provider → compute dependent |
| Service.hardware_id / compute_id | Explicit parent provider → service dependent |
| ServiceDependency | depends_on_id provider → service_id dependent |
| Storage.hardware_id | Hardware provider → storage dependent |
| ServiceStorage | Storage provider → service consumer |
| HardwareNetwork / ComputeNetwork | Connectivity/membership only; no peer clique |
| HardwareConnection | Physical connectivity by default; dependency only with explicit supported semantics/evidence |
| Existing typed inferred relations | Optional, only when actual stored provenance supports classification; otherwise do not populate inferred results |

Do not confuse provider-down simulation with observed state. Root status is observed metadata; summary should say “Potential impact if unavailable,” not unconditionally “root IS DOWN.”

## Response and complexity plan

Keep existing grouped impacted arrays/count fields for compatibility; add `paths, edges, evaluated_at, completeness, limits, inferred_available` or a versioned response negotiated with the frontend. Counts distinguish unique entities from path count. If result limits truncate traversal, label count as returned/known lower bound rather than an exact full impact total.

Return a deterministic representative explanatory path per asset initially. Alternate path exploration can be bounded; never enumerate every simple path in a cyclic graph. Confirmed versus inferred propagation applies to the whole path: one inferred edge prevents presenting the path as confirmed.

Load only needed columns and group entity resolution by type. Avoid hardware-network pair expansion and per-asset db.get. SQL queries should scale by relation/entity types and chunks, not by graph edges. Set practical maximum nodes/edges/depth, reject or disclose oversized cases, and measure against the existing load fixtures.

Visibility applies before response projection and traversal policy. Do not reveal a hidden dependency through its path/name/count. Return a safe incomplete-evidence state if necessary, consistent with actual backend scopes rather than a fabricated row-level ACL.

## Integration and tests

- [ ] Add relationship truth-table tests before changing graph construction.
- [ ] Correct edge builder and ServiceStorage inclusion.
- [ ] Add deterministic path/provenance and bounded traversal tests.
- [ ] Move API DTOs to schemas/intelligence.py and adapt old/new consumers.
- [ ] Verify selected-root 404/403 handling and client response races via request identity.
- [ ] Measure large shared-subnet fixture edge/query counts; no quadratic peer graph.
- [ ] Retain existing tests in apps/backend/tests/intelligence/test_dependency_graph.py and frontend blast-radius tests; add API/authorization cases.
- [ ] Coordinate only selected-entity/detail integration with the finished map refactor.

No SPOF score, risk ranking engine, or connectivity-to-dependency conversion without evidence.
