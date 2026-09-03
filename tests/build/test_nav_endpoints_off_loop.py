"""Route slice 2.5: nothing on the navigation path may block the event loop.

The rule this suite enforces is deliberately stronger than "the handler calls
`run_in_threadpool` somewhere". An earlier version asserted exactly that, and it
passed while `GET /hardware/telemetry/batch` ran up to fifty synchronous
`Session` reads on the loop — the threadpool hop it found covered only the
visibility check, and the loop-blocking work sat in the service function the
handler awaited afterwards. Presence of a call says nothing about what is left
beside it.

So the rule is the absence of the thing that blocks: **an async function on the
navigation path may not touch a `Session` directly.** Blocking reads go into a
plain `def` helper that `run_in_threadpool` runs, which is checkable from the
syntax alone and leaves no room for a partial conversion to look finished.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
API = ROOT / "apps/backend/src/app/api"
SERVICES = ROOT / "apps/backend/src/app/services"
CORE = ROOT / "apps/backend/src/app/core"

#: Names bound to a synchronous `Session` in the functions below. A call on any
#: of these is a database round trip, and on a coroutine it is one the event
#: loop waits for.
SESSION_NAMES = frozenset({"db", "session", "db_session"})

#: `Session` methods that issue SQL or block on the connection pool. `close`
#: and `expunge` are absent on purpose: they do not go to the server, and
#: banning them would push cleanup out of the handler for no benefit.
BLOCKING_SESSION_METHODS = frozenset(
    {
        "add",
        "add_all",
        "commit",
        "delete",
        "execute",
        "flush",
        "get",
        "merge",
        "query",
        "refresh",
        "rollback",
        "scalar",
        "scalars",
    }
)

#: Every async function that serves, or is awaited by, a navigation-path
#: request. `get_telemetry_for_hardware` is not a route: it is the service both
#: telemetry routes await, and it is on this list because the batch endpoint
#: calls it once per id — the single place where a read left on the loop is
#: multiplied by the size of the map the user is looking at.
NAV_PATH_ASYNC_FUNCTIONS = (
    (API / "capabilities.py", "get_capabilities"),
    (API / "agents.py", "get_agents_presence"),
    (API / "telemetry.py", "get_telemetry"),
    (API / "telemetry.py", "get_telemetry_batch"),
    (SERVICES / "telemetry_service.py", "get_telemetry_for_hardware"),
)


def _function(path: Path, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    """The top-level `def`/`async def` named *name* in *path*."""
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"{path.name} no longer defines {name}()")


def _direct_session_calls(node: ast.AST) -> list[str]:
    """Every `<session>.<blocking method>(...)` written literally inside *node*.

    Nested function definitions are skipped: a `def` inside the body is a
    threadpool target like any other, and the work it does is by definition not
    running on the loop when `run_in_threadpool` is what invokes it.
    """
    found: list[str] = []

    def walk(current: ast.AST, *, is_root: bool) -> None:
        for child in ast.iter_child_nodes(current):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue
            if (
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Attribute)
                and isinstance(child.func.value, ast.Name)
                and child.func.value.id in SESSION_NAMES
                and child.func.attr in BLOCKING_SESSION_METHODS
            ):
                found.append(f"{child.func.value.id}.{child.func.attr}() at line {child.lineno}")
            walk(child, is_root=False)

    walk(node, is_root=True)
    return found


def test_discovery_status_is_a_sync_fastapi_handler() -> None:
    """`GET /discovery/status` awaits nothing, so FastAPI should thread it."""
    node = _function(API / "discovery.py", "get_discovery_status")
    assert isinstance(node, ast.FunctionDef), (
        "get_discovery_status was converted back to `async def`; as a coroutine its "
        "ORM queries, APScheduler introspection and Docker socket probe all run on "
        "the event loop. It awaits nothing — leave it a plain `def`."
    )


@pytest.mark.parametrize(
    ("path", "name"),
    NAV_PATH_ASYNC_FUNCTIONS,
    ids=[f"{path.name}::{name}" for path, name in NAV_PATH_ASYNC_FUNCTIONS],
)
def test_nav_path_coroutines_never_touch_the_session_directly(path: Path, name: str) -> None:
    node = _function(path, name)
    assert isinstance(node, ast.AsyncFunctionDef), (
        f"{path.name}::{name} is no longer a coroutine; this suite's rule does not "
        "apply to a plain `def`, so either restore it or drop it from "
        "NAV_PATH_ASYNC_FUNCTIONS deliberately."
    )
    offenders = _direct_session_calls(node)
    assert not offenders, (
        f"{path.name}::{name} runs blocking Session work on the event loop: "
        f"{', '.join(offenders)}. Move the read into a plain `def` helper and call it "
        "through `run_in_threadpool`."
    )


@pytest.mark.parametrize(
    ("path", "name"),
    NAV_PATH_ASYNC_FUNCTIONS,
    ids=[f"{path.name}::{name}" for path, name in NAV_PATH_ASYNC_FUNCTIONS],
)
def test_nav_path_coroutines_hand_their_blocking_work_to_the_threadpool(
    path: Path, name: str
) -> None:
    """The other half of the rule: the work has to still happen somewhere.

    Without this, deleting the database read entirely would satisfy the
    no-direct-Session rule above.
    """
    node = _function(path, name)
    calls = {
        child.func.id
        for child in ast.walk(node)
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
    }
    assert "run_in_threadpool" in calls, (
        f"{path.name}::{name} no longer hands any work to the threadpool. If its "
        "database access moved elsewhere, move this entry to follow it."
    )


def test_the_rule_would_catch_a_regression() -> None:
    """The detector itself, against a handler that does the wrong thing.

    A static check that has never been shown to fail is indistinguishable from
    one that cannot.
    """
    offending = ast.parse(
        "async def handler(db):\n"
        "    ids = await run_in_threadpool(_visible, db)\n"
        "    return db.query(Hardware).all()\n"
    ).body[0]
    assert _direct_session_calls(offending) == ["db.query() at line 3"]

    compliant = ast.parse(
        "async def handler(db):\n"
        "    def _read(session):\n"
        "        return session.query(Hardware).all()\n"
        "    return await run_in_threadpool(_read, db)\n"
    ).body[0]
    assert _direct_session_calls(compliant) == []


#: The dependencies FastAPI resolves before any of the handlers above runs.
#: Declared `def`, they are resolved in the threadpool; declared `async def`,
#: their bodies run inline on the event loop.
_AUTH_DEPENDENCIES = (
    "get_optional_user",
    "require_write_auth",
    "require_auth_always",
)


def test_the_auth_prologue_is_not_an_async_def() -> None:
    """M3. The list above certified the nav handlers as off-loop while the
    dependencies resolved *ahead of every one of them* did blocking work inline.

    `get_optional_user` runs on every request: an AppSettings read through
    `get_or_create_settings`, a synchronous Redis MGET, and on a cache miss a
    full `APIToken` scan with a per-row HMAC verify. `require_write_auth` and
    `require_auth_always` add `db.get(User, ...)` and `_is_user_accessible`.
    None of them awaits anything, so `async def` bought nothing and cost the
    loop every one of those reads.

    This is why the gate mattered less than it looked: slice 2.5 moved five
    handlers off the loop behind a prologue that was never converted, so the
    loop-lag delta it was meant to demonstrate would have read as roughly
    nothing — and the conclusion drawn would have been about de-asyncing rather
    than about this.
    """
    source = (CORE / "security.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    offenders = [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name in _AUTH_DEPENDENCIES
    ]
    assert not offenders, (
        f"{offenders} are `async def` and await nothing, so FastAPI resolves them "
        "inline on the event loop — in front of every request the API serves. "
        "Declare them `def` and they are resolved in the threadpool instead."
    )


def test_the_auth_prologue_still_exists_under_those_names() -> None:
    """The check above passes vacuously if a dependency is renamed or removed,
    which is how a gate keyed on names quietly stops gating anything."""
    tree = ast.parse((CORE / "security.py").read_text(encoding="utf-8"))
    defined = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    missing = [name for name in _AUTH_DEPENDENCIES if name not in defined]
    assert not missing, f"auth dependencies renamed or removed: {missing}"
