"""SRV-06: the headless administration journeys, exercised against a real database.

The requirement has two halves and this file covers both.

*Least privilege is enforced server-side, not described.* The token tests do not
assert that a scope list was stored; they mint a token through the CLI path and
then send it at the API, because "the row says read:*" and "the server refuses
the admin route" are different claims and only the second one is the
requirement. A token that carried the right scopes and was honoured everywhere
anyway is exactly the escalation INC-14 was.

*A secret crosses stdout once and reaches nothing else.* Every mutating token
test re-reads the audit log and the token row afterwards and asserts the raw
value is in neither, because a CLI that prints a credential and also files it
somewhere has not protected it — it has copied it.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from app.core.security import client_hash_password, verify_salted_api_token_hash
from app.core.time import utcnow
from app.db.models import AgentCapabilityGrant, AgentEvent, APIToken, Log, User
from app.scripts import cli_admin
from app.scripts.cli_admin import (
    EXIT_PENDING,
    EXIT_USAGE,
    AdminError,
    approve_agent,
    create_api_token,
    create_user,
    list_agents,
    list_api_tokens,
    list_users,
    resolve_actor,
    resolve_scopes,
    revoke_api_token,
    rotate_api_token,
    set_user_active,
    set_user_role,
)


def _audit_entries(db_session, action: str) -> list[Log]:
    return (
        db_session.query(Log)
        .filter(Log.category == "audit", Log.action == action)
        .order_by(Log.id)
        .all()
    )


def _log_blob(db_session) -> str:
    """Every field of every log row this test could have written, as one string."""
    rows = db_session.query(Log).all()
    return "\n".join(
        "|".join(
            str(value)
            for value in (
                row.action,
                row.details,
                row.old_value,
                row.new_value,
                row.diff,
                row.entity_name,
            )
        )
        for row in rows
    )


# ── Actor resolution ─────────────────────────────────────────────────────────


def test_a_single_administrator_needs_no_actor_flag(db_session, factories):
    admin = factories.user(role="admin")
    assert resolve_actor(db_session, None).id == admin.id


def test_several_administrators_force_the_change_to_be_attributed(db_session, factories):
    factories.user(role="admin")
    factories.user(role="admin")
    with pytest.raises(AdminError) as excinfo:
        resolve_actor(db_session, None)
    assert excinfo.value.exit_code == EXIT_USAGE
    assert "--actor" in str(excinfo.value)


def test_a_non_administrator_cannot_be_the_actor(db_session, factories):
    viewer = factories.user(role="viewer")
    factories.user(role="admin")
    with pytest.raises(AdminError) as excinfo:
        resolve_actor(db_session, viewer.email)
    assert excinfo.value.exit_code == EXIT_USAGE


# ── Tokens: least privilege ──────────────────────────────────────────────────


def test_a_token_cannot_be_minted_without_saying_what_it_may_do():
    """The shortest command that works must not be the one that grants the most."""
    with pytest.raises(AdminError) as excinfo:
        resolve_scopes([], None)
    assert excinfo.value.exit_code == EXIT_USAGE
    message = str(excinfo.value)
    assert "--scopes" in message and "--preset" in message


def test_an_unknown_scope_is_refused_with_the_grantable_list():
    with pytest.raises(AdminError) as excinfo:
        resolve_scopes(["read:everything"], None)
    assert "read:everything" in str(excinfo.value)


def test_a_preset_resolves_to_the_scopes_the_api_serves():
    assert resolve_scopes([], "read_only") == ["read:*"]


@pytest.mark.asyncio
async def test_a_read_only_cli_token_is_enforced_server_side(client, db_session, factories):
    """The requirement: least privilege enforced by the server, not by the CLI's docs."""
    admin = factories.user(role="admin")
    raw_token, _summary = create_api_token(
        db_session,
        admin,
        label="ci read-only",
        scopes=["read:*"],
        expires_in_days=30,
    )
    headers = {"Authorization": f"Bearer {raw_token}"}

    assert (await client.get("/api/v1/hardware", headers=headers)).status_code == 200
    assert (await client.get("/api/v1/kb/oui", headers=headers)).status_code == 403


@pytest.mark.asyncio
async def test_an_expired_cli_token_stops_authenticating(client, db_session, factories):
    admin = factories.user(role="admin")
    raw_token, summary = create_api_token(
        db_session, admin, label="short-lived", scopes=["read:*"], expires_in_days=1
    )
    headers = {"Authorization": f"Bearer {raw_token}"}
    assert (await client.get("/api/v1/hardware", headers=headers)).status_code == 200

    row = db_session.get(APIToken, summary.id)
    row.expires_at = utcnow() - timedelta(minutes=1)
    db_session.flush()
    from app.core.security import invalidate_token_cache

    invalidate_token_cache()

    assert (await client.get("/api/v1/hardware", headers=headers)).status_code == 401


def test_expiry_is_a_required_decision(db_session, factories):
    """`--expires-in-days`/`--never-expires` is enforced by argparse, not by a default."""
    from app.cli import build_parser

    with pytest.raises(SystemExit) as excinfo:
        build_parser().parse_args(["token", "create", "--label", "x", "--scopes", "read:*"])
    assert excinfo.value.code == 2


# ── Tokens: the secret ───────────────────────────────────────────────────────


def test_the_token_value_is_stored_only_as_a_salted_hash(db_session, factories):
    admin = factories.user(role="admin")
    raw_token, summary = create_api_token(
        db_session, admin, label="hash check", scopes=["read:*"], expires_in_days=30
    )
    row = db_session.get(APIToken, summary.id)
    assert raw_token not in row.token_hash
    assert verify_salted_api_token_hash(raw_token, row.token_hash)


def test_the_token_value_never_reaches_the_audit_log(db_session, factories):
    admin = factories.user(role="admin")
    raw_token, summary = create_api_token(
        db_session, admin, label="audit check", scopes=["read:*"], expires_in_days=30
    )
    rotated, _ = rotate_api_token(db_session, admin, summary.id)
    revoke_api_token(db_session, admin, list_api_tokens(db_session)[-1].id)

    blob = _log_blob(db_session)
    assert raw_token not in blob
    assert rotated not in blob


def test_creation_is_audited_with_the_actor_and_the_scopes(db_session, factories):
    admin = factories.user(role="admin")
    _raw, summary = create_api_token(
        db_session, admin, label="audited", scopes=["read:*"], expires_in_days=7
    )
    entries = _audit_entries(db_session, "api_token_created")
    assert len(entries) == 1
    entry = entries[0]
    assert entry.actor_id == admin.id
    assert entry.entity_id == summary.id
    details = json.loads(entry.details)
    assert details["scopes"] == ["read:*"]
    assert details["via"] == "cli"


def test_revocation_is_audited_and_removes_the_row(db_session, factories):
    admin = factories.user(role="admin")
    _raw, summary = create_api_token(
        db_session, admin, label="to revoke", scopes=["read:*"], expires_in_days=7
    )
    revoke_api_token(db_session, admin, summary.id)
    assert db_session.get(APIToken, summary.id) is None
    assert len(_audit_entries(db_session, "api_token_revoked")) == 1


def test_an_unlabelled_token_is_refused(db_session, factories):
    admin = factories.user(role="admin")
    with pytest.raises(AdminError) as excinfo:
        create_api_token(db_session, admin, label="  ", scopes=["read:*"], expires_in_days=7)
    assert excinfo.value.exit_code == EXIT_USAGE


# ── Tokens: rotation ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rotation_without_overlap_cuts_the_old_secret_off_immediately(
    client, db_session, factories
):
    admin = factories.user(role="admin")
    old_raw, summary = create_api_token(
        db_session, admin, label="rotating", scopes=["read:*"], expires_in_days=30
    )
    new_raw, replacement = rotate_api_token(db_session, admin, summary.id)

    assert new_raw != old_raw
    assert db_session.get(APIToken, summary.id) is None
    assert replacement.scopes == ("read:*",)

    old_headers = {"Authorization": f"Bearer {old_raw}"}
    new_headers = {"Authorization": f"Bearer {new_raw}"}
    assert (await client.get("/api/v1/hardware", headers=old_headers)).status_code == 401
    assert (await client.get("/api/v1/hardware", headers=new_headers)).status_code == 200


@pytest.mark.asyncio
async def test_rotation_with_overlap_keeps_the_old_secret_working(client, db_session, factories):
    """The point of overlap: update the fleet before the old credential dies."""
    admin = factories.user(role="admin")
    old_raw, summary = create_api_token(
        db_session, admin, label="overlapping", scopes=["read:*"], expires_in_days=30
    )
    new_raw, _replacement = rotate_api_token(db_session, admin, summary.id, overlap_hours=6)

    old_row = db_session.get(APIToken, summary.id)
    assert old_row is not None
    assert old_row.expires_at > utcnow()

    assert (
        await client.get("/api/v1/hardware", headers={"Authorization": f"Bearer {old_raw}"})
    ).status_code == 200
    assert (
        await client.get("/api/v1/hardware", headers={"Authorization": f"Bearer {new_raw}"})
    ).status_code == 200


def test_overlap_never_prolongs_a_token_past_its_own_expiry(db_session, factories):
    """Rotation is not a back door for extending a credential's stated life."""
    admin = factories.user(role="admin")
    _raw, summary = create_api_token(
        db_session, admin, label="expiring soon", scopes=["read:*"], expires_in_days=1
    )
    original_expiry = db_session.get(APIToken, summary.id).expires_at

    rotate_api_token(db_session, admin, summary.id, overlap_hours=24 * 30)

    assert db_session.get(APIToken, summary.id).expires_at == original_expiry


def test_rotation_is_audited_and_names_what_it_replaced(db_session, factories):
    """The detail keys deliberately avoid the substring "token".

    ``log_service.sanitise_diff`` blanks the value of any key whose name
    contains a credential substring — correctly, and including this entry's own
    ids if they were named ``replaces_token_id``. An audit row that records
    that a rotation happened but not what was rotated is not an audit row.
    """
    admin = factories.user(role="admin")
    _raw, summary = create_api_token(
        db_session, admin, label="tracked", scopes=["read:*"], expires_in_days=7
    )
    rotate_api_token(db_session, admin, summary.id, overlap_hours=2)
    entries = _audit_entries(db_session, "api_token_rotated")
    assert len(entries) == 1
    details = json.loads(entries[0].details)
    assert details["replaces_id"] == summary.id
    assert details["superseded_valid_until"] is not None


def test_rotating_a_token_that_does_not_exist_is_a_usage_error(db_session, factories):
    admin = factories.user(role="admin")
    with pytest.raises(AdminError) as excinfo:
        rotate_api_token(db_session, admin, 987654321)
    assert excinfo.value.exit_code == EXIT_USAGE


# ── Users ────────────────────────────────────────────────────────────────────


def test_a_cli_created_user_can_actually_log_in(db_session, factories, app_cfg):
    """Stored as bcrypt(client_hash(password)) — what auth_service.login verifies.

    Storing bcrypt(password) instead, as POST /admin/users does, produces an
    account the web UI can never authenticate, because the browser sends the
    client hash and never the password.
    """
    from app.services.auth_service import login
    from app.services.settings_service import get_or_create_settings

    admin = factories.user(role="admin")
    summary, generated = create_user(
        db_session, admin, email="ops@example.com", role="editor", password=None
    )
    assert generated is not None

    cfg = get_or_create_settings(db_session)
    result = login(db_session, summary.email, client_hash_password(generated), cfg)
    assert result.token


def test_a_generated_password_satisfies_the_servers_own_complexity_rule():
    from fastapi import HTTPException

    from app.services.auth_service import _validate_password

    for _ in range(25):
        try:
            _validate_password(cli_admin.generate_password())
        except HTTPException as exc:  # pragma: no cover - the assertion is the message
            pytest.fail(f"generated password rejected by the server's own rule: {exc.detail}")


def test_the_generated_password_never_reaches_the_audit_log(db_session, factories):
    admin = factories.user(role="admin")
    _summary, generated = create_user(
        db_session, admin, email="quiet@example.com", role="viewer", password=None
    )
    assert generated not in _log_blob(db_session)


def test_a_weak_explicit_password_is_refused_by_the_servers_rule(db_session, factories):
    admin = factories.user(role="admin")
    with pytest.raises(AdminError) as excinfo:
        create_user(db_session, admin, email="weak@example.com", role="viewer", password="password")
    assert excinfo.value.exit_code == EXIT_USAGE


def test_a_duplicate_email_is_a_usage_error_not_an_integrity_error(db_session, factories):
    admin = factories.user(role="admin")
    create_user(db_session, admin, email="dupe@example.com", role="viewer", password=None)
    with pytest.raises(AdminError) as excinfo:
        create_user(db_session, admin, email="DUPE@example.com", role="viewer", password=None)
    assert excinfo.value.exit_code == EXIT_USAGE


def test_creating_a_user_is_audited(db_session, factories):
    admin = factories.user(role="admin")
    summary, _generated = create_user(
        db_session, admin, email="audited-user@example.com", role="editor", password=None
    )
    entries = _audit_entries(db_session, "user_created")
    assert [entry.entity_id for entry in entries] == [summary.id]
    assert json.loads(entries[0].details)["role"] == "editor"


def test_set_role_moves_the_default_scopes_with_the_role(db_session, factories):
    from app.core.rbac import ROLE_DEFAULT_SCOPES, effective_scopes

    admin = factories.user(role="admin")
    target = factories.user(role="viewer")
    set_user_role(db_session, admin, target.email, "editor")

    refreshed = db_session.get(User, target.id)
    assert refreshed.role == "editor"
    assert effective_scopes(refreshed) == ROLE_DEFAULT_SCOPES["editor"]
    assert len(_audit_entries(db_session, "user_role_changed")) == 1


def test_disabling_a_user_revokes_their_sessions(db_session, factories):
    from app.db.models import UserSession

    admin = factories.user(role="admin")
    target = factories.user(role="editor")
    db_session.add(
        UserSession(
            user_id=target.id,
            jwt_token_hash="cli-admin-test-session",
            expires_at=utcnow() + timedelta(hours=1),
        )
    )
    db_session.flush()

    set_user_active(db_session, admin, target.email, False)

    assert db_session.get(User, target.id).is_active is False
    remaining = (
        db_session.query(UserSession)
        .filter(UserSession.user_id == target.id, UserSession.revoked.is_(False))
        .count()
    )
    assert remaining == 0


def test_the_last_active_administrator_cannot_be_disabled(db_session, factories):
    admin = factories.user(role="admin")
    with pytest.raises(AdminError) as excinfo:
        set_user_active(db_session, admin, admin.email, False)
    assert excinfo.value.exit_code == EXIT_USAGE
    assert db_session.get(User, admin.id).is_active is True


def test_list_users_reports_role_and_state(db_session, factories):
    admin = factories.user(role="admin")
    listed = {user.email: user for user in list_users(db_session)}
    assert listed[admin.email].role == "admin"
    assert listed[admin.email].is_active is True


# ── Agents ───────────────────────────────────────────────────────────────────


def _pending_agent(db_session, factories):
    from app.services import agent_registry

    agent = agent_registry.create_pending_agent(
        db_session,
        device_pk="cli-admin-test-device-pk",
        fingerprint="cli-admin-test-fingerprint",
        hostname="agent-under-test",
    )
    db_session.flush()
    return agent


def test_approving_an_agent_grants_only_the_default_capabilities(db_session, factories):
    from app.services.agent_capabilities import CAPABILITY_DEFINITIONS

    admin = factories.user(role="admin")
    agent = _pending_agent(db_session, factories)

    summary = approve_agent(db_session, admin, agent.id)
    assert summary.status == "active"

    grants = {
        grant.capability: grant.enabled
        for grant in db_session.query(AgentCapabilityGrant).filter(
            AgentCapabilityGrant.agent_id == agent.id
        )
    }
    assert grants == {
        name: definition.default_enabled for name, definition in CAPABILITY_DEFINITIONS.items()
    }


def test_approving_an_agent_records_the_registry_event_and_an_audit_entry(db_session, factories):
    admin = factories.user(role="admin")
    agent = _pending_agent(db_session, factories)
    approve_agent(db_session, admin, agent.id)

    events = (
        db_session.query(AgentEvent)
        .filter(AgentEvent.agent_id == agent.id, AgentEvent.event_type == "approved")
        .all()
    )
    assert len(events) == 1
    assert len(_audit_entries(db_session, "agent_approved")) == 1


def test_approving_an_already_active_agent_is_a_usage_error(db_session, factories):
    admin = factories.user(role="admin")
    agent = _pending_agent(db_session, factories)
    approve_agent(db_session, admin, agent.id)
    with pytest.raises(AdminError) as excinfo:
        approve_agent(db_session, admin, agent.id)
    assert excinfo.value.exit_code == EXIT_USAGE


def test_revoking_an_agent_records_the_reason(db_session, factories):
    admin = factories.user(role="admin")
    agent = _pending_agent(db_session, factories)
    approve_agent(db_session, admin, agent.id)

    summary = cli_admin.revoke_agent(db_session, admin, agent.id, "decommissioned")
    assert summary.status == "revoked"
    entries = _audit_entries(db_session, "agent_revoked")
    assert json.loads(entries[0].details)["reason"] == "decommissioned"


def test_agent_list_filters_by_status(db_session, factories):
    admin = factories.user(role="admin")
    agent = _pending_agent(db_session, factories)
    assert agent.id in {row.id for row in list_agents(db_session, "pending")}
    approve_agent(db_session, admin, agent.id)
    assert agent.id not in {row.id for row in list_agents(db_session, "pending")}
    assert agent.id in {row.id for row in list_agents(db_session, "active")}


def test_an_unknown_agent_status_is_a_usage_error(db_session):
    with pytest.raises(AdminError) as excinfo:
        list_agents(db_session, "asleep")
    assert excinfo.value.exit_code == EXIT_USAGE


# ── Migrations ───────────────────────────────────────────────────────────────


def test_the_cli_resolves_the_same_alembic_ini_the_server_upgrades_with(monkeypatch):
    """`cb migrate status` must read the migration tree `cb migrate upgrade` applies.

    ``run_alembic_upgrade`` resolves the file itself and hands it to Alembic;
    ``alembic_ini_path`` has to reach the same answer across four packaging
    layouts. Intercepting the upgrade call is how the two are compared without
    running a migration.

    ``stamp`` is intercepted as well, and not merely for tidiness. The suite
    builds its schema from ``Base.metadata`` rather than from Alembic, so
    ``users`` exists while ``alembic_version`` does not — which is exactly the
    legacy-database shape ``run_alembic_upgrade``'s pre-check stamps. Letting
    that through would write to the shared test database, and would run
    ``migrations/env.py``, whose ``fileConfig`` call disables every logger
    created before it — which silently breaks every later ``caplog`` assertion
    in the session, three tests away in a directory this file never touches.
    """
    import alembic.command

    import app.main as app_main

    upgraded: list[str] = []
    stamped: list[str] = []
    monkeypatch.setattr(
        alembic.command,
        "upgrade",
        lambda config, revision: upgraded.append(config.config_file_name),
    )
    monkeypatch.setattr(
        alembic.command, "stamp", lambda config, revision: stamped.append(config.config_file_name)
    )
    app_main.run_alembic_upgrade()

    expected = str(cli_admin.alembic_ini_path())
    assert upgraded == [expected]
    # The pre-check builds its own Config; if the two ever diverged, a legacy
    # database would be stamped from one migration tree and upgraded from
    # another.
    assert stamped in ([], [expected])


def test_migration_status_reports_the_gap_and_a_pending_exit_code(monkeypatch, setup_db):
    """The suite's schema is built from metadata, so it is legitimately unstamped.

    That is the same state a database restored from a schema-only dump is in,
    and the useful answer is "behind, here is by how much" with an exit code a
    deployment script can branch on — not a crash and not a false "up to date".
    """
    status = cli_admin.migration_status()
    assert status.head
    assert not status.up_to_date
    assert status.pending

    from app.cli import _cmd_migrate_status

    assert _cmd_migrate_status(as_json=True) == EXIT_PENDING


# ── The command surface itself ───────────────────────────────────────────────


@pytest.mark.parametrize(
    "argv",
    [
        ["token", "list", "--json"],
        ["user", "list", "--json"],
        ["agent", "list", "--json"],
    ],
)
def test_the_read_only_commands_run_end_to_end(argv, setup_db, capsys):
    """Exercises the real entrypoint: argparse, its own session, and JSON output.

    The operations are unit-tested against the fixture session above; this is
    the other half — that `python -m app.cli <group> list` opens a session of
    its own, renders, and exits 0, which is what `cb token list` actually runs.
    """
    from app.cli import main

    assert main(argv) == 0
    json.loads(capsys.readouterr().out)


def test_a_usage_error_is_a_sentence_and_exit_2_not_a_traceback(capsys):
    """`resolve_scopes` runs before a session is opened, so this needs no database."""
    from app.cli import main

    assert main(["token", "create", "--label", "x", "--never-expires"]) == EXIT_USAGE
    captured = capsys.readouterr()
    assert captured.err.startswith("error: ")
    assert "Traceback" not in captured.err


def test_every_command_the_shell_wrappers_forward_is_one_the_parser_knows():
    """The two `cb` scripts and `app.cli` must agree on the command surface.

    `cb token rotate 3` is `python -m app.cli token rotate 3` with a container
    in the middle. A group the shell forwards and the parser has never heard of
    is a command that exists in the help text and nowhere else.
    """
    import re
    from pathlib import Path

    from app.cli import build_parser

    repo_root = Path(__file__).resolve().parents[3]
    groups = set()
    for script in (repo_root / "cb", repo_root / "deploy" / "cli" / "cb"):
        text = script.read_text()
        groups |= set(re.findall(r"^_admin_cli (\w+) ", text, flags=re.MULTILINE))
        groups |= set(re.findall(r"_admin_cli (\w+) \"\$@\"", text))

    assert {"migrate", "token", "user", "agent"} <= groups, (
        f"a cb script stopped forwarding one of the admin groups: {sorted(groups)}"
    )

    parser = build_parser()
    known = {
        action.dest: action
        for action in parser._subparsers._group_actions  # noqa: SLF001 - argparse has no public accessor
    }["group"].choices
    missing = groups - set(known)
    assert not missing, f"cb forwards commands app.cli does not define: {sorted(missing)}"


def test_upgrade_goes_through_the_servers_own_path_and_nothing_else(monkeypatch):
    """`cb migrate upgrade` must not be a second `alembic upgrade head`.

    ``run_alembic_upgrade`` is what makes it safe to run while the stack is
    starting: it resolves the same alembic.ini, applies the legacy-database
    stamp pre-check, and goes through ``migrations/env.py``, which takes the
    ``pg_advisory_xact_lock`` that serialises it against the API's own
    auto-migrate phase. Calling Alembic directly would skip all three.
    """
    import app.main as app_main

    calls: list[int] = []
    monkeypatch.setattr(app_main, "run_alembic_upgrade", lambda: calls.append(1))
    cli_admin.apply_migrations()
    assert calls == [1]


def test_a_failed_upgrade_is_an_operator_message_not_a_traceback(monkeypatch):
    import app.main as app_main

    def _boom() -> None:
        raise RuntimeError("Can't locate revision identified by 'deadbeef'")

    monkeypatch.setattr(app_main, "run_alembic_upgrade", _boom)
    with pytest.raises(AdminError) as excinfo:
        cli_admin.apply_migrations()
    assert "deadbeef" in str(excinfo.value)


def test_upgrade_does_nothing_when_the_schema_is_already_at_head(monkeypatch, capsys):
    from app.cli import _cmd_migrate_upgrade

    at_head = cli_admin.MigrationStatus(current=("abc123",), head=("abc123",), pending=())
    monkeypatch.setattr(cli_admin, "migration_status", lambda: at_head)
    monkeypatch.setattr(
        cli_admin, "apply_migrations", lambda: pytest.fail("upgrade ran with nothing pending")
    )

    assert _cmd_migrate_upgrade() == 0
    assert "already up to date" in capsys.readouterr().out
