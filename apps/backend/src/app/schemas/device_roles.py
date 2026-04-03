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
    slug: str = Field(max_length=64)
    label: str
    rank: int = Field(default=5, ge=1, le=5)
    icon_slug: str | None = None
    device_type_hints: list[str] = Field(default=[], max_length=50)
    hostname_patterns: list[str] = Field(default=[], max_length=50)

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, v: str) -> str:
        if not re.fullmatch(r"[a-z][a-z0-9_]*", v):
            raise ValueError(
                "slug must start with a lowercase letter and contain only"
                " lowercase letters, digits, and underscores"
            )
        return v

    @field_validator("device_type_hints", "hostname_patterns", mode="before")
    @classmethod
    def validate_list_items(cls, v: list) -> list:
        for item in v:
            if not isinstance(item, str):
                raise ValueError("list items must be strings")
            if len(item) > 128:
                raise ValueError("each item must be 128 characters or fewer")
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
    device_type_hints: list[str] | None = Field(default=None, max_length=50)
    hostname_patterns: list[str] | None = Field(default=None, max_length=50)

    @field_validator("device_type_hints", "hostname_patterns", mode="before")
    @classmethod
    def validate_list_items(cls, v: list | None) -> list | None:
        if v is None:
            return v
        for item in v:
            if not isinstance(item, str):
                raise ValueError("list items must be strings")
            if len(item) > 128:
                raise ValueError("each item must be 128 characters or fewer")
        return v

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
