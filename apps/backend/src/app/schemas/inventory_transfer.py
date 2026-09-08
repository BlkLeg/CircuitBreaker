"""Contracts for portable, previewed inventory transfer."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class PortableManifest(BaseModel):
    included: list[str]
    excluded: list[str]


class PortableInventory(BaseModel):
    format: Literal["circuitbreaker.inventory"]
    version: Literal[1]
    exported_at: datetime
    manifest: PortableManifest
    entities: dict[str, list[dict[str, Any]]]
    relationships: dict[str, list[dict[str, Any]]]


class TransferResolution(BaseModel):
    entity_type: str = Field(min_length=1, max_length=40)
    source_id: int = Field(gt=0)
    action: Literal["match"]
    target_id: int = Field(gt=0)


class TransferPreviewRequest(BaseModel):
    document: dict[str, Any]
    resolutions: list[TransferResolution] = Field(default_factory=list, max_length=5000)


class TransferConflict(BaseModel):
    entity_type: str
    source_id: int
    reason_code: str
    message: str
    candidates: list[int] = Field(default_factory=list)


class TransferPreviewResult(BaseModel):
    plan_id: str
    plan_digest: str
    expires_at: datetime
    creates: dict[str, int]
    matches: dict[str, int]
    relationships: dict[str, int]
    conflicts: list[TransferConflict]
    can_apply: bool
    warnings: list[str]


class TransferApplyRequest(BaseModel):
    plan_digest: str = Field(min_length=64, max_length=64)


class TransferApplyResult(BaseModel):
    operation_id: str
    state: Literal["completed"]
    created: dict[str, int]
    matched: dict[str, int]
    relationships_created: dict[str, int]
    warnings: list[str]
