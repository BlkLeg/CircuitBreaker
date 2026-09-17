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
    "fleet_limit",
    "completed",
]


class AssessmentIdentity(BaseModel):
    vendor: str | None = None
    product: str | None = None
    version: str | None = None
    version_scheme: Literal["dotted_numeric"] | None = None
    provenance: Literal["inventory", "operator"]
    # The operator-override row's revision, and the value a correction must send
    # back. An identity read from inventory has never been corrected, so its
    # revision is 0 — which is what `update_assessment_identity` expects for the
    # first correction. Reporting 1 here made every first correction conflict.
    revision: int = Field(ge=0)


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


class FleetAssessmentRow(BaseModel):
    """One entity's assessment, projected to what a fleet table needs."""

    entity_type: str
    entity_id: int
    name: str
    state: AssessmentState
    reason_code: AssessmentReason
    identity: AssessmentIdentity | None = None
    finding_count: int = Field(ge=0)
    max_severity: str | None = None
    max_cvss: float | None = None
    completeness: Literal["none", "partial", "complete"]


class FleetAssessmentSummary(BaseModel):
    """Fleet counts. Readiness is counted separately from findings, always."""

    total_entities: int = Field(ge=0)
    by_state: dict[str, int]
    entities_with_findings: int = Field(ge=0)
    findings_total: int = Field(ge=0)
    by_severity: dict[str, int]


class FleetAssessmentLimits(BaseModel):
    """What the pass could not do. A capped pass reports a floor, not a total."""

    identity_limit: int = Field(ge=1)
    identities_total: int = Field(ge=0)
    identities_assessed: int = Field(ge=0)
    identity_limit_reached: bool = False
    candidate_limited_products: list[str] = Field(default_factory=list)


class FleetAssessment(BaseModel):
    """The whole-fleet answer behind the Intel console."""

    feed: FeedState
    assessed_at: datetime
    summary: FleetAssessmentSummary
    rows: list[FleetAssessmentRow]
    limits: FleetAssessmentLimits
