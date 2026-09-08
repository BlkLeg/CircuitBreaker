"""Public vulnerability assessment and feed contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, computed_field, field_validator

AssessmentState = Literal["unavailable", "unassessed", "partial", "completed", "stale"]
AssessmentReason = Literal[
    "feed_missing",
    "feed_incomplete",
    "feed_stale",
    "identity_missing",
    "version_missing",
    "version_unsupported",
    "candidate_limit",
    "completed",
]


class AssessmentIdentity(BaseModel):
    vendor: str | None = None
    product: str | None = None
    version: str | None = None
    version_scheme: Literal["dotted_numeric"] | None = None
    provenance: Literal["inventory", "operator"]
    revision: int = Field(ge=1)


class IdentityPatch(BaseModel):
    vendor: str | None = Field(default=None, max_length=255)
    product: str | None = Field(default=None, max_length=255)
    version: str | None = Field(default=None, max_length=255)
    version_scheme: Literal["dotted_numeric"] | None = None
    revision: int = Field(ge=0)

    @field_validator("vendor", "product", "version")
    @classmethod
    def trim_values(cls, value: str | None) -> str | None:
        value = value.strip() if value else None
        return value or None


class ApplicabilityEvidence(BaseModel):
    criteria: str
    vendor: str | None = None
    product: str | None = None
    vulnerable: bool
    version_result: Literal["match", "no_match", "unknown"]
    reason: str | None = None


class VulnerabilityFinding(BaseModel):
    cve_id: str
    severity: str | None = None
    cvss_score: float | None = None
    summary: str | None = None
    published_at: datetime | None = None
    updated_at: datetime | None = None
    evidence: list[ApplicabilityEvidence]


class FeedState(BaseModel):
    state: Literal["unavailable", "incomplete", "ready", "stale"]
    reason_code: Literal["feed_missing", "feed_incomplete", "feed_stale", "ready"]
    generation: str | None = None
    completed_at: datetime | None = None
    age_seconds: int | None = Field(default=None, ge=0)
    total_records: int = Field(default=0, ge=0)
    coverage_complete: bool = False
    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None


class AssessmentResult(BaseModel):
    state: AssessmentState
    reason_code: AssessmentReason
    identity: AssessmentIdentity | None = None
    identity_revision: int = Field(default=0, ge=0)
    feed_generation: str | None = None
    feed_age_seconds: int | None = Field(default=None, ge=0)
    assessed_at: datetime
    findings: list[VulnerabilityFinding]
    total: int = Field(ge=0)
    completeness: Literal["none", "partial", "complete"]
    limitations: list[str]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def items(self) -> list[VulnerabilityFinding]:
        """Compatibility alias for the existing entity-panel client."""
        return self.findings
