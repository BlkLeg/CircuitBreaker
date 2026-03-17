# Loud Error Handling for Native Deployment

**Date:** 2026-03-17
**Context:** CircuitBreaker is shifting focus to native (non-Docker) deployment. Silent failures that were acceptable in Docker (where container orchestration surfaced crashes) are invisible in native mode — they disappear into the void while the process appears healthy. The goal is to make every failure visible in the terminal and `journalctl` without changing process liveness semantics (keep running, log loudly).

---

## Approach

Approach B: two global safety nets (APScheduler + asyncio) that cover entire classes of failures automatically, plus targeted fixes for the specific silent failures identified in an audit.

---

## Section 1: Global Safety Nets

Both go in `apps/backend/src/app/main.py` lifespan startup, before `scheduler.start()` and before background tasks are created.

### 1a — APScheduler Job Error + Missed Listener

APScheduler 3.x fires `EVENT_JOB_ERROR` when any job raises an unhandled exception and `EVENT_JOB_MISSED`/`EVENT_JOB_MAX_INSTANCES` when jobs are skipped. Currently these produce no output. One combined listener covers all future jobs automatically.

```python
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_MISSED, EVENT_JOB_MAX_INSTANCES

def _job_error_listener(event):
    _logger.error(
        "Scheduler job '%s' raised an unhandled exception",
        event.job_id,
        exc_info=event.exception,
    )

def _job_missed_listener(event):
    _logger.warning(
        "Scheduler job '%s' missed its fire time (scheduled=%s)",
        event.job_id,
        event.scheduled_run_time,
    )

scheduler.add_listener(_job_error_listener, EVENT_JOB_ERROR)
scheduler.add_listener(_job_missed_listener, EVENT_JOB_MISSED | EVENT_JOB_MAX_INSTANCES)
```

**Effect:** Every failing or skipped scheduled job prints a full stack trace or warning. Zero per-job changes required.

### 1b — asyncio Task Exception Handler

`asyncio.create_task()` coroutines that raise without being awaited are silently dropped by the event loop. One hook on the loop catches all of them.

```python
def _task_exception_handler(loop, context):
    exc = context.get("exception")
    _logger.error(
        "Unhandled asyncio task exception: %s",
        context.get("message", "no message"),
        exc_info=exc,
    )

asyncio.get_event_loop().set_exception_handler(_task_exception_handler)
```

**Effect:** Any `create_task()` crash — update check, NATS bridge handler, worker tasks — surfaces immediately.

---

## Section 2: Targeted Silent Failure Fixes

### Priority: CRITICAL

**JWT secret empty fallback** — `apps/backend/src/app/core/users.py`

If the DB is unavailable and `CB_JWT_SECRET` env var is unset, the current code silently proceeds with an empty string JWT secret. Auth breaks for all users with no indication why.

**Fix:** After exhausting the fallback chain, if the secret is empty or None, raise `SystemExit(1)` with a clear message.

---

### Priority: HIGH

**NATS disconnected at startup** — `apps/backend/src/app/main.py` (post-connect check)

NATS failing to connect currently logs at INFO and the app proceeds. For native deployment this is invisible.

**Fix:** After `await nats_client.connect()`, if `not nats_client.is_connected`, log at `WARNING`:
```
NATS is not connected — SSE event streaming and real-time notifications are degraded.
Check that the NATS container is running: make services-up
```

**APScheduler job max-instances hit** — `apps/backend/src/app/main.py`

When a proxmox poll job is still running when the next trigger fires, APScheduler silently skips the trigger. The `EVENT_JOB_MAX_INSTANCES` listener in Section 1a covers this automatically once added.

---

### Priority: MEDIUM

**mDNS + SSDP both inactive** — `apps/backend/src/app/services/listener_service.py`

Each service already logs a `WARNING` on failure. Add a post-init check: if both `mdns_active` and `ssdp_active` are `False` after startup, log at `ERROR`:
```
Both mDNS and SSDP listeners failed to start — network discovery is completely disabled.
```

**RBAC scope JSON corruption** — `apps/backend/src/app/core/rbac.py`

Silent `except: return set()` on malformed user scope JSON means a user silently gets fewer permissions than expected.

**Fix:** Change to `_logger.warning("RBAC: invalid scopes JSON for user_id=%s, falling back to role defaults: %s", user_id, e, exc_info=True)`.

**Audit actor lookup failures** — `apps/backend/src/app/core/audit.py`

Currently `_logger.debug`. An audit log missing the actor name is a data integrity problem.

**Fix:** Escalate to `_logger.warning` with `exc_info=True`.

---

### Priority: LOW

**Update check network failure** — `apps/backend/src/app/core/update_check.py`

Currently `return None` with no logging on any exception.

**Fix:** Add `_logger.debug("Update check failed: %s", e)` before returning `None`.

**Rate limit profile DB fallback** — `apps/backend/src/app/core/rate_limit.py`

Silent fallback to "normal" profile on DB error.

**Fix:** Add `_logger.debug("Rate limit profile fetch failed, using 'normal': %s", e)`.

---

## Files Modified

| File | Change |
|------|--------|
| `apps/backend/src/app/main.py` | Add APScheduler listeners + asyncio exception handler + NATS post-connect warning |
| `apps/backend/src/app/core/users.py` | Raise `SystemExit(1)` on empty JWT secret |
| `apps/backend/src/app/services/listener_service.py` | Add post-init ERROR if both mDNS and SSDP inactive |
| `apps/backend/src/app/core/rbac.py` | Escalate scope JSON error to WARNING |
| `apps/backend/src/app/core/audit.py` | Escalate actor lookup failure to WARNING |
| `apps/backend/src/app/core/update_check.py` | Add DEBUG log on network failure |
| `apps/backend/src/app/core/rate_limit.py` | Add DEBUG log on DB fallback |

---

## What This Does NOT Change

- Process liveness — the server keeps running on all non-CRITICAL failures
- API behavior — no endpoint responses change
- Existing ERROR/CRITICAL paths — already loud, left alone
- Docker deployment — all changes are additive log escalations, no behavioral change

---

## Verification

1. Stop NATS (`docker stop cb-nats-dev`), run `make backend` → terminal should show NATS WARNING immediately after startup
2. Configure a Proxmox integration with a wrong URL → after 30s, job error should appear in terminal with full stack trace
3. Corrupt a user's `scopes` column in DB (`UPDATE users SET scopes='bad json' WHERE id=1`) → next request from that user should log RBAC WARNING
4. Kill Redis (`docker stop cb-redis-dev`) → rate limit fallback DEBUG should appear if running with `--log-level debug`
5. Let the app run 5+ minutes → no silent proxmox poll failures; missed fires log at WARNING
