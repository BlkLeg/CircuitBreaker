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

---

## F-5. The agent cannot detect a black-hole network partition

**Found by:** Task 20, while choosing an outage mechanism for the catch-up test.

`internal/link` sets a read deadline only on the handshake path
(`link.go:944`); there is no steady-state read deadline on an established
connection. So if the network is severed in a way that drops packets silently —
`docker network disconnect`, a firewall DROP rule, a dead NAT entry — the agent
does not notice. It keeps believing the link is up, `runOnce`'s select loop
keeps writing into a socket that will never deliver, and nothing spools.

This is why the Task 20 e2e uses `docker compose stop circuitbreaker` (which
sends a TCP FIN the agent *does* see) rather than the plan's specified
`docker network disconnect`. The consequence is that **the plan's actual
network-partition scenario is covered by no test**, and neither is the silent
frame loss it causes.

**Fix direction:** set a read deadline on the established connection, sized off
the 20 s heartbeat interval (e.g. 3 missed heartbeats), and treat expiry as a
disconnect so the spool takes over. Then restore the e2e to the plan's
`docker network disconnect` mechanism and add a regression test for the
black-hole case.

---

## F-6. Task 20's catch-up assertions are weaker than the plan specifies

**Found by:** Task 20 verification. Recorded rather than fixed because the
product defect F-7 blocked the test from running at all until late.

Three assertions in `test_agent_host_telemetry_first_sample_catchup_and_disable`
are weaker than the plan's step 3 requires:

1. **Per-sample uniqueness is inferred, not asserted.** The plan wants "every
   `sample_id` appears once (re-issue the same window twice and compare)". The
   test compares aggregated 1 h history buckets, because the history endpoint
   returns bucket aggregates only. Uniqueness is inferred from
   `sample_count <= 4` per 30 s bucket plus bucket-equality across two reads.
   A per-sample assertion needs a different endpoint or a direct DB read.
2. **The catch-up budget is measured from the wrong instant.** The test allows
   240 s to first observe `spool_depth > 0` and only then starts the 30 s
   catch-up clock, so it can no longer distinguish "catch-up was bounded" from
   "reconnect backoff was long" — which is the property D-5 exists to pin.
3. **`outage_start` is stamped before `docker compose stop` returns**, so
   `_outage_points()` can include buckets collected and delivered live while the
   server was still up. If the stop takes longer than one bucket width, the
   `min_outage_samples = 3` floor can be met entirely by pre-outage buckets and
   the "`collected_at` preserved rather than rewritten to reconnect time" proof
   degrades to a tautology.

---

## F-7. RESOLVED — fresh installs could not persist a single host sample

Kept for the record because it is the reason F-5/F-6 were deferred, and because
the failure mode is worth recognising again.

`0001_init._copy_column` rebuilt every column without carrying `autoincrement`.
`agent_host_samples.id` and `hardware_live_metrics.id` are
`BigInteger, autoincrement=True` but only *part* of a composite `(id, <time>)`
primary key (so TimescaleDB can partition on time), and SQLAlchemy's default
`autoincrement="auto"` declines to emit `SERIAL` in that shape. Both therefore
became plain `BIGINT NOT NULL` with no sequence, and every INSERT omitting `id`
failed. `0095` could not save it: on a fresh install the tables already exist
(0001 builds the whole of `Base.metadata` up front), so 0095 short-circuits and
its own correct `create_table` never runs.

`ingest_host_sample`'s blanket `except IntegrityError:` then made it
unrecognisable — it assumed the only possible failure was the
`uq_agent_host_sample` dedupe, re-SELECTed, and surfaced the `NotNullViolation`
as an unrelated `NoResultFound` that took the `/link` socket down.

**Why no unit test caught it:** `tests/conftest.py` builds the schema with
`Base.metadata.create_all`, which uses the *model* metadata. Only a real Alembic
run — a fresh install, or the Docker e2e stack — goes through
`_build_bootstrap_metadata`. The e2e is what found it.

---

## F-8. `test_agent_update_success_and_forced_rollback` is broken on `dev`

**Found by:** Task 21 release-gate verification.

The e2e self-update/rollback test fails on **both** `dev` and this branch, so it
is pre-existing — but the two failure modes differ, and neither has been
diagnosed:

| | where it dies | how |
|---|---|---|
| `dev` | ~88 s, before the `cb-agent` container starts at all | `AssertionError` |
| this branch | ~212 s, after the agent is up, inside `_cut_agent_network` | `Error response from daemon: network sandbox for container … not found` |

The branch gets *further* than `dev` does. `apps/agent/internal/update/` is
untouched by the slice 1-2 hardening work, and the rollback logic's unit test
(`TestWatchForRollback_NoConfirmationTriggersRollback`) passes under `-race`.

The branch-side failure is a harness/daemon race, not a product assertion:
`docker network disconnect` is being issued before the container's network
sandbox exists. It is the same mechanism [[F-5]] rules out for the catch-up
test, which is more evidence for fixing that properly: give the link a
steady-state read deadline so a partition is detectable, then the e2e can stop
depending on `docker network disconnect` at all.

**Both failures need diagnosing before the e2e suite can be a trustworthy gate.**
The other five lifecycle tests pass (one xfailed), including Task 20's new
telemetry/catch-up/disable test.
