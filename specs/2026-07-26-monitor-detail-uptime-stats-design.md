# Monitor Detail Page: Extended Uptime Stats

Date: 2026-07-26

## Problem

The monitor detail page (`/monitors/:id`) shows only a single 24-hour uptime
figure. The original native monitoring engine design
(`specs/2026-07-25-native-monitoring-engine-design.md`) called for
24h/7d/30d uptime "from rollups," but slice 1 shipped 24h-only, computed
directly from raw telemetry, and left the rollup worker untouched (see
`plans/2026-07-25-native-monitoring-slice1.md` self-review notes). The
dashboard facelift (`specs/2026-07-26-monitors-dashboard-facelift-design.md`)
explicitly left the detail page out of scope.

This spec closes that gap: the detail page should show Total Uptime, Last
Polled, and 24-hour / 7-day / 30-day / 365-day availability.

## Constraint: 90-day raw retention

`telemetry_timeseries` (the raw per-check store) has a 90-day TimescaleDB
retention policy (`migrations/versions/0041_telemetry_hypertable.py`). 24h/7d/30d
availability can be computed directly from raw `avail` samples via the
existing `_uptime_pct_map(db, item_ids, hours=...)` helper. 365-day and
all-time ("Total Uptime") figures cannot — they require a rollup that
outlives the 90-day window.

The codebase already has a daily rollup, `DailyUptimeStats`
(`daily_uptime_stats`), populated by `workers/rollup_worker.py`. Today it's
scoped to `target_type == "hardware"` monitors only, keyed by `hardware_id`.
It has exactly one other consumer (`api/admin.py:404`, a table-dump list) and
no other business logic depends on it, so it's safe to generalize rather than
build a parallel table.

## Data model changes

- Rename `DailyUptimeStats` → `MonitorDailyStats` (table `daily_uptime_stats`
  → `monitor_daily_stats`), reflecting that it's no longer hardware-specific.
- Replace `hardware_id` (FK → `hardware`) with `item_id` (FK →
  `monitor_items.id`, `ondelete="CASCADE"`). Unique constraint on
  `(item_id, date)`.
- `rollup_worker.py`: remove the `target_type == "hardware"` filter in
  `calculate_daily_rollups`; roll up every `MonitorItem` directly by
  `item_id` (no more hardware-id indirection — every check already has an
  `item_id`).
- New Alembic migration performs the rename/column swap. Per this project's
  fresh-install convention, `0001_init.py` bootstraps new databases from
  current `models.py` minus an exclusion list — that list must be updated
  for the renamed table/column so fresh installs don't collide with the new
  migration. Verify with a fresh-volume mono boot (throwaway secrets, scratch
  `CB_DATA_DIR`, `docker compose up -d --build`, confirm `healthy` with
  `restarts=0`).
- Rollup coverage is not retroactive: for monitors that existed before this
  ships, `monitor_daily_stats` rows only start accumulating from deploy day
  forward. A monitor's 365d/Total figures will simply reflect however much
  rollup history exists for it — displayed as a computed value based on
  available data, not a placeholder (see UI section).

## Backend API changes

Extend `GET /monitors/{id}/uptime` (no new endpoint) to return:

```json
{
  "pct_24h": 99.8,
  "pct_7d": 99.5,
  "pct_30d": 98.9,
  "pct_365d": 99.1,
  "pct_total": 99.3,
  "last_polled_at": "2026-07-26T18:04:00Z"
}
```

- `pct_24h` / `pct_7d` / `pct_30d`: unchanged computation, via
  `_uptime_pct_map(db, [item_id], hours=24|168|720)` against raw
  `telemetry_timeseries`.
- `pct_365d`: sum `uptime_minutes` / sum `total_minutes` from
  `MonitorDailyStats` rows for that `item_id` where `date` falls in the last
  365 days. `None` if no rollup rows exist yet.
- `pct_total`: same aggregation, over all `MonitorDailyStats` rows for that
  `item_id` (no date bound). `None` if no rollup rows exist yet.
- `last_polled_at`: passthrough from `MonitorItem.last_polled_at`, included
  here so the frontend can get stats + timestamp in one call. The existing
  `getMonitor()` call keeps returning it too — additive, not a breaking
  change.
- `monitor_service.get_uptime()` becomes the single function computing all
  five percentages; `_uptime_pct_map` is unchanged and reused for the three
  short windows.

## Frontend changes

`MonitorDetailPage.jsx`'s existing stat `<dl>` block: replace the single
"Uptime (24h)" entry with six entries — Total Uptime, Last Polled, 24 Hour,
7-Day, 30-Day, 365-Day — alongside the existing Type/Target/Interval fields.
No new component; extend the existing markup pattern.

- Each renders `XX.X%` when present, `—` when `null` — matching the existing
  convention for missing 24h data.
- "Last Polled" reuses the existing "Last check" time formatting already on
  the page (rename/dedupe, not new logic).
- The page fetches uptime via `getMonitorUptime()` and the timestamp via the
  separate `getMonitor()` call; once the new `/uptime` response includes
  `last_polled_at`, prefer that value once both requests resolve, to avoid a
  stale-timestamp flash if one resolves first. Both calls are kept.
- No new API client function needed — `getMonitorUptime()` already exists
  and just returns a richer shape.

## Error handling

No new failure modes:
- Missing rollup data → `None` → `—`, same convention as current 24h nulls.
- Monitor deleted → `MonitorDailyStats` rows cascade-delete via FK, same as
  other item-scoped tables.
- Rollup worker failure → already logged via `log_worker_audit`, unaffected
  by the generalization.

## Testing

- Backend: unit tests for expanded `get_uptime()` — summing multiple
  `MonitorDailyStats` rows into `pct_365d`/`pct_total`, `None` when no rollup
  rows exist, correct rounding.
- `rollup_worker.py` test covering a non-hardware `target_type` (e.g. a
  `service` monitor) alongside the existing hardware case, confirming the
  filter removal doesn't break hardware rollups.
- Migration verified via fresh-volume mono boot.
- Frontend: render test for the stat block with all six values present, and
  with `null` values (new monitor, no rollup yet) rendering `—`.

## Out of scope

- Backfilling rollup history for monitors that predate this change.
- Any change to the dashboard card-wall / overview endpoint (only the
  `/monitors/{id}` detail page and `/monitors/{id}/uptime` endpoint are
  touched).
- Removing or renaming the legacy `UptimeEvent`/`IntegrationMonitor` bridge
  (tracked separately per the native-monitoring-engine design's slice plan).
