"""The administration journeys SRV-06 requires of ``cb``: migrations, tokens, users, agents.

Every function here is the *second* caller of something the server already
owns — ``app.main.run_alembic_upgrade`` for migrations,
``app.core.security``'s hashing for tokens, ``app.core.token_scopes`` for what
a scope is, ``app.services.agent_registry`` for agent lifecycle — for the
reason ``app.cli``'s docstring gives about second copies. A CLI that approved
an agent without writing an ``agent_events`` row, or minted a token by a
different hashing rule than the one that verifies it, would be an
administration surface that disagrees with the product.

Three properties are the module's own, because nothing above the CLI enforces
them:

**Least privilege is a required argument.** ``POST /auth/api-token`` defaults a
token's scopes to the creating admin's own, which for an admin is everything.
That default is defensible in a UI that shows a scope picker next to it; it is
indefensible on a command line, where the shortest command that works would
mint an unrestricted credential. ``token create`` therefore refuses to guess:
``--scopes`` or ``--preset``, or an error naming both.

**Expiry is a required argument** for the same reason, and by the same
mechanism: ``--expires-in-days`` or an explicit ``--never-expires``.

**A secret crosses stdout exactly once and reaches nothing else.** Token values
and generated passwords are returned by these functions and printed by their
caller at the moment of creation, which is the only moment they exist in
readable form. They are never passed to ``write_log``, never included in an
audit ``details`` string, and never recoverable afterwards — ``list`` reports
label, scopes, expiry and last use, and there is no command that reads a token
back, because the column holds a salted HMAC and not the token.

Nothing here takes a secret from ``argv``: a password is read from stdin or
generated, so it does not reach the shell history or another user's ``ps``.
"""

from __future__ import annotations

import json
import re
import secrets
import string
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.time import utcnow

# Exit codes, stable so a headless caller can branch on them (SRV-5 slice,
# step 3). 2 is argparse's own "usage error" and is reused deliberately: an
# operator who mistyped a flag and an operator who named a role that does not
# exist have made the same kind of mistake.
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2
# `migrate status` alone: the database is readable and behind. Distinct from a
# failure so a deployment script can tell "needs `cb migrate upgrade`" from
# "cannot reach the database" without parsing prose.
EXIT_PENDING = 3

_ROLES = ("admin", "editor", "viewer")
_AGENT_STATUSES = ("pending", "active", "revoked", "rejected")

# Long enough that a machine-generated password is not the weak link, and drawn
# from the same alphabet admin_users._generate_temp_password uses so a password
# from either path satisfies the same complexity rules on first login.
_TEMP_PASSWORD_LENGTH = 20
_TEMP_PASSWORD_ALPHABET = string.ascii_letters + string.digits + "!@#$%^&*"


class AdminError(Exception):
    """An operator-facing failure. The message is printed verbatim, without a traceback."""

    def __init__(self, message: str, exit_code: int = EXIT_FAILED) -> None:
        super().__init__(message)
        self.exit_code = exit_code


# ── Actor resolution ─────────────────────────────────────────────────────────


def resolve_actor(db: Session, email: str | None) -> Any:
    """The administrator an operation is recorded against.

    ``api_tokens.created_by`` and ``agent_events.actor_user_id`` are real
    foreign keys, so "the CLI did it" is not a value either column can hold —
    an audit trail that cannot say who is not an audit trail. When the install
    has exactly one administrator there is no ambiguity to resolve and the
    command runs without ``--actor``; when it has several, guessing which one
    to attribute an irreversible change to is precisely the thing not to do.
    """
    from app.db.models import User

    if email:
        normalised = email.strip().lower()
        actor = db.query(User).filter(User.email == normalised).first()
        if actor is None:
            raise AdminError(f"No user with the email {normalised!r}.", EXIT_USAGE)
        if not _is_admin(actor):
            raise AdminError(
                f"{normalised} has the role {actor.role!r}, which cannot perform "
                "administration. Name an administrator with --actor.",
                EXIT_USAGE,
            )
        if not actor.is_active:
            raise AdminError(
                f"{normalised} is deactivated. Re-enable the account with "
                "`cb user enable`, or name a different administrator with --actor.",
                EXIT_USAGE,
            )
        return actor

    admins = [user for user in db.query(User).order_by(User.id).all() if _is_admin(user)]
    active = [user for user in admins if user.is_active]
    if not active:
        raise AdminError(
            "This install has no active administrator to attribute the change to. "
            "Complete first-run setup, or create one with `cb user create --role admin`.",
            EXIT_USAGE,
        )
    if len(active) > 1:
        raise AdminError(
            "This install has more than one administrator "
            f"({', '.join(user.email for user in active)}), so the change cannot be "
            "attributed without being told to whom. Re-run with --actor <email>.",
            EXIT_USAGE,
        )
    return active[0]


def _is_admin(user: Any) -> bool:
    return (user.role or "").lower() == "admin" or bool(user.is_admin)


def _audit(
    db: Session,
    actor: Any,
    action: str,
    *,
    entity_type: str,
    entity_id: int | None = None,
    entity_name: str = "",
    details: dict[str, Any] | None = None,
) -> None:
    """Record one CLI administration action in the same audit log the UI writes to.

    ``category="audit"`` is what ``/logs?category=audit`` filters on and what
    ``app.core.audit.log_audit`` uses; ``via="cli"`` in the details is how an
    auditor tells a headless change from one made in a browser session. The
    caller's session is used rather than ``log_audit``'s own so the entry lands
    or rolls back with the change it describes — an audit row for a token that
    was never created is worse than no row.
    """
    from app.services.log_service import write_log

    payload = dict(details or {})
    payload["via"] = "cli"
    write_log(
        db=db,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        entity_name=entity_name,
        actor_name=actor.display_name or actor.email,
        actor_id=actor.id,
        actor=actor.email,
        severity="info",
        category="audit",
        details=json.dumps(payload, sort_keys=True, default=str),
    )


# ── Migrations ───────────────────────────────────────────────────────────────


def alembic_ini_path() -> Path:
    """The alembic.ini ``run_alembic_upgrade`` would use, resolved the same way.

    The private helpers are imported from ``app.main`` rather than reimplemented
    because the layouts they cover (repo checkout, mono container, PyInstaller
    bundle, deb/rpm share tree) are exactly the ones a packaged `cb migrate` has
    to work in, and a second list of them would be right until the day the
    packaging changed. ``test_cli_migrate`` asserts this returns the same file
    ``run_alembic_upgrade`` hands to Alembic, so the two cannot drift silently.
    """
    import os

    import app.main as app_main
    from app.main import (
        _ALEMBIC_INI_FILENAME,
        _bundle_share_candidate,
        _meipass_candidate,
        _resolve_existing_path,
        _share_dir_candidate,
    )

    main_path = Path(app_main.__file__).resolve()
    candidates: list[str | Path | None] = [
        os.environ.get("ALEMBIC_CONFIG"),
        os.environ.get("CB_ALEMBIC_INI"),
        _share_dir_candidate("backend", _ALEMBIC_INI_FILENAME),
        _bundle_share_candidate("backend", _ALEMBIC_INI_FILENAME),
        _meipass_candidate("backend", _ALEMBIC_INI_FILENAME),
        main_path.parent.parent.parent / _ALEMBIC_INI_FILENAME,
    ]
    if len(main_path.parents) > 4:
        candidates.append(main_path.parents[4] / "apps" / "backend" / _ALEMBIC_INI_FILENAME)
    resolved = _resolve_existing_path(*candidates)
    if resolved is None:
        raise AdminError(
            "Could not locate alembic.ini. Set CB_ALEMBIC_INI to its path — the mono "
            "container sets it to /app/backend/alembic.ini and a source checkout finds "
            "it at apps/backend/alembic.ini."
        )
    return Path(resolved)


@dataclass(frozen=True)
class MigrationStatus:
    current: tuple[str, ...]
    head: tuple[str, ...]
    pending: tuple[str, ...]

    @property
    def up_to_date(self) -> bool:
        return not self.pending and set(self.current) == set(self.head)


def migration_status() -> MigrationStatus:
    """Which revision the database is on, which one this build ships, and the gap.

    Read-only and lock-free: it takes no advisory lock, because reporting that
    a database is behind must not block the process that is bringing it
    forward.
    """
    from alembic.config import Config
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory

    from app.db.session import engine

    script = ScriptDirectory.from_config(Config(str(alembic_ini_path())))
    heads = tuple(script.get_heads())

    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(connection)
            current = tuple(context.get_current_heads())
    except Exception as exc:  # noqa: BLE001 - the CLI is the boundary
        raise AdminError(f"Could not read the database's migration state: {exc}") from exc

    if set(current) == set(heads):
        return MigrationStatus(current=current, head=heads, pending=())

    pending: list[str] = []
    for revision in script.walk_revisions():
        if revision.revision in current:
            break
        pending.append(revision.revision)
    return MigrationStatus(current=current, head=heads, pending=tuple(reversed(pending)))


def apply_migrations() -> None:
    """Run pending migrations through the server's own upgrade path.

    ``app.main.run_alembic_upgrade`` is called rather than
    ``alembic upgrade head``, so this shares three things with a server start
    that a bare Alembic invocation would not: the alembic.ini resolution above,
    the legacy-database stamp pre-check, and — through ``migrations/env.py`` —
    the ``pg_advisory_xact_lock`` that makes concurrent upgraders safe. That
    lock is the reason `cb migrate upgrade` can be run while the stack is
    coming up without racing the API's own auto-migrate phase.
    """
    from app.main import run_alembic_upgrade

    try:
        run_alembic_upgrade()
    except Exception as exc:  # noqa: BLE001 - the CLI is the boundary
        raise AdminError(f"Migration failed: {exc}") from exc


# ── API tokens / service accounts ────────────────────────────────────────────


@dataclass(frozen=True)
class TokenSummary:
    id: int
    label: str | None
    scopes: tuple[str, ...]
    created_at: str | None
    expires_at: str | None
    last_used_at: str | None
    created_by: int | None
    expired: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "scopes": list(self.scopes),
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "last_used_at": self.last_used_at,
            "created_by": self.created_by,
            "expired": self.expired,
        }


def resolve_scopes(scopes: Sequence[str], preset: str | None) -> list[str]:
    """The scopes a new token gets — never inferred, always stated.

    ``validate_scopes`` and ``SCOPE_PRESETS`` are the API's own, so a scope the
    CLI grants is one ``rbac.has_scope`` can actually enforce and one the UI's
    picker can display.
    """
    from app.core.token_scopes import GRANTABLE_SCOPES, SCOPE_PRESETS, validate_scopes

    if preset and scopes:
        raise AdminError("Use --scopes or --preset, not both.", EXIT_USAGE)
    if preset:
        for entry in SCOPE_PRESETS:
            if entry["key"] == preset:
                return validate_scopes(list(entry["scopes"]))
        raise AdminError(
            f"Unknown preset {preset!r}. Available presets: "
            f"{', '.join(entry['key'] for entry in SCOPE_PRESETS)}.",
            EXIT_USAGE,
        )
    if not scopes:
        raise AdminError(
            "A token needs an explicit privilege. Pass --scopes (one or more of "
            f"{', '.join(sorted(GRANTABLE_SCOPES))}) or --preset (one of "
            f"{', '.join(entry['key'] for entry in SCOPE_PRESETS)}). There is no default: "
            "the shortest command that worked would otherwise be the one that grants the "
            "most.",
            EXIT_USAGE,
        )
    try:
        return validate_scopes(list(scopes))
    except ValueError as exc:
        raise AdminError(str(exc), EXIT_USAGE) from exc


def create_api_token(
    db: Session,
    actor: Any,
    *,
    label: str,
    scopes: Sequence[str],
    expires_in_days: int | None,
) -> tuple[str, TokenSummary]:
    """Mint a token. The raw value is returned once and is not stored anywhere."""
    from app.core.security import create_salted_api_token_hash
    from app.db.models import APIToken

    label = label.strip()
    if not label:
        raise AdminError("--label is required: an unlabelled token cannot be audited.", EXIT_USAGE)
    if expires_in_days is not None and expires_in_days < 1:
        raise AdminError("--expires-in-days must be at least 1.", EXIT_USAGE)

    raw_token = secrets.token_urlsafe(32)
    expires_at = utcnow() + timedelta(days=expires_in_days) if expires_in_days else None
    row = APIToken(
        token_hash=create_salted_api_token_hash(raw_token),
        label=label,
        created_by=actor.id,
        scopes=list(scopes),
        expires_at=expires_at,
    )
    db.add(row)
    db.flush()
    _audit(
        db,
        actor,
        "api_token_created",
        entity_type="api_token",
        entity_id=row.id,
        entity_name=label,
        details={
            "scopes": list(scopes),
            "expires_at": expires_at.isoformat() if expires_at else None,
        },
    )
    db.commit()
    return raw_token, _token_summary(row)


def list_api_tokens(db: Session) -> list[TokenSummary]:
    from app.db.models import APIToken

    rows = db.query(APIToken).order_by(APIToken.id).all()
    return [_token_summary(row) for row in rows]


def rotate_api_token(
    db: Session, actor: Any, token_id: int, *, overlap_hours: int = 0
) -> tuple[str, TokenSummary]:
    """Replace a token's secret, keeping its label, scopes and expiry.

    ``--overlap-hours`` is what makes rotation usable without an outage: the
    superseded secret keeps working for that long, so the fleet that holds it
    can be updated before it stops being accepted. It is implemented by moving
    the old row's expiry forward rather than by any new mechanism —
    ``core.security`` already refuses a token whose ``expires_at`` has passed,
    on the same code path that verifies every other token — and it never
    extends an expiry that was already sooner than the overlap window, because
    rotation must not be a way to prolong a credential past its stated life.
    """
    from app.core.security import create_salted_api_token_hash, invalidate_token_cache
    from app.db.models import APIToken

    if overlap_hours < 0:
        raise AdminError("--overlap-hours cannot be negative.", EXIT_USAGE)

    old = db.get(APIToken, token_id)
    if old is None:
        raise AdminError(f"No API token with id {token_id}.", EXIT_USAGE)

    raw_token = secrets.token_urlsafe(32)
    replacement = APIToken(
        token_hash=create_salted_api_token_hash(raw_token),
        label=old.label,
        created_by=actor.id,
        scopes=list(old.scopes or []),
        expires_at=old.expires_at,
    )
    db.add(replacement)

    superseded_until: str | None = None
    if overlap_hours:
        cutoff = utcnow() + timedelta(hours=overlap_hours)
        if old.expires_at is not None and old.expires_at < cutoff:
            cutoff = old.expires_at
        old.expires_at = cutoff
        superseded_until = cutoff.isoformat()
    else:
        db.delete(old)

    db.flush()
    _audit(
        db,
        actor,
        "api_token_rotated",
        entity_type="api_token",
        entity_id=replacement.id,
        entity_name=old.label or "",
        # No key here may contain "token" or "secret": log_service.sanitise_diff redacts the
        # value of any key whose name matches a credential substring, and it is
        # right to — but it would blank the id of the row this entry exists to
        # link to, leaving an audit trail that records a rotation without
        # recording what was rotated.
        details={
            "replaces_id": token_id,
            "scopes": list(replacement.scopes or []),
            "superseded_valid_until": superseded_until,
        },
    )
    db.commit()
    invalidate_token_cache()
    return raw_token, _token_summary(replacement)


def revoke_api_token(db: Session, actor: Any, token_id: int) -> TokenSummary:
    from app.core.security import invalidate_token_cache
    from app.db.models import APIToken

    row = db.get(APIToken, token_id)
    if row is None:
        raise AdminError(f"No API token with id {token_id}.", EXIT_USAGE)
    summary = _token_summary(row)
    db.delete(row)
    db.flush()
    _audit(
        db,
        actor,
        "api_token_revoked",
        entity_type="api_token",
        entity_id=token_id,
        entity_name=summary.label or "",
        details={"scopes": list(summary.scopes)},
    )
    db.commit()
    invalidate_token_cache()
    return summary


def _token_summary(row: Any) -> TokenSummary:
    expires_at = row.expires_at
    return TokenSummary(
        id=row.id,
        label=row.label,
        scopes=tuple(row.scopes or []),
        created_at=row.created_at.isoformat() if row.created_at else None,
        expires_at=expires_at.isoformat() if expires_at else None,
        last_used_at=row.last_used_at.isoformat() if row.last_used_at else None,
        created_by=row.created_by,
        expired=bool(expires_at and expires_at <= utcnow()),
    )


# ── Users ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class UserSummary:
    id: int
    email: str
    display_name: str | None
    role: str
    is_active: bool
    last_login: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "email": self.email,
            "display_name": self.display_name,
            "role": self.role,
            "is_active": self.is_active,
            "last_login": self.last_login,
        }


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def generate_password() -> str:
    """A password strong enough that the generated case is not the weak one.

    One character from each required class first, so the result always
    satisfies ``auth_service._validate_password`` — a generated password that
    the server's own complexity rule would reject is a failure the operator
    cannot do anything about — then shuffled, so the class order carries no
    information.
    """
    required = [
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.digits),
        secrets.choice("!@#$%^&*"),
    ]
    rest = [
        secrets.choice(_TEMP_PASSWORD_ALPHABET)
        for _ in range(_TEMP_PASSWORD_LENGTH - len(required))
    ]
    characters = required + rest
    # secrets.SystemRandom, not random.shuffle: the sequence must not be
    # reproducible from a seed an attacker can reach.
    secrets.SystemRandom().shuffle(characters)
    return "".join(characters)


def list_users(db: Session) -> list[UserSummary]:
    from app.db.models import User

    return [_user_summary(user) for user in db.query(User).order_by(User.id).all()]


def create_user(
    db: Session,
    actor: Any,
    *,
    email: str,
    role: str,
    password: str | None,
    display_name: str | None = None,
) -> tuple[UserSummary, str | None]:
    """Create a local account. Returns the summary and, when generated, the password.

    The stored form is ``bcrypt(client_hash(password))``, which is what
    ``POST /admin/users/local`` stores and what ``auth_service.login``
    verifies against the hash the browser sends. Storing ``bcrypt(password)``
    instead — as ``POST /admin/users`` does — produces an account that cannot
    log in through the web UI at all, so this path deliberately follows the
    local-user one.
    """
    from app.core.security import client_hash_password, gravatar_hash, hash_password
    from app.core.time import utcnow_iso
    from app.db.models import User
    from app.services.settings_service import get_or_create_settings

    email = email.strip().lower()
    if not _EMAIL_RE.match(email):
        raise AdminError(f"{email!r} is not an email address.", EXIT_USAGE)
    if role not in _ROLES:
        raise AdminError(f"--role must be one of {', '.join(_ROLES)}.", EXIT_USAGE)
    if db.query(User).filter(User.email == email).first() is not None:
        raise AdminError(f"A user with the email {email} already exists.", EXIT_USAGE)

    generated: str | None = None
    if password is None:
        password = generated = generate_password()
    else:
        _require_acceptable_password(password)

    cfg = get_or_create_settings(db)
    user = User(
        email=email,
        hashed_password=hash_password(client_hash_password(password)),
        gravatar_hash=gravatar_hash(email),
        display_name=display_name or email.split("@")[0],
        language=cfg.language or "en",
        is_admin=(role == "admin"),
        is_superuser=(role == "admin"),
        is_active=True,
        created_at=utcnow_iso(),
        role=role,
        scopes=_scopes_for_role(role),
        force_password_change=True,
    )
    db.add(user)
    db.flush()
    _audit(
        db,
        actor,
        "user_created",
        entity_type="user",
        entity_id=user.id,
        entity_name=email,
        details={"role": role, "password_generated": generated is not None},
    )
    db.commit()
    return _user_summary(user), generated


def set_user_role(db: Session, actor: Any, email: str, role: str) -> UserSummary:

    if role not in _ROLES:
        raise AdminError(f"role must be one of {', '.join(_ROLES)}.", EXIT_USAGE)
    user = _require_user(db, email)
    previous = user.role
    user.role = role
    user.is_admin = role == "admin"
    user.is_superuser = role == "admin"
    user.scopes = _scopes_for_role(role)
    db.flush()
    _audit(
        db,
        actor,
        "user_role_changed",
        entity_type="user",
        entity_id=user.id,
        entity_name=user.email,
        details={"from": previous, "to": role},
    )
    db.commit()
    return _user_summary(user)


def set_user_active(db: Session, actor: Any, email: str, active: bool) -> UserSummary:
    """Enable or disable an account, and cut its live sessions when disabling.

    Deactivating a user that keeps a valid session cookie is not a
    deactivation. ``core.security._is_user_accessible`` refuses an inactive
    user on the next request, and ``revoke_all_sessions`` removes the rows, so
    both the cached and the persisted halves of the session are gone.
    """
    from app.services.user_service import revoke_all_sessions

    user = _require_user(db, email)
    if not active and _is_admin(user):
        remaining = [
            other
            for other in list_users(db)
            if other.id != user.id and other.role == "admin" and other.is_active
        ]
        if not remaining:
            raise AdminError(
                f"{user.email} is the only active administrator; deactivating it would "
                "leave the install with no way to administer itself. Create another "
                "administrator first.",
                EXIT_USAGE,
            )
    user.is_active = active
    if not active:
        user.login_attempts = 0
        user.locked_until = None
        revoke_all_sessions(db, user.id)
    db.flush()
    _audit(
        db,
        actor,
        "user_enabled" if active else "user_disabled",
        entity_type="user",
        entity_id=user.id,
        entity_name=user.email,
    )
    db.commit()
    return _user_summary(user)


def _require_user(db: Session, email: str) -> Any:
    from app.db.models import User

    normalised = email.strip().lower()
    user = db.query(User).filter(User.email == normalised).first()
    if user is None:
        raise AdminError(f"No user with the email {normalised!r}.", EXIT_USAGE)
    return user


def _require_acceptable_password(password: str) -> None:
    """The server's own complexity rule, not a second one."""
    from fastapi import HTTPException

    from app.services.auth_service import _validate_password

    try:
        _validate_password(password)
    except HTTPException as exc:
        raise AdminError(str(exc.detail), EXIT_USAGE) from exc


def _scopes_for_role(role: str) -> str:
    from app.core.rbac import ROLE_DEFAULT_SCOPES

    return json.dumps(sorted(ROLE_DEFAULT_SCOPES.get(role, ROLE_DEFAULT_SCOPES["viewer"])))


def _user_summary(user: Any) -> UserSummary:
    return UserSummary(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=user.role,
        is_active=bool(user.is_active),
        last_login=user.last_login,
    )


# ── Agents ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AgentSummary:
    id: int
    name: str | None
    hostname: str | None
    status: str
    agent_version: str | None
    last_seen_at: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "hostname": self.hostname,
            "status": self.status,
            "agent_version": self.agent_version,
            "last_seen_at": self.last_seen_at,
        }


def list_agents(db: Session, status: str | None = None) -> list[AgentSummary]:
    from app.services import agent_registry

    if status is not None and status not in _AGENT_STATUSES:
        raise AdminError(f"--status must be one of {', '.join(_AGENT_STATUSES)}.", EXIT_USAGE)
    return [_agent_summary(agent) for agent in agent_registry.list_agents(db, status=status)]


def approve_agent(db: Session, actor: Any, agent_id: int) -> AgentSummary:
    """Approve an enrolment through the registry, capability defaults and all.

    ``agent_registry.approve_agent`` is the only writer of the default
    capability grants, and the Global Constraint it enforces — an approval
    never enables more than ``CAPABILITY_DEFINITIONS`` says is default — is
    the reason this does not set ``status`` itself.
    """
    from app.services import agent_registry

    agent = _require_agent(db, agent_id)
    if agent.status == "active":
        raise AdminError(f"Agent {agent_id} is already active.", EXIT_USAGE)
    # No `_audit` call beside this one. `agent_registry.approve_agent` routes
    # the approval through `record_event`, which since slice 4.3 (F17) writes
    # the hash-chained audit entry for *every* surface — so auditing here too
    # would put two rows in the chain for one decision. The `via="cli"`
    # provenance this used to add is threaded into that single entry instead.
    approved = agent_registry.approve_agent(db, agent_id, approving_user_id=actor.id, via="cli")
    db.commit()
    return _agent_summary(approved)


def revoke_agent(db: Session, actor: Any, agent_id: int, reason: str | None = None) -> AgentSummary:
    from app.services import agent_registry

    _require_agent(db, agent_id)
    # One chained entry per revocation, written by record_event for every
    # surface — see approve_agent above for why this no longer audits
    # separately.
    revoked = agent_registry.revoke_agent(
        db, agent_id, actor_user_id=actor.id, reason=reason, via="cli"
    )
    db.commit()
    return _agent_summary(revoked)


def _require_agent(db: Session, agent_id: int) -> Any:
    from app.services import agent_registry

    agent = agent_registry.get_agent(db, agent_id)
    if agent is None:
        raise AdminError(f"No agent with id {agent_id}.", EXIT_USAGE)
    return agent


def _agent_summary(agent: Any) -> AgentSummary:
    last_seen = getattr(agent, "last_seen_at", None)
    return AgentSummary(
        id=agent.id,
        name=agent.name,
        hostname=agent.hostname,
        status=agent.status,
        agent_version=agent.agent_version,
        last_seen_at=last_seen.isoformat() if last_seen else None,
    )
