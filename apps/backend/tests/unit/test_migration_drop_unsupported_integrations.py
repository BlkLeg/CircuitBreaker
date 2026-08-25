"""The truenas/unifi cleanup actually removes the credential (INC-16).

Narrowing `VALID_PROVIDERS` without this migration would be worse than leaving it alone: the
API would stop serving those provider paths while their rows — and the encrypted credentials
attached to them — stayed in the database with nothing in the product able to reach them.
The ordering matters too, since `integration_configs.credential_id` is a foreign key:
deleting the credential first violates the constraint and aborts the whole upgrade.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext

_VERSIONS_DIR = Path(__file__).resolve().parents[2] / "migrations" / "versions"
_MIGRATION = "7d2e4a81c6f3_drop_unsupported_integration_configs"


def _load_migration(name: str):
    path = _VERSIONS_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_migration_{name}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(connection, step) -> None:
    context = MigrationContext.configure(connection)
    with Operations.context(context):
        step()


def _seed(db_session, provider: str) -> tuple[int, int]:
    from app.db.models import Credential, IntegrationConfig

    cred = Credential(
        credential_type="api_key",
        encrypted_value="gAAAAABciphertext",
        label=f"{provider}-cred",
    )
    db_session.add(cred)
    db_session.flush()
    cfg = IntegrationConfig(
        type=provider,
        name=f"{provider} box",
        config_url="https://box.example.com",
        credential_id=cred.id,
    )
    db_session.add(cfg)
    db_session.flush()
    return cfg.id, cred.id


def test_the_config_and_its_credential_both_go(db_session):
    from app.db.models import Credential, IntegrationConfig

    cfg_id, cred_id = _seed(db_session, "truenas")
    connection = db_session.get_bind()

    _run(connection, _load_migration(_MIGRATION).upgrade)
    db_session.expire_all()

    assert db_session.get(IntegrationConfig, cfg_id) is None
    assert db_session.get(Credential, cred_id) is None


def test_a_supported_provider_is_left_alone(db_session):
    from app.db.models import Credential, IntegrationConfig

    cfg_id, cred_id = _seed(db_session, "proxmox")
    connection = db_session.get_bind()

    _run(connection, _load_migration(_MIGRATION).upgrade)
    db_session.expire_all()

    assert db_session.get(IntegrationConfig, cfg_id) is not None
    assert db_session.get(Credential, cred_id) is not None


def test_the_removal_is_recorded_where_the_operator_can_find_it(db_session):
    """Someone configured that integration. Deleting it silently is not an option."""
    from app.db.models import Log

    cfg_id, _ = _seed(db_session, "unifi")
    connection = db_session.get_bind()

    _run(connection, _load_migration(_MIGRATION).upgrade)

    entry = (
        db_session.query(Log)
        .filter(Log.action == "integration_config_removed", Log.entity_id == cfg_id)
        .one()
    )
    assert "unifi" in entry.details
    assert entry.level == "warning"


def test_an_install_with_nothing_to_remove_is_a_no_op(db_session):
    from app.db.models import Log

    before = db_session.query(Log).filter(Log.action == "integration_config_removed").count()
    connection = db_session.get_bind()

    _run(connection, _load_migration(_MIGRATION).upgrade)

    after = db_session.query(Log).filter(Log.action == "integration_config_removed").count()
    assert after == before


def test_a_config_with_no_credential_does_not_break_the_upgrade(db_session):
    """credential_id is nullable, and `DELETE ... WHERE id = ANY(NULL)` is not what we want."""
    from app.db.models import IntegrationConfig

    cfg = IntegrationConfig(type="unifi", name="No cred", config_url="https://u.example.com")
    db_session.add(cfg)
    db_session.flush()
    cfg_id = cfg.id
    connection = db_session.get_bind()

    _run(connection, _load_migration(_MIGRATION).upgrade)
    db_session.expire_all()

    assert db_session.get(IntegrationConfig, cfg_id) is None


def test_the_revision_chains_onto_the_acme_columns():
    module = _load_migration(_MIGRATION)

    assert module.revision == "7d2e4a81c6f3"
    assert module.down_revision == "3b1f0c7a9d24"


def test_only_one_migration_claims_that_parent():
    """Two children of one revision is two heads, and `upgrade head` then fails outright."""
    parent = 'down_revision: str | Sequence[str] | None = "3b1f0c7a9d24"'
    claimants = [
        path.name
        for path in _VERSIONS_DIR.glob("*.py")
        if parent in path.read_text(encoding="utf-8")
    ]

    assert claimants == [f"{_MIGRATION}.py"], claimants


def test_no_orphaned_credential_is_left_behind(db_session):
    """The whole point: narrowing the API without this leaves the ciphertext unreachable."""

    _, cred_id = _seed(db_session, "truenas")
    connection = db_session.get_bind()

    _run(connection, _load_migration(_MIGRATION).upgrade)

    remaining = db_session.execute(
        sa.text("SELECT count(*) FROM credentials WHERE id = :i"), {"i": cred_id}
    ).scalar()
    assert remaining == 0
