# cbi-agent Slices 1-2 Cohesion Hardening — Deferred Follow-ups

**Date:** 2026-08-06

Items the hardening plan
(`plans/2026-08-06-cbi-agent-slice12-cohesion-hardening-tasks.md`) explicitly
deferred rather than fixed. Each is out of scope for that plan and needs its own
change.

---

## F-1. `Sidebar.jsx` double-scales `cpu_pct` for agent-linked Proxmox hardware

**Filed by:** Task 5 (plan line ~890, "File a follow-up (do not fix here)").

`apps/frontend/src/components/Map/Sidebar.jsx:241` renders CPU as
`Math.round(data.cpu_pct * 100)`, which assumes the Proxmox convention where
`cpu_pct` is a 0–1 fraction. The platform normalizer
(`app/services/telemetry_normalize.py`) deliberately keeps `cpu_pct` on the
0–100 convention that every other consumer reads.

The two only collide on a Hardware row that is **both** agent-linked and
Proxmox-managed: the branch is gated on `integration_config_id != null`, so a
purely agent-linked host never reaches it. When they do collide, an agent
reporting `cpu_pct: 12.5` renders as `1250%`.

**Fix direction:** normalize at the Proxmox ingest boundary so `cpu_pct` is
0–100 everywhere, then delete the `* 100` in `Sidebar.jsx`. Do not special-case
the source in the component — that reintroduces the two-conventions problem the
single normalizer exists to remove.

---

## F-2. `tests/unit/test_startup_schema_guard.py` is red on `dev`

**Found by:** Task 8 verification, while establishing the known-red baseline.

`test_assert_required_schema_retries_migration_once` and
`test_assert_required_schema_exits_when_schema_still_missing` fail on `dev`
before any work in the hardening plan. Root cause is
`_REQUIRED_SCHEMA_TABLES = frozenset({"app_settings"})`
(`apps/backend/src/app/main.py:136`), narrowed by dev commit `66f16c29`, so
`_assert_required_schema` never enters the retry branch the tests assert.

Neither `main.py` nor the test file is in the hardening plan's scope, so it was
left alone. Either the narrowing or the tests are stale — decide which, and fix
that one.

---

## F-3. `dockerStatsSummary`'s non-200 short-circuit is not independently pinned

**Found by:** Task 2 verification.

`apps/agent/internal/collect/host/docker.go:57-59` returns early on a non-200
stats response. Both table cases in `TestDocker_StatsFailure...` use non-JSON
bodies, so the decode guard one line later absorbs the mutation and deleting the
status check leaves the suite green. A 500 response carrying *valid* JSON would
still produce a full stats map.

The plan asked for "stats 500 or malformed" and got both, so this is a coverage
gap rather than a plan violation. Add a case with a 500 + well-formed body.

---

## F-4. `collect.Runner`'s `Collect`-error branch has no test

**Found by:** Task 2 verification.

`apps/agent/internal/collect/collect.go:62` (`if err == nil`) is the only
uncovered statement in `run` (94.4%). `fakeCollector.err` exists and is wired
into `Collect` but no test sets it. Task 9 owns the `OnReadiness` assertion on
that path; the frame-channel half is untested by anyone.
