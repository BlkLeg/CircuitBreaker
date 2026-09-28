# tests/build/test_postgres_utf8_policy.py
"""Every PostgreSQL cluster is UTF8, and every backend connection speaks UTF8.

QUAR-001 / #162. The mono image ran `initdb` with no `--encoding` and no LANG,
so every cluster it created is SQL_ASCII. psycopg2 maps SQL_ASCII to Python's
`ascii` codec, and the first non-ASCII character a user typed — or the em dash
in a discovery profile name — raised UnicodeEncodeError on INSERT. Freeform
first means any name must save, so two things have to hold, and each has a way
of quietly stopping:

* **New clusters are UTF8.** Every `initdb` the product runs names the encoding
  instead of inheriting it from whatever locale the process happens to have.
* **Existing clusters still work.** A SQL_ASCII cluster cannot be re-encoded in
  place, so every psycopg2 engine the backend creates asks for the UTF8 client
  encoding. SQL_ASCII performs no conversion, so the UTF-8 bytes are stored and
  returned as they are. A new `create_engine` that forgets this reintroduces the
  bug for every upgraded deployment, which is why each engine is named below:
  an unlisted one fails here until it is classified.
"""

from __future__ import annotations

import ast
import configparser
import importlib.util
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "apps" / "backend"
APP = BACKEND / "src" / "app"
MONO_INITDB = REPO_ROOT / "docker" / "10-init-postgres.sh"
NATIVE_SETUP = REPO_ROOT / "deploy" / "setup.sh"
PGBOUNCER_CONFIGS = (
    REPO_ROOT / "docker" / "pgbouncer.ini",
    REPO_ROOT / "deploy" / "config" / "pgbouncer.ini",
)

#: The helper every PostgreSQL engine passes as `connect_args`.
UTF8_HELPER = "pg_connect_args"

#: Every psycopg2 engine the backend creates: (file relative to apps/backend,
#: enclosing function or "<module>").
POSTGRES_ENGINES = frozenset(
    {
        ("src/app/db/session.py", "<module>"),
        ("src/app/core/job_lock.py", "lock_session"),
        ("src/app/cli.py", "_read_app_settings"),
        ("src/app/db/db_client.py", "_make_primary_engine"),
        ("migrations/env.py", "run_migrations_online"),
    }
)

#: Engines that are not PostgreSQL, and why the rule does not apply to them.
NON_POSTGRES_ENGINES = {
    ("src/app/db/cve_session.py", "<module>"): "SQLite CVE cache",
    ("src/app/db/db_client.py", "_make_analytics_engine"): "DuckDB analytics file",
}

_ENGINE_FACTORIES = frozenset({"create_engine", "_create_engine"})


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        prefix = func.value.id + "." if isinstance(func.value, ast.Name) else ""
        return prefix + func.attr
    return ""


def _engine_calls(path: Path) -> list[tuple[str, ast.Call]]:
    """Every engine factory or raw psycopg2 connect in *path*, with its enclosing
    function name."""
    found: list[tuple[str, ast.Call]] = []

    def visit(node: ast.AST, scope: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                visit(child, child.name)
                continue
            if isinstance(child, ast.Call):
                name = _call_name(child)
                if name in _ENGINE_FACTORIES or name in {
                    "psycopg2.connect",
                    "psycopg.connect",
                }:
                    found.append((scope, child))
            visit(child, scope)

    visit(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)), "<module>")
    return found


def _all_engine_calls() -> dict[tuple[str, str], ast.Call]:
    calls: dict[tuple[str, str], ast.Call] = {}
    sources = [*APP.rglob("*.py"), *(BACKEND / "migrations").glob("*.py")]
    for path in sorted(sources):
        for scope, call in _engine_calls(path):
            key = (path.relative_to(BACKEND).as_posix(), scope)
            assert key not in calls, f"two engines in {key}; name them separately here"
            calls[key] = call
    return calls


def _initdb_lines(path: Path) -> list[str]:
    return [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if re.search(r"\binitdb\b\s+-D", line) and not line.lstrip().startswith("#")
    ]


def test_every_backend_engine_is_classified():
    """An engine nobody has looked at is the one that forgets the encoding."""
    found = set(_all_engine_calls())
    expected = POSTGRES_ENGINES | set(NON_POSTGRES_ENGINES)
    assert found == expected, (
        f"unclassified engines: {sorted(found - expected)}; "
        f"listed but gone: {sorted(expected - found)}"
    )


def test_every_postgres_engine_forces_the_utf8_client_encoding():
    calls = _all_engine_calls()
    for key in sorted(POSTGRES_ENGINES):
        call = calls[key]
        connect_args = next(
            (kw.value for kw in call.keywords if kw.arg == "connect_args"), None
        )
        assert (
            isinstance(connect_args, ast.Call)
            and _call_name(connect_args) == UTF8_HELPER
        ), (
            f"{key[0]}:{call.lineno} ({key[1]}) must pass connect_args={UTF8_HELPER}(...)"
        )


def test_the_helper_asks_psycopg2_for_utf8():
    """Loaded by path: the helper must stay importable with no app dependencies,
    because `cli.py` reaches it before the application is configured."""
    spec = importlib.util.spec_from_file_location(
        "pg_encoding", APP / "db" / "pg_encoding.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    pg_connect_args = module.pg_connect_args

    assert pg_connect_args()["client_encoding"].lower() in {"utf8", "utf-8"}
    # Extra arguments ride along without displacing the encoding.
    merged = pg_connect_args(connect_timeout=5)
    assert merged["connect_timeout"] == 5
    assert merged["client_encoding"].lower() in {"utf8", "utf-8"}


def test_the_async_engine_is_asyncpg():
    """asyncpg always sends `client_encoding=utf-8` in its startup packet, so the
    async engine needs no helper — as long as it stays asyncpg."""
    text = (APP / "db" / "async_session.py").read_text(encoding="utf-8")
    assert '"postgresql+asyncpg://"' in text
    assert "create_async_engine(" in text


def test_the_mono_initdb_creates_a_utf8_cluster():
    lines = _initdb_lines(MONO_INITDB)
    assert len(lines) == 1, lines
    assert "--encoding=UTF8" in lines[0]
    # C.UTF-8 ships in Debian's libc-bin (/usr/lib/locale/C.utf8), so it exists
    # in the debian:12-slim runtime without installing `locales`.
    assert "--locale=C.UTF-8" in lines[0]


def test_the_native_initdb_creates_a_utf8_cluster():
    lines = _initdb_lines(NATIVE_SETUP)
    assert len(lines) == 1, lines
    assert "--encoding=UTF8" in lines[0]
    assert "--locale=" in lines[0]


def test_pgbouncer_passes_the_client_encoding_through():
    """PgBouncer tracks `client_encoding` itself and re-applies it on every server
    connection it hands a client. Listing it in `ignore_startup_parameters` would
    silently drop the UTF8 request on the pooled path, which is the mono image's
    main engine."""
    for path in PGBOUNCER_CONFIGS:
        parser = configparser.ConfigParser()
        parser.read(path, encoding="utf-8")
        ignored = parser.get("pgbouncer", "ignore_startup_parameters", fallback="")
        names = {name.strip().lower() for name in ignored.split(",")}
        assert "client_encoding" not in names, path
