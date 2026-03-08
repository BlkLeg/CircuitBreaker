"""FastAPI-Users configuration: UserManager, auth backends, and dependencies.

Central wiring for the fastapi-users library.  Uses an async SQLAlchemy
session (db/async_session.py) while the rest of the app stays sync.
"""

import logging
import re
import secrets
from collections.abc import AsyncGenerator

from fastapi import Depends, Request
from fastapi_users import BaseUserManager, FastAPIUsers, IntegerIDMixin
from fastapi_users.authentication import AuthenticationBackend, BearerTransport, JWTStrategy
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.async_session import get_async_db
from app.db.models import User

_logger = logging.getLogger(__name__)

_FALLBACK_SECRET = secrets.token_hex(32)


# ---------------------------------------------------------------------------
# User DB adapter
# ---------------------------------------------------------------------------


async def get_user_db(
    session: AsyncSession = Depends(get_async_db),
) -> AsyncGenerator[SQLAlchemyUserDatabase, None]:
    yield SQLAlchemyUserDatabase(session, User)


# ---------------------------------------------------------------------------
# UserManager
# ---------------------------------------------------------------------------


class UserManager(IntegerIDMixin, BaseUserManager[User, int]):  # type: ignore[type-var]
    """Custom user manager with audit logging hooks and password validation."""

    async def validate_password(self, password: str, user: User | None = None) -> None:  # type: ignore[override]
        errors: list[str] = []
        if len(password) < 8:
            errors.append("at least 8 characters")
        if not re.search(r"[A-Z]", password):
            errors.append("one uppercase letter")
        if not re.search(r"[a-z]", password):
            errors.append("one lowercase letter")
        if not re.search(r"\d", password):
            errors.append("one digit")
        if not re.search(r"[^A-Za-z0-9]", password):
            errors.append("one special character")
        if errors:
            from fastapi_users.exceptions import InvalidPasswordException

            raise InvalidPasswordException(reason=f"Password must contain: {', '.join(errors)}")

    async def on_after_register(self, user: User, request: Request | None = None) -> None:
        from app.services.log_service import write_log

        write_log(
            db=None,
            action="register_user",
            entity_type="user",
            entity_id=user.id,
            entity_name=user.display_name or user.email,
            severity="info",
            category="auth",
            actor_name=user.display_name or user.email,
            actor_id=user.id,
        )

    async def on_after_login(
        self,
        user: User,
        request: Request | None = None,
        response=None,
    ) -> None:
        import json

        from app.db.session import SessionLocal
        from app.services.log_service import write_log
        from app.services.user_service import record_session

        ip = request.client.host if request and request.client else None

        # Extract the raw JWT from the response body so we can record the session.
        raw_token: str | None = None
        try:
            if response is not None and hasattr(response, "body"):
                raw_token = json.loads(response.body).get("access_token")
        except Exception:
            pass

        # Write last_login and record the session using the sync session.
        db = SessionLocal()
        try:
            from app.core.time import utcnow_iso

            db_user = db.get(User, user.id)
            if db_user:
                db_user.last_login = utcnow_iso()
                db.commit()
                db.refresh(db_user)
                if raw_token:
                    record_session(db, db_user, request, raw_token)
        except Exception:
            _logger.exception("on_after_login: failed to persist last_login/session")
        finally:
            db.close()

        write_log(
            db=None,
            action="login_success",
            entity_type="auth",
            entity_id=user.id,
            entity_name=user.display_name or user.email,
            severity="info",
            category="auth",
            ip_address=ip,
            actor_name=user.display_name or user.email,
            actor_id=user.id,
        )

    async def on_after_forgot_password(
        self, user: User, token: str, request: Request | None = None
    ) -> None:
        from app.db.session import SessionLocal
        from app.services.settings_service import get_or_create_settings
        from app.services.smtp_service import SmtpService

        db = SessionLocal()
        try:
            cfg = get_or_create_settings(db)
            if cfg.smtp_enabled and cfg.smtp_from_email:
                from app.services.smtp_service import (
                    public_base_from_request_headers,
                    resolve_public_base_url,
                )

                if request:
                    request_headers = getattr(request, "headers", None)
                    request_base_url = str(getattr(request, "base_url", "")).rstrip("/")
                    header_fallback = (
                        public_base_from_request_headers(request_headers, request_base_url)
                        if request_headers is not None
                        else request_base_url
                    )
                else:
                    header_fallback = ""
                base_url = resolve_public_base_url(cfg, header_fallback)
                await SmtpService(cfg).send_password_reset(user.email, token, base_url)
                _logger.info("Password reset email sent to %s", user.email)
            else:
                _logger.info(
                    "Password reset token for %s (SMTP not configured): %s",
                    user.email,
                    token,
                )
        except Exception as exc:
            _logger.warning("Failed to send password reset email to %s: %s", user.email, exc)
        finally:
            db.close()


async def get_user_manager(
    user_db: SQLAlchemyUserDatabase = Depends(get_user_db),
) -> AsyncGenerator[UserManager, None]:
    manager = UserManager(user_db)
    manager.reset_password_token_secret = _get_jwt_secret()
    manager.verification_token_secret = _get_jwt_secret()
    yield manager


# ---------------------------------------------------------------------------
# Auth backend: Bearer + JWT
# ---------------------------------------------------------------------------

bearer_transport = BearerTransport(tokenUrl="/api/v1/auth/jwt/login")


def _get_jwt_secret() -> str:
    """Read jwt_secret from AppSettings at call time, with fallback."""
    try:
        from app.db.session import SessionLocal
        from app.services.settings_service import get_or_create_settings

        db = SessionLocal()
        try:
            cfg = get_or_create_settings(db)
            if cfg.jwt_secret:
                return cfg.jwt_secret
        finally:
            db.close()
    except Exception:
        pass
    return _FALLBACK_SECRET


def get_jwt_strategy() -> JWTStrategy:
    try:
        from app.db.session import SessionLocal
        from app.services.settings_service import get_or_create_settings

        db = SessionLocal()
        try:
            cfg = get_or_create_settings(db)
            lifetime = cfg.session_timeout_hours * 3600
            secret = cfg.jwt_secret or _FALLBACK_SECRET
        finally:
            db.close()
    except Exception:
        lifetime = 86400
        secret = _FALLBACK_SECRET
    return JWTStrategy(secret=secret, lifetime_seconds=lifetime)


auth_backend = AuthenticationBackend(
    name="jwt",
    transport=bearer_transport,
    get_strategy=get_jwt_strategy,
)


# ---------------------------------------------------------------------------
# FastAPIUsers instance and common dependencies
# ---------------------------------------------------------------------------

fastapi_users = FastAPIUsers[User, int](get_user_manager, [auth_backend])  # type: ignore[type-var]

current_active_user = fastapi_users.current_user(active=True)
current_superuser = fastapi_users.current_user(active=True, superuser=True)
current_optional_user = fastapi_users.current_user(active=True, optional=True)
