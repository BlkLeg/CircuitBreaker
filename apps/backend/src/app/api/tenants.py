"""Tenant Management API - Multi-tenancy CRUD and member management."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.rbac import require_role
from app.core.time import utcnow
from app.db.models import Tenant, User
from app.db.session import get_db
from app.schemas.tenant import (
    TenantCreate,
    TenantMemberAdd,
    TenantMemberRead,
    TenantMemberUpdate,
    TenantRead,
    TenantUpdate,
    TenantWithMembersRead,
)
from app.services.log_service import write_log

_logger = logging.getLogger(__name__)

router = APIRouter(tags=["tenants"])


# ── Tenant CRUD ───────────────────────────────────────────────────────────────


@router.get("", response_model=list[TenantRead])
def list_tenants(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _=require_role("admin"),
):
    """List all tenants (admin only)."""
    q = select(Tenant).order_by(Tenant.created_at.desc()).offset(offset).limit(limit)
    tenants = db.execute(q).scalars().all()
    return tenants


@router.get("/{tenant_id}", response_model=TenantWithMembersRead)
def get_tenant(
    tenant_id: int,
    db: Session = Depends(get_db),
    _=require_role("admin"),
):
    """Get tenant by ID with member list (admin only)."""
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    # Build member list with user details and tenant_role
    members_data = []
    member_rows = db.execute(
        text(
            """
            SELECT u.id, u.email, u.display_name, tm.tenant_role
            FROM users u
            JOIN tenant_members tm ON u.id = tm.user_id
            WHERE tm.tenant_id = :tenant_id
            ORDER BY u.email
            """
        ),
        {"tenant_id": tenant_id},
    ).fetchall()

    for row in member_rows:
        members_data.append(
            TenantMemberRead(
                user_id=row[0],
                email=row[1],
                display_name=row[2],
                tenant_role=row[3],
            )
        )

    result = TenantWithMembersRead.model_validate(tenant)
    result.members = members_data
    return result


@router.post("", response_model=TenantRead, status_code=201)
def create_tenant(
    payload: TenantCreate,
    db: Session = Depends(get_db),
    current_user=require_role("admin"),
):
    """Create a new tenant (admin only)."""
    # Check for duplicate name
    existing = db.execute(select(Tenant).where(Tenant.name == payload.name)).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Tenant with this name already exists")

    # Check for duplicate slug if provided
    if payload.slug:
        existing_slug = db.execute(
            select(Tenant).where(Tenant.slug == payload.slug)
        ).scalar_one_or_none()
        if existing_slug:
            raise HTTPException(status_code=409, detail="Tenant with this slug already exists")

    tenant = Tenant(**payload.model_dump())
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    try:
        write_log(
            db,
            action="tenant_created",
            entity_type="tenant",
            entity_id=tenant.id,
            entity_name=tenant.name,
            actor=current_user.email if hasattr(current_user, "email") else str(current_user.id),
        )
    except Exception as exc:
        _logger.debug("Failed to write audit log for tenant creation (non-fatal): %s", exc)

    return tenant


@router.patch("/{tenant_id}", response_model=TenantRead)
def update_tenant(
    tenant_id: int,
    payload: TenantUpdate,
    db: Session = Depends(get_db),
    current_user=require_role("admin"),
):
    """Update tenant (admin only)."""
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    # Check for duplicate name if changing
    if payload.name and payload.name != tenant.name:
        existing = db.execute(
            select(Tenant).where(Tenant.name == payload.name, Tenant.id != tenant_id)
        ).scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=409, detail="Tenant with this name already exists")

    # Check for duplicate slug if changing
    if payload.slug and payload.slug != tenant.slug:
        existing_slug = db.execute(
            select(Tenant).where(Tenant.slug == payload.slug, Tenant.id != tenant_id)
        ).scalar_one_or_none()
        if existing_slug:
            raise HTTPException(status_code=409, detail="Tenant with this slug already exists")

    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(tenant, key, value)

    tenant.updated_at = utcnow()
    db.commit()
    db.refresh(tenant)

    try:
        write_log(
            db,
            action="tenant_updated",
            entity_type="tenant",
            entity_id=tenant.id,
            entity_name=tenant.name,
            actor=current_user.email if hasattr(current_user, "email") else str(current_user.id),
        )
    except Exception as exc:
        _logger.debug("Failed to write audit log for tenant update (non-fatal): %s", exc)

    return tenant


@router.delete("/{tenant_id}", status_code=204)
def delete_tenant(
    tenant_id: int,
    db: Session = Depends(get_db),
    current_user=require_role("admin"),
):
    """Delete tenant (admin only). Cascades to tenant_members."""
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    tenant_name = tenant.name

    try:
        write_log(
            db,
            action="tenant_deleted",
            entity_type="tenant",
            entity_id=tenant.id,
            entity_name=tenant_name,
            actor=current_user.email if hasattr(current_user, "email") else str(current_user.id),
        )
    except Exception as exc:
        _logger.debug("Failed to write audit log for tenant deletion (non-fatal): %s", exc)

    db.delete(tenant)
    db.commit()


# ── Member Management ─────────────────────────────────────────────────────────


@router.get("/{tenant_id}/members", response_model=list[TenantMemberRead])
def list_tenant_members(
    tenant_id: int,
    db: Session = Depends(get_db),
    _=require_role("admin"),
):
    """List all members of a tenant (admin only)."""
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    member_rows = db.execute(
        text(
            """
            SELECT u.id, u.email, u.display_name, tm.tenant_role
            FROM users u
            JOIN tenant_members tm ON u.id = tm.user_id
            WHERE tm.tenant_id = :tenant_id
            ORDER BY u.email
            """
        ),
        {"tenant_id": tenant_id},
    ).fetchall()

    members = []
    for row in member_rows:
        members.append(
            TenantMemberRead(
                user_id=row[0],
                email=row[1],
                display_name=row[2],
                tenant_role=row[3],
            )
        )

    return members


@router.post("/{tenant_id}/members", response_model=dict[str, Any], status_code=201)
def add_tenant_member(
    tenant_id: int,
    payload: TenantMemberAdd,
    db: Session = Depends(get_db),
    current_user=require_role("admin"),
):
    """Add a user to a tenant (admin only)."""
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    user = db.get(User, payload.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Check if user is already a member
    existing = db.execute(
        text("SELECT 1 FROM tenant_members WHERE tenant_id = :tenant_id AND user_id = :user_id"),
        {"tenant_id": tenant_id, "user_id": payload.user_id},
    ).scalar_one_or_none()

    if existing:
        raise HTTPException(status_code=409, detail="User is already a member of this tenant")

    # Add member
    db.execute(
        text(
            """
            INSERT INTO tenant_members (tenant_id, user_id, tenant_role)
            VALUES (:tenant_id, :user_id, :tenant_role)
            """
        ),
        {"tenant_id": tenant_id, "user_id": payload.user_id, "tenant_role": payload.tenant_role},
    )
    db.commit()

    try:
        write_log(
            db,
            action="tenant_member_added",
            entity_type="tenant",
            entity_id=tenant.id,
            entity_name=tenant.name,
            details=f"user_id={payload.user_id}, role={payload.tenant_role}",
            actor=current_user.email if hasattr(current_user, "email") else str(current_user.id),
        )
    except Exception as exc:
        _logger.debug("Failed to write audit log for member addition (non-fatal): %s", exc)

    return {"status": "success", "tenant_id": tenant_id, "user_id": payload.user_id}


@router.patch("/{tenant_id}/members/{user_id}", response_model=dict[str, Any])
def update_tenant_member(
    tenant_id: int,
    user_id: int,
    payload: TenantMemberUpdate,
    db: Session = Depends(get_db),
    current_user=require_role("admin"),
):
    """Update a tenant member's role (admin only)."""
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    # Check if member exists
    existing = db.execute(
        text(
            "SELECT tenant_role FROM tenant_members WHERE tenant_id = :tenant_id AND user_id = :user_id"
        ),
        {"tenant_id": tenant_id, "user_id": user_id},
    ).scalar_one_or_none()

    if not existing:
        raise HTTPException(status_code=404, detail="User is not a member of this tenant")

    # Update role
    db.execute(
        text(
            """
            UPDATE tenant_members
            SET tenant_role = :tenant_role
            WHERE tenant_id = :tenant_id AND user_id = :user_id
            """
        ),
        {"tenant_id": tenant_id, "user_id": user_id, "tenant_role": payload.tenant_role},
    )
    db.commit()

    try:
        write_log(
            db,
            action="tenant_member_updated",
            entity_type="tenant",
            entity_id=tenant.id,
            entity_name=tenant.name,
            details=f"user_id={user_id}, new_role={payload.tenant_role}",
            actor=current_user.email if hasattr(current_user, "email") else str(current_user.id),
        )
    except Exception as exc:
        _logger.debug("Failed to write audit log for member update (non-fatal): %s", exc)

    return {"status": "success", "tenant_id": tenant_id, "user_id": user_id}


@router.delete("/{tenant_id}/members/{user_id}", status_code=204)
def remove_tenant_member(
    tenant_id: int,
    user_id: int,
    db: Session = Depends(get_db),
    current_user=require_role("admin"),
):
    """Remove a user from a tenant (admin only)."""
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    # Check if member exists
    existing = db.execute(
        text("SELECT 1 FROM tenant_members WHERE tenant_id = :tenant_id AND user_id = :user_id"),
        {"tenant_id": tenant_id, "user_id": user_id},
    ).scalar_one_or_none()

    if not existing:
        raise HTTPException(status_code=404, detail="User is not a member of this tenant")

    # Remove member
    db.execute(
        text("DELETE FROM tenant_members WHERE tenant_id = :tenant_id AND user_id = :user_id"),
        {"tenant_id": tenant_id, "user_id": user_id},
    )
    db.commit()

    try:
        write_log(
            db,
            action="tenant_member_removed",
            entity_type="tenant",
            entity_id=tenant.id,
            entity_name=tenant.name,
            details=f"user_id={user_id}",
            actor=current_user.email if hasattr(current_user, "email") else str(current_user.id),
        )
    except Exception as exc:
        _logger.debug("Failed to write audit log for member removal (non-fatal): %s", exc)
