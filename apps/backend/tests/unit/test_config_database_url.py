"""Settings.database_url must resolve from CB_DB_URL.

Every other URL on Settings declares a CB_-prefixed validation alias
(redis_url, rate_limit_storage_url, egress_proxy_url). database_url did not, so
pydantic-settings bound it to the bare field name DATABASE_URL and CB_DB_URL --
the variable the whole project actually sets, and the one this field's own
comment names -- never reached it.

app/db/session.py hid the consequence: it reads os.environ["CB_DB_URL"] itself
and only falls back to settings.database_url, so the transactional path works
regardless. app/db/db_client.py does not. `_make_primary_engine()` builds from
settings.database_url alone, which is what get_engine("analytics") falls back to
whenever DuckDB is unavailable -- so catalog_service's device-catalog search hit
create_engine("") and raised ArgumentError. docker-compose.yml sets neither
CB_DB_URL nor DATABASE_URL in its environment block, so that was the shipped
Docker behavior, not just a test artifact.

Worse than empty: apps/backend/.env.example still carries
DATABASE_URL=sqlite:///./data/app.db, and Settings.model_config loads .env. A
developer who follows that file's own "copy this to .env" instruction pointed
the analytics engine at a SQLite file while the rest of the app spoke to
Postgres -- SQLite having been unsupported since v0.2.0.
"""

from app.core.config import Settings

PG = "postgresql://breaker:breaker@localhost:5432/circuitbreaker"
OTHER = "postgresql://breaker:breaker@localhost:5432/other"


def _settings(monkeypatch, **env):
    for key in ("CB_DB_URL", "DATABASE_URL"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    # _env_file=None: this asserts on the environment, not on whatever .env
    # happens to sit in the working directory of whoever runs the suite.
    return Settings(_env_file=None)


def test_database_url_comes_from_cb_db_url(monkeypatch):
    assert _settings(monkeypatch, CB_DB_URL=PG).database_url == PG


def test_database_url_still_accepts_the_unprefixed_name(monkeypatch):
    """deploy/setup.sh writes DATABASE_URL, so it stays a valid spelling."""
    assert _settings(monkeypatch, DATABASE_URL=PG).database_url == PG


def test_cb_db_url_wins_when_both_are_set(monkeypatch):
    """Same precedence as app/db/session.py, which prefers CB_DB_URL over the
    settings value — the two must not disagree about which database is live."""
    assert _settings(monkeypatch, CB_DB_URL=PG, DATABASE_URL=OTHER).database_url == PG
