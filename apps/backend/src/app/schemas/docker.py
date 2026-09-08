"""Contracts for Docker source configuration, enumeration, and reconciliation."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

DockerOutcome = Literal["success", "partial", "failed"]
DockerRunState = Literal["queued", "running", "succeeded", "partial", "failed", "interrupted"]
ParentType = Literal["hardware", "compute"]


class DockerConnectionConfig(BaseModel):
    """Internal effective connection configuration; never return this from APIs."""

    identity: str = Field(min_length=1, max_length=64)
    base_url: str
    endpoint_hint: str
    connection_kind: Literal["socket", "proxy"]
    network_types: list[str] = Field(default_factory=lambda: ["bridge"])


class DockerNetworkObservation(BaseModel):
    native_id: str = Field(min_length=1, max_length=255)
    name: str = Field(min_length=1, max_length=255)
    driver: str | None = None
    network_type: str | None = None
    subnet: str | None = None
    gateway: str | None = None
    scope: str | None = None


class DockerContainerObservation(BaseModel):
    native_id: str = Field(min_length=1, max_length=255)
    short_id: str | None = None
    name: str = Field(min_length=1, max_length=255)
    image: str | None = None
    status: str = "unknown"
    ip_address: str | None = None
    labels: dict[str, str] = Field(default_factory=dict)
    workload_key: str | None = None
    network_ids: list[str] = Field(default_factory=list)


class DockerEnumeration(BaseModel):
    source_identity: str
    daemon_id: str | None = None
    outcome: DockerOutcome
    containers_complete: bool
    networks_complete: bool
    attempted_at: datetime
    completed_at: datetime
    containers: list[DockerContainerObservation] = Field(default_factory=list)
    networks: list[DockerNetworkObservation] = Field(default_factory=list)
    reason_code: str | None = None
    safe_message: str | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> DockerEnumeration:
        if self.outcome == "success" and not self.containers_complete:
            raise ValueError("successful enumeration must have complete containers")
        if self.outcome == "failed" and self.containers_complete:
            raise ValueError("failed enumeration cannot establish container completeness")
        return self


class DockerSourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    connection_kind: str
    endpoint_hint: str
    enabled: bool
    revision: int
    parent_type: str | None
    parent_id: int | None
    parent_provenance: str
    last_attempt_at: datetime | None
    last_success_at: datetime | None
    created_at: datetime
    updated_at: datetime


class DockerSyncRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source_id: int
    source_revision: int
    status: DockerRunState
    triggered_by: str | None
    started_at: datetime | None
    completed_at: datetime | None
    containers_complete: bool
    networks_complete: bool
    containers_observed: int
    networks_observed: int
    containers_created: int
    containers_updated: int
    containers_stopped: int
    networks_created: int
    networks_updated: int
    conflict_count: int
    reason_code: str | None
    safe_message: str | None
    created_at: datetime


class DockerSyncAccepted(BaseModel):
    status: Literal["queued"] = "queued"
    source_id: int
    run_id: str


class DockerManagedContainerOut(BaseModel):
    id: int
    source_id: int
    native_id: str
    name: str
    image: str | None
    status: str | None
    ip_address: str | None
    workload_key: str | None
    network_ids: list[str]
    parent_type: ParentType | None
    parent_id: int | None
    parent_provenance: str
    last_seen_at: datetime | None


class DockerParentAssignment(BaseModel):
    parent_type: ParentType | None = None
    parent_id: int | None = Field(default=None, gt=0)
    expected_revision: int = Field(ge=1)

    @model_validator(mode="after")
    def parent_fields_move_together(self) -> DockerParentAssignment:
        if (self.parent_type is None) != (self.parent_id is None):
            raise ValueError("parent_type and parent_id must both be set or both be null")
        return self


class DockerReconciliationResult(BaseModel):
    containers_created: int = 0
    containers_updated: int = 0
    containers_stopped: int = 0
    networks_created: int = 0
    networks_updated: int = 0
    conflicts: list[str] = Field(default_factory=list)
