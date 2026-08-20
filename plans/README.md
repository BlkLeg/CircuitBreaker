# Plans — Index

Implementation plans, newest first. **A plan is a record of intent at its date;
it is not evidence that the work shipped.** The requirement ledger
([`specs/1.0.0/release-control/requirement-ledger.csv`](../specs/1.0.0/release-control/requirement-ledger.csv))
is. GOV-13 is the requirement this index closes.

Several documents here describe finished work in the present tense. That is
normal for a plan and is not a defect in the plan — it is the reason this index
carries a status column.

## Status vocabulary

- **Complete** — the work landed. Each row names the evidence: the commits, or
  the artifact you can open right now.
- **Active** — being executed, or its follow-ups are still open.
- **Superseded** — a later plan replaced it.
- **Reference** — never a work item; a review, an index, or a deferred-item list.

## v1.0.0 remediation (2026-08-18)

Five plans derived from [`specs/1.0.0/gap-audit-2026-08-18.md`](../specs/1.0.0/gap-audit-2026-08-18.md),
catalogued in the index below.

| Plan | Date | Status |
|---|---|---|
| [v1 remediation index](./2026-08-18-v1-remediation-index.md) | 2026-08-18 | **Reference** — the map of the five plans and what each closes. |
| [Release pipeline](./2026-08-18-v1-release-pipeline.md) | 2026-08-18 | **Complete** — all six tasks landed in `76ea8584`, `b6d0e8b1`, `639afcf8`, `db93586a`, `ea8d3626`, `b76bc316` (channel/prerelease decision, GOV-09 version parity, multi-arch build, installed-artifact smoke test, prerelease marking, pinned build tools + ledger validator in CI). |
| [Live defects](./2026-08-18-v1-live-defects.md) | 2026-08-18 | **Complete** — all five tasks landed in `101558f4` (AGT-12), `49ebec77` (SEC-05), `a9561af7` (AGT-11), `5a154766` (AGT-10), `1007767b` (AGT-04). |
| [Browser test harness](./2026-08-18-v1-browser-harness.md) | 2026-08-18 | **Complete** — Playwright harness `5c46fb0f` (REL-17), a11y gate `09d41ed3`/`d6695c1b` (ACC-10), visual baselines `d0a016ed`/`6f56c858` (REL-18), frontend coverage gate `c63ee889`/`61c5c2d5` (REL-15), backend ratchet `ec0d2d9f` (REL-14), CI wiring `3bc04e08`. `known_bugs` #1 was investigated in `d347fdd5` and `268a03c0`: it reproduces, and the plan's suspected cause was wrong — read both before reopening it. |
| [Server contract](./2026-08-18-v1-server-contract.md) | 2026-08-18 | **Active** — in execution. Closes SRV-03, SRV-05, SRV-06, RC-05, GOV-05. |
| [Governance hygiene](./2026-08-18-v1-governance-hygiene.md) | 2026-08-18 | **Active** — in execution. Closes GOV-01, GOV-08, GOV-10, GOV-11, GOV-12, GOV-16, NPM-01–15, GOV-06/07. This index is one of its deliverables. |

## cb-agent / cbi-agent (2026-07-27 … 2026-08-09)

The four-slice agent programme. All four slices are implemented: `apps/agent/`
is a Go module with `cmd/`, `internal/` and its own `e2e/` suite, and the
composed journey (`apps/agent/e2e/test_agent_e2e.py`) runs nightly from
[`e2e.yml`](../.github/workflows/e2e.yml).

| Plan | Date | Status |
|---|---|---|
| [cbi-agent finalization](./2026-08-09-cbi-agent-finalization.md) | 2026-08-09 | **Complete** — the 17-step release gate it demanded exists as `apps/agent/e2e/test_agent_release_gate.py` and the composed journey runs on the nightly schedule. Its verified-green baseline table is from 2026-08-09 and is stale; re-measure, do not quote it. |
| [Slice 4 — local discovery: tasks](./2026-08-08-cbi-agent-slice4-local-discovery-tasks.md) | 2026-08-08 | **Complete** — `feat(backend): run a discovery scan on an agent, end to end`, `feat(backend): discover an agent's own networks without being asked to`, `feat(frontend): show where a discovery scan ran…`, proven by `test(agent): prove zero-configuration local discovery end to end` (2026-08-08 … 2026-08-09). |
| [Slice 4 — local discovery](./2026-08-04-cbi-agent-slice4-local-discovery.md) | 2026-08-04 | **Complete** — design for the task breakdown above. |
| [Slice 1-2 cohesion hardening: tasks](./2026-08-06-cbi-agent-slice12-cohesion-hardening-tasks.md) | 2026-08-06 | **Complete** — merged as `Merge slice 1-2 cohesion hardening` (2026-08-07). |
| [Slice 1-2 deferred follow-ups](./2026-08-06-cbi-agent-slice12-followups.md) | 2026-08-06 | **Reference, mostly closed** — F-5 and F-7 are marked RESOLVED in the document itself; F-1 is fixed in the tree (`apps/frontend/src/components/Map/Sidebar.jsx:247` now renders `Math.round(data.cpu_pct)` with the convention documented above it); F-2's two tests pass on `dev` today. F-3, F-4, F-6 and F-8 were not re-verified for this index — check before assuming. |
| [cb-agent self-update fix (Bug 1): tasks](./2026-08-05-cb-agent-self-update-fix-tasks.md) | 2026-08-05 | **Complete** — symlink-indirection swap/rollback and the un-xfailed regression test landed 2026-08-05 … 2026-08-06, merged as `Merge branch 'fix/cb-agent-self-update'`. |
| [Slice 3 — remote probe: tasks](./2026-08-04-cbi-agent-slice3-remote-probe-tasks.md) | 2026-08-04 | **Complete** — `feat(backend): build the remote-probe dispatch and result pipeline`, merged as `Merge slice 3: remote probe` (2026-08-07). |
| [Slice 3 — remote probe](./2026-08-04-cbi-agent-slice3-remote-probe.md) | 2026-08-04 | **Complete** — design for the task breakdown above. |
| [Slice 2 — host telemetry: tasks](./2026-08-04-cbi-agent-slice2-host-telemetry-tasks.md) | 2026-08-04 | **Complete** — collectors, spool-depth reporting and `test(agent): Docker E2E for host telemetry, outage catch-up and disable` (2026-08-06 … 2026-08-07). |
| [Slice 2 — host telemetry](./2026-08-04-cbi-agent-slice2-host-telemetry.md) | 2026-08-04 | **Complete** — design for the task breakdown above. |
| [Slice 1 gap-closure: tasks](./2026-08-04-cbi-agent-slice1-gap-closure-tasks.md) | 2026-08-04 | **Complete** — closed by the Slice 1-2 cohesion hardening merge. |
| [Slice 1 gap-closure](./2026-08-04-cbi-agent-slice1-gap-closure.md) | 2026-08-04 | **Complete** — design for the task breakdown above. |
| [Slices 1–4 E2E cohesion review](./2026-08-04-cbi-agent-e2e-cohesion-review.md) | 2026-08-04 | **Reference** — not a work item. It is the document that defines the bar ("E2E complete only when the full-system release gate passes"); the finalization plan above cites it as authoritative. Still worth reading. |
| [cb-agent Slice 1 (foundation)](./2026-07-27-cb-agent-slice1.md) | 2026-07-27 | **Complete** — `apps/agent/` exists with enrollment, spool and update paths, and its own e2e suite. |

## Native monitoring (2026-07-25 … 2026-07-27)

| Plan | Date | Status |
|---|---|---|
| [Proxmox as priority uptime signal](./2026-07-26-proxmox-uptime-priority.md) | 2026-07-26 | **Complete** — `feat(monitors): add apply_proxmox_overrides…`, `feat(monitors): wire Proxmox priority override into process_batch`, `feat(monitors): stamp telemetry_last_polled on Proxmox VM poll`, plus the follow-up fix to override liveness, scope and audit trail. |
| [Monitors dashboard facelift](./2026-07-26-monitors-dashboard-facelift.md) | 2026-07-26 | **Complete** — `feat(monitors): dashboard primitives…`, `…dashboard components…`, `…card-wall dashboard with filters and expandable cards`, `…overview endpoint with compact latency and check series`. Shipped as `apps/frontend/src/pages/MonitorsPage.jsx`. |
| [Monitor detail uptime stats](./2026-07-26-monitor-detail-uptime-stats.md) | 2026-07-26 | **Complete** — `feat(monitors): compute 7d/30d/365d/total uptime in get_uptime`, `…return all uptime windows from GET /monitors/{id}/uptime`, `…show total/24h/7d/30d/365d uptime on the detail page`. Shipped as `apps/frontend/src/pages/MonitorDetailPage.jsx`. |
| [Native monitoring engine — Slice 1](./2026-07-25-native-monitoring-slice1.md) | 2026-07-25 | **Complete** — the engine exists, all under `apps/backend/src/`: `app/workers/monitor_scheduler.py`, `app/workers/monitor_poll_worker.py`, `app/workers/monitor_probe_dispatch.py`, `app/services/monitoring/`, `app/api/monitor.py`, `app/api/ws_monitors.py`. |

## Adding a plan

Add the row here in the same commit that adds the plan, and set its status to
**Active**. Update the status when the work lands, naming the evidence — a
commit hash or a path, not an adjective. An unindexed plan is the exact GOV-13
gap this file closes.
