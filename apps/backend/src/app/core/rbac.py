"""Role-based access control for Phase 6.5 user management.

Provides require_role() dependency factory for FastAPI endpoints.
"""

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.security import get_optional_user
from app.core.time import utcnow
from app.db.models import User
from app.db.session import get_db

ROLE_HIERARCHY = {"viewer": 0, "editor": 1, "admin": 2}
VALID_ROLES = frozenset(ROLE_HIERARCHY)


def _service_user() -> User:
    """Return a sentinel User for service account (CB_API_TOKEN)."""
    from types import SimpleNamespace

    u = SimpleNamespace()
    u.id = 0
    u.email = "api-token@system"
    u.role = "admin"
    u.is_admin = True
    u.is_superuser = True
    u.is_active = True
    u.locked_until = None
    return u  # type: ignore[return-value]


def require_role(*roles: str):
    """FastAPI dependency that checks user role against allowed roles.

    - Service account (user_id=0) and is_superuser bypass all checks.
    - Locked users receive 423 Locked.
    - Insufficient role receives 403 Forbidden.
    """

    async def _dep(
        user_id: int | None = Depends(get_optional_user),
        db: Session = Depends(get_db),
    ) -> User:
        if user_id is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        if user_id == 0:
            return _service_user()
        user = db.get(User, user_id)
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        if user.locked_until and user.locked_until > utcnow():
            raise HTTPException(
                status_code=423,
                detail="Account locked due to failed login attempts. Contact an administrator.",
            )
        if user.is_superuser:
            return user
        effective_role = getattr(user, "role", None) or ("admin" if user.is_admin else "viewer")
        if effective_role not in roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user

    return Depends(_dep)
