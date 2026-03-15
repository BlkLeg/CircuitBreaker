"""Tenant schemas for multi-tenancy API."""

from datetime import datetime

from pydantic import BaseModel, Field


class TenantBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    slug: str | None = Field(None, max_length=32, pattern=r"^[a-z0-9-]+$")


class TenantCreate(TenantBase):
    pass


class TenantUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    slug: str | None = Field(None, max_length=32, pattern=r"^[a-z0-9-]+$")


class TenantRead(TenantBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TenantMemberRead(BaseModel):
    user_id: int
    email: str
    display_name: str | None = None
    tenant_role: str = "member"

    model_config = {"from_attributes": True}


class TenantMemberAdd(BaseModel):
    user_id: int
    tenant_role: str = Field("member", pattern=r"^(member|admin|owner)$")


class TenantMemberUpdate(BaseModel):
    tenant_role: str = Field(..., pattern=r"^(member|admin|owner)$")


class TenantWithMembersRead(TenantRead):
    members: list[TenantMemberRead] = []
