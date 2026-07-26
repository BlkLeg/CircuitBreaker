# Proxmox as Priority Signal for Monitor Uptime

Date: 2026-07-26

## Problem

A user reported a monitor for a Proxmox node showing "down" (11 consecutive
failed ICMP retries, "100% packet loss" logged) while the physical machine
was fully up. Root cause for that specific incident turned out to be
environmental (the monitoring instance had no network path to the target at
all) — not a code defect. But it surfaced a real, independent gap: Proxmox's
own API already reports authoritative reachability/uptime for nodes and
VMs/containers, and CircuitBreaker already polls it (`proxmox_telemetry.py`),
but that signal is only ever used for dashboard telemetry (CPU/mem/uptime
display) — it never influences the native monitoring engine's up/down
decision or the availability percentages built from it. A transient ICMP
block, firewall change, or network blip against a Proxmox-linked target can
therefore report false "down" and drag down uptime stats, even though
Proxmox itself can already see the entity is running.

This spec adds Proxmox as a priority signal: for monitors on Proxmox-linked
targets, a fresh, disagreeing Proxmox status overrides the raw ICMP/TCP
check result — including the underlying availability sample that feeds the
uptime percentages, not just the live status badge.

## Scope

Applies to both target types with existing Proxmox linkage:
- `Hardware` (`proxmox_node_name` set) — Proxmox nodes.
- `ComputeUnit` (`proxmox_vmid` set) — VMs and containers.

Out of scope: retroactively correcting historical samples/events from before
this change ships; any change to the Proxmox integration's own polling,
credentials, or API client; any change to the ICMP/TCP collectors themselves
(they remain pure network checks, unaware of Proxmox).

## Design

### Where the override happens

`monitor_poll_worker.poll_one()` runs collectors in worker threads with no
DB access by design (pure, non-blocking). The override instead runs once per
batch in `process_batch()`, right after `asyncio.gather(...)` produces
`outcomes` and before `write_samples()`/`apply_result()` — so both the
stored telemetry sample and the state-machine transition see the corrected
result.

New module: `app/services/monitoring/proxmox_override.py`

```python
def apply_proxmox_overrides(
    db: Session,
    items: list[dict],
    outcomes: list[tuple[SampleRow, bool, str]],
) -> list[tuple[SampleRow, bool, str]]:
    ...
```

### Mechanics

1. Batch-fetch every `Hardware`/`ComputeUnit` referenced by this batch's
   `target_type`/`target_id` (one query per entity type, no N+1).
2. For each, determine whether Proxmox has a fresh opinion:
   - `Hardware`: `proxmox_node_name` is set AND `telemetry_last_polled` is
     within the freshness window. A successful poll *is* the reachability
     signal — `proxmox_telemetry.py`'s node-poll loop only updates
     `telemetry_last_polled` when the Proxmox API call for that node
     actually succeeds; a failed/unreachable node is skipped and its
     timestamp goes stale. So "fresh timestamp" already means "Proxmox
     confirms this node is up" — no separate boolean needed.
   - `ComputeUnit`: `proxmox_vmid` is set AND `telemetry_last_polled` (new
     column, see below) is within the freshness window. The running signal
     is `status == "active"` (already set by the existing VM-poll path).
3. Freshness window: a flat 5 minutes for both entity types — comfortably
   above the default poll intervals (30s for nodes, 120s for VMs), short
   enough that a broken/disabled Proxmox integration stops influencing
   monitors within minutes. A constant, not user-configurable.
4. When Proxmox has a fresh opinion **and it disagrees with the raw check's
   `up`**, rebuild that outcome:
   - Replace the `avail` Sample's value to match Proxmox's determination
     (`1.0`/`0.0`). Leave every other sample (latency, packet_loss_pct,
     jitter, etc.) untouched — those remain genuine network-level
     diagnostics.
   - Set `up` to Proxmox's determination.
   - Append a note to `msg`, e.g. `"... (overridden: Proxmox reports node
     running)"`, so the discrepancy stays visible in the events log instead
     of silently disappearing.
   - `Sample`, `CheckResult`, and the `SampleRow` tuple are frozen/immutable
     — this constructs new instances rather than mutating.
5. When they agree, or Proxmox has no fresh opinion, the outcome passes
   through completely unchanged (no rewriting, same object).
6. The override applies **symmetrically** — Proxmox can correct a false
   "down" (ICMP blocked, Proxmox says running) or a false "up" (stray ICMP
   reply after Proxmox reports the VM stopped) the same way. This follows
   directly from "Proxmox wins outright" and avoids an arbitrary asymmetric
   special case.

### Downstream effect

Because the override rewrites the outcome *before* `write_samples()` and
`apply_result()` run, everything downstream sees the corrected data with no
further changes needed:
- The stored `avail` telemetry sample reflects Proxmox's view, so the
  existing 24h/7d/30d percentage math (`_uptime_pct_map`, unchanged) and the
  daily rollup (`rollup_worker.py`, unchanged) both compute correctly off
  it.
- `state.apply_result()` receives the corrected `up` boolean and applies its
  existing retry/transition/notification logic unchanged — a Proxmox-based
  "up" override naturally resets `consecutive_failures` and can fire a
  "recovered" notification exactly as a real successful check would.

### Schema change

Add `telemetry_last_polled: Mapped[datetime | None]` to `ComputeUnit`,
mirroring the existing column on `Hardware` exactly. Set it in
`proxmox_telemetry.py`'s VM-poll path alongside the existing `cu.status`
assignment. One migration, following this repo's fresh-install
exclusion-list convention (verify with a fresh-volume boot or the
alembic upgrade/downgrade substitute used when Docker Compose isn't
available).

## Error handling

- **No Proxmox link, or link present but stale** (no successful poll within
  5 minutes — includes a disabled/misconfigured integration, bad
  credentials, or the integration never having run): outcome passes through
  unchanged, identical to today's pure ICMP/TCP behavior.
- **Target row missing/deleted**: treated the same as "no link" — skip,
  pass through.
- **A bug inside `apply_proxmox_overrides` itself**: caught per-item,
  falling back to the raw, un-overridden outcome for that item rather than
  propagating — mirrors `poll_one()`'s existing "never raises" philosophy.
  A defect in this new code degrades to today's behavior, not a batch
  failure.

## Testing

- **Unit tests for `apply_proxmox_overrides()`** (real Postgres, no mocks,
  this repo's convention): fresh `Hardware`/`proxmox_node_name` paired with
  a down ICMP outcome → up, `avail=1.0`, annotated `msg`, other samples
  untouched. Stale `telemetry_last_polled` → no change. No
  `proxmox_node_name` → no change. `ComputeUnit` with fresh polling and
  `status == "inactive"` paired with an up TCP outcome → flips down
  (symmetric direction). An agreement case → outcome unchanged, not just
  equal, confirming no needless rewriting.
- **Wiring test in `monitor_poll_worker.process_batch`**: a down ICMP result
  for a fresh Proxmox-linked monitor lands in `telemetry_timeseries` as
  `avail=1.0` and drives the state machine to up/recovered, using the
  existing real-session pattern in `test_monitor_poll_worker.py`.
- **`proxmox_telemetry.py`**: confirm `cu.telemetry_last_polled` is set
  alongside `cu.status` in the VM-poll path.
- **Migration**: verified via fresh-volume boot (or the alembic
  upgrade/downgrade substitute).

## Out of scope

- Retroactively correcting historical telemetry/events from before this
  ships.
- Any change to `proxmox_client.py`, the Proxmox polling schedule, or
  credential handling.
- Any change to the ICMP/TCP collectors (`collectors/net.py`) — they remain
  pure, Proxmox-unaware network checks.
- A user-facing "conflict" UI state — Proxmox silently wins per the
  design's resolution rule; the only visible trace of a disagreement is the
  annotated `msg` in the events log.
