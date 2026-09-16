"""Contracts for portable, previewed inventory transfer."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


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
    """One operator decision about an incoming record.

    ``match`` adopts an existing local record for the incoming row, ``rename``
    creates the row under a new unique value, and ``reassign`` binds one
    reference field of the incoming row to an existing local target.
    """

    entity_type: str = Field(min_length=1, max_length=40)
    source_id: int = Field(gt=0)
    action: Literal["match", "rename", "reassign"]
    target_id: int | None = Field(default=None, gt=0)
    new_value: str | None = Field(default=None, min_length=1, max_length=200)
    field: str | None = Field(default=None, min_length=1, max_length=64)

    @model_validator(mode="after")
    def _fields_match_action(self) -> TransferResolution:
        if self.action == "match":
            if self.target_id is None:
                raise ValueError("a match resolution requires target_id")
            if self.field is not None or self.new_value is not None:
                raise ValueError("a match resolution takes only target_id")
        elif self.action == "rename":
            if self.new_value is None:
                raise ValueError("a rename resolution requires new_value")
            if self.target_id is not None or self.field is not None:
                raise ValueError("a rename resolution takes only new_value")
        else:
            if self.target_id is None or self.field is None:
                raise ValueError("a reassign resolution requires target_id and field")
            if self.new_value is not None:
                raise ValueError("a reassign resolution does not take new_value")
        return self


class TransferPreviewRequest(BaseModel):
    document: dict[str, Any]
    resolutions: list[TransferResolution] = Field(default_factory=list, max_length=5000)


class TransferConflict(BaseModel):
    entity_type: str
    source_id: int
    reason_code: str
    message: str
    candidates: list[int] = Field(default_factory=list, max_length=20)
    candidate_labels: list[str] = Field(default_factory=list, max_length=20)
    field: str | None = None


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


class TransferSummary(BaseModel):
    """Counts behind the transfer page's summary strip."""

    format: Literal["circuitbreaker.inventory"]
    version: Literal[1]
    assets: dict[str, int]
    assets_total: int
    relationships: dict[str, int]
    relationships_total: int
