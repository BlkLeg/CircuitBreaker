# 06 · Explainable dependency impact

Status: approved. Depends on plan 00; integrate after the separate map refactor exposes its stable selection/detail boundary.

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

- [ ] **I1:** Rebase integration assumptions on the completed map split; identify the selected-entity and detail-panel interfaces. Do not reopen unrelated layout/node-command refactoring.
- [ ] **I2:** Define typed directed edges and response/evidence schema. Add graph fixtures for host/guest/service, service/storage, shared network, cycles, duplicate paths, and missing entities.
- [ ] **I3:** Correct dependency construction and traversal in the existing service; include storage consumers and remove subnet clique construction.
- [ ] **I4:** Bulk-resolve entity metadata and bound traversal with honest completeness indicators. Measure query/edge growth.
- [ ] **I5:** Build the approved affected list, focused graph, path inspection, and confirmed/inferred controls using theme-aware graph styling.
- [ ] **I6:** Wire selection and cancellation. Rapidly changing selected assets must not show an earlier asset's result under the new heading.
- [ ] **I7:** Verify graph authorization: do not reveal names or paths through entities the user cannot access. Report incomplete evidence safely where filtering changes completeness.

## Acceptance and tests

- Two independent devices on one subnet are not reported as operational dependents.
- Host and storage scenarios include their explicit consumers with understandable directional paths.
- Cycles and duplicate relationships do not cause infinite traversal or inflated counts.
- Every listed effect has evidence; inferred paths are distinguishable, and incomplete results disclose limitations.
- Selecting an affected entity preserves normal map navigation/state behavior and supports keyboard/list access without requiring graph gestures.
- Theme changes update graph and panel colors without resetting map position/selection.
- Existing blast-radius tests plus directed-graph, authorization, race, and large-fixture query-count tests pass.

SPOF scoring, risk ranking based on unsupported assumptions, a new graph engine, and unrelated map UI changes remain excluded.
