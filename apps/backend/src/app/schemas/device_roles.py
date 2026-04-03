"""Pydantic v2 schemas for the device roles API."""

from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DeviceRoleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    label: str
    rank: int
    icon_slug: str | None = None
    is_builtin: bool
    device_type_hints: list[str] = []
    hostname_patterns: list[str] = []
    created_at: datetime


class DeviceRoleCreate(BaseModel):
    slug: str
    label: str
    rank: int = Field(default=5, ge=1, le=5)
    icon_slug: str | None = None
    device_type_hints: list[str] = []
    hostname_patterns: list[str] = []

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, v: str) -> str:
        if not re.fullmatch(r"[a-z][a-z0-9_]*", v):
            raise ValueError(
                "slug must start with a lowercase letter and contain only"
                " lowercase letters, digits, and underscores"
            )
        return v

    @field_validator("label")
    @classmethod
    def validate_label(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("label cannot be empty")
        if len(v) > 64:
            raise ValueError("label must be 64 characters or fewer")
        return v


class DeviceRoleUpdate(BaseModel):
    label: str | None = None
    rank: int | None = Field(default=None, ge=1, le=5)
    icon_slug: str | None = None
    device_type_hints: list[str] | None = None
    hostname_patterns: list[str] | None = None

    @field_validator("label")
    @classmethod
    def validate_label(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("label cannot be empty")
            if len(v) > 64:
                raise ValueError("label must be 64 characters or fewer")
        return v
