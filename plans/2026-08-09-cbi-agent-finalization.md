# cbi-agent — Finalization: what stands between here and "coded, pending user testing"

**Date:** 2026-08-09

**Status at time of writing:** all four slices in `specs/2026-07-26-cb-agent-design.md` §8 are
implemented and their per-slice gates are green. This document is the delta between that and the
project's own definition of done. It is written to be actionable from a cold context: every item
carries the file, the evidence, and the command that proves it.

**Derived from:**
- `specs/2026-07-26-cb-agent-design.md` — §7 (UI), §8 (the four slices, and there are only four)
- `plans/2026-08-04-cbi-agent-e2e-cohesion-review.md` — **authoritative for the bar.** §"Full-System
  E2E Release Gate" (the 17-step journey) and §"Completeness Assessment"
- `plans/2026-08-06-cbi-agent-slice12-followups.md` — F-1 … F-8
- `plans/2026-08-04-cbi-agent-slice3-remote-probe-tasks.md` — §"Deferred / follow-ups"
- `plans/2026-08-08-cbi-agent-slice4-local-discovery-tasks.md` — §"Definition of done", §"Follow-ups"

**The bar, quoted, because it is the reason this document exists**
(`plans/2026-08-04-cbi-agent-e2e-cohesion-review.md`, §Completeness Assessment):

> The cbi-agent is E2E complete only when the full-system release gate passes. Completing four sets
> of unit tests or four isolated demonstrations is insufficient.

Four isolated demonstrations is exactly what exists today.

---

## Verified-green baseline (2026-08-09, branch `slice-4-local-discovery`)

Re-establish this before starting; do not inherit it on faith, and do not "fix" anything here inside
a finalization commit.

| Command | Result |
|---|---|
| `cd apps/agent && go vet ./... && go test -race ./...` | green, 17 packages |
| `cd apps/agent && GOOS=darwin go build ./...` | green (the `//go:build !linux` stubs compile) |
| `cd apps/backend && ruff check src/app` | green |
| `cd apps/backend && PYTHONPATH=src mypy src/app` | green, 279 files |
| `cd apps/frontend && npm run lint` | 0 errors (22 pre-existing warnings) |
| `cd apps/frontend && npm test` | 70 files, 374 tests |
| `cd apps/backend && PYTHONPATH=src pytest --maxfail=60 -q --no-cov` | **2146 passed, 17 skipped, 0 failed** |
| `cd apps/agent/e2e && pytest -q --no-cov -p no:randomly` | 11 passed, 1 xfailed, **1 failed (F-8)** |

`--no-cov` is mandatory on any targeted backend run; `pyproject.toml`'s `--cov-fail-under=60` makes a
subset run exit 1 regardless of results. Judge coverage only on a full run.

**Do not run two e2e sessions at once.** The compose project name is shared (`cb-agent-e2e`) and now
carries six networks, two agent volumes and seven services. A concurrent session running
`docker compose down -v` will destroy the other's stack mid-test and the failure will surface
somewhere unrelated, minutes later. This actually happened on 2026-08-09 and cost real time.

---

## Work items, in dependency order

### 1. Diagnose and fix F-8 — the self-update/rollback e2e

**Why first:** it *is* step 17 of the release gate in item 4, so that work cannot be completed around
it. It is also the only lifecycle path with no working automated proof.

`apps/agent/e2e/test_agent_e2e.py::test_agent_update_success_and_forced_rollback` has been red since
before slice 3, on both `dev` and this branch, **with different failure modes on each** and neither
diagnosed:

| | dies at | how |
|---|---|---|
| `dev` | ~88 s, before `cb-agent` starts | `AssertionError` |
| this branch | ~212 s, inside `_cut_agent_network` | `network sandbox for container … not found` |

The recorded read (`plans/2026-08-06-cbi-agent-slice12-followups.md` F-8) is that the branch-side
failure is a harness race — `docker network disconnect` issued before the re-exec'd container's
network sandbox exists — and the fix direction is to **wait for the sandbox to exist before
detaching, not to change mechanism** (the test genuinely needs the detach; it only needs "the
re-exec'd agent cannot complete a `hello.ack`"). `test_agent_black_hole_partition_is_detected_and_spools`
uses the same helper against a long-running container and does not hit the race, which supports that
reading.

But it is a *reading*, not a diagnosis. `TestWatchForRollback_NoConfirmationTriggersRollback` passing
under `-race` is a narrower claim than "`internal/update` is sound." **Diagnose both failure modes
before deciding this is harness-only.** If it turns out to be a product bug, it is a Slice 1 defect
that has been invisible for four slices.

Green: `cd apps/agent/e2e && pytest -q --no-cov -p no:randomly -k update_success` — and then a full
e2e run, because the fix touches a shared helper.

---

### 2. Build the "Create monitor from this agent" action

**This is the only unimplemented v1 feature.** It fell through the seam between two plans and is in
neither's task list.

`plans/2026-08-04-cbi-agent-slice3-remote-probe-tasks.md` §Deferred:

> §7's "Create monitor from this agent" action for Slice 4 discoveries. The design places it in Slice
> 3's UI section, but it depends on Slice 4's device findings, which do not exist. **Deferred to Slice 4.**

Slice 4 then never picked it up — `grep -in "create monitor\|monitor from"` across both
`plans/2026-08-04-cbi-agent-slice4-local-discovery.md` and
`plans/2026-08-08-cbi-agent-slice4-local-discovery-tasks.md` returns nothing.

Everything it needs already exists, so this is wiring rather than new machinery:
- `apps/frontend/src/components/monitors/RunFromSelect.jsx` — the agent-vantage picker
- `MonitorForm.jsx` already round-trips `probe_agent_id` (see `__tests__/monitor-run-from.test.jsx`)
- monitor-any-inventory-entity already exists (commit `724e7382`)

The action is the shortcut from a discovered/imported device to a monitor **with the discovering
agent preselected as the vantage** — which is the part that makes it more than a link. Read design
§7 for the intended placement before choosing where it hangs (agent detail vs. the review queue vs.
the Hardware row); do not guess.

Test-first, per the repo's convention: an RTL test in `apps/frontend/src/__tests__/`, cloned from
`monitor-run-from.test.jsx`.

Green: `cd apps/frontend && npm test` and `npm run lint`.

---

### 3. Fix F-1 — `cpu_pct` double-scaling

The only open product bug. Verified still present 2026-08-09:

`apps/frontend/src/components/Map/Sidebar.jsx:241`
```js
const cpuPct = data.cpu_pct != null ? Math.round(data.cpu_pct * 100) : null;
```

That assumes the Proxmox 0–1 convention. `app/services/telemetry_normalize.py` deliberately keeps
`cpu_pct` on the 0–100 convention every other consumer reads. The two collide only on a Hardware row
that is **both** agent-linked and Proxmox-managed (the branch is gated on
`integration_config_id != null`), where an agent reporting `12.5` renders as `1250%`.

**Fix direction is prescribed and worth honoring:** normalize at the Proxmox ingest boundary so
`cpu_pct` is 0–100 everywhere, then delete the `* 100`. Do **not** special-case the source in the
component — that reintroduces the two-conventions problem the single normalizer exists to remove.

Green: `npm test`, plus whatever backend telemetry tests the ingest change touches.

---

### 4. Write the full-system release gate

**The bulk of the remaining work, and the item the project's own documents call non-negotiable.**

The spec is `plans/2026-08-04-cbi-agent-e2e-cohesion-review.md` §"Full-System E2E Release Gate" —
17 steps, one continuous journey, one stack, plus a §"Required assertions" list. Read it in full
before writing anything.

What exists instead: 12 independent tests in `apps/agent/e2e/test_agent_e2e.py`, each of which
stands its own stack up and tears it down. Every individual capability is covered. What is **not**
covered is that the states compose.

The concrete hole, and the one to design the new test around — **step 8**:

> Create ICMP, TCP, HTTP(S), and DNS monitors from the discovered device with the agent vantage.

Slice 3's `test_remote_probe_assignment_execution_and_unavailability` does create all four check
types with `probe_agent_id` (`test_agent_e2e.py:2456-2504`), but against a **hardcoded fixture IP**.
No test creates a monitor against a Hardware row that agent discovery found and import created.
That join — discovery → review → import → Hardware → agent-vantage monitor → monitor pipeline — is
the thing four isolated demonstrations structurally cannot prove.

Also uncomposed today: step 16's "disable discovery during a scan, **then** revoke the agent" as one
continuous act across all capability handlers, and step 14's "restart agent and backend
independently; verify presence, profiles, schedules, and grants reconcile without duplication" with
all four slices' state live at once.

Harness assets already available (built by Slice 4 Task 31 — reuse, don't rebuild):
`_up_fixture_target(service)`, `_attach_agent_to_late_net()`, `_agent_route_networks(service=)`,
`_agent_attachments(service=)`, `_network_subnet(suffix)`, `_container_ipv4(container, network)`,
and `service=` on `_enroll_agent` / `_agent_status` / `_agent_logs` / `_cut_agent_network` /
`_agent_network_name`. Six pinned subnets, two agents, four fixture targets.

Two mechanisms the gate must respect or it will produce false results:
- `hostinfo.Collect()` runs once per link connection (`internal/link/link.go`), so a subnet attached
  mid-test reaches the server only on the agent's **next** hello. Trigger with
  `docker compose restart cb-agent`, and **never** `up --force-recreate` — the runtime network
  attachment lives on the container and a recreate silently undoes the thing under test.
- Any "the backend cannot reach this" assertion needs a **positive control** first. Without one,
  `assert returncode != 0` is satisfied just as well by a missing binary or a dropped capability as
  by an absent route. The existing pattern is at `test_agent_e2e.py`'s
  `test_e2e_harness_topology_is_pinned_and_two_agents_stay_isolated` — backend pings cb-agent's own
  agent-net address, and `nc` hits its own 8443, before the six negative probes run.

Expect this to be slow (the current 12-test suite is ~35 min) and to want its own long-timeout
invocation.

---

### 5. Close F-6 — the Slice 2 catch-up assertions

Not a blocker for handoff, but it means a property you will rely on during testing is not actually
pinned. Three assertions in `test_agent_host_telemetry_first_sample_catchup_and_disable` are weaker
than the plan specifies; full detail in `plans/2026-08-06-cbi-agent-slice12-followups.md` F-6. The
one that matters most:

> **The catch-up budget is measured from the wrong instant.** The test allows 240 s to first observe
> `spool_depth > 0` and only then starts the 30 s catch-up clock, so it can no longer distinguish
> "catch-up was bounded" from "reconnect backoff was long" — which is the property D-5 exists to pin.

The other two: per-sample `sample_id` uniqueness is inferred from bucket aggregates rather than
asserted (needs a different endpoint or a direct DB read), and `outage_start` is stamped before
`docker compose stop` returns, which can let the `min_outage_samples = 3` floor be met entirely by
pre-outage buckets — degrading the "`collected_at` preserved rather than rewritten" proof to a
tautology.

---

### 6. Close F-3 and F-4 — two small coverage gaps

- **F-3:** `apps/agent/internal/collect/host/docker.go:57-59` returns early on a non-200 stats
  response, but both cases in `TestDocker_StatsFailure...` use non-JSON bodies, so the decode guard
  one line later absorbs the mutation — deleting the status check leaves the suite green. Add a case
  with **500 + well-formed JSON**.
- **F-4:** `apps/agent/internal/collect/collect.go:62` (`if err == nil`) is the only uncovered
  statement in `run`. `fakeCollector.err` is already wired into `Collect` but no test sets it; the
  frame-channel half of that branch is untested by anyone.

Green: `cd apps/agent && go test -race ./internal/collect/...`.

---

### 7. F-9 — get these tests into CI

Won't block user testing; will decide whether anything found during it stays fixed. `.github/workflows/`
runs **no** backend pytest and **no** docker e2e job — everything above is locally enforced only.

Blocked behind a real decision, which is why it is last: adding a pytest job requires resolving the
52%-actual vs 60%-required coverage gate in `pyproject.toml:200-208`. Slice 4 explicitly declined to
fix that and it should not be smuggled in here either. Decide the gate first, then add the job.

---

## Explicitly not gaps

Deliberately out of v1 scope. None of these count against "all coded" and none should be started
without a new product decision:

- **SNMP and mDNS/SSDP discovery** — `plans/2026-08-04-cbi-agent-slice4-local-discovery.md` §11
  defers these to a second milestone, after the connect-scan path is complete.
- **A managed rendezvous/relay** for a Circuit Breaker installation that is itself behind NAT with
  no public/VPN path. §11 correctly calls this a separate architectural slice. The agent's remote
  subnet needs only outbound access in either model.
- **macOS and Windows agents** — spec §9, out of scope for v1; the Go choice and the `Collector`
  interface are what keep the door open.
- **Maintenance windows** — no implementation exists; Slice 3 §6's "preserve maintenance behavior"
  is a no-op (Slice 3 Deviation 2).
- **Monitor read-route authentication** — `api/monitor.py`'s GET routes have no auth dependency.
  Predates Slice 3; tightening it breaks the frontend and existing tests (Slice 3 D-15).
- **Repo-wide `ruff check .` and `ruff format --check src/app`** — both red at baseline on unrelated
  files. A separate cleanup commit, never inside a finalization task. **Do not run `make format`.**
- **Bumping CI to Go 1.23+** — would remove Slice 3 D-11's dependency pins, but is unrelated.
- **Query-plan verification at fleet scale** — needs a seeded performance fixture; belongs with
  broader scheduler performance work.

## Resolved — do not re-open

`F-2` (`tests/unit/test_startup_schema_guard.py`) is **green**; re-verified 2026-08-09, exit 0. The
followups file still describes it as red — that entry is stale. `F-5` (black-hole partition
detection) and `F-7` (fresh installs could not persist a host sample) are marked RESOLVED in the
followups file and are consistent with the current suite.

`TestStartDaemonState_CachedGrantFaultIsReportedAtStartup` in `cmd/cb-agent` is flaky roughly 1 in 3
on a `t.TempDir` cleanup error, not an assertion. Re-run before blaming a change.

---

## The thing no item above can deliver

Every e2e run in this repo is Docker containers on a single host. The slice's central claim — one
install command on a machine in another home, VLAN, or site; outbound WSS only; no inbound rule, no
CIDR typed, no scanner installed, no certificate copied — has been proven against *simulated*
network isolation and never against a real remote network with real NAT, a real firewall, and real
latency. Items 1–7 make the automated gate honest. They do not substitute for pointing this at a
real remote subnet, which is what the user testing is for and should be its first target.
