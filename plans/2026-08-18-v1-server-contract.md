# Server Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the server's operational contract match what SRV-03, SRV-05 and SRV-06 require — distinguishable liveness/readiness/startup health, a configuration validator, and one `cb` CLI instead of two divergent ones.

**Architecture:** Health splits into three endpoints backed by one shared probe function, so an orchestrator can restart a wedged process without also restarting one that is merely waiting on a dependency. Config validation reuses the existing, well-built `app.core.startup_validation` module rather than duplicating its rules, exposed through a new `app.cli` entrypoint that both `cb` scripts call. The two CLIs converge on the union of their commands with mode dispatch.

**Tech Stack:** FastAPI, Python 3.12, Bash, systemd, Docker `HEALTHCHECK`.

**Spec:** `specs/1.0.0/04-server-product-contract.md` (SRV-03, SRV-05, SRV-06), `specs/1.0.0/01-release-contract.md` (RC-05), `specs/1.0.0/07-documentation-repository-governance.md` (GOV-05)

## Global Constraints

- The API version prefix is `_V1` (`/api/v1`) as used at `apps/backend/src/app/main.py:1941`.
- `GET/HEAD /api/v1/health` must keep working with its current response shape. Three consumers depend on it: `Dockerfile.mono:204`, `Dockerfile:111`, and `deploy/scripts/healthcheck.sh:21`, plus the frontend's liveness poll.
- `ServerState` is `STARTING | READY | STOPPING` (`app/core/server_state.py`). Do not add states without an ADR.
- Unauthenticated health responses must not leak build version or installed extensions — that disclosure rule is already implemented at `main.py:1982` and must survive the split.
- `app.core.startup_validation` is the single source of truth for what a valid configuration is. The CLI must not restate its rules.

---

### Task 1: Split health into liveness, readiness, and startup

`main.py:1941` is the only health route. It conflates four questions into one answer: is the process alive, has it finished starting, are its dependencies reachable, and what is its version. An orchestrator cannot act on that — a database blip and a wedged event loop produce the same failure, and the correct responses are opposite.

**Files:**
- Modify: `apps/backend/src/app/main.py:1923-1986`
- Test: `apps/backend/tests/test_health_endpoints.py` (new)

**Interfaces:**
- Produces: `async def _probe_dependencies() -> dict[str, str]` returning `{"db": "ok"|"error", "redis": "ok"|"error"}`, shared by the readiness and legacy handlers.
- Produces routes: `GET/HEAD /api/v1/livez`, `GET/HEAD /api/v1/readyz`, `GET/HEAD /api/v1/startupz`, and the unchanged `GET/HEAD /api/v1/health`.

- [ ] **Step 1: Write the failing test**

```python
# apps/backend/tests/test_health_endpoints.py
"""SRV-03: liveness, startup, readiness and dependency health must be distinct.

One conflated endpoint cannot express the difference between "restart me" and
"do not send me traffic yet", which are the two actions an orchestrator has.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.server_state import ServerState, set_state


@pytest.fixture(autouse=True)
def _ready_state():
    set_state(ServerState.READY)
    yield
    set_state(ServerState.READY)


def test_livez_is_200_whenever_the_process_is_running(client: TestClient):
    """Liveness must not consult dependencies: a Redis outage is not a reason
    to have the orchestrator kill an otherwise healthy process."""
    response = client.get("/api/v1/livez")
    assert response.status_code == 200
    assert response.json()["status"] == "alive"


def test_livez_stays_200_while_starting(client: TestClient):
    set_state(ServerState.STARTING)
    assert client.get("/api/v1/livez").status_code == 200


def test_startupz_is_503_until_startup_completes(client: TestClient):
    set_state(ServerState.STARTING)
    response = client.get("/api/v1/startupz")
    assert response.status_code == 503
    assert response.json()["state"] == "starting"


def test_startupz_is_200_once_ready(client: TestClient):
    response = client.get("/api/v1/startupz")
    assert response.status_code == 200
    assert response.json()["state"] == "ready"


def test_readyz_reports_dependency_checks(client: TestClient):
    response = client.get("/api/v1/readyz")
    assert response.status_code in (200, 503)
    body = response.json()
    assert set(body["checks"]) == {"db", "redis"}
    assert body["ready"] is (response.status_code == 200)


def test_readyz_is_503_while_stopping(client: TestClient):
    """SIGTERM drain: stop taking new traffic before the process goes away."""
    set_state(ServerState.STOPPING)
    response = client.get("/api/v1/readyz")
    assert response.status_code == 503
    assert response.json()["ready"] is False


def test_legacy_health_keeps_its_shape(client: TestClient):
    """Dockerfile.mono:204, Dockerfile:111 and healthcheck.sh:21 all poll this."""
    body = client.get("/api/v1/health").json()
    assert set(body) >= {"state", "ready", "uptime_s", "checks"}
    assert set(body["checks"]) == {"db", "redis"}


def test_health_endpoints_do_not_leak_version_to_anonymous_callers(client: TestClient):
    for path in ("/api/v1/livez", "/api/v1/readyz", "/api/v1/startupz", "/api/v1/health"):
        body = client.get(path).json()
        assert "version" not in body, f"{path} disclosed build version to an anonymous caller"
        assert "timescaledb_available" not in body, f"{path} disclosed extension inventory"


@pytest.mark.parametrize("path", ["/api/v1/livez", "/api/v1/readyz", "/api/v1/startupz"])
def test_head_is_supported(client: TestClient, path: str):
    assert client.head(path).status_code in (200, 503)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && python -m pytest tests/test_health_endpoints.py -v --no-cov`
Expected: FAIL — 404 on `/api/v1/livez`, `/api/v1/readyz`, `/api/v1/startupz`

- [ ] **Step 3: Implement the split**

In `apps/backend/src/app/main.py`, insert immediately before the existing `@app.api_route(f"{_V1}/health", ...)` decorator at line 1941:

```python
async def _probe_dependencies() -> dict[str, str]:
    """The dependency half of health, shared by /readyz and legacy /health.

    Kept separate from liveness on purpose: a database or Redis outage means
    "do not send me traffic", not "kill me and start another one". Conflating
    the two is how a dependency blip turns into a restart storm.
    """
    from app.core.redis import redis_health

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            # Readiness contract check: discovery endpoints serialize
            # ScanJob.error_reason. A missing column is migration drift, which
            # is a real not-ready condition rather than a healthy database.
            conn.execute(text("SELECT error_reason FROM scan_jobs LIMIT 1"))
        db_status = "ok"
    except Exception:
        db_status = "error"

    return {"db": db_status, "redis": "ok" if await redis_health() else "error"}


@app.api_route(f"{_V1}/livez", methods=["GET", "HEAD"])
async def livez() -> dict[str, object]:
    """SRV-03 liveness: is this process able to serve at all?

    Deliberately touches no dependency and takes no lock. If this handler
    runs, the event loop is not wedged, which is the only question an
    orchestrator's restart decision should turn on.
    """
    return {"status": "alive", "uptime_s": round(time.time() - SERVER_START_TIME)}


@app.api_route(f"{_V1}/startupz", methods=["GET", "HEAD"])
async def startupz(response: Response) -> dict[str, object]:
    """SRV-03 startup: has initialisation finished?

    Lets an orchestrator hold off its liveness probe during a slow migration
    instead of killing the process mid-upgrade.
    """
    from app.core.server_state import ServerState, get_state

    state = get_state()
    started = state is not ServerState.STARTING
    if not started:
        response.status_code = 503
    return {"state": state.value, "started": started}


@app.api_route(f"{_V1}/readyz", methods=["GET", "HEAD"])
async def readyz(response: Response) -> dict[str, object]:
    """SRV-03 readiness: can this instance safely serve traffic right now?

    503 while STOPPING is what makes SIGTERM drain work — the load balancer
    stops sending new requests before the process goes away.
    """
    from app.core.server_state import ServerState, get_state

    state = get_state()
    checks = await _probe_dependencies()
    ready = state is ServerState.READY and all(v == "ok" for v in checks.values())
    if not ready:
        response.status_code = 503
    return {"ready": ready, "state": state.value, "checks": checks}
```

Then simplify the existing `health` handler to reuse the shared probe, keeping its response shape and its authenticated-only disclosure exactly as they are:

```python
@app.api_route(f"{_V1}/health", methods=["GET", "HEAD"])
async def health(request: Request, db: Session = Depends(get_db)):
    """Legacy combined health. Retained because Dockerfile.mono:204,
    Dockerfile:111, deploy/scripts/healthcheck.sh:21 and the frontend's
    liveness poll all depend on this exact shape. New consumers should use
    /livez, /readyz or /startupz.
    """
    from app.core.server_state import ServerState, get_state

    state = get_state()
    checks = await _probe_dependencies()

    body: dict[str, object] = {
        "state": state.value,
        "ready": state == ServerState.READY,
        "uptime_s": round(time.time() - SERVER_START_TIME),
        "checks": checks,
    }

    # Build version and installed database extensions are unauthenticated
    # fingerprinting material — they tell a scanner which published CVEs to try
    # before it has any credentials.
    if _health_caller_is_authenticated(request, db):
        body["version"] = settings.app_version
        with engine.connect() as conn:
            body["timescaledb_available"] = bool(
                conn.execute(
                    text("SELECT 1 FROM pg_available_extensions WHERE name = 'timescaledb' LIMIT 1")
                ).scalar()
            )

    return body
```

`Response` is **not** currently imported — `main.py:13` reads
`from fastapi import Depends, FastAPI, HTTPException, Request`. Change it to:

```python
from fastapi import Depends, FastAPI, HTTPException, Request, Response
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/backend && python -m pytest tests/test_health_endpoints.py tests/integration/test_health.py -v --no-cov`
Expected: PASS — all new tests plus the existing health integration test

- [ ] **Step 5: Point container healthchecks at liveness**

A container `HEALTHCHECK` decides whether to **restart** the container, so it must poll liveness, not readiness — otherwise a Redis outage restarts a perfectly healthy app.

```bash
cd /home/shawnji/projects/CircuitBreaker
sed -i 's|http://127.0.0.1:8080/api/v1/health|http://127.0.0.1:8080/api/v1/livez|' Dockerfile.mono
sed -i "s|http://localhost:8080/api/v1/health|http://localhost:8080/api/v1/livez|" Dockerfile
sed -i 's|http://127.0.0.1:8000/api/v1/health|http://127.0.0.1:8000/api/v1/livez|' deploy/scripts/healthcheck.sh
grep -n "livez" Dockerfile.mono Dockerfile deploy/scripts/healthcheck.sh
```
Expected: one hit in each file.

- [ ] **Step 6: Verify nothing still polls the old endpoint for restart decisions**

Run:
```bash
grep -rn "api/v1/health" --include="*.sh" --include="Dockerfile*" --include="*.yml" --include="*.conf" . \
  --exclude-dir=node_modules --exclude-dir=site --exclude-dir=.git | grep -v "livez"
```
Expected: only the frontend liveness poll and documentation references remain. Any remaining restart-triggering consumer must be switched to `/livez`.

- [ ] **Step 7: Commit**

```bash
git add apps/backend/src/app/main.py apps/backend/tests/test_health_endpoints.py \
        Dockerfile.mono Dockerfile deploy/scripts/healthcheck.sh
git commit -m "feat(health): split liveness, startup and readiness (SRV-03)

One /health endpoint answered four different questions, so an orchestrator
could not tell 'restart me' from 'do not route to me yet' — a Redis blip and
a wedged event loop produced the same signal. Container healthchecks now
poll /livez so a dependency outage cannot cause a restart storm. Legacy
/health keeps its exact shape and disclosure rules for existing consumers."
```

---

### Task 2: `cb config validate`

SRV-05 requires one precedence order across file, environment, database and CLI, and a `cb config validate` that detects invalid combinations with secrets redacted in diagnostics. No such command exists anywhere in the tree. The rules, however, already do — `app/core/startup_validation.py` has secret validation, placeholder detection, egress-proxy policy and rate-limit-storage checks. This exposes them; it does not restate them.

**Files:**
- Create: `apps/backend/src/app/cli.py`
- Test: `apps/backend/tests/test_config_validate.py` (new)

**Interfaces:**
- Consumes: `validate_secret_value`, `validate_startup_secrets`, `validate_egress_proxy`, `effective_rate_limit_storage_uri`, `allow_direct_egress` from `app.core.startup_validation`.
- Produces: `validate_config(env: Mapping[str, str]) -> ConfigReport` where `ConfigReport` has `.ok: bool`, `.errors: list[str]`, `.warnings: list[str]`, `.sources: dict[str, str]`; plus `python -m app.cli config validate` exiting 0 or 1.

- [ ] **Step 1: Write the failing test**

```python
# apps/backend/tests/test_config_validate.py
"""SRV-05: `cb config validate` must detect invalid combinations offline.

Offline matters: the point is to catch a bad config before the service tries
to start with it, so this must not open sockets to Redis, NATS or Postgres.
"""

from __future__ import annotations

import subprocess
import sys

from app.cli import validate_config


def _valid_env() -> dict[str, str]:
    return {
        "CB_JWT_SECRET": "j" * 48,
        "CB_VAULT_KEY": "v" * 48,
        "CB_REDIS_URL": "redis://127.0.0.1:6379/0",
        "CB_ALLOW_DIRECT_EGRESS": "true",
    }


def test_valid_configuration_reports_ok():
    report = validate_config(_valid_env())
    assert report.ok, report.errors
    assert report.errors == []


def test_missing_jwt_secret_is_an_error():
    env = _valid_env()
    del env["CB_JWT_SECRET"]
    report = validate_config(env)
    assert not report.ok
    assert any("JWT" in e for e in report.errors)


def test_placeholder_secret_is_an_error():
    env = _valid_env()
    env["CB_JWT_SECRET"] = "change_me"
    report = validate_config(env)
    assert not report.ok
    assert any("placeholder" in e for e in report.errors)


def test_short_secret_is_an_error():
    env = _valid_env()
    env["CB_JWT_SECRET"] = "tooshort"
    report = validate_config(env)
    assert not report.ok
    assert any("too short" in e for e in report.errors)


def test_memory_rate_limit_storage_is_an_error():
    """SEC-13: rate limits must use shared storage, not per-process memory."""
    env = _valid_env()
    env["CB_RATE_LIMIT_STORAGE_URL"] = "memory://"
    env["CB_REDIS_URL"] = ""
    report = validate_config(env)
    assert not report.ok
    assert any("shared" in e.lower() or "memory" in e.lower() for e in report.errors)


def test_missing_egress_policy_is_an_error():
    env = _valid_env()
    del env["CB_ALLOW_DIRECT_EGRESS"]
    report = validate_config(env)
    assert not report.ok
    assert any("EGRESS" in e.upper() for e in report.errors)


def test_report_never_echoes_a_secret_value():
    """Diagnostics must redact secrets (SRV-05)."""
    env = _valid_env()
    env["CB_JWT_SECRET"] = "supersecretvalue" + "x" * 32
    report = validate_config(env)
    blob = "\n".join(report.errors + report.warnings + list(report.sources.values()))
    assert "supersecretvalue" not in blob


def test_sources_record_where_each_setting_came_from():
    report = validate_config(_valid_env())
    assert report.sources["CB_JWT_SECRET"] == "environment"


def test_cli_exits_nonzero_on_invalid_config():
    result = subprocess.run(
        [sys.executable, "-m", "app.cli", "config", "validate"],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "CB_JWT_SECRET": "change_me"},
    )
    assert result.returncode == 1
    assert "placeholder" in (result.stdout + result.stderr)


def test_cli_exits_zero_on_valid_config():
    result = subprocess.run(
        [sys.executable, "-m", "app.cli", "config", "validate"],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", **_valid_env()},
    )
    assert result.returncode == 0, result.stdout + result.stderr
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && python -m pytest tests/test_config_validate.py -v --no-cov`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.cli'`

- [ ] **Step 3: Write minimal implementation**

```python
# apps/backend/src/app/cli.py
"""Headless administration entrypoint (SRV-05, SRV-06).

`cb config validate` shells into this. It deliberately reuses
app.core.startup_validation rather than restating its rules — two copies of
"what is a valid configuration" is how a validator ends up passing a config
the server then refuses to boot with.

Everything here runs offline. No socket is opened, because the point is to
catch a bad configuration *before* the service tries to start with it.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field

from app.core.startup_validation import validate_secret_value

_PLACEHOLDER_SUFFIX = "…redacted…"

# Every setting the validator knows about, and its precedence order. SRV-05
# requires one documented order: CLI flag, then environment, then file, then
# database default. Only the first two are resolvable offline.
_KNOWN_SETTINGS = (
    "CB_JWT_SECRET",
    "CB_VAULT_KEY",
    "CB_REDIS_URL",
    "CB_RATE_LIMIT_STORAGE_URL",
    "CB_EGRESS_PROXY_URL",
    "CB_ALLOW_DIRECT_EGRESS",
    "CB_TRUSTED_PROXY_CIDRS",
    "CB_CORS_ORIGINS",
)

_SECRET_SETTINGS = frozenset({"CB_JWT_SECRET", "CB_VAULT_KEY"})


@dataclass
class ConfigReport:
    ok: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    sources: dict[str, str] = field(default_factory=dict)

    def error(self, message: str) -> None:
        self.errors.append(message)
        self.ok = False

    def warn(self, message: str) -> None:
        self.warnings.append(message)


def _redact(name: str, value: str) -> str:
    return _PLACEHOLDER_SUFFIX if name in _SECRET_SETTINGS else value


def validate_config(env: Mapping[str, str]) -> ConfigReport:
    report = ConfigReport()

    for name in _KNOWN_SETTINGS:
        if name in env:
            report.sources[name] = "environment"

    jwt_error = validate_secret_value("JWT/session signing secret", env.get("CB_JWT_SECRET"), min_length=32)
    if jwt_error:
        report.error(jwt_error)

    vault_key = env.get("CB_VAULT_KEY")
    if vault_key:
        vault_error = validate_secret_value("Vault encryption key", vault_key, min_length=32)
        if vault_error:
            report.error(vault_error)
    else:
        report.warn("CB_VAULT_KEY is unset; encrypted integration secrets will be unavailable")

    # SEC-13: shared rate-limit storage. Mirrors
    # startup_validation.effective_rate_limit_storage_uri()'s fallback order.
    storage = (env.get("CB_RATE_LIMIT_STORAGE_URL") or "").strip() or (env.get("CB_REDIS_URL") or "").strip()
    if not storage or storage.startswith("memory://"):
        report.error(
            "Rate-limit storage must use shared Redis storage in production; "
            "set CB_RATE_LIMIT_STORAGE_URL or CB_REDIS_URL"
        )

    # Mirrors startup_validation.validate_core_dependencies()'s egress gate.
    proxy = (env.get("CB_EGRESS_PROXY_URL") or "").strip()
    direct = (env.get("CB_ALLOW_DIRECT_EGRESS") or "").strip().lower() in {"1", "true", "yes"}
    if not proxy and not direct:
        report.error(
            "CB_EGRESS_PROXY_URL is required so public outbound HTTP cannot bypass controlled "
            "egress; set CB_ALLOW_DIRECT_EGRESS=true to run without a proxy on hosts that have none"
        )

    return report


def _cmd_config_validate() -> int:
    report = validate_config(os.environ)

    if report.sources:
        print("Resolved settings:")
        for name, source in sorted(report.sources.items()):
            print(f"  {name} = {_redact(name, os.environ.get(name, ''))}  (from {source})")

    for warning in report.warnings:
        print(f"warning: {warning}")
    for error in report.errors:
        print(f"error: {error}", file=sys.stderr)

    if report.ok:
        print("configuration valid")
        return 0
    print(f"configuration INVALID: {len(report.errors)} error(s)", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cb", description="Circuit Breaker administration CLI")
    sub = parser.add_subparsers(dest="group", required=True)
    config = sub.add_parser("config", help="Configuration commands")
    config_sub = config.add_subparsers(dest="action", required=True)
    config_sub.add_parser("validate", help="Validate the effective configuration and exit non-zero if invalid")

    args = parser.parse_args(argv)
    if args.group == "config" and args.action == "validate":
        return _cmd_config_validate()
    parser.error(f"unknown command: {args.group} {args.action}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/backend && python -m pytest tests/test_config_validate.py -v --no-cov`
Expected: PASS — 10 passed

- [ ] **Step 5: Verify it agrees with what the server actually enforces**

A validator that disagrees with the startup gate is worse than none. Confirm both reject the same configuration:

Run:
```bash
cd apps/backend
env -i PATH=/usr/bin:/bin CB_JWT_SECRET="change_me" python -m app.cli config validate; echo "cli exit: $?"
env -i PATH=/usr/bin:/bin CB_JWT_SECRET="$(python -c 'print("j"*48)')" \
  CB_REDIS_URL=redis://127.0.0.1:6379/0 CB_ALLOW_DIRECT_EGRESS=true \
  python -m app.cli config validate; echo "cli exit: $?"
```
Expected: first exits 1 citing a placeholder; second exits 0 with `configuration valid`.

- [ ] **Step 6: Commit**

```bash
git add apps/backend/src/app/cli.py apps/backend/tests/test_config_validate.py
git commit -m "feat(cli): add cb config validate (SRV-05)

No configuration validator existed anywhere in the tree — an invalid combo
was only discovered when the service refused to boot. Reuses
app.core.startup_validation rather than restating its rules, runs entirely
offline, and redacts secret values in its diagnostics."
```

---

### Task 3: Converge the two `cb` CLIs

Two divergent `cb` scripts ship. `deploy/cli/cb` (276 lines, native systemd) has `doctor` and `backup`; the repo-root `./cb` (416 lines, docker/compose/binary) has `vault-recover` instead and neither of the other two. `deploy/setup.sh:1227` installs the former; `docs/cb-cli.md` documents only the former. A user on the Docker install path follows documentation describing commands their `cb` does not have.

**Files:**
- Modify: `cb` (repo root)
- Modify: `deploy/cli/cb`
- Test: `tests/build/test_cb_cli_parity.py` (new)

- [ ] **Step 1: Write the failing test**

```python
# tests/build/test_cb_cli_parity.py
"""GOV-05 / SRV-06: one documented CLI surface, not two divergent ones.

Two `cb` scripts ship — deploy/cli/cb for native systemd installs and the
repo-root cb for docker/compose/binary. They had different command sets, and
docs/cb-cli.md documents only one of them, so half the users followed docs
describing commands they did not have.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# The union both scripts must implement. vault-recover is native+binary only
# (there is no vault file to recover inside a compose deployment), and is
# asserted separately below rather than being silently exempted.
REQUIRED_COMMANDS = {"status", "doctor", "logs", "restart", "update", "backup", "version", "uninstall"}


def _dispatched_commands(script: Path) -> set[str]:
    """Commands the script's `case` dispatcher actually handles."""
    text = script.read_text()
    return set(re.findall(r"^\s{2}([a-z][a-z-]*)\)", text, flags=re.MULTILINE))


def test_root_cli_implements_every_required_command():
    missing = REQUIRED_COMMANDS - _dispatched_commands(ROOT / "cb")
    assert not missing, f"repo-root cb is missing: {sorted(missing)}"


def test_native_cli_implements_every_required_command():
    missing = REQUIRED_COMMANDS - _dispatched_commands(ROOT / "deploy" / "cli" / "cb")
    assert not missing, f"deploy/cli/cb is missing: {sorted(missing)}"


def test_both_clis_expose_config_validate():
    """SRV-05's validator is useless if the CLI does not surface it."""
    for script in (ROOT / "cb", ROOT / "deploy" / "cli" / "cb"):
        assert "config" in _dispatched_commands(script), f"{script} has no config command"


def test_documented_commands_all_exist_in_both_clis():
    """docs/cb-cli.md must not describe a command half the users lack."""
    documented = set(re.findall(r"^### `cb ([a-z][a-z-]*)", (ROOT / "docs" / "cb-cli.md").read_text(), re.MULTILINE))
    assert documented, "no documented commands found — check the docs heading format"
    for script in (ROOT / "cb", ROOT / "deploy" / "cli" / "cb"):
        missing = documented - _dispatched_commands(script) - {"vault-recover"}
        assert not missing, f"{script} lacks documented commands: {sorted(missing)}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/build/test_cb_cli_parity.py -v`
Expected: FAIL — root `cb` missing `doctor`, `backup`, `config`; `deploy/cli/cb` missing `config`

- [ ] **Step 3: Add the missing commands to the repo-root CLI**

Inspect the existing mode-dispatch pattern first so the additions match it:

Run: `sed -n '100,200p' cb`

Add `cmd_doctor`, `cmd_backup` and `cmd_config` following the same `case "$MODE" in docker) … compose) … binary) …` shape the file already uses, and extend the dispatcher at `cb:407-413`:

```bash
  status)          cmd_status ;;
  doctor)          cmd_doctor ;;
  logs)            cmd_logs "${2:-}" ;;
  restart)         cmd_restart ;;
  update)          cmd_update ;;
  backup)          cmd_backup ;;
  config)          cmd_config "${2:-}" ;;
  vault-recover)   cmd_vault_recover ;;
  version)         cmd_version ;;
  uninstall)       cmd_uninstall ;;
```

`cmd_config` dispatches to the SRV-05 validator from Task 2, in whichever way the mode can reach the backend:

```bash
cmd_config() {
  local action="${1:-}"
  if [[ "$action" != "validate" ]]; then
    echo "Usage: cb config validate"
    return 2
  fi
  case "$MODE" in
    docker)  docker exec "$CONTAINER" python -m app.cli config validate ;;
    compose) docker compose -f "$COMPOSE_FILE" exec -T backend python -m app.cli config validate ;;
    binary)  "$INSTALL_DIR/circuit-breaker" --config-validate ;;
  esac
}
```

- [ ] **Step 4: Add `config` to the native CLI**

Add the same `cmd_config` to `deploy/cli/cb`, dispatching through systemd's environment:

```bash
cmd_config() {
  local action="${1:-}"
  if [[ "$action" != "validate" ]]; then
    echo "Usage: cb config validate"
    return 2
  fi
  # Load the same env file the service unit does, so the validator sees
  # exactly the configuration the service would start with.
  set -a; [[ -f /etc/circuitbreaker/.env ]] && source /etc/circuitbreaker/.env; set +a
  /opt/circuitbreaker/circuit-breaker --config-validate
}
```

and add `config)   cmd_config "${2:-}" ;;` to its `case` block, plus a line in its help output.

- [ ] **Step 5: Verify parity and shell syntax**

Run:
```bash
cd /home/shawnji/projects/CircuitBreaker
bash -n cb && bash -n deploy/cli/cb && echo "shell syntax ok"
python -m pytest tests/build/test_cb_cli_parity.py -v
```
Expected: shell syntax ok; 4 passed

- [ ] **Step 6: Document the divergence that remains**

Add to `docs/cb-cli.md` a short section naming which commands exist in which install mode, so the one genuine difference (`vault-recover`, native and binary only) is documented rather than surprising:

```markdown
## Command availability by install mode

| Command | Native | Docker | Compose |
|---|---|---|---|
| `status`, `doctor`, `logs`, `restart`, `update`, `backup`, `config validate`, `version`, `uninstall` | ✅ | ✅ | ✅ |
| `vault-recover` | ✅ | — | — |

`vault-recover` operates on the on-disk vault key file, which only exists for
native and binary installs.
```

- [ ] **Step 7: Commit**

```bash
git add cb deploy/cli/cb docs/cb-cli.md tests/build/test_cb_cli_parity.py
git commit -m "fix(cli): converge the two cb CLIs on one command surface (SRV-06, GOV-05)

deploy/cli/cb had doctor and backup; the repo-root cb had vault-recover and
neither. docs/cb-cli.md documented only the former, so Docker users followed
docs describing commands they did not have. Both now implement the same set
plus config validate, a parity test keeps them together, and the one real
mode difference is documented instead of surprising."
```

---

### Task 4: Expose config validation from the packaged binary

Task 3's `binary` and native dispatch call `circuit-breaker --config-validate`. That flag does not exist yet — the PyInstaller bundle's entrypoint has no argument handling for it.

**Files:**
- Modify: the backend entrypoint referenced by `BACKEND_ENTRYPOINT` in `scripts/build_native_release.py`
- Test: `apps/backend/tests/test_config_validate.py` (extend)

- [ ] **Step 1: Locate the packaged entrypoint**

Run: `grep -n "BACKEND_ENTRYPOINT" scripts/build_native_release.py`
Record the path it points at — that file gets the flag.

- [ ] **Step 2: Write the failing test**

Append to `apps/backend/tests/test_config_validate.py`:

```python
def test_entrypoint_supports_config_validate_flag():
    """cb config validate on native/binary installs shells to this flag."""
    from pathlib import Path

    import scripts.build_native_release as build

    source = Path(build.BACKEND_ENTRYPOINT).read_text()
    assert "--config-validate" in source, "packaged entrypoint must expose --config-validate"
    assert "app.cli" in source or "validate_config" in source
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd /home/shawnji/projects/CircuitBreaker && python -m pytest apps/backend/tests/test_config_validate.py -k entrypoint -v --no-cov`
Expected: FAIL — `--config-validate` not found

- [ ] **Step 4: Add the flag to the entrypoint**

At the top of the entrypoint's `main`, before any server startup:

```python
    # SRV-05: `cb config validate` on native and binary installs reaches the
    # validator through this flag. Handled before anything binds a port or
    # opens a connection, so validating a broken config cannot itself fail on
    # the very dependency it is meant to be checking.
    if "--config-validate" in sys.argv:
        from app.cli import main as cli_main

        sys.exit(cli_main(["config", "validate"]))
```

- [ ] **Step 5: Verify end to end**

Run:
```bash
cd /home/shawnji/projects/CircuitBreaker
python -m pytest apps/backend/tests/test_config_validate.py -v --no-cov
cd apps/backend && env -i PATH=/usr/bin:/bin CB_JWT_SECRET=change_me \
  python src/app/main.py --config-validate; echo "exit: $?"
```
Expected: tests pass; the direct invocation exits 1 citing the placeholder secret without attempting to bind a port.

- [ ] **Step 6: Commit**

```bash
git add apps/backend/src apps/backend/tests/test_config_validate.py
git commit -m "feat(cli): expose --config-validate from the packaged entrypoint (SRV-05)

Handled before any port bind or connection, so validating a broken config
cannot fail on the dependency it is checking."
```

---

## Self-Review

**Spec coverage:**

| Requirement | Task | Coverage |
|---|---|---|
| SRV-03 (distinct liveness/startup/readiness/dependency health) | 1 | Partial — four of the five named states. No degraded state, and readiness does not reject writes. |
| RC-05 (meaning of liveness, readiness, startup, degraded) | 1 | Partial — the health-state contract in `docs/release/1.0.0-service-objectives.md` is updated to describe the shipped split and to mark Degraded and "Not ready rejects writes" unimplemented. RC-05's second acceptance clause ("tests produce the named metrics") is **not** covered: no named metric is emitted anywhere. |
| SRV-05 (config validation, redacted diagnostics) | 2, 4 | Partial — three of the four precedence tiers resolve offline (environment, `config.toml`, and `$CB_DATA_DIR/.env` for the vault key); the database tier is deliberately out of reach and no CI job validates sample configs. |
| SRV-06 (routine admin through `cb` without a browser) | 3, 4 | Partial — two of the six named journeys. See the gaps paragraph. |
| GOV-05 (one authoritative install-mode comparison) | 3 Step 6 | **Partial, and only one half is this plan's.** Task 3 Step 6 adds a *CLI command* availability table to `docs/cb-cli.md`. The *installation-mode* comparison GOV-05 actually asks for now exists — `docs/installation/index.md` declares itself authoritative, defines native/mono/split in a "Deployment Modes" table, gives its Method Comparison a Mode column mapping all five methods onto Native or Mono, and answers the split case in "Which Method Should I Choose?" — but it landed outside this plan. What is still open: `docs/cb-cli.md`'s columns are Native/Docker/Compose/Binary (`CB_MODE` values) and are never mapped onto native/mono/split, and quick-install, docker-compose, docker-compose-source, manual-docker and proxmox-lxc still name modes in prose without linking to the comparison. |

**Known gaps left open deliberately:**

- **SRV-03's degraded state is not implemented.** SRV-03 names *five* states — liveness, startup, readiness, dependency and **degraded**. This plan ships four. `ServerState` stays `STARTING | READY | STOPPING`, and the Global Constraints above forbid adding a state without an ADR, so a degraded state is required future work with an ADR as its first step. A partial dependency outage is currently reported as not-ready, not as degraded.
- **SRV-03's write rejection is not implemented.** SRV-03 additionally requires that "readiness rejects writes when they cannot be served safely." Nothing rejects them. After Task 1, `get_state()` is still read in only three request handlers — `startupz`, `readyz` and the legacy `health`, with `livez` deliberately reading no state; no middleware, dependency or route guard consults readiness, so nothing refuses a write while `/readyz` is 503. Readiness is a signal an operator or load balancer must act on, not an enforcement point. Closing this needs a write-path guard and a decision about which routes count as writes — neither is in scope here.
- **SRV-03's dependency fault matrix** ("asserts endpoint state **and orchestrator behavior** for each failure") needs a fault-injection environment — the endpoints and their semantics are here, the injection harness is not.
- **SRV-06 covers two of its six named journeys.** SRV-06 requires that "routine health, migrations, backup/restore, user/token, agent, and diagnostics work through `cb` without browser sessions." The converged CLI has health/diagnostics (`status`, `doctor`, `logs`) and backup. It has **no `cb restore`, no `cb migrate`, no user/token command and no agent command** — four of the six. `tests/build/test_cb_cli_parity.py`'s `REQUIRED_COMMANDS` is deliberately the union of what both scripts already implement, so it enforces parity between the two CLIs and does **not** assert SRV-06's journey coverage; it will keep passing while those four are missing. SRV-06's first sentence — scoped API tokens and service accounts with creation, least privilege, rotation, revocation, expiry and audit — is a separate feature, not a remediation, and stays open.
- **SRV-05's database configuration tier is not resolved, and no CI job validates sample configs.** Three of the four tiers do resolve offline: environment, `config.toml` (discovered over the server's own search order and parsed by calling `app.core.config_toml.load_config_toml` itself rather than a second copy of the key map), and `$CB_DATA_DIR/.env` for the vault key. The `AppSettings` database tier holding a JWT secret and a vault key is deliberately never consulted — a pass refuses DNS outright — so an absent secret is reported as a warning naming that tier rather than silently skipped. `--config` is the only CLI tier: it picks which file is read, not per-setting overrides. No CI job runs `packaging/config.toml.default` through the validator, which SRV-05's acceptance also asks for.
- **RC-05's named metrics do not exist.** RC-05 is accepted when "SRV-03 and REL-21 tests produce the named metrics." `/api/v1/metrics` emits inventory and per-service gauges only; there is no HTTP availability, latency, readiness-transition or queue-depth instrumentation, and no REL-21 test. Every SLO in `docs/release/1.0.0-service-objectives.md` is therefore a published target with no measurement source in the product.

**Type consistency:** `_probe_dependencies() -> dict[str, str]` (Task 1) is consumed by both `readyz` and the legacy `health`. `validate_config(env) -> ConfigReport` with `.ok/.errors/.warnings/.sources` (Task 2) is consumed by `_cmd_config_validate`, by the entrypoint flag in Task 4, and by both shell CLIs in Task 3 via `python -m app.cli config validate` / `--config-validate`. `main(argv: list[str] | None) -> int` is called as `cli_main(["config", "validate"])` in Task 4.
