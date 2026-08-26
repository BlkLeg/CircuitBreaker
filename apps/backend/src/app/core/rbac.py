"""Role and scope-based access control dependencies."""

from __future__ import annotations

import json
from datetime import UTC
from typing import cast

from fastapi import Depends, HTTPException, params
from sqlalchemy.orm import Session
from starlette.requests import HTTPConnection

from app.core.security import get_optional_user
from app.core.time import utcnow
from app.db.models import User
from app.db.session import get_db

ROLE_HIERARCHY = {"viewer": 0, "editor": 1, "admin": 2, "demo": 0}
VALID_ROLES = frozenset(ROLE_HIERARCHY)
_SCOPE_READ_ALL = "read:*"
_SCOPE_WRITE_ALL = "write:*"
_SCOPE_DELETE_ALL = "delete:*"
_SCOPE_ADMIN_ALL = "admin:*"

ROLE_DEFAULT_SCOPES: dict[str, set[str]] = {
    "viewer": {_SCOPE_READ_ALL},
    "demo": {_SCOPE_READ_ALL},
    "editor": {
        _SCOPE_READ_ALL,
        "write:hardware",
        "write:services",
        "write:networks",
        "write:clusters",
        "write:external",
        "write:compute",
        "write:storage",
        "write:misc",
        "write:docs",
        "write:graph",
        "write:layout",
    },
    "admin": {_SCOPE_READ_ALL, _SCOPE_WRITE_ALL, _SCOPE_DELETE_ALL, _SCOPE_ADMIN_ALL},
}

# What a TOKEN must hold to satisfy a require_role gate. Roles are a user
# concept; a token carries scopes, so a role gate has to be expressed as a
# scope check before it can mean anything for a token. The mapping mirrors
# ROLE_DEFAULT_SCOPES above — the scope each role's default set is defined by —
# so the two cannot describe different privilege ladders.
ROLE_SCOPE_REQUIREMENT: dict[str, tuple[str, str]] = {
    "viewer": ("read", "*"),
    "demo": ("read", "*"),
    "editor": ("write", "*"),
    "admin": ("admin", "*"),
}


def _service_user() -> User:
    """Return a sentinel User for service account (CB_API_TOKEN)."""
    from types import SimpleNamespace

    u = SimpleNamespace()
    u.id = 0
    u.email = "api-token@system"
    u.role = "admin"
    u.scopes = json.dumps(sorted(ROLE_DEFAULT_SCOPES["admin"]))
    u.is_admin = True
    u.is_superuser = True
    u.is_active = True
    u.locked_until = None
    u.demo_expires = None
    return u  # type: ignore[return-value]


def _effective_role(user: User) -> str:
    role = (getattr(user, "role", None) or ("admin" if user.is_admin else "viewer")).lower()
    return role if role in VALID_ROLES else "viewer"


def _explicit_scopes(user: User) -> set[str]:
    raw = getattr(user, "scopes", None)
    if not raw:
        return set()
    if isinstance(raw, list):
        return {str(x).strip() for x in raw if str(x).strip()}
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return {str(x).strip() for x in parsed if str(x).strip()}
    except Exception:
        return set()
    return set()


def effective_scopes(user: User) -> set[str]:
    role = _effective_role(user)
    defaults = ROLE_DEFAULT_SCOPES.get(role, ROLE_DEFAULT_SCOPES["viewer"])
    explicit = _explicit_scopes(user)
    if explicit:
        return set(defaults).union(explicit)
    return set(defaults)


def has_scope(user_scopes: set[str], action: str, resource: str) -> bool:
    needed = f"{action}:{resource}"
    if needed in user_scopes:
        return True
    if f"{action}:*" in user_scopes:
        return True
    if f"*:{resource}" in user_scopes:
        return True
    if "*:*" in user_scopes:
        return True
    # Legacy/editor compatibility where resource groups are slash-separated.
    if "/" in resource and f"{action}:{resource.split('/')[0]}" in user_scopes:
        return True
    return False


def _request_token_scopes(request: HTTPConnection) -> set[str] | None:
    raw = getattr(request.state, "token_scopes", None)
    if raw is None:
        return None
    return {str(scope).strip() for scope in raw if str(scope).strip()}


def _is_demo_expired(user: User) -> bool:
    demo_expires = getattr(user, "demo_expires", None)
    if not demo_expires:
        return False
    expiry = demo_expires
    if getattr(expiry, "tzinfo", None) is None:
        expiry = expiry.replace(tzinfo=UTC)
    return bool(expiry <= utcnow())


def require_role(*roles: str) -> params.Depends:
    """FastAPI dependency that checks user role against allowed roles.

    - Service account (user_id=0) and is_superuser bypass all checks.
    - Locked users receive 423 Locked.
    - Insufficient role receives 403 Forbidden.
    - A scoped token is checked against the role's scope requirement (B1/INC-14).
    """

    # What a TOKEN must hold to satisfy a require_role gate for these roles.
    # Roles are a user concept; a token carries scopes, so a role gate has to
    # be expressed as a scope check before it can mean anything for a token.
    # The mapping mirrors ROLE_DEFAULT_SCOPES — the scope each role's default
    # set is defined by — so the two cannot describe different ladders.
    # Uses the LOWEST-ranked accepted role, matching require_role's own
    # min(allowed_ranks) logic.
    ranked = sorted(roles, key=lambda r: ROLE_HIERARCHY.get(r, 0))
    lowest = ranked[0] if ranked else "admin"
    role_scope = ROLE_SCOPE_REQUIREMENT.get(lowest, ("admin", "*"))

    async def _dep(
        request: HTTPConnection,
        user_id: int | None = Depends(get_optional_user),
        db: Session = Depends(get_db),
    ) -> User:
        if user_id is None:
            raise HTTPException(status_code=401, detail="Authentication required")

        # A request authenticated by a scoped token is limited by that token,
        # even on role-guarded routes. Without this, scopes narrowed only the
        # two require_scope checks in the codebase and every token was a
        # superuser everywhere else (INC-14). token_scopes is None for session
        # users and for legacy unscoped tokens, so this branch never runs for
        # them and their behaviour is unchanged.
        token_scopes = _request_token_scopes(request)
        if token_scopes is not None and roles:
            action, resource = role_scope
            if not has_scope(token_scopes, action, resource):
                raise HTTPException(status_code=403, detail="Insufficient permissions")

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
        role = _effective_role(user)
        if role == "demo" and _is_demo_expired(user):
            raise HTTPException(status_code=401, detail="Demo session expired")
        if user.is_superuser:
            return user

        # Check hierarchy: if any requested role is satisfied by user's role rank
        user_rank = ROLE_HIERARCHY.get(role, 0)
        allowed_ranks = [ROLE_HIERARCHY.get(r, 0) for r in roles]
        if not allowed_ranks:
            return user
        if user_rank < min(allowed_ranks):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user

    # What this gate actually demands, readable without running it. The SEC-06
    # write gate needs to tell `require_scope("read", "*")` apart from a scope
    # that permits writing, and both compile to the same `_dep` qualname, so the
    # declaration has to travel on the object rather than in its name.
    _dep.cb_authorization = ("role", tuple(roles))  # type: ignore[attr-defined]

    return cast(params.Depends, Depends(_dep))


def require_scope(action: str, resource: str) -> params.Depends:
    """FastAPI dependency for scope-based authorization."""

    async def _dep(
        request: HTTPConnection,
        user_id: int | None = Depends(get_optional_user),
        db: Session = Depends(get_db),
    ) -> User:
        if user_id is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        token_scopes = _request_token_scopes(request)
        if user_id == 0:
            if token_scopes is not None:
                if has_scope(token_scopes, action, resource):
                    return _service_user()
                raise HTTPException(status_code=403, detail="Insufficient permissions")
            return _service_user()

        user = db.get(User, user_id)
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        if user.locked_until and user.locked_until > utcnow():
            raise HTTPException(
                status_code=423,
                detail="Account locked due to failed login attempts. Contact an administrator.",
            )
        role = _effective_role(user)
        if role == "demo" and _is_demo_expired(user):
            raise HTTPException(status_code=401, detail="Demo session expired")
        if token_scopes is not None:
            if has_scope(token_scopes, action, resource):
                return user
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        if user.is_superuser:
            return user

        scopes = effective_scopes(user)
        if has_scope(scopes, action, resource):
            return user

        raise HTTPException(status_code=403, detail="Insufficient permissions")

    # See the note in require_role: the declared action/resource is what lets a
    # structural gate judge whether this authorizes a write or only a read.
    _dep.cb_authorization = ("scope", action, resource)  # type: ignore[attr-defined]

    return cast(params.Depends, Depends(_dep))
