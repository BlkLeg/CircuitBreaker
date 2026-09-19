"""Pytest wiring shared by `test_agent_e2e.py` and `test_agent_release_gate.py`.

The only thing here is the one step that has to happen before any `docker
compose` invocation in this directory can succeed: materialising `.env` from
the tracked `.env.example`. See `ensure_env.py` for why it is needed and why
the implementation lives there rather than inline.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

import pytest
from ensure_env import ENV_FILE, ensure_env_file

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(scope="session", autouse=True)
def e2e_env_file():
    """Guarantee `apps/agent/e2e/.env` exists before the first test runs.

    Autouse and session-scoped deliberately: every test in this directory
    shells out to `docker compose -f <this dir>/docker-compose.yml`, which
    interpolates the repo-root compose file's `${CB_DB_PASSWORD:?...}` guards
    from that file. Putting it here rather than only in the CI workflow means
    a developer running the suite straight from a fresh clone gets the same
    working setup CI does, with nothing to remember.

    The file is intentionally NOT removed afterwards: it is gitignored, it
    holds nothing but placeholders, and leaving it in place is what lets a
    developer run a bare `docker compose ... logs` against the stack after a
    failing run to see what happened.
    """
    written = ensure_env_file()
    if written:
        print(f"\n[e2e] created/updated {ENV_FILE} from .env.example: {', '.join(written)}")
    return ENV_FILE


# Every `httpx.Client` the suite opens, until the test that opened it ends.
#
# Two problems, one list. A client that is never closed leaks its TLS
# connection pool, and when the garbage collector eventually finalises the
# socket, Python emits a `ResourceWarning` — which pytest's
# `unraisableexception` plugin escalates to `PytestUnraisableExceptionWarning`
# and attributes to *whichever test happens to be running when the collector
# ran*. That is why the nightly's failing set reshuffled every night while the
# real defect never moved: the suite opened 18 clients and closed 4.
#
# Holding a strong reference until teardown fixes the attribution (nothing is
# collected mid-test) and the fixture below fixes the leak (everything is
# closed deterministically, in the test that opened it).
_OPEN_HTTP_CLIENTS: list = []

_ClientT = TypeVar("_ClientT")


def register_http_client(client: _ClientT) -> _ClientT:
    """Hand a freshly-built client to the autouse fixture below, and return it.

    Returns its argument so call sites stay a single expression — the point is
    that opening a client and arranging for it to be closed cannot drift apart
    into two statements that someone later separates.
    """
    _OPEN_HTTP_CLIENTS.append(client)
    return client


@pytest.fixture(autouse=True)
def close_registered_http_clients() -> Iterator[None]:
    """Close every client `register_http_client` saw during this test.

    Autouse and function-scoped: the tests here are long, shell out constantly
    and have elaborate `finally` blocks already, so "remember to close the
    client too" is exactly the kind of bookkeeping that does not survive
    contact with a 6000-line module. Errors while closing are swallowed
    deliberately — the stack is usually already torn down by this point, and a
    failure to close must not replace the failure the test was reporting.
    """
    yield
    while _OPEN_HTTP_CLIENTS:
        client = _OPEN_HTTP_CLIENTS.pop()
        try:
            client.close()
        except Exception as exc:  # noqa: BLE001 — teardown must never mask a result
            # Reported rather than silently dropped: a swallowed cleanup error
            # is the exact shape of bug this fixture exists to undo.
            print(f"[e2e] could not close {client!r}: {exc}")
