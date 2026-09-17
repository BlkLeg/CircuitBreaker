# 03 · Docker discovery and source reconciliation

Status: **implemented.** The source-oriented Docker surface shipped with
`components/discovery/DockerSourcesPanel.jsx` and its per-source sync, outcome and
reconciliation handling; see the 0.4.2 entries in [CHANGELOG.md](../../../CHANGELOG.md).
Depends on plan 00 and shared selectors/errors in 07.

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

- [x] **D1:** Inventory existing single/multiple daemon and agent discovery capabilities. Scope the source UI to supported sources; do not enable arbitrary remote Docker endpoints merely because the design shows a source selector.
- [x] **D2:** Define result and parent-association schemas; write tests for complete, empty, partial, failed, recreated, and cross-source cases.
- [x] **D3:** Build source summary, last-success/current-attempt indicators, container list, and host picker with unresolved-parent correction. Explain when a manual assignment is retained.
- [x] **D4:** Return structured enumeration outcomes; keep timeouts, socket lifecycle cleanup, egress/daemon access protections, and secret handling intact.
- [x] **D5:** Fix reconciliation to be source-scoped and completeness-aware, including disappearance of the final container. Prevent an older/concurrent scan from overwriting a newer authoritative result.
- [x] **D6:** Resolve explicit hardware/compute parentage and provenance; preview consequential association/reconciliation changes when user input is required.
- [x] **D7:** Connect real run progress/results through existing job/event mechanisms. Disable duplicate sync for an active source; expose retry without discarding prior successful data.
- [x] **D8:** Document source identity, manual-override policy, and stale/stopped container semantics.

> Status 2026-09-15: D1/D2/D4/D5 landed with the backend in `4729e8bd`
> (`docker_enumeration.py`, `docker_sources.py`, `docker_reconcile.py`, migration
> `0112`). D3/D6/D7/D8 are this slice: `DockerSourcesPanel` + `DockerSourceCard`
> under Discovery → Docker, host correction through the shared `EntityPicker`
> (`action="docker_parent"`, which plan 07 built for this), and run results
> arriving over the existing `docker_sync_completed` discovery-stream event
> rather than a new poll loop.
>
> Status 2026-09-17 (correction): the surface above was only honest inside the
> session that triggered a sync. `GET /docker/sources` carried no run, so every
> page load rendered `run = null` and fell through to "Synced — the daemon was
> reachable and reported 0 container(s)", failing the first acceptance check on
> this page for any failed daemon. Fixed by giving a source its `last_run`
> (`DockerSourceOut.last_run`, `docker_sources.source_view`), which the parent
> route now answers with too, so assigning a host cannot blank it. Three further
> gaps closed with it: a queued run was never refreshed (a finished sync stayed
> "Sync queued" with Sync disabled until reload — run state is now the server's
> on every load, and the locally queued run is dropped as soon as it answers); a
> container list that failed to load was rendered as a source reporting no
> containers (now reported unreadable); and the per-source Sync button discarded
> the source id it was given (`POST /docker/sync` now takes an optional
> `source_id`, and an empty body still means the configured daemon). An
> attempted source with no run available is reported "Outcome unknown" rather
> than as success.
>
> Still open: the real-browser regression pass in *Acceptance and tests* below —
> theme switching, keyboard correction, and responsive tables have unit coverage
> but have not been exercised in a browser.

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
