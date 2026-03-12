---
name: cb-code-quality
description: Enforces Circuit Breaker code quality standards: cognitive complexity
  ≤ 20 per function, file length ≤ 150 lines, no magic numbers, specific exception
  handling required for all I/O, nesting ≤ 3 levels deep, and tests required for
  unverified features. Use whenever writing, reviewing, or refactoring any backend
  Python (FastAPI/SQLAlchemy) or frontend TypeScript/React code in Circuit Breaker,
  before committing any changes, or when asked about code structure, complexity,
  naming conventions, constants, error handling patterns, or test requirements.
---

# Circuit Breaker — Code Quality Standards

## 1. Cognitive Complexity ≤ 20 / File Length ≤ 150 Lines

Every function must stay at or below a cognitive complexity score of 20. Files must not exceed 150 lines. Both limits are hard gates — violations block commit.

**What raises complexity:**
- Each `if`/`elif`/`else` branch: +1
- Each `for`/`while` loop: +1
- Each `try`/`except`: +1
- Each nested scope (function-in-function, lambda-in-loop): +2
- Boolean operators (`and`/`or`) in conditions: +1 each

**When you exceed the limit — split, don't compress:**

```python
# ❌ VIOLATES: one large function doing too much
def process_scan_results(scan_id, results, notify=True):
    hardware = []
    for r in results:
        if r.get("type") == "hardware":
            if r.get("status") == "active":
                try:
                    item = _build_hardware(r)
                    if item and item.get("ip"):
                        hardware.append(item)
                        if notify:
                            _send_alert(item)
                except Exception:
                    pass
    return hardware

# ✅ CORRECT: split into focused helpers
def process_scan_results(scan_id: int, results: list, notify: bool = True) -> list:
    active = [r for r in results if _is_active_hardware(r)]
    built = [_build_hardware(r) for r in active]
    valid = [h for h in built if h and h.get("ip")]
    if notify:
        _notify_all(valid)
    return valid

def _is_active_hardware(r: dict) -> bool:
    return r.get("type") == "hardware" and r.get("status") == "active"

def _notify_all(items: list) -> None:
    for item in items:
        try:
            _send_alert(item)
        except AlertError as e:
            logger.warning(f"[notify] failed for {item.get('ip')}: {e}")
```

### Verify Before Committing (Python)
```bash
pip install cognitive-complexity
flake8 --max-cognitive-complexity=20 apps/backend/
```

### Verify Before Committing (JavaScript/TypeScript)
```bash
# ESLint with complexity rule
npx eslint --rule '{"complexity": ["error", 20]}' apps/frontend/src/
```

---

## 2. No Magic Numbers

Every literal value that carries meaning must be named.

**Where to define constants**:
```
Python     : apps/backend/src/app/core/constants.py
TypeScript : apps/frontend/src/lib/constants.ts
```

```python
# ❌ BAD — bare literals
await redis.setex(cache_key, 300, payload)
if temp > 85:
    status = "critical"
backoff = min(backoff * 1.5, 30000)

# ✅ CORRECT — named constants
from app.core.constants import (
    TELEMETRY_CACHE_TTL_SECONDS,
    TEMP_CRITICAL_THRESHOLD_C,
    BACKOFF_MULTIPLIER,
    MAX_BACKOFF_MS,
)
await redis.setex(cache_key, TELEMETRY_CACHE_TTL_SECONDS, payload)
if temp > TEMP_CRITICAL_THRESHOLD_C:
    status = "critical"
backoff = min(backoff * BACKOFF_MULTIPLIER, MAX_BACKOFF_MS)
```

```ts
// ❌ BAD
setTimeout(poll, 30000);
if (cpuPct > 90) setStatus("critical");

// ✅ CORRECT
import { POLL_INTERVAL_MS, CPU_CRITICAL_THRESHOLD } from "@/lib/constants";
setTimeout(poll, POLL_INTERVAL_MS);
if (cpuPct > CPU_CRITICAL_THRESHOLD) setStatus("critical");
```

**Rule:** If you write a number or string literal that isn't `0`, `1`, `""`, `True`, `False`, or a format string — extract it.

---

## 3. Error Handling — try/except Required

Every function that touches I/O (DB, Redis, SMTP, HTTP, filesystem, device) **must** have a try/except. Bare `except Exception` is forbidden — always catch the specific exception first.

### Exception Hierarchy (use most specific first)
```python
# Order: specific → broad → never bare
except redis.ConnectionError     # Most specific
except redis.RedisError          # Broad Redis
except json.JSONDecodeError      # Specific decode
except ValueError                # Broad value
except Exception as e            # Last resort — must log + re-raise or return typed fallback
```

```python
# ❌ BAD
def get_cached_telemetry(hardware_id: int):
    raw = redis_client.get(f"telemetry:{hardware_id}")
    return json.loads(raw)

# ✅ CORRECT
async def get_cached_telemetry(hardware_id: int) -> dict | None:
    cache_key = f"telemetry:{hardware_id}"
    try:
        raw = await get_redis_client().get(cache_key)
        if raw is None:
            return None
        return json.loads(raw)
    except redis.ConnectionError as e:
        logger.warning(f"[telemetry_cache] Redis unavailable for hw:{hardware_id}: {e}")
        return None
    except json.JSONDecodeError as e:
        logger.error(f"[telemetry_cache] Corrupt cache for hw:{hardware_id}: {e}")
        await get_redis_client().delete(cache_key)
        return None
```

**Never swallow errors silently.** Every `except` block must either log + return a safe fallback, or re-raise.

---

## 4. Nesting ≤ 3 Levels Deep

Count indentation levels from the function body. Loops, conditions, try/except, and with-blocks each add one level.

```python
# ❌ VIOLATES: 5 levels deep
def process(items):               # Level 1
    for item in items:            # Level 2
        if item.active:           # Level 3
            try:                  # Level 4
                if item.type == "hw":  # Level 5 ← VIOLATION
                    ...

# ✅ CORRECT: extract inner logic
def process(items):
    for item in items:
        if item.active:
            _process_active_item(item)

def _process_active_item(item):
    try:
        _dispatch_by_type(item)
    except ProcessingError as e:
        logger.error(f"[process] failed item:{item.id}: {e}")
```

```tsx
// ✅ CORRECT (TypeScript — same rule)
// Extract JSX into sub-components, callbacks into named functions
const NodeCard: React.FC<Props> = ({ node, telemetry }) => (
  <div className="node-card">
    <NodeHeader node={node} />
    <TelemetryBadge telemetry={telemetry} />
  </div>
);
// Not: nested ternaries + map + condition + render = 5 levels
```

---

## 5. Self-Documenting Code + Naming Conventions

Code must read as a description of what it does. Comments explain *why*, not *what*.

### Naming Conventions
```
Python functions : verb_noun()          → poll_device(), write_telemetry()
Python classes   : PascalCase           → TelemetryCollector, LiveMetric
Constants        : UPPER_SNAKE_CASE     → MAX_RETRY_COUNT, CACHE_TTL_SECONDS
Booleans         : is_/has_/can_        → is_active, has_telemetry, can_retry
TS components    : PascalCase           → TelemetryBadge, NodeCard
TS hooks         : useCamelCase         → useTelemetry, useGraphLayout
```

```python
# ❌ BAD names
def proc(d, f=False):
    x = d.get("t")
    if x and x > 80:
        return True
    return f

# ✅ CORRECT names
def is_temperature_critical(device_data: dict, default: bool = False) -> bool:
    temperature = device_data.get("temperature_c")
    if temperature is None:
        return default
    return temperature > TEMP_CRITICAL_THRESHOLD_C
```

**Avoid:** single-letter variables (except loop counters `i`, `j`), abbreviations (`cfg`, `mgr`, `proc`), and generic names (`data`, `result`, `info`, `temp` for non-temperature values).

---

## 6. Tests — Required for Unverified Features

Any new function, endpoint, or hook that has not been manually verified end-to-end **must** have tests before merging. The minimum bar is one unit test + one integration test for backend, one component test for frontend.

### Unit Test Template (Python)
```python
# apps/backend/tests/unit/test_telemetry_service.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.services.telemetry_service import get_telemetry_for_hardware
from app.schemas.telemetry import TelemetryResponse

@pytest.mark.asyncio
async def test_get_telemetry_returns_cached_value():
    mock_redis = AsyncMock()
    mock_redis.get.return_value = b'{"cpu_pct": 42.0, "status": "ok"}'
    with patch("app.services.telemetry_service.get_redis_client", return_value=mock_redis):
        result = await get_telemetry_for_hardware(hardware_id=1)
    assert isinstance(result, TelemetryResponse)
    assert result.cpu_pct == 42.0

@pytest.mark.asyncio
async def test_get_telemetry_falls_back_to_db_on_cache_miss():
    mock_redis = AsyncMock()
    mock_redis.get.return_value = None
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = MagicMock(
        cpu_pct=55.0, status="warn"
    )
    with patch("app.services.telemetry_service.get_redis_client", return_value=mock_redis):
        result = await get_telemetry_for_hardware(hardware_id=1, db=mock_db)
    assert result.cpu_pct == 55.0
```

### Integration Test Template (Python)
```python
# apps/backend/tests/integration/test_telemetry_e2e.py
import pytest
from httpx import AsyncClient
from app.main import app

@pytest.mark.asyncio
async def test_telemetry_endpoint_returns_200_for_known_hardware():
    async with AsyncClient(app=app, base_url="http://test") as client:
        for hw_id in [1, 2, 3]:
            resp = await client.get(f"/api/v1/telemetry/{hw_id}")
            assert resp.status_code in (200, 404)  # 404 OK if not seeded

@pytest.mark.asyncio
async def test_telemetry_write_persists_to_redis_and_db():
    payload = {"cpu_pct": 72.5, "temp_c": 65.0, "status": "ok"}
    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.post("/api/v1/telemetry/1", json=payload)
        assert resp.status_code == 200
        verify = await client.get("/api/v1/telemetry/1")
        assert verify.json()["cpu_pct"] == 72.5
```

---

## 7. Pre-Commit Checklist

Run this gate before every commit. All items must pass.

### Complexity & Size
- [ ] Every function: cognitive complexity ≤ 20 (`flake8 --max-cognitive-complexity=20`)
- [ ] Every file: ≤ 150 lines (`wc -l` or editor line count)
- [ ] No function > 40 lines — if so, split it

### Magic Numbers
- [ ] No bare integer/float/string literals with semantic meaning
- [ ] All constants defined in `core/constants.py` or `lib/constants.ts`
- [ ] Constant names are UPPER_SNAKE_CASE and self-describing

### Error Handling
- [ ] Every I/O function has try/except
- [ ] No bare `except:` or `except Exception:` without logging
- [ ] Every except block logs with `[module_name]` prefix and the exception
- [ ] Redis errors caught as `redis.ConnectionError` / `redis.RedisError`
- [ ] JSON errors caught as `json.JSONDecodeError`
- [ ] HTTP errors caught as `httpx.HTTPError` or `requests.RequestException`
- [ ] DB errors caught as `sqlalchemy.exc.SQLAlchemyError`

### Nesting
- [ ] No function body exceeds 3 indentation levels
- [ ] No JSX renders with more than 3 nesting levels without sub-component extraction

### Naming
- [ ] Python functions use `verb_noun()` pattern
- [ ] No single-letter variables outside loop counters
- [ ] No abbreviations: `cfg`, `mgr`, `proc`, `tmp`, `res`, `val`
- [ ] Booleans use `is_`/`has_`/`can_` prefix

### Tests
- [ ] New backend functions have at least one unit test
- [ ] New API endpoints have at least one integration test
- [ ] New React hooks or components have at least one component test
- [ ] Tests cover both the happy path and at least one error/edge case

### General
- [ ] No commented-out code in the diff
- [ ] No `print()` debug statements (use `logger`)
- [ ] No `TODO` added without a linked issue number

---

## 8. CI/CD Auto-Enforcement

Add `.github/workflows/quality.yml` to enforce limits in CI:

```yaml
name: Code Quality

on: [push, pull_request]

jobs:
  quality:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Python complexity check
        run: |
          pip install flake8 flake8-cognitive-complexity
          flake8 --max-cognitive-complexity=20 apps/backend/src/

      - name: Python file length check
        run: |
          find apps/backend/src -name "*.py" | while read f; do
            lines=$(wc -l < "$f")
            if [ "$lines" -gt 150 ]; then
              echo "FAIL: $f has $lines lines (max 150)"
              exit 1
            fi
          done

      - name: Frontend lint (complexity)
        run: |
          cd apps/frontend
          npx eslint --rule '{"complexity": ["error", 20]}' src/
```

---

## Quick Reference Card

| Rule | Limit | Tool |
|------|-------|------|
| Cognitive complexity | ≤ 20 per function | `flake8 --max-cognitive-complexity=20` |
| File length | ≤ 150 lines | `wc -l` |
| Nesting depth | ≤ 3 levels | Manual / ESLint `max-depth` |
| Magic numbers | 0 bare literals | Code review |
| I/O without try/except | 0 | Code review |
| Tests for new features | Required | `pytest` / `vitest` |

### Constants File Locations
```
Backend  : apps/backend/src/app/core/constants.py
Frontend : apps/frontend/src/lib/constants.ts
```

### Exception Priority Order
```
redis.ConnectionError → redis.RedisError
json.JSONDecodeError → ValueError
httpx.TimeoutException → httpx.HTTPError
sqlalchemy.exc.OperationalError → sqlalchemy.exc.SQLAlchemyError
Exception (last resort — log + re-raise or return typed fallback)
```

### Naming Cheat Sheet
```
Python fn   : poll_device()       write_telemetry()    get_cached_metrics()
Python cls  : TelemetryCollector  LiveMetric           VaultService
Constants   : MAX_RETRY_COUNT     CACHE_TTL_SECONDS    TEMP_CRITICAL_THRESHOLD_C
Booleans    : is_active           has_telemetry        can_retry
TS component: TelemetryBadge      NodeCard             ProxmoxModal
TS hook     : useTelemetry        useGraphLayout       useDiscoveryState
```
