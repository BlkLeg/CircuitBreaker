"""Pytest wiring shared by `test_agent_e2e.py` and `test_agent_release_gate.py`.

The only thing here is the one step that has to happen before any `docker
compose` invocation in this directory can succeed: materialising `.env` from
the tracked `.env.example`. See `ensure_env.py` for why it is needed and why
the implementation lives there rather than inline.
"""

from __future__ import annotations

import pytest
from ensure_env import ENV_FILE, ensure_env_file


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
