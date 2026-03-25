"""Tenants API — CRUD and member management."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from app.core.rbac import require_role
from app.db.models import Tenant, User, tenant_members
from app.db.session import get_db

router = APIRouter()


# ── Schemas ──────────────────────────────────────────────────────────────────


class TenantOut(BaseModel):
    id: int
    name: str
    slug: str | None
    created_at: datetime | None
    updated_at: datetime | None

    model_config = {"from_attributes": True}


class TenantCreateRequest(BaseModel):
    name: str
    slug: str | None = None


class TenantUpdateRequest(BaseModel):
    name: str | None = None
    slug: str | None = None


class MemberOut(BaseModel):
    id: int
    email: str
    display_name: str | None
    tenant_role: str


class AddMemberRequest(BaseModel):
    user_id: int
    role: str = "member"


# ── Routes ───────────────────────────────────────────────────────────────────


@router.get("", response_model=list[TenantOut])
def list_tenants(db: Session = Depends(get_db)):
    return db.execute(select(Tenant).order_by(Tenant.name)).scalars().all()


@router.get("/{tenant_id}", response_model=TenantOut)
def get_tenant(
    tenant_id: int,
    db: Session = Depends(get_db),
):
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant


@router.post("", response_model=TenantOut, status_code=201)
def create_tenant(
    body: TenantCreateRequest,
    _user: Annotated[User, require_role("admin")],
    db: Session = Depends(get_db),
):
    tenant = Tenant(name=body.name, slug=body.slug or None)
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    return tenant


@router.patch("/{tenant_id}", response_model=TenantOut)
def update_tenant(
    tenant_id: int,
    body: TenantUpdateRequest,
    _user: Annotated[User, require_role("admin")],
    db: Session = Depends(get_db),
):
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if body.name is not None:
        tenant.name = body.name
    if body.slug is not None:
        tenant.slug = body.slug or None
    db.commit()
    db.refresh(tenant)
    return tenant


@router.delete("/{tenant_id}", status_code=204)
def delete_tenant(
    tenant_id: int,
    _user: Annotated[User, require_role("admin")],
    db: Session = Depends(get_db),
):
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    db.delete(tenant)
    db.commit()


@router.get("/{tenant_id}/members", response_model=list[MemberOut])
def get_members(
    tenant_id: int,
    _user: Annotated[User, require_role("admin")],
    db: Session = Depends(get_db),
):
    if not db.get(Tenant, tenant_id):
        raise HTTPException(status_code=404, detail="Tenant not found")
    rows = db.execute(
        select(User, tenant_members.c.tenant_role)
        .join(tenant_members, User.id == tenant_members.c.user_id)
        .where(tenant_members.c.tenant_id == tenant_id)
    ).all()
    return [
        MemberOut(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
            tenant_role=role,
        )
        for user, role in rows
    ]


@router.post("/{tenant_id}/members", status_code=201)
def add_member(
    tenant_id: int,
    body: AddMemberRequest,
    _user: Annotated[User, require_role("admin")],
    db: Session = Depends(get_db),
):
    if not db.get(Tenant, tenant_id):
        raise HTTPException(status_code=404, detail="Tenant not found")
    if not db.get(User, body.user_id):
        raise HTTPException(status_code=404, detail="User not found")
    # Upsert — remove existing row first to avoid PK conflict
    db.execute(
        delete(tenant_members).where(
            tenant_members.c.tenant_id == tenant_id,
            tenant_members.c.user_id == body.user_id,
        )
    )
    db.execute(
        insert(tenant_members).values(
            tenant_id=tenant_id,
            user_id=body.user_id,
            tenant_role=body.role,
        )
    )
    db.commit()
    return {"ok": True}


@router.delete("/{tenant_id}/members/{user_id}", status_code=204)
def remove_member(
    tenant_id: int,
    user_id: int,
    _user: Annotated[User, require_role("admin")],
    db: Session = Depends(get_db),
):
    db.execute(
        delete(tenant_members).where(
            tenant_members.c.tenant_id == tenant_id,
            tenant_members.c.user_id == user_id,
        )
    )
    db.commit()
