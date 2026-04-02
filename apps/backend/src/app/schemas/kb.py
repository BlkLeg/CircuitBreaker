"""Pydantic schemas for the KB (knowledge base) management API."""

from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, field_validator

_HEX6 = re.compile(r"^[0-9A-Fa-f]{6}$")


class KbOuiOut(BaseModel):
    prefix: str
    vendor: str
    device_type: str | None
    os_family: str | None
    source: str
    seen_count: int
    first_seen_at: datetime
    last_seen_at: datetime

    model_config = {"from_attributes": True}


class KbOuiCreate(BaseModel):
    prefix: str
    vendor: str
    device_type: str | None = None
    os_family: str | None = None

    @field_validator("prefix")
    @classmethod
    def validate_prefix(cls, v: str) -> str:
        v = v.upper().strip()
        if not _HEX6.match(v):
            raise ValueError("prefix must be exactly 6 hexadecimal characters")
        return v

    @field_validator("vendor")
    @classmethod
    def strip_vendor(cls, v: str) -> str:
        return v.strip()[:128]


class KbOuiUpdate(BaseModel):
    vendor: str | None = None
    device_type: str | None = None
    os_family: str | None = None

    @field_validator("vendor")
    @classmethod
    def strip_vendor(cls, v: str | None) -> str | None:
        return v.strip()[:128] if v else v


_MATCH_TYPES = {"prefix", "exact", "contains"}


class KbHostnameOut(BaseModel):
    id: int
    pattern: str
    match_type: str
    vendor: str | None
    device_type: str | None
    os_family: str | None
    source: str
    seen_count: int
    first_seen_at: datetime
    last_seen_at: datetime

    model_config = {"from_attributes": True}


class KbHostnameCreate(BaseModel):
    pattern: str
    match_type: str = "prefix"
    vendor: str | None = None
    device_type: str | None = None
    os_family: str | None = None

    @field_validator("pattern")
    @classmethod
    def strip_pattern(cls, v: str) -> str:
        v = v.strip()[:128]
        if not v:
            raise ValueError("pattern must not be empty")
        return v

    @field_validator("match_type")
    @classmethod
    def validate_match_type(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in _MATCH_TYPES:
            raise ValueError(f"match_type must be one of: {', '.join(sorted(_MATCH_TYPES))}")
        return v

    @field_validator("vendor")
    @classmethod
    def strip_vendor(cls, v: str | None) -> str | None:
        return v.strip()[:128] if v else v


class KbHostnameUpdate(BaseModel):
    vendor: str | None = None
    device_type: str | None = None
    os_family: str | None = None
    match_type: str | None = None

    @field_validator("match_type")
    @classmethod
    def validate_match_type(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip().lower()
        if v not in _MATCH_TYPES:
            raise ValueError(f"match_type must be one of: {', '.join(sorted(_MATCH_TYPES))}")
        return v

    @field_validator("vendor")
    @classmethod
    def strip_vendor(cls, v: str | None) -> str | None:
        return v.strip()[:128] if v else v
