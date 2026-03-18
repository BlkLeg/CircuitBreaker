"""Phase 6.5: Admin user management — CRUD, invites, masquerade, unlock, audit."""

import logging
import secrets
import string
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.rbac import require_role
from app.core.security import client_hash_password, create_token, hash_password
from app.db.models import Log, User, UserInvite, UserSession
from app.db.session import get_db
from app.services.settings_service import get_or_create_settings
from app.services.user_service import (
    create_invite,
    revoke_invite,
    unlock_user,
)

_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin-users"])


# ── Schemas ─────────────────────────────────────────────────────────────────


class UserListItem(BaseModel):
    id: int
    email: str
    display_name: str | None
    gravatar_hash: str | None
    role: str
    is_active: bool
    last_login: str | None
    session_count: int
    locked_until: datetime | None
    login_attempts: int


class UserCreateRequest(BaseModel):
    email: str
    password: str
    role: str = "viewer"
    display_name: str | None = None


class UserUpdateRequest(BaseModel):
    role: str | None = None
    is_active: bool | None = None


class InviteCreateRequest(BaseModel):
    email: str
    role: str = "viewer"


class InviteListItem(BaseModel):
    id: int
    email: str
    role: str
    invited_by: int
    expires: datetime
    status: str
    created_at: datetime
    email_status: str = "not_sent"
    email_error: str | None = None


class InviteCreateResponse(BaseModel):
    invite_id: int
    token: str
    invite_url: str
    expires: datetime
    email_status: str = "not_sent"  # not_sent | sent | failed


class MasqueradeResponse(BaseModel):
    token: str
    target_user_id: int
    expires_in_seconds: int


class CreateLocalUserRequest(BaseModel):
    email: str
    display_name: str | None = None
    role: str = "viewer"
    generate_password: bool = True
    manual_password: str | None = None


class CreateLocalUserResponse(BaseModel):
    user_id: int
    email: str
    display_name: str
    role: str
    temp_password: str | None = None  # only when generate_password=True
    force_change: bool = True


# ── Helpers ─────────────────────────────────────────────────────────────────


def _generate_temp_password() -> str:
    """Generate a cryptographically secure 12-character temp password."""
    chars = string.ascii_letters + string.digits + "!@#$%^&*"
    return (
        secrets.choice(string.ascii_uppercase)
        + secrets.choice(string.ascii_lowercase)
        + secrets.choice(string.digits)
        + secrets.choice("!@#$%^&*")
        + "".join(secrets.choice(chars) for _ in range(8))
    )


# ── User CRUD ───────────────────────────────────────────────────────────────


@router.get("/users", response_model=list[UserListItem])
def list_users(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, require_role("admin")],
) -> list[UserListItem]:
    """List all users with role, status, last_login, session count."""
    users = db.query(User).filter(User.id > 0).all()
    from app.core.time import utcnow

    result = []
    for u in users:
        session_count = (
            db.query(UserSession)
            .filter(UserSession.user_id == u.id)
            .filter(UserSession.revoked == False)  # noqa: E712
            .filter(UserSession.expires_at > utcnow())
        ).count()
        # Only expose gravatar_hash for the requesting user (self); null it out for other users
        gravatar_hash_value = u.gravatar_hash if u.id == user.id else None
        result.append(
            UserListItem(
                id=u.id,
                email=u.email,
                display_name=u.display_name,
                gravatar_hash=gravatar_hash_value,
                role=getattr(u, "role", None) or ("admin" if u.is_admin else "viewer"),
                is_active=u.is_active,
                last_login=u.last_login,
                session_count=session_count,
                locked_until=getattr(u, "locked_until", None),
                login_attempts=getattr(u, "login_attempts", 0) or 0,
            )
        )
    return result


@router.post("/users")
def create_user(
    payload: UserCreateRequest,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, require_role("admin")],
) -> dict[str, Any]:
    """Create a user directly (admin only)."""
    from app.core.security import gravatar_hash, hash_password
    from app.core.time import utcnow_iso
    from app.services.auth_service import _validate_password

    _validate_password(payload.password)
    role = payload.role if payload.role in ("admin", "editor", "viewer") else "viewer"
    now = utcnow_iso()
    cfg = get_or_create_settings(db)
    new_user = User(
        email=payload.email.strip().lower(),
        hashed_password=hash_password(payload.password),
        gravatar_hash=gravatar_hash(payload.email),
        display_name=payload.display_name or payload.email.split("@")[0],
        language=cfg.language or "en",
        is_admin=(role == "admin"),
        is_superuser=(role == "admin"),
        is_active=True,
        created_at=now,
        role=role,
    )
    db.add(new_user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="A user with this email already exists."
        ) from None
    db.refresh(new_user)
    return {
        "id": new_user.id,
        "email": new_user.email,
        "role": new_user.role,
        "display_name": new_user.display_name,
    }


@router.post("/users/local", response_model=CreateLocalUserResponse)
def create_local_user(
    payload: CreateLocalUserRequest,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, require_role("admin")],
) -> CreateLocalUserResponse:
    """Create a user instantly without an email invite (admin only).

    When generate_password=True a secure temp password is returned once in the
    response and never stored in plaintext or logs.  The account is flagged
    force_password_change=True so the user is required to set a new password on
    first login. Passwords are stored as bcrypt(client_hash(plain)) so login
    with the frontend (which sends password_hash only) works.
    """
    from app.core.security import gravatar_hash
    from app.core.time import utcnow_iso
    from app.db.models import Log
    from app.services.auth_service import _validate_password

    email = payload.email.strip().lower()
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=409, detail="Email already in use")

    role = payload.role if payload.role in ("admin", "editor", "viewer") else "viewer"

    if payload.generate_password:
        _temp = _generate_temp_password()
        temp_password: str | None = _temp
        client_hash = client_hash_password(_temp)
        hashed = hash_password(client_hash)
    else:
        if not payload.manual_password:
            raise HTTPException(
                status_code=400, detail="manual_password is required when generate_password=False"
            )
        _validate_password(payload.manual_password)
        client_hash = client_hash_password(payload.manual_password)
        hashed = hash_password(client_hash)
        temp_password = None  # never expose manual passwords

    cfg = get_or_create_settings(db)
    now = utcnow_iso()
    new_user = User(
        email=email,
        hashed_password=hashed,
        gravatar_hash=gravatar_hash(email),
        display_name=payload.display_name or email.split("@")[0],
        language=cfg.language or "en",
        is_admin=(role == "admin"),
        is_superuser=(role == "admin"),
        is_active=True,
        created_at=now,
        role=role,
        force_password_change=True,
    )
    db.add(new_user)
    try:
        db.flush()  # get new_user.id before audit log
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="A user with this email already exists."
        ) from None

    audit = Log(
        level="info",
        category="admin",
        action="user_local_created",
        actor=actor.email,
        actor_name=actor.display_name or actor.email,
        actor_id=actor.id,
        entity_type="user",
        entity_id=new_user.id,
        entity_name=new_user.email,
        details=str(
            {
                "email": email,
                "role": role,
                "password_generated": payload.generate_password,
            }
        ),
        created_at_utc=now,
    )
    db.add(audit)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="A user with this email already exists."
        ) from None
    db.refresh(new_user)

    return CreateLocalUserResponse(
        user_id=new_user.id,
        email=new_user.email,
        display_name=new_user.display_name or "",
        role=new_user.role,
        temp_password=temp_password,
        force_change=True,
    )


@router.patch("/users/{user_id}")
def update_user(
    user_id: int,
    payload: UserUpdateRequest,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, require_role("admin")],
) -> dict[str, Any]:
    """Update user role or is_active."""
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target.id == 0:
        raise HTTPException(status_code=403, detail="Cannot modify service account")
    if payload.role is not None:
        if payload.role not in ("admin", "editor", "viewer"):
            raise HTTPException(status_code=400, detail="Invalid role")
        target.role = payload.role
        target.is_admin = payload.role == "admin"
        target.is_superuser = payload.role == "admin"
    if payload.is_active is not None:
        target.is_active = payload.is_active
    db.commit()
    db.refresh(target)
    return {"id": target.id, "role": target.role, "is_active": target.is_active}


@router.delete("/users/{user_id}", status_code=204)
def delete_user(
    user_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, require_role("admin")],
    permanent: bool = Query(False, description="If true, remove the user entirely (hard delete)."),
) -> None:
    """Soft-delete user (is_active=False) or, when permanent=true, remove the user entirely."""
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target.id == 0:
        raise HTTPException(status_code=403, detail="Cannot delete service account")
    if permanent:
        from app.services.auth_service import delete_user_permanent

        delete_user_permanent(
            db,
            user_id,
            actor_id=user.id,
            actor_name=user.display_name or user.email,
        )
        return
    target.is_active = False
    db.commit()


@router.post("/users/{user_id}/unlock")
def unlock_user_endpoint(
    user_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, require_role("admin")],
) -> dict[str, Any]:
    """Unlock a user after failed login lockout."""
    target = unlock_user(db, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    return {"id": target.id, "status": "unlocked"}


@router.post("/users/{user_id}/masquerade", response_model=MasqueradeResponse)
def masquerade_user(
    request: Request,
    user_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, require_role("admin")],
) -> MasqueradeResponse:
    """Issue a short-lived masquerade token (admin login-as)."""
    from app.core.audit import log_audit

    cfg = get_or_create_settings(db)
    if not getattr(cfg, "masquerade_enabled", True):
        raise HTTPException(status_code=403, detail="Masquerade is disabled")
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if not target.is_active:
        raise HTTPException(status_code=400, detail="Cannot masquerade as inactive user")
    # Short-lived token (15 min) with masquerade claims for audit trail
    token = create_token(
        target.id,
        cfg.jwt_secret,  # type: ignore[arg-type]
        timeout_hours=15 / 60,  # type: ignore[arg-type]  # 15 minutes as fraction of hour
        extra_claims={
            "is_masquerade": True,
            "masquerade_by": user.id,
        },
    )
    log_audit(
        db,
        request,
        user_id=user.id,
        action="admin_masquerade",
        resource=f"user:{target.id}",
        status="ok",
        details=(
            f"Admin masquerade as user_id={target.id}"
            f" ({target.email or target.display_name or 'unknown'})"
        ),
    )
    db.commit()
    return MasqueradeResponse(
        token=token,
        target_user_id=target.id,
        expires_in_seconds=15 * 60,
    )


# ── Per-user audit ─────────────────────────────────────────────────────────


@router.get("/user-actions/{user_id}")
def get_user_actions(
    user_id: int,
    user: Annotated[User, require_role("admin")],
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    start_time: str | None = None,
    end_time: str | None = None,
    action: str | None = None,
) -> dict[str, Any]:
    """Filtered audit log for a specific user."""
    q = select(Log).where(Log.actor_id == user_id).order_by(Log.timestamp.desc())
    count_q = select(func.count()).select_from(Log).where(Log.actor_id == user_id)

    if start_time:
        try:
            dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
            q = q.where(Log.timestamp >= dt)
            count_q = count_q.where(Log.timestamp >= dt)
        except ValueError:
            pass
    if end_time:
        try:
            dt = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
            q = q.where(Log.timestamp <= dt)
            count_q = count_q.where(Log.timestamp <= dt)
        except ValueError:
            pass
    if action:
        q = q.where(Log.action == action)
        count_q = count_q.where(Log.action == action)

    total = db.execute(count_q).scalar_one()
    rows = db.execute(q.offset(offset).limit(limit)).scalars().all()

    from app.core.time import elapsed_seconds
    from app.schemas.logs import LogEntry

    entries = []
    for row in rows:
        e = LogEntry.model_validate(row)
        e.elapsed_seconds = elapsed_seconds(row.created_at_utc) if row.created_at_utc else None
        entries.append(e)

    return {
        "logs": [e.model_dump() for e in entries],
        "total_count": total,
        "has_more": (offset + limit) < total,
    }


# ── Invites ─────────────────────────────────────────────────────────────────


@router.post("/invites", response_model=InviteCreateResponse)
async def create_invite_endpoint(
    payload: InviteCreateRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, require_role("admin")],
) -> InviteCreateResponse:
    """Generate an invite (email + role) and auto-send via SMTP if configured."""
    if payload.role not in ("admin", "editor", "viewer"):
        raise HTTPException(status_code=400, detail="Invalid role")
    invite, token = create_invite(db, user, payload.email, payload.role)
    invite_url = f"/invite/accept?token={token}"

    # Auto-send invite email if SMTP is configured
    email_status = "not_sent"
    email_error: str | None = None
    cfg = get_or_create_settings(db)
    if cfg.smtp_enabled and cfg.smtp_host and cfg.smtp_from_email:
        from app.services.smtp_service import (
            SmtpService,
            resolve_public_base_url,
        )

        try:
            # Use api_base_url only — never fall back to request.base_url which is
            # the backend URL (localhost:8000) and not reachable by invite recipients.
            base_url = resolve_public_base_url(cfg)
            if not base_url:
                _logger.warning(
                    "Invite email for %s: api_base_url is not set — "
                    "link will be relative. Set App URL in Settings.",
                    payload.email,
                )
            await SmtpService(cfg).send_invite(payload.email, token, user.email, base_url)
            email_status = "sent"
        except Exception as exc:
            email_status = "failed"
            email_error = str(exc)
            _logger.warning("Invite email failed for %s: %s", payload.email, exc)

    invite.email_status = email_status
    invite.email_error = email_error
    if email_status == "sent":
        invite.email_sent_at = datetime.utcnow().isoformat()
    db.commit()

    return InviteCreateResponse(
        invite_id=invite.id,
        token=token,
        invite_url=invite_url,
        expires=invite.expires,
        email_status=email_status,
    )


@router.get("/invites", response_model=list[InviteListItem])
def list_invites(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, require_role("admin")],
    status: str | None = Query(None),
) -> list[InviteListItem]:
    """List invites (default: pending only)."""
    q = db.query(UserInvite).order_by(UserInvite.created_at.desc())
    if status:
        q = q.filter(UserInvite.status == status)
    invites = q.all()
    return [
        InviteListItem(
            id=i.id,
            email=i.email,
            role=i.role,
            invited_by=i.invited_by,
            expires=i.expires,
            status=i.status,
            created_at=i.created_at,
            email_status=getattr(i, "email_status", "not_sent") or "not_sent",
            email_error=getattr(i, "email_error", None),
        )
        for i in invites
    ]


class InviteUpdateRequest(BaseModel):
    action: str  # "revoked" | "extend"


@router.patch("/invites/{invite_id}")
def update_invite(
    invite_id: int,
    payload: InviteUpdateRequest,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, require_role("admin")],
) -> dict[str, Any]:
    """Revoke or extend an invite."""
    invite = db.get(UserInvite, invite_id)
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found")
    if payload.action == "revoked":
        revoke_invite(db, invite_id)
        return {"id": invite_id, "status": "revoked"}
    if payload.action == "extend":
        from datetime import timedelta

        cfg = get_or_create_settings(db)
        invite.expires = invite.expires + timedelta(days=getattr(cfg, "invite_expiry_days", 7))
        db.commit()
        db.refresh(invite)
        return {"id": invite_id, "expires": invite.expires.isoformat()}
    raise HTTPException(status_code=400, detail="Invalid action")
