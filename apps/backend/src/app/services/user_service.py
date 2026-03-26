"""Phase 6.5: User management — sessions, invites, lockout."""

import hashlib
import logging
import secrets
from datetime import UTC, timedelta

import jwt
from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import gravatar_hash, hash_password, invalidate_session_cache
from app.core.time import utcnow, utcnow_iso
from app.db.models import AppSettings, User, UserInvite, UserSession

_logger = logging.getLogger(__name__)

INVITE_TOKEN_AUD = "circuitbreaker:invite"
VALID_ROLES = frozenset({"admin", "editor", "viewer"})


def _get_settings(db: Session) -> AppSettings:
    from app.services.settings_service import get_or_create_settings

    return get_or_create_settings(db)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def record_session(
    db: Session,
    user: User,
    request: Request | None,
    token: str,
    cfg: AppSettings | None = None,
) -> UserSession | None:
    """Record a new session for the user. Enforce concurrent_sessions limit."""
    if user.id == 0:
        return None
    cfg = cfg or _get_settings(db)
    ip = request.client.host if request and request.client else None
    ua = (request.headers.get("User-Agent") or "")[:500] if request else None

    expires_at = utcnow() + timedelta(hours=cfg.session_timeout_hours)
    token_hash = _hash_token(token)

    # Enforce concurrent_sessions: revoke oldest
    active = (
        db.execute(
            select(UserSession)
            .where(UserSession.user_id == user.id)
            .where(UserSession.revoked == False)  # noqa: E712
            .where(UserSession.expires_at > utcnow())
            .order_by(UserSession.created_at.asc())
            .with_for_update()
        )
        .scalars()
        .all()
    )
    active = list(active)
    limit = getattr(cfg, "concurrent_sessions", 5)
    while len(active) >= limit:
        oldest = active.pop(0)
        oldest.revoked = True
        db.flush()

    session = UserSession(
        user_id=user.id,
        jwt_token_hash=token_hash,
        ip_address=ip,
        user_agent=ua,
        expires_at=expires_at,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def revoke_session(db: Session, session_id: int, user_id: int) -> bool:
    """Revoke a session. Only the owner or admin can revoke."""
    session = db.get(UserSession, session_id)
    if not session:
        return False
    if session.user_id != user_id:
        return False
    session.revoked = True
    db.commit()
    invalidate_session_cache(None)
    return True


def revoke_all_sessions(db: Session, user_id: int, except_token_hash: str | None = None) -> int:
    """Revoke all sessions for a user. Returns count revoked."""
    q = (
        db.query(UserSession)
        .filter(UserSession.user_id == user_id)
        .filter(UserSession.revoked == False)  # noqa: E712
    )
    if except_token_hash:
        q = q.filter(UserSession.jwt_token_hash != except_token_hash)
    sessions = q.all()
    revoked = 0
    for s in sessions:
        s.revoked = True
        revoked += 1
    db.commit()
    if revoked:
        invalidate_session_cache(None)
    return revoked


def revoke_token_session(db: Session, token: str | None) -> bool:
    """Revoke the specific tracked session that matches a raw JWT."""
    if not token:
        return False
    token_hash = _hash_token(token)
    session = (
        db.query(UserSession)
        .filter(UserSession.jwt_token_hash == token_hash)
        .filter(UserSession.revoked == False)  # noqa: E712
        .first()
    )
    if not session:
        return False
    session.revoked = True
    db.commit()
    invalidate_session_cache(token)
    return True


def record_failed_login(db: Session, user: User, cfg: AppSettings | None = None) -> None:
    """Increment login_attempts; lock if threshold reached."""
    if user.id == 0:
        return
    cfg = cfg or _get_settings(db)
    user.login_attempts = (user.login_attempts or 0) + 1
    threshold = getattr(cfg, "login_lockout_attempts", 5)
    lockout_min = getattr(cfg, "login_lockout_minutes", 15)
    if user.login_attempts >= threshold:
        user.locked_until = utcnow() + timedelta(minutes=lockout_min)
    db.commit()


def reset_login_attempts(db: Session, user: User) -> None:
    """Reset login_attempts and locked_until on successful login."""
    user.login_attempts = 0
    user.locked_until = None
    db.commit()


def unlock_user(db: Session, user_id: int) -> User | None:
    """Reset login_attempts and locked_until for a user."""
    user = db.get(User, user_id)
    if not user:
        return None
    user.login_attempts = 0
    user.locked_until = None
    db.commit()
    db.refresh(user)
    return user


def create_invite(
    db: Session,
    admin: User,
    email: str,
    role: str,
    cfg: AppSettings | None = None,
) -> tuple[UserInvite, str]:
    """Create an invite and return (invite, token)."""
    if role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"Invalid role: {role}")
    cfg = cfg or _get_settings(db)
    expiry_days = getattr(cfg, "invite_expiry_days", 7)
    expires = utcnow() + timedelta(days=expiry_days)

    from app.services.settings_service import get_or_create_settings

    settings = get_or_create_settings(db)
    secret = settings.jwt_secret or secrets.token_hex(32)
    payload = {
        "aud": INVITE_TOKEN_AUD,
        "email": email.strip().lower(),
        "role": role,
        "exp": expires,
    }
    token = jwt.encode(payload, secret, algorithm="HS256")
    if isinstance(token, bytes):  # type: ignore[unreachable]
        token = token.decode()  # type: ignore[unreachable]

    invite = UserInvite(
        token=token,
        email=email.strip().lower(),
        role=role,
        invited_by=admin.id if hasattr(admin, "id") else admin,
        expires=expires,
        status="pending",
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)

    from app.services.log_service import write_log

    write_log(
        db,
        action="invite_issued",
        entity_type="invite",
        entity_id=invite.id,
        entity_name=email,
        severity="info",
        category="auth",
        actor_id=admin.id if hasattr(admin, "id") else admin,  # type: ignore[arg-type]
        actor_name=getattr(admin, "display_name", None) or getattr(admin, "email", "admin"),  # type: ignore[arg-type]
        details=f"Invited {email} as {role}",
    )

    return invite, token


def accept_invite(
    db: Session,
    token: str,
    password: str,
    display_name: str | None = None,
) -> User:
    """Validate invite token, create user, mark invite accepted."""
    from app.services.settings_service import get_or_create_settings

    settings = get_or_create_settings(db)
    secret = settings.jwt_secret
    if not secret:
        raise HTTPException(status_code=400, detail="Invite system not configured")

    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"], audience=[INVITE_TOKEN_AUD])
    except jwt.PyJWTError as err:
        raise HTTPException(status_code=400, detail="Invalid or expired invite") from err

    email = payload.get("email")
    role = payload.get("role", "viewer")
    if not email or role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail="Invalid invite payload")

    invite = db.query(UserInvite).filter(UserInvite.token == token).first()
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found")
    if invite.status != "pending":
        raise HTTPException(status_code=400, detail="Invite already used or revoked")

    expires = invite.expires
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if expires < utcnow():
        invite.status = "expired"
        db.commit()
        raise HTTPException(status_code=400, detail="Invite has expired")

    from app.services.auth_service import _is_client_hash, _validate_password

    if _is_client_hash(password):
        pass
    else:
        _validate_password(password)

    now = utcnow_iso()
    user = User(
        email=email.strip().lower(),
        hashed_password=hash_password(password),
        gravatar_hash=gravatar_hash(email),
        display_name=display_name or email.split("@")[0],
        language=settings.language or "en",
        is_admin=(role == "admin"),
        is_superuser=(role == "admin"),
        is_active=True,
        created_at=now,
        role=role,
        invited_by=invite.invited_by,
    )
    db.add(user)
    db.flush()

    invite.status = "accepted"
    invite.accepted_at = utcnow()
    db.commit()
    db.refresh(user)

    from app.services.log_service import write_log

    write_log(
        db,
        action="invite_accepted",
        entity_type="user",
        entity_id=user.id,
        entity_name=user.display_name or user.email,
        severity="info",
        category="auth",
        actor_id=user.id,
        actor_name=user.display_name or user.email,
        details=f"Accepted invite as {role}",
    )

    return user


def revoke_invite(db: Session, invite_id: int) -> bool:
    """Revoke an invite."""
    invite = db.get(UserInvite, invite_id)
    if not invite:
        return False
    if invite.status != "pending":
        return False
    invite.status = "revoked"
    db.commit()
    return True


def is_session_revoked(db: Session, token: str) -> bool:
    """Check if the given token's session has been revoked."""
    token_hash = _hash_token(token)
    session = (
        db.query(UserSession)
        .filter(UserSession.jwt_token_hash == token_hash)
        .filter(UserSession.revoked == True)  # noqa: E712
    ).first()
    return session is not None


def consume_invite_for_oauth(
    db: Session,
    invite_token: str,
    oauth_email: str,
) -> tuple[str, str]:
    """Validate and consume an invite token during an OAuth sign-in.

    Decodes the JWT, verifies the DB record, enforces case-insensitive email
    match against the OAuth account, then marks the invite accepted.

    Returns:
        (email, role) to be used when creating the OAuth user.

    Raises:
        HTTPException 400 — invalid/expired token, wrong email, or already used.
    """
    from app.services.settings_service import get_or_create_settings

    settings = get_or_create_settings(db)
    secret = settings.jwt_secret
    if not secret:
        raise HTTPException(status_code=400, detail="Invite system not configured")

    try:
        payload = jwt.decode(
            invite_token, secret, algorithms=["HS256"], audience=[INVITE_TOKEN_AUD]
        )
    except jwt.PyJWTError as err:
        raise HTTPException(status_code=400, detail="Invalid or expired invite") from err

    invite_email = payload.get("email", "")
    role = payload.get("role", "viewer")
    if not invite_email or role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail="Invalid invite payload")

    if invite_email.lower() != oauth_email.strip().lower():
        raise HTTPException(
            status_code=400,
            detail="OAuth account email does not match this invite",
        )

    invite = db.query(UserInvite).filter(UserInvite.token == invite_token).first()
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found")
    if invite.status != "pending":
        raise HTTPException(status_code=400, detail="Invite already used or revoked")

    expires = invite.expires
    if expires.tzinfo is None:
        from datetime import UTC

        expires = expires.replace(tzinfo=UTC)
    if expires < utcnow():
        invite.status = "expired"
        db.commit()
        raise HTTPException(status_code=400, detail="Invite has expired")

    invite.status = "accepted"
    invite.accepted_at = utcnow()
    db.commit()

    return invite_email, role
