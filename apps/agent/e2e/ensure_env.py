"""Materialise this directory's `.env` from `.env.example`.

GOV-12 correctly untracked `apps/agent/e2e/.env` and left `.env.example` in
its place. Nothing, however, recreated the file, and the harness cannot run
without it: `docker-compose.yml` here `extends` the repo-root
`docker-compose.yml`, whose service environment uses `${CB_DB_PASSWORD:?...}`
style guards, and `extends` interpolates the *extended* file's variables using
THIS project's env context — i.e. `apps/agent/e2e/.env`. With no such file
even `docker compose config` exits 1 ("required variable CB_DB_PASSWORD is
missing a value"), so every consumer fails before the stack is ever built:
`test_agent_e2e.py`'s `_up_server`, `test_agent_release_gate.py` (which
imports the same `COMPOSE` list), and `.github/workflows/e2e.yml` — which
`release.yml` gates the release on. A `.gitignore` note and a header comment
in the template are prose; this module is the executable step they describe.

Two callers, one implementation, so CI and a developer's laptop cannot drift:

  * `conftest.py` calls `ensure_env_file()` from a session-scoped autouse
    fixture, so `python -m pytest test_agent_e2e.py` works with no preceding
    ritual, locally and in CI alike.
  * `.github/workflows/e2e.yml` runs `python ensure_env.py` as its own step,
    so the file also exists for everything in that job that is NOT pytest
    (diagnostics collection, any future `docker compose` call), and so a
    template problem fails on a step that names itself instead of inside a
    75-minute test run.

Reconciliation, not blind copying: an existing `.env` is never overwritten.
Only keys the template declares and the file lacks are appended, carrying the
template's own comment block for each so the explanation travels with the
value. That keeps a developer's locally edited credentials while still fixing
the "someone added a new `${VAR:?}` guard last week" case, which a plain
`cp -n` silently leaves broken.

The template's values are placeholders of the right shape and reach nothing
deployed (see `.env.example`), so generating a file from them is safe. `.env`
stays gitignored (`.gitignore` line 47); `.env.example` is exempted by the
`!.env.example` negation and stays tracked.
"""

from __future__ import annotations

import sys
from pathlib import Path

E2E_DIR = Path(__file__).resolve().parent
ENV_FILE = E2E_DIR / ".env"
TEMPLATE_FILE = E2E_DIR / ".env.example"


def _template_blocks(text: str) -> list[tuple[str, str]]:
    """Every `KEY=VALUE` assignment in the template, paired with the comment
    and blank lines immediately above it. Returned in file order."""
    blocks: list[tuple[str, str]] = []
    preamble: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            preamble.append(line)
            continue
        if "=" not in stripped:
            # Not an assignment and not a comment — keep it attached to
            # whatever assignment follows rather than dropping it.
            preamble.append(line)
            continue
        key = stripped.split("=", 1)[0].strip()
        blocks.append((key, "\n".join([*preamble, line])))
        preamble = []
    return blocks


def _declared_keys(text: str) -> set[str]:
    keys: set[str] = set()
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        keys.add(stripped.split("=", 1)[0].strip())
    return keys


def ensure_env_file() -> list[str]:
    """Create or top up `.env` from `.env.example`.

    Returns the keys that were written. An empty list means the existing
    `.env` already declared everything the template does.
    """
    if not TEMPLATE_FILE.is_file():
        raise FileNotFoundError(
            f"{TEMPLATE_FILE} is missing — it is tracked, so this means the "
            "checkout is incomplete, not that a local file was forgotten."
        )
    template = TEMPLATE_FILE.read_text(encoding="utf-8")

    if not ENV_FILE.exists():
        ENV_FILE.write_text(template, encoding="utf-8")
        return [key for key, _ in _template_blocks(template)]

    existing = ENV_FILE.read_text(encoding="utf-8")
    have = _declared_keys(existing)
    missing = [(key, block) for key, block in _template_blocks(template) if key not in have]
    if not missing:
        return []

    addition = "\n".join(block for _, block in missing)
    separator = "" if existing.endswith("\n") else "\n"
    ENV_FILE.write_text(
        f"{existing}{separator}\n"
        f"# Appended from .env.example by ensure_env.py — these keys were\n"
        f"# declared by the template but absent here.\n"
        f"{addition}\n",
        encoding="utf-8",
    )
    return [key for key, _ in missing]


def main() -> int:
    written = ensure_env_file()
    if written:
        print(f"{ENV_FILE}: wrote {len(written)} key(s): {', '.join(written)}")
    else:
        print(f"{ENV_FILE}: already complete against {TEMPLATE_FILE.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
