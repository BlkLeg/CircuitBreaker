"""Metric alert rule, catalog, state, and preview contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Comparator = Literal[">", ">=", "<", "<="]


class MetricDefinition(BaseModel):
    key: str
    label: str
    unit: str
    comparators: list[Comparator]
    target_types: list[Literal["hardware"]]
    default_freshness_s: int
    default_max_gap_s: int


class MetricAlertRuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    target_type: Literal["hardware"]
    target_id: int = Field(gt=0)
    metric_key: str = Field(max_length=32)
    source: str | None = Field(default=None, max_length=32)
    comparator: Comparator
    threshold: float
    unit: str = Field(max_length=16)
    breach_duration_s: int = Field(default=300, ge=0, le=86400)
    recovery_threshold: float
    recovery_duration_s: int = Field(default=300, ge=0, le=86400)
    max_gap_s: int = Field(default=180, ge=10, le=3600)
    freshness_s: int = Field(default=180, ge=10, le=3600)
    enabled: bool = False
    severity: Literal["info", "warning", "critical"] = "warning"
    sink_id: int | None = Field(default=None, gt=0)


class MetricAlertRuleUpdate(MetricAlertRuleCreate):
    revision: int = Field(gt=0)


class MetricAlertRuleOut(MetricAlertRuleCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    revision: int
    created_at: datetime
    updated_at: datetime
    assessment: str = "unknown"
    open_incident_id: str | None = None


class MetricSampleIn(BaseModel):
    timestamp: datetime
    value: float
    sample_id: str | None = None


class MetricAlertPreviewRequest(BaseModel):
    rule: MetricAlertRuleCreate
    window_seconds: int = Field(default=3600, ge=60, le=86400)


class MetricAlertPreview(BaseModel):
    assessment: Literal["disabled", "unknown", "normal", "pending", "firing", "recovering"]
    reason_code: str
    sample_count: int
    window_start: datetime | None = None
    window_end: datetime | None = None
    limitations: list[str]
    would_emit: Literal["firing", "recovered"] | None = None
