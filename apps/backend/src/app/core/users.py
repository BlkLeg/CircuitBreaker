"""FastAPI-Users configuration: UserManager, auth backends, and dependencies.

Central wiring for the fastapi-users library.  Uses an async SQLAlchemy
session (db/async_session.py) while the rest of the app stays sync.
"""

import logging
import os
import re
from collections.abc import AsyncGenerator

from fastapi import Depends, Request, Response
from fastapi_users import BaseUserManager, FastAPIUsers, IntegerIDMixin
from fastapi_users.authentication import AuthenticationBackend, BearerTransport, JWTStrategy
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.async_session import get_async_db
from app.db.models import User

_logger = logging.getLogger(__name__)

# JWT secret: DB (from OOBE/settings) or CB_JWT_SECRET env only.
# No vault/API-token or runtime random.
CB_JWT_SECRET_ENV = "CB_JWT_SECRET"


# ---------------------------------------------------------------------------
# Password helper — wraps the app's existing bcrypt hash/verify so that
# FastAPI-Users endpoints (forgot-password, reset-password) produce the
# same hash format as the custom auth layer in core/security.py.
# ---------------------------------------------------------------------------


class _BcryptPasswordHelper:
    """Minimal PasswordHelper implementation backed by the app's own bcrypt usage."""

    def hash(self, password: str) -> str:
        import bcrypt as _bc

        return _bc.hashpw(password.encode(), _bc.gensalt()).decode()

    def verify_and_update(self, plain_password: str, hashed_password: str) -> tuple[bool, str]:
        import bcrypt as _bc

        try:
            valid = _bc.checkpw(plain_password.encode(), hashed_password.encode())
        except Exception:
            return False, hashed_password
        return valid, hashed_password

    def generate(self) -> str:
        import secrets

        return secrets.token_urlsafe(16)


_password_helper = _BcryptPasswordHelper()


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
        response: Response | None = None,
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


async def get_user_manager(
    user_db: SQLAlchemyUserDatabase = Depends(get_user_db),
) -> AsyncGenerator[UserManager, None]:
    manager = UserManager(user_db, password_helper=_password_helper)
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

    # Dedicated JWT secret only; no vault/API-token or auto-generation.
    env_secret = os.environ.get(CB_JWT_SECRET_ENV)
    if env_secret:
        return env_secret
    return ""


def get_jwt_strategy() -> JWTStrategy:
    try:
        from app.db.session import SessionLocal
        from app.services.settings_service import get_or_create_settings

        db = SessionLocal()
        try:
            cfg = get_or_create_settings(db)
            lifetime = cfg.session_timeout_hours * 3600
            secret = cfg.jwt_secret or os.environ.get(CB_JWT_SECRET_ENV) or ""
        finally:
            db.close()
    except Exception:
        lifetime = 86400
        secret = os.environ.get(CB_JWT_SECRET_ENV) or ""

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
