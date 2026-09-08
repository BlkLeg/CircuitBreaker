# 03 · Docker discovery and source reconciliation

Status: approved. Depends on plan 00 and shared selectors/errors in 07.

## Outcome and location

A source-oriented Docker surface under Discovery shows host association, current attempt, last successful observation, containers, and reconciliation outcomes. Existing Settings → Integrations remains a configuration entry point into the same workflow—not an independent copy.

Existing integration points: frontend `pages/DiscoveryPage.jsx`, `pages/settings/IntegrationsSection.jsx`, `pages/SettingsPage.jsx`, existing discovery components/hooks/client; backend `services/discovery_safe.py` (`docker_discover`) and `services/docker_discovery.py` (`sync_docker_topology`).

Proposed UI boundary: `components/discovery/DockerSourcesPanel.jsx` and focused source/container/parent-resolution children. Reuse existing discovery status and job infrastructure where it fits.

## Outcome and reconciliation contract

| Enumeration result | UI meaning | Reconciliation authority |
| --- | --- | --- |
| Successful, populated | Containers were observed | Reconcile only this source's complete result |
| Successful, empty | Daemon was reachable; no containers found | Mark this source's disappeared observations stopped/stale according to policy |
| Partial | Some observations may be usable; coverage incomplete | No disappearance inference from missing objects |
| Failed | Enumeration did not complete | Preserve prior inventory and last-success timestamp |
| Never run / running | No completed result / active attempt | No absence inference |

A structured result carries stable source identity, outcome, completeness, attempt and success timestamps, observed container identities, parent-resolution state, and sanitized failure classification. Empty and failed must never both be represented as an unqualified empty list.

Containers retain source/provenance identity. Preserve explicit user parent assignments; auto-resolution may fill only unresolved/automatic associations unless the user deliberately changes that policy. Recreated containers need a documented stable identity/replacement rule, not display-name-only deduplication.

## Work packages

- [ ] **D1:** Inventory existing single/multiple daemon and agent discovery capabilities. Scope the source UI to supported sources; do not enable arbitrary remote Docker endpoints merely because the design shows a source selector.
- [ ] **D2:** Define result and parent-association schemas; write tests for complete, empty, partial, failed, recreated, and cross-source cases.
- [ ] **D3:** Build source summary, last-success/current-attempt indicators, container list, and host picker with unresolved-parent correction. Explain when a manual assignment is retained.
- [ ] **D4:** Return structured enumeration outcomes; keep timeouts, socket lifecycle cleanup, egress/daemon access protections, and secret handling intact.
- [ ] **D5:** Fix reconciliation to be source-scoped and completeness-aware, including disappearance of the final container. Prevent an older/concurrent scan from overwriting a newer authoritative result.
- [ ] **D6:** Resolve explicit hardware/compute parentage and provenance; preview consequential association/reconciliation changes when user input is required.
- [ ] **D7:** Connect real run progress/results through existing job/event mechanisms. Disable duplicate sync for an active source; expose retry without discarding prior successful data.
- [ ] **D8:** Document source identity, manual-override policy, and stale/stopped container semantics.

## Acceptance and tests

- Daemon failure shows failure and preserves prior observations; last attempt and last success are distinct.
- A successful empty enumeration reconciles disappeared containers even when none remain.
- Partial enumeration never stops unseen containers as if they were confirmed absent.
- Reconciliation cannot affect another source. Concurrent/out-of-order runs have deterministic protection.
- Parent selection finds eligible hosts beyond a loaded inventory page; manual assignments survive rediscovery.
- Container recreation does not generate unexplained duplicates or attach to a similarly named host.
- Authorization, invalid source settings, unreachable daemon, deleted parent, retry, empty, and running states are covered.
- Existing discovery/map behavior, theme switching, keyboard correction, and responsive tables pass regression tests.

Do not add new appliance providers, Docker lifecycle management, or container start/stop controls to this slice.
