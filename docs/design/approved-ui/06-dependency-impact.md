# 06 · Explainable dependency impact

Status: **implemented.** The Impact panel explains itself with typed, provenance-tagged
paths, a bounded focused graph, opt-in inferred relationships and explicit traversal limits;
see the 0.4.2 entries in [CHANGELOG.md](../../../CHANGELOG.md).
Depends on plan 00.

## Outcome and location

The existing impact panel for a selected map asset shows affected entities and the relationship paths explaining them. A focused graph supports that explanation; it is not a replacement map or a prediction that every connected asset will fail.

Existing integration points: frontend `components/details/BlastRadiusPanel.jsx`, final map/detail composition, `config/mapTheme.js`; backend `services/intelligence/dependency_graph.py` (`_build_adjacency`, `_resolve`, `calculate_blast_radius`).

Proposed boundaries: typed dependency-edge building and bulk resolution within the existing intelligence service; small impact-path/evidence components alongside the current panel.

## Graph and response contract

- Distinguish **hosting**, **explicit operational dependency**, **inferred dependency**, and **connectivity**. Document edge direction once; for example, dependent → dependency, with reverse traversal for impact.
- Host failure includes explicitly hosted guests/workloads; storage failure includes explicit consumers.
- Shared subnet membership is connectivity, not mutual operational dependency. Do not expand a network into all device pairs.
- Return unique affected identities plus traceable paths containing edge type, direction, confidence/provenance, and any limitations. A confidence label must reflect actual evidence, not a fabricated numeric score.
- Confirmed impact is the default. An inferred-relationship toggle changes evidence scope and counts transparently; show ordinary connectivity separately.
- Use bulk entity/name/status resolution. Cycles terminate, duplicate paths are controlled, and bounded/truncated traversal is explicitly labelled rather than presented as exhaustive.
- Describe this as potential dependency impact, not observed outage. Empty results with incomplete graph evidence are not proof that an asset has no dependents.

## Work packages

- [x] **I1:** Rebase integration assumptions on the completed map split; identify the selected-entity and detail-panel interfaces. Do not reopen unrelated layout/node-command refactoring.
- [x] **I2:** Define typed directed edges and response/evidence schema. Add graph fixtures for host/guest/service, service/storage, shared network, cycles, duplicate paths, and missing entities.
- [x] **I3:** Correct dependency construction and traversal in the existing service; include storage consumers and remove subnet clique construction.
- [x] **I4:** Bulk-resolve entity metadata and bound traversal with honest completeness indicators. Measure query/edge growth.
- [x] **I5:** Build the approved affected list, focused graph, path inspection, and confirmed/inferred controls using theme-aware graph styling.
- [x] **I6:** Wire selection and cancellation. Rapidly changing selected assets must not show an earlier asset's result under the new heading.
- [x] **I7:** Verify graph authorization: do not reveal names or paths through entities the user cannot access. Report incomplete evidence safely where filtering changes completeness.

> Status 2026-09-15: I2/I3/I4 landed with the backend in `4729e8bd`
> (`services/intelligence/dependency_edges.py` typed edges with provenance —
> storage consumers via `ServiceStorage`, no subnet clique, memberships as
> connectivity only; `dependency_graph.py` bounded traversal with
> `completeness`/`truncation_reason`/`limits`; fixtures in
> `apps/backend/tests/intelligence/test_dependency_graph.py` incl. cycle,
> shared-network, storage-consumer, truncation and a
> `test_query_count_is_bounded_not_per_asset` measurement: 128-asset and
> 2-asset trees cost the same statement count). I1 required no map change —
> the panel stays where the detail composition mounts it.
> I5/I6 are the frontend correction this session
> (`components/details/BlastRadiusPanel.jsx` + `lib/impactPaths.js` +
> `styles/impact.css`): per-entry "Why" paths in dependency direction, an
> opt-in confirmed/inferred toggle that appears only when
> `inferred_available`, connectivity listed separately and never counted,
> truncation disclosed, and a bounded token-themed focused graph (≤ 40 nodes,
> skipped with a note beyond that). The result is stored with the exact
> `asset:scope` key it answers and rendered only while that key matches, so a
> changed selection can never show an earlier asset's answer; tests pin the
> mid-flight supersession case. I7: the intel router is readable by any
> signed-in user by existing documented policy (`api/intel.js`), the panel has
> no write affordances, and the docs state the authorization boundary.
> Tests: `__tests__/blast-radius-panel.test.jsx` (16 cases),
> `__tests__/impact-paths-lib.test.js` (the pure projections:
> truncation wording, honest empty, path chaining, graph bounds), plus
> `__tests__/intel-api.test.js` for the scope parameter.
>
> Status 2026-09-17 (correction): two robustness gaps, no contract change.
> `graphLayout` dereferenced `root_asset` unguarded, so a result with impact but
> no root would take the panel down rather than falling back to the list; it now
> returns no layout. Connectivity rows keyed on `edge.identity` with no fallback.
>
> Still open: the browser/theme/keyboard pass from *Acceptance and tests* below
> has not been run in a real browser — including the graph's arrowheads and
> dashed inferred strokes across light/dark themes.

## Acceptance and tests

- Two independent devices on one subnet are not reported as operational dependents.
- Host and storage scenarios include their explicit consumers with understandable directional paths.
- Cycles and duplicate relationships do not cause infinite traversal or inflated counts.
- Every listed effect has evidence; inferred paths are distinguishable, and incomplete results disclose limitations.
- Selecting an affected entity preserves normal map navigation/state behavior and supports keyboard/list access without requiring graph gestures.
- Theme changes update graph and panel colors without resetting map position/selection.
- Existing blast-radius tests plus directed-graph, authorization, race, and large-fixture query-count tests pass.

SPOF scoring, risk ranking based on unsupported assumptions, a new graph engine, and unrelated map UI changes remain excluded.
