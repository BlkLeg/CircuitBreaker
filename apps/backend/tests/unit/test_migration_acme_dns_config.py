"""Schema-level guarantees for the ACME DNS-01 columns (INC-07).

Three things this migration has to get right, none of which the ORM test suite would catch —
it builds its schema from ``Base.metadata`` and never replays a migration:

* It chains onto the current head. A second migration claiming the same parent gives alembic
  two heads and breaks ``upgrade head`` on every deployment.
* ``certificates.acme_challenge`` is nullable with no default. It records how a certificate
  was issued, and a default of 'http-01' would claim an issuance path that every pre-existing
  row never took — including the self-signed ones.
* ``certificates.acme_staging`` is NOT NULL with a server default, because it is read
  unconditionally by the renewal path and a NULL there is not a third answer.

Mirrors ``tests/unit/test_migration_0101_discovery_retention_and_global_pause.py``.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext

_VERSIONS_DIR = Path(__file__).resolve().parents[2] / "migrations" / "versions"
_MIGRATION = "3b1f0c7a9d24_acme_dns_config"
_REVISION = "3b1f0c7a9d24"
_PARENT = "122698ed7f44"


def _load_migration(name: str):
    """`migrations/versions` is not a package, so import by file path."""
    path = _VERSIONS_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_migration_{name}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(connection, migration_step) -> None:
    context = MigrationContext.configure(connection)
    with Operations.context(context):
        migration_step()


def _columns(connection, table: str) -> dict:
    return {c["name"]: c for c in sa.inspect(connection).get_columns(table)}


def test_revision_chains_onto_the_certificate_retype():
    module = _load_migration(_MIGRATION)

    assert module.revision == _REVISION
    assert module.down_revision == _PARENT


def test_only_one_migration_claims_that_parent():
    """Two children of one revision is two heads, and `upgrade head` then fails outright."""
    claimants = [
        path.name
        for path in _VERSIONS_DIR.glob("*.py")
        if f'down_revision: str | Sequence[str] | None = "{_PARENT}"' in path.read_text()
        or f'down_revision = "{_PARENT}"' in path.read_text()
    ]

    assert claimants == [f"{_MIGRATION}.py"], claimants


def test_downgrade_then_upgrade_restores_every_column(db_session):
    """Read the migration's own DDL rather than the create_all schema underneath it."""
    module = _load_migration(_MIGRATION)
    connection = db_session.get_bind()

    _run(connection, module.downgrade)
    assert "acme_dns_config" not in _columns(connection, "app_settings")
    assert "acme_challenge" not in _columns(connection, "certificates")

    _run(connection, module.upgrade)
    assert "acme_dns_provider" in _columns(connection, "app_settings")
    assert "acme_dns_config" in _columns(connection, "app_settings")
    assert "acme_challenge" in _columns(connection, "certificates")
    assert "acme_staging" in _columns(connection, "certificates")


def test_the_upgrade_is_safe_to_run_twice(db_session):
    """Guarded DDL, like the rest of this tree: 0001_init already creates both columns from
    Base.metadata on a fresh database, so the migration must be a no-op there."""
    module = _load_migration(_MIGRATION)
    connection = db_session.get_bind()

    _run(connection, module.upgrade)
    _run(connection, module.upgrade)

    assert "acme_dns_config" in _columns(connection, "app_settings")


def test_the_challenge_column_does_not_claim_a_default(db_session):
    """NULL is the honest record for a row ACME did not issue."""
    module = _load_migration(_MIGRATION)
    connection = db_session.get_bind()
    _run(connection, module.downgrade)
    _run(connection, module.upgrade)

    column = _columns(connection, "certificates")["acme_challenge"]

    assert column["nullable"] is True
    assert column["default"] is None


def test_staging_is_not_null_with_a_default(db_session):
    """The renewal path reads it unconditionally; NULL is not a third answer."""
    module = _load_migration(_MIGRATION)
    connection = db_session.get_bind()
    _run(connection, module.downgrade)
    _run(connection, module.upgrade)

    column = _columns(connection, "certificates")["acme_staging"]

    assert column["nullable"] is False
    assert "false" in str(column["default"]).lower()
