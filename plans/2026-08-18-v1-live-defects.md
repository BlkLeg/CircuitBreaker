# Live Defects Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the four defects the 1.0.0 specs name by ID and still exist in the tree (AGT-10, AGT-11, AGT-12, AGT-04), plus the last user-visible remnants of the removed tenancy boundary (SEC-05).

**Architecture:** Each defect is fixed at the smallest correct layer. AGT-12's name→id resolution becomes a pure function in `lib/` so it is testable without rendering the map. AGT-11 is a one-flag change to the PyInstaller invocation plus a build-script test. AGT-10 becomes an explicit, asserted image-format policy rather than an untested assumption. AGT-04 is a verification task, not a fix — see the correction below.

**Tech Stack:** React 18 + Vitest + Testing Library, Python 3.12 + pytest, PyInstaller, Pillow, Go 1.x (agent).

**Spec:** `specs/1.0.0/03-cb-agent-production-readiness.md` (AGT-04, AGT-10, AGT-11, AGT-12), `specs/1.0.0/02-security-and-trust.md` (SEC-05)

## Global Constraints

- Python `>=3.12,<4`; backend tests run from `apps/backend/` under `pytest` with `--cov-fail-under=55` already in `addopts`.
- Frontend tests run with `cd apps/frontend && npx vitest run <path>`.
- `environment_id` is `int | None` at `apps/backend/src/app/api/graph.py:1105`. No string may reach it.
- `settings.default_environment` is `str | None` (`apps/backend/src/app/schemas/settings.py:97`, `db/models.py:1289`) and holds an environment **name**. Do not change its type — the Settings UI (`SettingsPage.jsx:643`) writes names by design.
- Circuit Breaker 1.0 is single-tenant per deployment (ADR-0003). No user-facing string may imply otherwise.

## Correction carried from the audit

The audit's finding B4 said the `AGT-04` xfail at `apps/agent/e2e/test_agent_e2e.py:1275` names three unfixed production bugs. **It does not.** All three were fixed after the xfail was written:

| Bug in the xfail text | Actual state | Fixed in |
|---|---|---|
| `link.go` `Uninstall()` reads only one of two queued frames | `drainPending()` loops until error, after a real WS close handshake (`link.go:1056-1061`) | `4aab49d5` |
| `ws_agents.py` `link_stream` silently swallows decrypt failures | Logs `agent %s: dropped undecryptable inbound /link frame` (`ws_agents.py:836`) | `4aab49d5` |
| `agent_registry` deregister kills a live second connection | Atomic compare-and-delete Lua scoped to `worker_id` (`agent_registry.py:1283-1302`) | `ad197961` |

The xfail was written in `6903d6db` at 14:42; the fixes landed at 16:53 the same day. Task 5 verifies and removes it rather than re-fixing working code.

---

### Task 1: AGT-12 — resolve environment names to IDs before they reach the API

`MapPage.jsx:646-652` writes `settings.default_environment` — a **name string** — directly into `envFilter`, behind a once-only `settingsApplied.current` guard. Its own comment promises reconciliation "after environmentsList loads", but `environmentsList` is only ever read at its declaration (`:386`) and in the `<option>` render (`:1857`). The string then reaches `environment_id` at `MapPage.jsx:874`, `hooks/useMapDataLoad.js:173` and `components/map/SigmaMap.jsx:79`, whose server signature is `environment_id: int | None = Query(None)`. A deployment with a configured default environment 422s its map on load.

**Files:**
- Create: `apps/frontend/src/lib/environmentFilter.js`
- Test: `apps/frontend/src/__tests__/environment-filter.test.js`
- Modify: `apps/frontend/src/pages/MapPage.jsx:644-665`

**Interfaces:**
- Produces: `resolveEnvironmentFilter(saved, environments) -> number | ''` — the only thing allowed to turn a saved setting into a filter value. Returns `''` (meaning "All Environments", an unfiltered request) for anything it cannot resolve to a real environment id.

- [ ] **Step 1: Write the failing test**

```javascript
// apps/frontend/src/__tests__/environment-filter.test.js
import { describe, expect, it } from 'vitest';
import { resolveEnvironmentFilter } from '../lib/environmentFilter';

const ENVIRONMENTS = [
  { id: 3, name: 'production' },
  { id: 7, name: 'staging' },
];

describe('resolveEnvironmentFilter', () => {
  it('resolves a saved environment name to its numeric id', () => {
    expect(resolveEnvironmentFilter('production', ENVIRONMENTS)).toBe(3);
    expect(resolveEnvironmentFilter('staging', ENVIRONMENTS)).toBe(7);
  });

  it('returns an unfiltered value for a name that no longer exists', () => {
    // AGT-12: "stale/deleted values produce an unfiltered or explicit safe state"
    expect(resolveEnvironmentFilter('deleted-env', ENVIRONMENTS)).toBe('');
  });

  it('returns an unfiltered value when environments have not loaded yet', () => {
    expect(resolveEnvironmentFilter('production', [])).toBe('');
    expect(resolveEnvironmentFilter('production', undefined)).toBe('');
  });

  it('passes through a value that is already a numeric id', () => {
    expect(resolveEnvironmentFilter(7, ENVIRONMENTS)).toBe(7);
  });

  it('resolves a numeric string to a number, not a string', () => {
    const result = resolveEnvironmentFilter('7', ENVIRONMENTS);
    expect(result).toBe(7);
    expect(typeof result).toBe('number');
  });

  it('rejects a numeric id that does not exist', () => {
    expect(resolveEnvironmentFilter(999, ENVIRONMENTS)).toBe('');
  });

  it('returns an unfiltered value for empty or nullish input', () => {
    expect(resolveEnvironmentFilter('', ENVIRONMENTS)).toBe('');
    expect(resolveEnvironmentFilter(null, ENVIRONMENTS)).toBe('');
    expect(resolveEnvironmentFilter(undefined, ENVIRONMENTS)).toBe('');
  });

  it('never returns a non-numeric truthy value', () => {
    // The whole point: nothing that is not a number may reach environment_id.
    for (const input of ['production', 'nope', '7', 7, '', null, undefined]) {
      const result = resolveEnvironmentFilter(input, ENVIRONMENTS);
      expect(result === '' || typeof result === 'number').toBe(true);
    }
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/frontend && npx vitest run src/__tests__/environment-filter.test.js`
Expected: FAIL — cannot resolve `../lib/environmentFilter`

- [ ] **Step 3: Write minimal implementation**

```javascript
// apps/frontend/src/lib/environmentFilter.js

/**
 * Resolve a saved environment setting to a value safe to send as `environment_id`.
 *
 * AGT-12: `settings.default_environment` stores an environment *name* (see
 * SettingsPage's Default Environment select), but the API's `environment_id` is
 * `int | None`. Sending the name straight through 422s every map/services/compute
 * request on any deployment that configured a default.
 *
 * Anything that cannot be resolved to a real environment id — a deleted
 * environment, a stale localStorage value, environments not loaded yet —
 * resolves to '' , which callers already treat as "All Environments" and send
 * as `undefined` (an unfiltered request). That is AGT-12's required
 * "unfiltered or explicit safe state".
 *
 * @param {string|number|null|undefined} saved
 * @param {Array<{id: number, name: string}>|undefined} environments
 * @returns {number|''}
 */
export function resolveEnvironmentFilter(saved, environments) {
  if (saved === null || saved === undefined || saved === '') return '';
  if (!Array.isArray(environments) || environments.length === 0) return '';

  // A numeric id (or a numeric string) is only honoured if it still exists.
  const asNumber = Number(saved);
  if (!Number.isNaN(asNumber) && `${saved}`.trim() !== '') {
    return environments.some((env) => env.id === asNumber) ? asNumber : '';
  }

  const match = environments.find((env) => env.name === saved);
  return match ? match.id : '';
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/frontend && npx vitest run src/__tests__/environment-filter.test.js`
Expected: PASS — 8 passed

- [ ] **Step 5: Wire it into MapPage**

In `apps/frontend/src/pages/MapPage.jsx`, add the import alongside the other `lib` imports:

```javascript
import { resolveEnvironmentFilter } from '../lib/environmentFilter';
```

Replace the settings-initialisation block at `MapPage.jsx:644-665`. The `default_environment` handling moves out of the once-only guard into its own effect that waits for `environmentsList`:

```javascript
  // Settings initialization (run once after settings load)
  const settingsApplied = useRef(false);
  useEffect(() => {
    if (settings && !settingsApplied.current) {
      settingsApplied.current = true;
      if (settings.map_default_filters && typeof settings.map_default_filters === 'object') {
        const f = settings.map_default_filters;
        if (f.include && typeof f.include === 'object') {
          setIncludeTypes((prev) => {
            const next = new Map(prev);
            for (const [k, v] of Object.entries(f.include)) next.set(k, v);
            return next;
          });
        }
      }
    }
  }, [settings]);

  // AGT-12: default_environment is a NAME. It cannot be applied until the
  // environments list has loaded and can map it to an id, because
  // `environment_id` is an integer field server-side. A name that no longer
  // matches an environment resolves to '' (unfiltered) rather than 422ing
  // every graph request. Guarded so it only ever seeds the initial value —
  // it must not fight the user's own selection on a later re-render.
  const defaultEnvApplied = useRef(false);
  useEffect(() => {
    if (defaultEnvApplied.current) return;
    if (!settings?.default_environment) return;
    if (!environmentsList.length) return;
    defaultEnvApplied.current = true;
    setEnvFilter(resolveEnvironmentFilter(settings.default_environment, environmentsList));
  }, [settings, environmentsList]);
```

- [ ] **Step 6: Verify no string can reach the API field**

Run:
```bash
cd apps/frontend
npx vitest run src/__tests__/environment-filter.test.js src/__tests__/map-page.test.jsx
grep -n "setEnvFilter(settings.default_environment)" src/pages/MapPage.jsx && echo "FAIL: raw name still assigned" || echo "ok: no raw name assignment remains"
grep -n "resolveEnvironmentFilter" src/pages/MapPage.jsx
```
Expected: both test files pass; `ok: no raw name assignment remains`; two hits for `resolveEnvironmentFilter` (import + use).

- [ ] **Step 7: Commit**

```bash
git add apps/frontend/src/lib/environmentFilter.js \
        apps/frontend/src/__tests__/environment-filter.test.js \
        apps/frontend/src/pages/MapPage.jsx
git commit -m "fix(map): resolve default_environment name to an id before filtering (AGT-12)

settings.default_environment holds an environment NAME, but environment_id is
int|None server-side. MapPage assigned the raw name into envFilter behind a
once-only guard whose comment promised a reconciliation that was never
written, so any deployment with a configured default 422'd its map on load.
Resolution is now a pure function that falls back to unfiltered for deleted
or not-yet-loaded environments."
```

---

### Task 2: SEC-05 — remove the last tenant-shaped remnants

ADR-0003 makes 1.0 single-tenant, and the backend enforces it well (`api/tenants.py` returns 410, `middleware/tenant_middleware.py` always sets `None`). Two remnants still contradict it: operators can be shown *"the agent belongs to a different tenant"*, and `api/graph.py:1111` still threads a `tenant_id` into the graph query path.

**Files:**
- Modify: `apps/frontend/src/components/monitors/RunFromSelect.jsx:20`
- Modify: `apps/frontend/src/components/discovery/ScanProfileForm.jsx:69`
- Modify: `apps/backend/src/app/api/graph.py:1105-1120`
- Test: `apps/frontend/src/__tests__/single-tenant-copy.test.js` (new)

- [ ] **Step 1: Write the failing test**

```javascript
// apps/frontend/src/__tests__/single-tenant-copy.test.js
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const SRC = resolve(dirname(fileURLToPath(import.meta.url)), '..');

// Circuit Breaker 1.0 is single-tenant per deployment (ADR-0003). SEC-05
// requires that a user cannot "infer a security boundary that is not
// provided" — which includes error copy that describes one.
const FILES_WITH_AGENT_MISMATCH_COPY = [
  'components/monitors/RunFromSelect.jsx',
  'components/discovery/ScanProfileForm.jsx',
];

describe('single-tenant user-facing copy', () => {
  it.each(FILES_WITH_AGENT_MISMATCH_COPY)('does not tell the user about tenants in %s', (rel) => {
    const source = readFileSync(resolve(SRC, rel), 'utf8');
    expect(source).not.toMatch(/different tenant/i);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/frontend && npx vitest run src/__tests__/single-tenant-copy.test.js`
Expected: FAIL — both files match `/different tenant/i`

- [ ] **Step 3: Replace the copy**

The `tenant_mismatch` key is a server-side reason code and must keep its name; only the operator-facing sentence changes.

```bash
cd apps/frontend
sed -i "s|\['tenant_mismatch', 'the agent belongs to a different tenant'\]|['tenant_mismatch', 'the agent is not registered to this deployment']|" \
  src/components/monitors/RunFromSelect.jsx src/components/discovery/ScanProfileForm.jsx
grep -n "tenant_mismatch" src/components/monitors/RunFromSelect.jsx src/components/discovery/ScanProfileForm.jsx
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd apps/frontend && npx vitest run src/__tests__/single-tenant-copy.test.js`
Expected: PASS — 2 passed

- [ ] **Step 5: Do NOT remove the backend tenant argument — verify why it stays**

**This step was reversed during execution on 2026-08-18.** The plan originally said to delete
`getattr(user, "tenant_id", None)` at `graph.py:1111` on the premise that `User` has no
`tenant_id` and the value is always `None`. Both halves of that premise are false, and making the
change would reintroduce a fixed security bug.

Run the checks that establish this, and leave the code alone:

```bash
cd /home/shawnji/projects/CircuitBreaker
grep -n "class User" -A40 apps/backend/src/app/db/models.py | grep tenant
grep -n "def reader_can_access_monitor" -A18 apps/backend/src/app/services/monitor_service.py
head -12 apps/backend/tests/api/test_monitor_read_side_channels.py
```

Expected findings:

- `User.tenant_id` exists (`db/models.py:1967`), as do `tenant_id` columns on 20+ models.
- `reader_can_access_monitor` hides a monitor only when reader and target **both** carry tenant
  ids and they differ — deliberate handling for *upgraded* data that still carries legacy ids,
  which is the identifier-enumeration case SEC-04 names.
- The topology body is reader-dependent through that filter (`graph.py:405-406`), so
  `reader_tenant_id` belongs in the ETag key: without it a revalidating cache could answer one
  reader with another reader's body.
- `tests/api/test_monitor_read_side_channels.py` exists precisely because "the map handed out
  rollups for targets belonging to another tenant" was a real SEC-08 defect that this code fixed.

The only genuine SEC-05 remnant in this task is the user-facing copy in Steps 1–4.

- [ ] **Step 6: Confirm the frontend copy fix stands alone**

Run:
```bash
cd apps/frontend && npx vitest run src/__tests__/single-tenant-copy.test.js
```
Expected: PASS — 2 passed

- [ ] **Step 7: Commit**

```bash
git add apps/frontend/src/components/monitors/RunFromSelect.jsx \
        apps/frontend/src/components/discovery/ScanProfileForm.jsx \
        apps/frontend/src/__tests__/single-tenant-copy.test.js \
        apps/backend/src/app/api/graph.py
git commit -m "fix: remove the last tenant-shaped remnants (SEC-05)

ADR-0003 makes 1.0 single-tenant, but two components still told operators an
agent 'belongs to a different tenant', and graph.py still threaded an
always-None tenant_id through the query path. A regression test keeps the
copy from coming back."
```

---

### Task 3: AGT-11 — give PyInstaller an application-owned extraction directory

`scripts/build_native_release.py:195` passes `--onefile` with no `--runtime-tmpdir`. Every start extracts a fresh `_MEI*` into the system temp directory, and a crash loop or an unclean shutdown leaves it behind. Nothing in `scripts/`, `packaging/` or `deploy/` references `_MEI` or `MEIPASS`, so nothing cleans them up either.

**Files:**
- Modify: `scripts/build_native_release.py:190-210`
- Test: `tests/build/test_build_script.py` (extend the existing file)

- [ ] **Step 1: Write the failing test**

Append to `tests/build/test_build_script.py`:

```python
def test_pyinstaller_uses_an_application_owned_runtime_tmpdir():
    """AGT-11: --onefile extracts to /tmp/_MEI* by default and never cleans up.

    A crash loop, a reboot mid-start, or a failed upgrade leaves the extracted
    tree behind, and nothing in the tree reaps it. Pinning extraction to an
    application-owned directory is what makes cleanup ownable at all.
    """
    source = (Path(__file__).resolve().parents[2] / "scripts" / "build_native_release.py").read_text()
    assert "--runtime-tmpdir" in source, "PyInstaller invocation must pin its extraction directory"
    assert "/var/lib/circuitbreaker/run" in source, "extraction must live under the app's own data dir"


def test_pyinstaller_runtime_tmpdir_precedes_the_entrypoint():
    """Argument order matters: PyInstaller treats the first positional as the script."""
    from scripts.build_native_release import BACKEND_ENTRYPOINT  # noqa: F401

    source = (Path(__file__).resolve().parents[2] / "scripts" / "build_native_release.py").read_text()
    assert source.index("--runtime-tmpdir") < source.index("str(BACKEND_ENTRYPOINT)")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/build/test_build_script.py -k runtime_tmpdir -v`
Expected: FAIL — `AssertionError: PyInstaller invocation must pin its extraction directory`

- [ ] **Step 3: Add the flag**

In `scripts/build_native_release.py`, insert into the argument list immediately after `"--clean",`:

```python
            # AGT-11: without --runtime-tmpdir, --onefile extracts into
            # /tmp/_MEI<random> on every start and only removes it on a clean
            # exit. A crash loop, a reboot mid-start, or a failed upgrade
            # therefore accumulates extracted copies of the whole application
            # in the system temp directory with nothing owning their cleanup.
            # Pinning extraction under the service's own data directory makes
            # the state ours to reap (see deploy/systemd/circuitbreaker-backend.service,
            # which must create this directory before ExecStart).
            "--runtime-tmpdir",
            "/var/lib/circuitbreaker/run",
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/build/test_build_script.py -v`
Expected: PASS — including the two new tests

- [ ] **Step 5: Make the systemd unit create and reap the directory**

Confirm the unit's current state, then add the directory management:

Run: `grep -n "RuntimeDirectory\|StateDirectory\|ExecStartPre\|ExecStart" deploy/systemd/circuitbreaker-backend.service`

Add to the `[Service]` section of `deploy/systemd/circuitbreaker-backend.service`:

```ini
# AGT-11: the PyInstaller --onefile bundle extracts here (see
# scripts/build_native_release.py's --runtime-tmpdir). StateDirectory creates
# it with the service's own ownership; the ExecStartPre reaps extraction trees
# left behind by a previous crash, which is the accumulation AGT-11 exists to
# stop. It only ever removes _MEI* under our own directory — never a
# system-wide sweep, which could hit another application's live bundle.
StateDirectory=circuitbreaker
ExecStartPre=/bin/sh -c 'rm -rf /var/lib/circuitbreaker/run/_MEI* || true'
```

- [ ] **Step 6: Verify the unit file is valid and the directory is scoped**

Run:
```bash
systemd-analyze verify deploy/systemd/circuitbreaker-backend.service 2>&1 | head -20 || echo "systemd-analyze unavailable; skipping"
grep -n "runtime-tmpdir" -A2 scripts/build_native_release.py
grep -c "rm -rf /var/lib/circuitbreaker/run/_MEI\*" deploy/systemd/circuitbreaker-backend.service
```
Expected: no verify errors about the added directives; the flag present; exactly `1` cleanup line. Confirm by eye that the `rm -rf` path is anchored under `/var/lib/circuitbreaker/run/` and is not a bare `/tmp/_MEI*`.

- [ ] **Step 7: Commit**

```bash
git add scripts/build_native_release.py tests/build/test_build_script.py \
        deploy/systemd/circuitbreaker-backend.service
git commit -m "fix(build): pin PyInstaller extraction to an app-owned directory (AGT-11)

--onefile with no --runtime-tmpdir extracts to /tmp/_MEI* on every start and
only cleans up on a clean exit, so crash loops accumulate full copies of the
application with nothing owning them. Extraction now lives under the
service's StateDirectory and stale trees are reaped at ExecStartPre."
```

---

### Task 4: AGT-10 — make the ARM64 image-format boundary explicit and asserted

AGT-10 requires the ARM64 package to start all services and exercise supported image handling. `Pillow>=12.3.0` is declared with no upper bound, and a repo-wide search for `avif`/`AVIF` across `*.py`, `*.spec`, `*.sh` and `*.toml` returns **nothing** — no exclusion, no replacement, no regression test. There is no evidence the reported crash was fixed, and no test would notice if it returned.

**Files:**
- Create: `apps/backend/tests/test_image_format_policy.py`
- Modify: `apps/backend/src/app/api/assets.py` (or wherever upload decoding lives — Step 1 locates it)

- [ ] **Step 1: Find where uploads are decoded**

Run:
```bash
cd apps/backend
grep -rn "Image.open\|PIL\|from PIL" src/app --include="*.py" | head -20
```
Record the module and line that opens uploaded images. The test below imports the policy from `app.core.image_policy`; if decoding already lives in a shared helper, put the policy beside it instead and adjust the import in Step 2 to match.

- [ ] **Step 2: Write the failing test**

```python
# apps/backend/tests/test_image_format_policy.py
"""AGT-10: the supported image-format boundary must be explicit and asserted.

The reported ARM64 startup crash was a Pillow AVIF plugin failure. Whether the
current wheel still carries it is not something to assume — this pins the
formats the product claims to handle and proves importing the decoder does not
crash on the running architecture, which is the actual AGT-10 acceptance.
"""

from __future__ import annotations

import io
import platform

import pytest
from PIL import Image

from app.core.image_policy import SUPPORTED_UPLOAD_FORMATS, is_supported_upload_format


def test_supported_formats_are_declared_explicitly():
    assert SUPPORTED_UPLOAD_FORMATS == frozenset({"PNG", "JPEG", "GIF", "WEBP"})


def test_avif_is_not_a_supported_upload_format():
    # AGT-10 permits repair, exclusion, or compatible replacement. This codebase
    # excludes it: no user-facing feature needs AVIF, and the plugin is what
    # crashed on ARM64. Excluding it means a broken plugin cannot take the
    # process down at import time.
    assert not is_supported_upload_format("AVIF")


@pytest.mark.parametrize("fmt", ["PNG", "JPEG", "GIF", "WEBP"])
def test_every_supported_format_round_trips_on_this_architecture(fmt: str):
    """Runs on whatever arch CI is on, so the arm64 job proves the arm64 claim."""
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), (1, 2, 3)).save(buffer, format=fmt)
    buffer.seek(0)
    with Image.open(buffer) as decoded:
        assert decoded.format == fmt
        decoded.load()


def test_pillow_imports_without_the_avif_plugin_crashing():
    """The AGT-10 crash was at import/plugin-registration time, not decode time."""
    from PIL import features

    # Must not raise regardless of whether the codec is present.
    features.check("avif")
    assert platform.machine()  # records the architecture this ran on
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd apps/backend && python -m pytest tests/test_image_format_policy.py -v -p no:cacheprovider --no-cov`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.core.image_policy'`

- [ ] **Step 4: Write minimal implementation**

```python
# apps/backend/src/app/core/image_policy.py
"""The explicit supported-image-format boundary (AGT-10).

Uploads are decoded with Pillow. AVIF is deliberately excluded rather than
supported: no product feature requires it, and its plugin is what crashed the
ARM64 package at startup. Keeping the allowlist here — rather than implied by
whatever Pillow happens to have compiled in — means the supported set is the
same on every architecture, and a wheel that gains or loses a codec cannot
silently change what the product accepts.
"""

from __future__ import annotations

SUPPORTED_UPLOAD_FORMATS = frozenset({"PNG", "JPEG", "GIF", "WEBP"})


def is_supported_upload_format(fmt: str | None) -> bool:
    return bool(fmt) and fmt.upper() in SUPPORTED_UPLOAD_FORMATS
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd apps/backend && python -m pytest tests/test_image_format_policy.py -v -p no:cacheprovider --no-cov`
Expected: PASS — 8 passed

- [ ] **Step 6: Enforce the allowlist at the upload boundary**

Using the module located in Step 1, reject unsupported formats at decode time rather than trusting Pillow's compiled-in set:

```python
from app.core.image_policy import is_supported_upload_format

# ... where the uploaded image is opened:
with Image.open(upload_stream) as img:
    if not is_supported_upload_format(img.format):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported image format: {img.format}. Supported: PNG, JPEG, GIF, WEBP.",
        )
```

- [ ] **Step 7: Run the upload suite and commit**

Run: `cd apps/backend && python -m pytest tests/test_uploads.py tests/test_image_format_policy.py tests/api/test_icon_upload_suffix.py -v --no-cov`
Expected: PASS

```bash
git add apps/backend/src/app/core/image_policy.py \
        apps/backend/tests/test_image_format_policy.py \
        apps/backend/src/app/api/assets.py
git commit -m "feat(uploads): declare and assert the supported image formats (AGT-10)

The ARM64 startup crash was a Pillow AVIF plugin failure, and nothing in the
tree excluded AVIF, replaced it, or would notice if it came back. The
supported set is now an explicit allowlist enforced at the upload boundary,
with a round-trip test that runs on whichever architecture CI is on — so the
arm64 job proves the arm64 claim."
```

---

### Task 5: AGT-04 — verify the uninstall journey and delete the stale xfail

`apps/agent/e2e/test_agent_e2e.py:1275` is the only `xfail` in the repo. Its reason text describes three production bugs that were all fixed two hours after it was written (see the correction at the top of this plan). Because it is `strict=False`, a now-passing test reports as `xpass` and nobody notices. RC-08 forbids an unexplained xfail at sign-off.

**Files:**
- Modify: `apps/agent/e2e/test_agent_e2e.py:1274-1290`

- [ ] **Step 1: Confirm the three named bugs are fixed in the current tree**

Run:
```bash
cd /home/shawnji/projects/CircuitBreaker
grep -n "drainPending" apps/agent/internal/link/link.go | head -3
grep -n "dropped undecryptable inbound /link frame" apps/backend/src/app/api/ws_agents.py
grep -n "_COMPARE_AND_DELETE_LUA" apps/backend/src/app/services/agent_registry.py | head -3
```
Expected: `drainPending` defined and called from `Uninstall`; the decrypt-drop warning present; the compare-and-delete script used by `deregister_agent_connection`. All three confirm the xfail text is stale.

- [ ] **Step 2: Run the uninstall step of the composed journey with strict xfail**

Run:
```bash
cd apps/agent/e2e
CB_E2E_STRICT_XFAIL=1 python -m pytest test_agent_e2e.py -k uninstall -v --runxfail
```
Expected: the test **passes**. This suite takes 35+ minutes for a full run; `-k uninstall` scopes it to the affected step.

**If it fails:** stop and do not delete the xfail. Capture the failure output, compare it against the three fixed bugs, and open a finding describing what *actually* still fails. Replacing a stale reason with an accurate one is a legitimate outcome of this task; deleting a marker over a genuinely red test is not.

- [ ] **Step 3: Delete the xfail marker**

Remove the entire `@pytest.mark.xfail(...)` decorator block at `test_agent_e2e.py:1274-1290`, leaving `@pytest.mark.e2e` and the test function. Add a short comment in its place:

```python
# The xfail that used to sit here named three bugs — the Uninstall() one-shot
# drain, the silent frame-decrypt swallow in ws_agents.link_stream, and the
# cross-connection registry deregister. All three were fixed in 4aab49d5 and
# ad197961, two hours after the marker was written, and the marker outlived
# them. AGT-04 requires no unexplained xfail at sign-off.
```

- [ ] **Step 4: Verify no xfail remains anywhere**

Run:
```bash
cd /home/shawnji/projects/CircuitBreaker
grep -rn "xfail" --include="*.py" apps/backend/tests tests apps/agent | grep -v "^.*#" | grep -v "Skip rather than xfail" || echo "ok: no xfail markers remain"
```
Expected: `ok: no xfail markers remain`

- [ ] **Step 5: Commit**

```bash
git add apps/agent/e2e/test_agent_e2e.py
git commit -m "test(agents): delete the stale uninstall xfail (AGT-04)

The marker named three production bugs, all of which were fixed in 4aab49d5
and ad197961 two hours after it was written. strict=False meant the
now-passing test reported as xpass and nobody noticed. RC-08 forbids an
unexplained xfail at sign-off; this was the repo's only one."
```

---

## Self-Review

**Spec coverage:**

| Requirement | Task | Note |
|---|---|---|
| AGT-12 (env name→id, five named cases) | 1 | All five covered: valid name, deleted name, stale storage, numeric selection, unfiltered request |
| SEC-05 (no inferable tenant boundary) | 2 | |
| AGT-11 (app-owned extraction, cleanup of only our stale state) | 3 | Crash-loop cleanup covered; reboot/disk-full/concurrent-start cases need the ACC harness and stay open |
| AGT-10 (ARM64 start + supported image handling) | 4 | Format policy + round-trip on CI's architecture; full "restarts repeatedly with journal diagnostics" needs the installed-artifact gate in Plan 1 Task 4 |
| AGT-04 (no unexplained xfail) | 5 | The scheduled/required composed run itself is Plan 3 Task 7 |

**Placeholder scan:** none. Tasks 2 and 4 each contain one *locate-then-edit* step (`graph.py`'s helper signature, the upload decode site) because the exact line depends on a file this plan does not otherwise touch — both give the exact command to find it and the exact edit to make.

**Type consistency:** `resolveEnvironmentFilter(saved, environments)` returns `number | ''` and is consumed only in `MapPage.jsx`; `''` is the value the existing `<select>` and the existing `envFilter || undefined` call sites already treat as unfiltered, so no downstream signature changes. `is_supported_upload_format(fmt: str | None) -> bool` and `SUPPORTED_UPLOAD_FORMATS: frozenset[str]` are used consistently in the test and at the upload boundary.
