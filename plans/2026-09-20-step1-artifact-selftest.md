# Step 1 — Artifact Self-Test Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make it impossible to build, publish, or install a Circuit Breaker binary that does not contain the application it claims to serve.

**Architecture:** One new entrypoint flag, `--selftest`, that resolves the ASGI target exactly as uvicorn does and imports every worker module and the Alembic environment. It is then wired at three points that fail for different reasons: inside `build_native_release.py` before the bundle is staged, inside `artifact-smoke.yml` after the `.deb` is installed on a clean host, and inside `cb doctor` so an operator runs the same assertion the release gate runs.

**Tech Stack:** Python 3.12, `importlib`, argparse, pytest, PyInstaller, GitHub Actions, Bash.

**Spec:** `docs/design/2026-09-20-install-experience-and-release-verification-design.md` §8, §9, §10.

## Global Constraints

- Python 3.12. snake_case, full type annotations — mypy runs with `disallow_untyped_defs`. Docstrings on classes and public functions.
- **No placeholders.** No `TODO`, bare `pass`, or `NotImplementedError`.
- **Backward compatible.** `--selftest` is a new flag alongside existing ones; nothing is renamed or removed.
- **Air-gap is first-class.** `--selftest` must make no outbound request, touch no database, and require no Redis, NATS or network. It runs on an air-gapped host and in a container with no services.
- Never hardcode credentials, tokens, signing material or vault keys — including in CI workflows and fixtures.
- Commits: `feat:` / `fix:` / `chore:` / `docs:`.
- This plan modifies `apps/backend/src/app`, so the pre-push gate is **`make verify-full`**, not `make verify`. `make verify` skips the backend unit suite entirely.
- Never lower the coverage gate to make a build green.

## Background an implementer needs

`apps/backend/src/app/start.py` is the frozen binary's entrypoint. At line 322 it resolves `--version` and returns:

```python
args = build_parser().parse_args(argv)
if args.version:
    print(resolve_app_version())
    return 0
```

`resolve_app_version` is imported at line 60 from `app.core.config` and reads a `VERSION` file that PyInstaller embeds with `--add-data`. The function returns **before** line 370 (`from app.startup.schema import run_alembic_upgrade`) and line 380 (`uvicorn.run("app.main:app", ...)`).

That is why v0.4.2 passed every gate while containing no application: `--version` is the one code path that cannot observe whether the application was packaged.

PyInstaller builds from a static import graph. A module named only by a string — `"app.main:app"` handed to uvicorn, Alembic revisions loaded by path — is invisible to it and gets dropped. `scripts/build_native_release.py` carries three collectors that exist to recover from this, each written after a shipped failure.

## File Structure

| File | Responsibility |
|---|---|
| `apps/backend/src/app/startup/selftest.py` | The check itself: resolve the ASGI app, import every worker module, import the Alembic environment. Pure function, returns a result object. No I/O beyond imports. |
| `apps/backend/src/app/start.py` | Adds `--selftest` to the parser and dispatches to the above. Adds `ASGI_TARGET` beside the `uvicorn.run` call. |
| `apps/backend/src/app/workers/main.py` | Adds `WORKER_MODULES`, the type→module mapping that `_dispatch`'s if-chain currently encodes only as control flow. |
| `apps/backend/tests/test_selftest.py` | Both directions: passes on a correct tree, fails when a named module is unimportable. |
| `tests/build/test_selftest_targets_match_runtime.py` | `ASGI_TARGET` equals the literal uvicorn is actually given; `WORKER_MODULES` covers every branch in `_dispatch`. |
| `scripts/build_native_release.py` | Runs `--selftest` on the freshly built binary before staging. |
| `.github/workflows/artifact-smoke.yml` | Runs `--selftest` on the installed binary. |
| `deploy/cli/cb` | `cb doctor` gains a self-test check. |

---

### Task 1: `WORKER_MODULES` — make the worker mapping data

**Files:**
- Modify: `apps/backend/src/app/workers/main.py`
- Create: `tests/build/test_selftest_targets_match_runtime.py` (first half; second half added in Task 2)

**Interfaces:**
- Produces: `app.workers.main.WORKER_MODULES: dict[str, str]`, mapping worker type name → fully qualified module path. Task 3's `selftest.py` imports it.

**Why this task exists.** `_dispatch` is an if-chain. The mapping from worker type to module lives only in control flow, so nothing can enumerate it. `--selftest` needs that enumeration, and a hand-copied second list would drift the first time a worker is added — which is the exact failure mode this whole plan exists to close.

- [ ] **Step 1: Write the failing test**

Create `tests/build/test_selftest_targets_match_runtime.py`:

```python
"""The self-test must check what the runtime actually loads.

A self-test naming a hand-copied list of modules is a second source of truth,
and the first time the two disagree the gate passes on a binary the runtime
cannot start. That is the v0.4.2 failure with an extra step, so both halves of
what --selftest checks are pinned to the code that does the loading.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_SRC = REPO_ROOT / "apps" / "backend" / "src"
WORKERS_MAIN = BACKEND_SRC / "app" / "workers" / "main.py"

sys.path.insert(0, str(BACKEND_SRC))


def _dispatch_branch_types() -> set[str]:
    """Every worker type string compared against in `_dispatch`.

    Read from the AST rather than by importing, so this suite stays runnable
    without the backend's dependency tree installed.
    """
    tree = ast.parse(WORKERS_MAIN.read_text(encoding="utf-8"), filename=str(WORKERS_MAIN))
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != "_dispatch":
            continue
        for inner in ast.walk(node):
            if not isinstance(inner, ast.Compare) or len(inner.comparators) != 1:
                continue
            left, right = inner.left, inner.comparators[0]
            if (
                isinstance(left, ast.Name)
                and left.id == "kind"
                and isinstance(right, ast.Constant)
                and isinstance(right.value, str)
            ):
                found.add(right.value)
    return found


def test_worker_modules_covers_every_dispatch_branch() -> None:
    from app.workers.main import WORKER_MODULES

    branches = _dispatch_branch_types()
    assert branches, (
        "No `kind == \"...\"` comparisons were found in _dispatch. Either the "
        "function was restructured or this parser is broken; either way the "
        "assertion below would pass vacuously."
    )
    missing = branches - set(WORKER_MODULES)
    extra = set(WORKER_MODULES) - branches
    assert not missing, (
        f"_dispatch handles worker types {sorted(missing)} that WORKER_MODULES "
        "does not list, so --selftest would not check the module they load. "
        "Add them to WORKER_MODULES."
    )
    assert not extra, (
        f"WORKER_MODULES lists {sorted(extra)}, which _dispatch cannot dispatch. "
        "Remove them, or add the dispatch branch."
    )
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/build/test_selftest_targets_match_runtime.py -v`

Expected: FAIL with `ImportError: cannot import name 'WORKER_MODULES'`.

- [ ] **Step 3: Add `WORKER_MODULES` to `apps/backend/src/app/workers/main.py`**

Insert directly after the existing `_TYPE_MAP` block (which ends at line 20):

```python
# The module each worker type loads, as data rather than as control flow.
#
# `_dispatch` below is an if-chain, so the mapping it encodes cannot be
# enumerated by anything else — and `--selftest` has to enumerate it, because a
# worker module missing from the frozen binary fails at dispatch time on a
# customer's host rather than in the build. Keeping this beside _TYPE_MAP and
# pinning the two together in
# tests/build/test_selftest_targets_match_runtime.py means a new worker cannot
# be added to one and forgotten in the other.
#
# Keys are the resolved type names _dispatch compares against — not _TYPE_MAP's
# numeric aliases, which resolve to these before dispatch.
WORKER_MODULES: dict[str, str] = {
    "discovery": "app.workers.discovery",
    "notification": "app.workers.notification_worker",
    "telemetry": "app.workers.telemetry_collector",
    "integration": "app.workers.integration_worker",
    "monitor_scheduler": "app.workers.monitor_scheduler",
    "monitor_poll": "app.workers.monitor_poll_worker",
    "monitor_probe_dispatch": "app.workers.monitor_probe_dispatch",
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/build/test_selftest_targets_match_runtime.py -v`

Expected: PASS.

- [ ] **Step 5: Prove the guard has teeth**

Temporarily delete the `"integration"` line from `WORKER_MODULES`, re-run, confirm the failure names `['integration']`, then restore it.

Run: `pytest tests/build/test_selftest_targets_match_runtime.py -v`

Expected: FAIL naming `integration` while removed; PASS after restoring.

- [ ] **Step 6: Commit**

```bash
git add apps/backend/src/app/workers/main.py tests/build/test_selftest_targets_match_runtime.py
git commit -m "feat: enumerate worker modules as data, not control flow

_dispatch's if-chain is the only record of which module each worker type
loads, so nothing could enumerate it. --selftest needs that enumeration, and a
hand-copied second list would drift. WORKER_MODULES is pinned to _dispatch's
branches by an AST test.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `ASGI_TARGET` — pin the self-test to what uvicorn is given

**Files:**
- Modify: `apps/backend/src/app/start.py`
- Modify: `tests/build/test_selftest_targets_match_runtime.py` (add the second half)

**Interfaces:**
- Produces: `app.start.ASGI_TARGET: str`, the `"<module>:<attribute>"` string. Task 3's `selftest.py` imports it.

**Critical constraint.** `scripts/build_native_release.py::_collect_asgi_target_hidden_imports` parses `start.py`'s AST and **requires the first argument of `uvicorn.run` to be an `ast.Constant` string**, raising `SystemExit` otherwise. So `uvicorn.run("app.main:app", ...)` must keep its string literal. Do **not** replace it with `uvicorn.run(ASGI_TARGET, ...)` — that breaks the build. Instead define the constant separately and pin the two together with a test.

- [ ] **Step 1: Write the failing test**

Append to `tests/build/test_selftest_targets_match_runtime.py`:

```python
START_PY = BACKEND_SRC / "app" / "start.py"


def _uvicorn_target_literal() -> str:
    """The ASGI target string literally handed to uvicorn.run in start.py."""
    tree = ast.parse(START_PY.read_text(encoding="utf-8"), filename=str(START_PY))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "uvicorn"
            and func.attr == "run"
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            return node.args[0].value
    raise AssertionError(
        "No `uvicorn.run(\"<module>:<attr>\", ...)` call with a string literal "
        "was found in start.py. scripts/build_native_release.py's "
        "_collect_asgi_target_hidden_imports requires that literal and raises "
        "SystemExit without it, so the build is already broken if this fires."
    )


def test_asgi_target_constant_matches_what_uvicorn_is_given() -> None:
    from app.start import ASGI_TARGET

    literal = _uvicorn_target_literal()
    assert ASGI_TARGET == literal, (
        f"ASGI_TARGET is {ASGI_TARGET!r} but uvicorn.run is given {literal!r}. "
        "--selftest would verify a different application from the one the "
        "binary serves, which is a gate passing for the wrong reason — exactly "
        "the v0.4.2 shape."
    )


def test_asgi_target_is_in_uvicorn_import_string_form() -> None:
    from app.start import ASGI_TARGET

    module, separator, attribute = ASGI_TARGET.partition(":")
    assert separator and module and attribute, (
        f"ASGI_TARGET {ASGI_TARGET!r} is not in uvicorn's required "
        '"<module>:<attribute>" form.'
    )
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/build/test_selftest_targets_match_runtime.py -v`

Expected: the two new tests FAIL with `ImportError: cannot import name 'ASGI_TARGET'`.

- [ ] **Step 3: Add the constant to `apps/backend/src/app/start.py`**

Insert immediately after the `import uvicorn  # noqa: E402` line (line 58) and before the `from app.core.config import resolve_app_version` line:

```python
# The ASGI application this binary serves, as uvicorn's import string.
#
# Duplicated deliberately rather than passed as a variable to uvicorn.run
# below: scripts/build_native_release.py::_collect_asgi_target_hidden_imports
# parses this file's AST and requires that call's first argument to be a string
# literal, raising SystemExit otherwise, because PyInstaller's static import
# graph cannot see a module named by a variable any more than by a string.
#
# The duplication is safe because it is pinned:
# tests/build/test_selftest_targets_match_runtime.py fails if this constant and
# that literal ever disagree. Both are needed — the literal so the build can
# find the module, this constant so --selftest can load it at runtime, where
# there is no source tree to parse.
ASGI_TARGET = "app.main:app"
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/build/test_selftest_targets_match_runtime.py -v`

Expected: 4 passed.

- [ ] **Step 5: Prove the pin has teeth**

Temporarily change `ASGI_TARGET` to `"app.notmain:app"`, re-run, confirm the failure names both strings, then restore.

Expected: FAIL while changed; PASS after restoring.

- [ ] **Step 6: Commit**

```bash
git add apps/backend/src/app/start.py tests/build/test_selftest_targets_match_runtime.py
git commit -m "feat: pin the ASGI target constant to the literal uvicorn is given

--selftest must load the application the binary actually serves. The literal
stays at the uvicorn.run call because the build's AST collector requires it;
the constant exists because the frozen binary has no source tree to parse. A
test fails if they diverge.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: The self-test itself

**Files:**
- Create: `apps/backend/src/app/startup/selftest.py`
- Create: `apps/backend/tests/test_selftest.py`

**Interfaces:**
- Consumes: `app.start.ASGI_TARGET` (Task 2), `app.workers.main.WORKER_MODULES` (Task 1).
- Produces:
  - `run_selftest() -> SelfTestResult`
  - `SelfTestResult` — a frozen dataclass with `ok: bool`, `checked: list[str]`, `failure: str | None`.
  - `format_result(result: SelfTestResult) -> str` — the one-line human summary.

- [ ] **Step 1: Write the failing test**

Create `apps/backend/tests/test_selftest.py`:

```python
"""--selftest must fail for the reason v0.4.2 failed, and pass otherwise.

v0.4.2 shipped a frozen binary with no `app.main` in it. Every release gate was
green, because the only execution any of them performed was `--version`, which
start.py resolves from an embedded file and returns on before the application
is ever imported.

So both directions are asserted here. A self-test that only ever passes is the
gate that let v0.4.2 through, wearing a different name.
"""

from __future__ import annotations

import pytest

from app.startup.selftest import SelfTestResult, format_result, run_selftest


def test_selftest_passes_on_a_correct_tree() -> None:
    result = run_selftest()
    assert result.ok, f"self-test failed on a correct tree: {result.failure}"
    assert result.failure is None
    assert "app.main" in result.checked
    assert "app.workers.discovery" in result.checked


def test_selftest_fails_when_the_asgi_module_is_unimportable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exact v0.4.2 shape: the application is not in the bundle."""
    monkeypatch.setattr("app.startup.selftest.ASGI_TARGET", "app.definitely_not_here:app")
    result = run_selftest()
    assert not result.ok
    assert result.failure is not None
    assert "app.definitely_not_here" in result.failure


def test_selftest_fails_when_a_worker_module_is_unimportable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.startup import selftest as selftest_module

    monkeypatch.setattr(
        selftest_module,
        "WORKER_MODULES",
        {**selftest_module.WORKER_MODULES, "phantom": "app.workers.phantom_worker"},
    )
    result = run_selftest()
    assert not result.ok
    assert result.failure is not None
    assert "app.workers.phantom_worker" in result.failure


def test_selftest_fails_when_the_asgi_attribute_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Importing the module is not enough — uvicorn does a getattr too."""
    monkeypatch.setattr("app.startup.selftest.ASGI_TARGET", "app.main:no_such_attribute")
    result = run_selftest()
    assert not result.ok
    assert result.failure is not None
    assert "no_such_attribute" in result.failure


def test_format_result_is_one_line_and_names_the_counts() -> None:
    result = SelfTestResult(ok=True, checked=["app.main", "app.workers.discovery"], failure=None)
    line = format_result(result)
    assert "\n" not in line
    assert "2" in line
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd apps/backend && pytest tests/test_selftest.py -v`

Expected: FAIL at collection with `ModuleNotFoundError: No module named 'app.startup.selftest'`.

- [ ] **Step 3: Write the implementation**

Create `apps/backend/src/app/startup/selftest.py`:

```python
"""Prove this binary contains the application it claims to serve.

PyInstaller builds from a static import graph, so a module reached only through
a runtime string is invisible to it and gets dropped silently. v0.4.2 shipped
exactly that: a signed, attested, SBOM'd, version-parity-checked binary with no
`app.main` inside it. Every native install died on

    ERROR: Error loading ASGI app. Could not import module "app.main".

after the release had been published.

This module is the assertion that was missing. It resolves the ASGI target the
way uvicorn resolves it — import the module, then getattr the attribute, because
importing alone would pass on a module that exists but exports nothing — and
imports every worker module and the Alembic environment.

It deliberately touches no database, no Redis, no NATS, no network and no
filesystem beyond the bundle, so it runs in seconds, in a container with no
services, and on an air-gapped host.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass

from app.start import ASGI_TARGET
from app.workers.main import WORKER_MODULES

ALEMBIC_ENV_MODULE = "app.startup.schema"


@dataclass(frozen=True)
class SelfTestResult:
    """The outcome of a self-test run.

    Attributes:
        ok: True when every target resolved.
        checked: Fully qualified names of everything that resolved, in order.
        failure: A human-readable description of the first failure, or None.
    """

    ok: bool
    checked: list[str]
    failure: str | None


def _resolve_asgi_target(target: str, checked: list[str]) -> str | None:
    """Resolve `<module>:<attribute>` as uvicorn does. Returns a failure or None."""
    module_name, separator, attribute = target.partition(":")
    if not separator or not module_name or not attribute:
        return (
            f"ASGI target {target!r} is not in uvicorn's required "
            '"<module>:<attribute>" form'
        )
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:  # noqa: BLE001 — any import failure is the finding
        return f"could not import ASGI module {module_name!r}: {exc!r}"
    checked.append(module_name)
    if not hasattr(module, attribute):
        return f"{module_name!r} has no attribute {attribute!r} for uvicorn to serve"
    checked.append(target)
    return None


def run_selftest() -> SelfTestResult:
    """Import everything this binary must be able to load to run.

    Returns:
        A SelfTestResult naming the first failure, or listing what resolved.
    """
    checked: list[str] = []

    failure = _resolve_asgi_target(ASGI_TARGET, checked)
    if failure is not None:
        return SelfTestResult(ok=False, checked=checked, failure=failure)

    for worker_type, module_name in sorted(WORKER_MODULES.items()):
        try:
            importlib.import_module(module_name)
        except Exception as exc:  # noqa: BLE001
            return SelfTestResult(
                ok=False,
                checked=checked,
                failure=(
                    f"could not import worker module {module_name!r} for worker "
                    f"type {worker_type!r}: {exc!r}"
                ),
            )
        checked.append(module_name)

    try:
        importlib.import_module(ALEMBIC_ENV_MODULE)
    except Exception as exc:  # noqa: BLE001
        return SelfTestResult(
            ok=False,
            checked=checked,
            failure=f"could not import migration entrypoint {ALEMBIC_ENV_MODULE!r}: {exc!r}",
        )
    checked.append(ALEMBIC_ENV_MODULE)

    return SelfTestResult(ok=True, checked=checked, failure=None)


def format_result(result: SelfTestResult) -> str:
    """One line, suitable for a CI log or a doctor check."""
    if result.ok:
        return f"selftest OK — {len(result.checked)} targets resolved"
    return f"selftest FAILED — {result.failure}"
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd apps/backend && pytest tests/test_selftest.py -v`

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/src/app/startup/selftest.py apps/backend/tests/test_selftest.py
git commit -m "feat: add the artifact self-test

Resolves the ASGI target the way uvicorn does — import, then getattr, because
importing alone passes on a module that exports nothing — and imports every
worker module and the migration entrypoint. Touches no database, no broker and
no network, so it runs in a bare container and on an air-gapped host.

This is the assertion v0.4.2 needed and nobody had.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Wire `--selftest` into the entrypoint

**Files:**
- Modify: `apps/backend/src/app/start.py` — `build_parser` and `main`
- Modify: `apps/backend/tests/test_selftest.py` — add the CLI-level tests

**Interfaces:**
- Consumes: `app.startup.selftest.run_selftest`, `format_result` (Task 3).
- Produces: the `--selftest` CLI contract — exit 0 on success, exit 1 on failure, one line on stdout for success and on stderr for failure.

- [ ] **Step 1: Write the failing test**

Append to `apps/backend/tests/test_selftest.py`:

```python
def test_cli_selftest_exits_zero_and_prints_one_line(capsys: pytest.CaptureFixture[str]) -> None:
    from app.start import main

    code = main(["--selftest"])
    captured = capsys.readouterr()
    assert code == 0
    assert captured.out.strip().startswith("selftest OK")
    assert captured.out.strip().count("\n") == 0


def test_cli_selftest_exits_one_and_reports_to_stderr(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("app.startup.selftest.ASGI_TARGET", "app.definitely_not_here:app")
    from app.start import main

    code = main(["--selftest"])
    captured = capsys.readouterr()
    assert code == 1
    assert "selftest FAILED" in captured.err
    assert "app.definitely_not_here" in captured.err


def test_cli_selftest_runs_before_config_is_loaded(monkeypatch: pytest.MonkeyPatch) -> None:
    """--selftest must not need a config file, a database URL or a data dir.

    It runs inside a build container and on a freshly installed host before any
    of those exist. If configure_runtime is reached, the flag is wired too late.
    """

    def _explode(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("configure_runtime must not run under --selftest")

    monkeypatch.setattr("app.start.configure_runtime", _explode)
    from app.start import main

    assert main(["--selftest"]) == 0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd apps/backend && pytest tests/test_selftest.py -v -k cli`

Expected: FAIL with `SystemExit: 2` / `unrecognized arguments: --selftest`.

- [ ] **Step 3: Add the flag to `build_parser`**

In `apps/backend/src/app/start.py`, immediately after the `--version` argument (line 142):

```python
    parser.add_argument(
        "--selftest",
        action="store_true",
        help=(
            "Verify this binary contains the application it serves, then exit. "
            "Imports the ASGI target, every worker module and the migration "
            "entrypoint. Touches no database, broker or network."
        ),
    )
```

- [ ] **Step 4: Dispatch it in `main`, immediately after the `--version` block**

In `apps/backend/src/app/start.py`, after:

```python
    args = build_parser().parse_args(argv)
    if args.version:
        print(resolve_app_version())
        return 0
```

insert:

```python
    # Before configure_runtime, deliberately. --selftest runs inside the build
    # container and on a freshly installed host, where no config file, database
    # URL or data directory exists yet. Anything that reads configuration would
    # make the check need the very environment it exists to be independent of.
    if args.selftest:
        from app.startup.selftest import format_result, run_selftest

        result = run_selftest()
        line = format_result(result)
        if result.ok:
            print(line)
            return 0
        print(line, file=sys.stderr)
        return 1
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd apps/backend && pytest tests/test_selftest.py -v`

Expected: 8 passed.

- [ ] **Step 6: Verify the flag works against the real interpreter**

```bash
cd apps/backend && PYTHONPATH=src python3 -m app.start --selftest; echo "exit=$?"
```

Expected: `selftest OK — N targets resolved` and `exit=0`.

- [ ] **Step 7: Run lint and types**

Run: `make lint`

Expected: clean. `disallow_untyped_defs` is on, so every new function needs annotations — they are present above.

- [ ] **Step 8: Commit**

```bash
git add apps/backend/src/app/start.py apps/backend/tests/test_selftest.py
git commit -m "feat: add --selftest to the entrypoint

Dispatched before configure_runtime, because the check runs inside the build
container and on a freshly installed host where no config, database URL or data
directory exists. Exit 0 with one line on stdout; exit 1 with the failure on
stderr.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: The build cannot emit an amputated binary

**Files:**
- Modify: `scripts/build_native_release.py` — `build_binary`
- Modify: `tests/build/test_build_script.py`

**Interfaces:**
- Consumes: the `--selftest` CLI contract (Task 4).
- Produces: `assert_binary_contains_application(binary_path: Path) -> None`, raising `SystemExit` on failure.

**Why here.** ADR 0005's new rule — cheapest disproof first — and incident 2: v0.4.0 failed `artifact-smoke` *after* every package and image had been built on both architectures. This check costs seconds and gates everything downstream. Because every package format wraps this same binary, one check covers the tarball, deb, rpm, apk, AppImage and `pkg.tar.zst` simultaneously.

- [ ] **Step 1: Write the failing test**

Append to `tests/build/test_build_script.py`:

```python
def test_build_runs_the_selftest_before_staging_the_bundle() -> None:
    """Cheapest disproof first.

    v0.4.0 failed artifact-smoke after every package and every image had already
    been built, on both architectures. v0.4.2 was not caught at all. A binary
    that cannot import its own application is disprovable in seconds, inside the
    job that produced it, before anything is staged or packaged.
    """
    source = BUILD_SCRIPT.read_text(encoding="utf-8")
    assert "assert_binary_contains_application" in source, (
        "build_native_release.py does not assert the built binary contains the "
        "application. PyInstaller drops modules named only by strings, and the "
        "build is the cheapest place to find out."
    )
    build_binary_body = re.search(
        r"def build_binary\(.*?\n(?=\ndef )", source, re.DOTALL
    )
    assert build_binary_body, "build_binary() not found in build_native_release.py"
    assert "assert_binary_contains_application(binary_path)" in build_binary_body.group(0), (
        "assert_binary_contains_application exists but build_binary does not "
        "call it, so a build can still emit a binary with no application in it."
    )
```

**Note:** `BUILD_SCRIPT` and `re` are already defined at the top of `tests/build/test_build_script.py`. Confirm before adding; if `re` is absent, add `import re` to that file's imports.

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/build/test_build_script.py -k selftest -v`

Expected: FAIL — `assert_binary_contains_application` is not in the source.

- [ ] **Step 3: Add the assertion function to `scripts/build_native_release.py`**

Insert immediately before `def build_binary(`:

```python
def assert_binary_contains_application(binary_path: Path) -> None:
    """Refuse to stage a binary that cannot import the application it serves.

    PyInstaller builds from a static import graph, so a module reached only
    through a runtime string is dropped silently. The three collectors above
    exist to re-declare the ones we know about; this asserts the outcome rather
    than trusting the inputs, which is the difference between a mitigation and
    a gate.

    v0.4.2 is what its absence costs: a binary with no `app.main` inside it was
    signed, attested, SBOM'd, version-parity-checked and published, and died on
    every native install. `--version` — the only thing any gate executed —
    resolves from an embedded file and returns before the application is
    imported, so it cannot observe the defect by construction.

    Runs in seconds, needs no services, and gates every package format at once:
    the tarball, deb, rpm, apk, AppImage and pkg.tar.zst all wrap this binary.

    Raises:
        SystemExit: if the binary reports a self-test failure or cannot be run.
    """
    print(f"Verifying {binary_path.name} contains its application...")
    completed = subprocess.run(
        [str(binary_path), "--selftest"],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    output = (completed.stdout + completed.stderr).strip()
    if completed.returncode != 0:
        raise SystemExit(
            f"{binary_path.name} failed its self-test (exit {completed.returncode}).\n"
            f"{output}\n\n"
            "The frozen binary cannot import something it needs at runtime — "
            "almost always a module named only by a string, which PyInstaller's "
            "static import graph cannot see. Add it to hidden_imports in "
            "build_binary(), or to the collector that should have found it.\n"
            "Refusing to stage a bundle that would fail on every install."
        )
    print(f"  {output}")
```

Confirm `subprocess` is imported at the top of the file; it is used by `run()` already.

- [ ] **Step 4: Call it from `build_binary`**

In `scripts/build_native_release.py::build_binary`, replace the final lines:

```python
    binary_path = dist_dir / binary_name(target_os)
    if not binary_path.exists():
        raise SystemExit(f"Expected PyInstaller output missing: {binary_path}")
    return binary_path
```

with:

```python
    binary_path = dist_dir / binary_name(target_os)
    if not binary_path.exists():
        raise SystemExit(f"Expected PyInstaller output missing: {binary_path}")
    assert_binary_contains_application(binary_path)
    return binary_path
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `pytest tests/build/test_build_script.py -k selftest -v`

Expected: PASS.

- [ ] **Step 6: Prove it end to end against a real build**

This is the only step in this plan that exercises PyInstaller, and it is the one that matters. It takes several minutes.

```bash
make build-deps          # only if nfpm/PyInstaller are not already present
.venv/bin/python scripts/build_native_release.py --version "$(cat VERSION)"
```

Expected: the build prints `Verifying circuit-breaker contains its application...` followed by `selftest OK — N targets resolved`, and completes.

Then prove the gate fires. Temporarily add `"--exclude-module=app.main"` to the PyInstaller argument list in `build_binary`, rebuild, and confirm the build **fails** with the SystemExit message above rather than producing a bundle. Remove the exclusion afterwards.

Expected: build fails, no tarball is produced, and the message names the import failure.

- [ ] **Step 7: Commit**

```bash
git add scripts/build_native_release.py tests/build/test_build_script.py
git commit -m "feat: refuse to stage a binary that cannot import its application

The three hidden-import collectors mitigate PyInstaller's static graph; this
asserts the outcome, which is the difference between a mitigation and a gate.
One check covers every package format, because they all wrap this binary.

v0.4.2 is what its absence cost.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: `artifact-smoke.yml` executes the application

**Files:**
- Modify: `.github/workflows/artifact-smoke.yml`

**Interfaces:**
- Consumes: the `--selftest` CLI contract (Task 4), present in the installed binary at `/usr/local/bin/circuit-breaker` (path from `nfpm.yaml`, already asserted by the existing version step).

**Why redundant with Task 5, deliberately.** Task 5 guards the build. This guards the artifact after it has survived packaging, transport and installation — a different failure surface. Both are cheap.

- [ ] **Step 1: Add the step**

In `.github/workflows/artifact-smoke.yml`, immediately after the existing step `Assert the installed binary reports the candidate version`, insert:

```yaml
      # ADR 0005: a gate may not pass by not asking. Every assertion above is an
      # identity check — they all pass on a binary with no application in it,
      # because `--version` resolves from an embedded VERSION file and exits
      # before `app.main` is ever imported. That is exactly how v0.4.2 shipped:
      # signed, attested, SBOM'd, version-parity-checked, and empty.
      #
      # This is the cheapest execution that can disprove publishability. No
      # database, no broker, no network, seconds of runtime, and it runs on both
      # the amd64 and the ubuntu-22.04-arm legs of this matrix.
      - name: Assert the installed binary can load the application it serves
        run: |
          /usr/local/bin/circuit-breaker --selftest
```

- [ ] **Step 2: Verify the YAML parses and the step is inside the right job**

```bash
python3 -c "
import yaml, pathlib
d = yaml.safe_load(pathlib.Path('.github/workflows/artifact-smoke.yml').read_text())
steps = d['jobs']['deb-install']['steps']
names = [s.get('name') for s in steps]
print('\n'.join(str(n) for n in names))
assert any('load the application' in str(n) for n in names), 'step not found in deb-install'
print('OK')
"
```

Expected: the step list prints and ends with `OK`.

- [ ] **Step 3: Confirm ordering — the new step runs after install, before uninstall**

Read the printed step order from Step 2. The self-test must appear after `Install the candidate .deb on a clean host` and before `Assert uninstall removes what it installed`. A self-test after uninstall would run against a deleted binary.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/artifact-smoke.yml
git commit -m "feat: make the release smoke gate execute the application

Every existing assertion in this gate is an identity check and passes on a
binary with no application in it — which is how v0.4.2 published. Adds the
cheapest execution that can disprove publishability, on both architectures.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: `cb doctor` runs the same assertion

**Files:**
- Modify: `deploy/cli/cb`
- Modify: `tests/build/test_cb_cli_contract.py` (confirm the exact filename with `ls tests/build | grep cli` before editing)

**Interfaces:**
- Consumes: the `--selftest` CLI contract (Task 4).
- Produces: a `cb doctor` check named `selftest`.

**Why.** An operator diagnosing a host should run the same assertion the release gate runs. v0.4.2's support conversation becomes one command.

- [ ] **Step 1: Find the binary path and the check idiom**

```bash
grep -n 'circuit-breaker\|/opt/circuitbreaker/bin\|doctor' deploy/cli/cb | head -30
ls tests/build | grep -i cli
```

Read the surrounding checks and follow their exact shape — name, pass/fail reporting, and how `cb doctor --json` serialises a check. Do not invent a new reporting idiom.

- [ ] **Step 2: Add the check**

Following the idiom found in Step 1, add a check that runs the installed binary with `--selftest`, reports its one-line output, and marks the check failed on a non-zero exit. The binary path is `/opt/circuitbreaker/bin/circuit-breaker` for the native/tarball layout and `/usr/local/bin/circuit-breaker` for the package layout — resolve it the way the neighbouring checks already resolve paths, via the install identity record rather than by guessing.

Include this comment above the check:

```sh
# The same assertion the release gate runs. v0.4.2 shipped a binary with no
# application in it and every gate was green, because the only thing any of them
# executed was --version. An operator who can run this gets the answer in one
# command instead of a support thread.
```

- [ ] **Step 3: Run the CLI contract suite**

Run: `pytest tests/build -k cli -v`

Expected: pass. If the suite asserts an exact check count or an exact JSON key set, update that assertion in the same commit — it is a contract, and adding a check legitimately changes it.

- [ ] **Step 4: Exercise it locally**

```bash
bash deploy/cli/cb doctor 2>&1 | grep -i selftest
```

Expected: a line reporting the self-test. On a machine with no install, the check reports the binary is absent rather than crashing — confirm that path too.

- [ ] **Step 5: Commit**

```bash
git add deploy/cli/cb tests/build/
git commit -m "feat: cb doctor runs the artifact self-test

An operator diagnosing a host now runs the same assertion the release gate
runs, which turns a v0.4.2-shaped support thread into one command.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Definition of done

- [ ] `cd apps/backend && pytest tests/test_selftest.py -v` — 8 passed.
- [ ] `pytest tests/build -q` — all pass.
- [ ] `make lint` — clean, including mypy on the new annotated functions.
- [ ] **`make verify-full`** — this plan touches `apps/backend/src/app`, so `make verify` is not sufficient and must not be quoted as evidence.
- [ ] A real `scripts/build_native_release.py` run prints `selftest OK` and completes (Task 5 Step 6).
- [ ] A deliberately amputated build **fails the build**, not the smoke gate (Task 5 Step 6).
- [ ] `artifact-smoke.yml` parses and the new step sits between install and uninstall.
- [ ] `cb doctor` reports a self-test check.

## What this plan does NOT cover

Per CLAUDE.md's rules for claiming something is verified: `make verify-full` runs no browser, no agent, and no installer. It does not execute `artifact-smoke.yml`. The workflow change in Task 6 is verified here only by YAML parsing and step ordering; its first real execution is on the next release candidate, and that is a known gap, not a covered one. Task 5 Step 6 is the only step in this plan that exercises PyInstaller end to end — do not report this plan complete without having run it.
