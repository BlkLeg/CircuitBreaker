"""DB-backed device role catalog — replaces hardcoded _VALID_ROLES and ROLE_RANK."""

from __future__ import annotations

import logging
import re

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.db.models import AppSettings, DeviceRole

_logger = logging.getLogger(__name__)


# ── Cache helpers ─────────────────────────────────────────────────────────────

# Module-level cache keyed on roles_version (an int).  Using Session objects as
# cache keys with @lru_cache never hits in production because each request gets
# a new Session instance with a distinct identity hash.
_roles_cache: dict[int, list] = {}


def _get_roles_version(db: Session) -> int:
    s = db.query(AppSettings).first()
    return s.roles_version if s else 0


def _get_roles_cached(db: Session, version: int) -> list[DeviceRole]:
    """Return all DeviceRole rows for *version*, fetching from DB on a cache miss."""
    if version not in _roles_cache:
        _roles_cache.clear()  # evict stale version(s) — we only ever need the latest
        _roles_cache[version] = (
            db.query(DeviceRole).order_by(DeviceRole.rank, DeviceRole.slug).all()
        )
    return _roles_cache[version]


def _bust_roles_cache(db: Session) -> None:
    """Increment roles_version so the next lookup fetches fresh data."""
    s = db.query(AppSettings).first()
    if s:
        s.roles_version = (s.roles_version or 0) + 1
        db.flush()
    _roles_cache.clear()


def _all_roles(db: Session) -> list[DeviceRole]:
    return _get_roles_cached(db, _get_roles_version(db))


# ── Public helpers ─────────────────────────────────────────────────────────────


def get_valid_slugs(db: Session, _version: int) -> set[str]:
    return {r.slug for r in _get_roles_cached(db, _version)}


def get_rank_map(db: Session, _version: int) -> dict[str, int]:
    return {r.slug: r.rank for r in _get_roles_cached(db, _version)}


def get_hint_map(db: Session, _version: int) -> dict[str, str]:
    """Map device_type hint string → role slug. Lower-rank roles win on conflict."""
    result: dict[str, str] = {}
    for role in _get_roles_cached(db, _version):
        for hint in role.device_type_hints or []:
            if hint not in result:
                result[hint] = role.slug
    return result


def get_hostname_map(db: Session, _version: int) -> list[tuple[str, str]]:
    """Return [(pattern, slug)] sorted longest-pattern-first for greedy matching."""
    pairs: list[tuple[str, str]] = []
    for role in _get_roles_cached(db, _version):
        for pattern in role.hostname_patterns or []:
            pairs.append((pattern, role.slug))
    pairs.sort(key=lambda p: len(p[0]), reverse=True)
    return pairs


def valid_slugs(db: Session) -> set[str]:
    return get_valid_slugs(db, _get_roles_version(db))


def rank_map(db: Session) -> dict[str, int]:
    return get_rank_map(db, _get_roles_version(db))


def hint_map(db: Session) -> dict[str, str]:
    return get_hint_map(db, _get_roles_version(db))


def hostname_map(db: Session) -> list[tuple[str, str]]:
    return get_hostname_map(db, _get_roles_version(db))


# ── CRUD ──────────────────────────────────────────────────────────────────────


def list_roles(db: Session) -> list[DeviceRole]:
    return _all_roles(db)


def create_role(
    db: Session,
    *,
    slug: str,
    label: str,
    rank: int = 5,
    icon_slug: str | None = None,
    device_type_hints: list[str] | None = None,
    hostname_patterns: list[str] | None = None,
) -> DeviceRole:
    if not re.fullmatch(r"[a-z][a-z0-9_]*", slug):
        raise HTTPException(
            status_code=422,
            detail="slug must be lowercase letters, digits, and underscores only",
        )
    existing = db.query(DeviceRole).filter(DeviceRole.slug == slug).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Role slug '{slug}' already exists")
    role = DeviceRole(
        slug=slug,
        label=label,
        rank=rank,
        icon_slug=icon_slug,
        is_builtin=False,
        device_type_hints=device_type_hints or [],
        hostname_patterns=hostname_patterns or [],
    )
    db.add(role)
    db.flush()
    _bust_roles_cache(db)
    return role


def update_role(
    db: Session,
    role_id: int,
    *,
    label: str | None = None,
    rank: int | None = None,
    icon_slug: str | None = None,
    device_type_hints: list[str] | None = None,
    hostname_patterns: list[str] | None = None,
) -> DeviceRole:
    role = db.query(DeviceRole).filter(DeviceRole.id == role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    if label is not None:
        role.label = label
    if rank is not None:
        role.rank = rank
    if icon_slug is not None:
        role.icon_slug = icon_slug
    if device_type_hints is not None:
        role.device_type_hints = device_type_hints
    if hostname_patterns is not None:
        role.hostname_patterns = hostname_patterns
    db.flush()
    _bust_roles_cache(db)
    return role


def delete_role(db: Session, role_id: int) -> None:
    role = db.query(DeviceRole).filter(DeviceRole.id == role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    if role.is_builtin:
        raise HTTPException(
            status_code=409, detail=f"Built-in role '{role.slug}' cannot be deleted"
        )
    db.delete(role)
    db.flush()
    _bust_roles_cache(db)
