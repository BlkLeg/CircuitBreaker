"""Notification configuration, alert, and delivery result contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ProviderType = Literal["slack", "discord", "teams", "email"]
DeliveryState = Literal["accepted", "retryable", "terminal"]


class SinkCreate(BaseModel):
    """Create a notification destination."""

    name: str = Field(min_length=1, max_length=200)
    provider_type: ProviderType
    provider_config: dict[str, Any]
    enabled: bool = True


class SinkUpdate(BaseModel):
    """Update supplied notification destination fields."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    provider_type: ProviderType | None = None
    provider_config: dict[str, Any] | None = None
    enabled: bool | None = None


class SinkOut(BaseModel):
    """A notification destination with secret values redacted."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    provider_type: str
    provider_config: dict[str, Any]
    enabled: bool


class RouteCreate(BaseModel):
    """Create a severity-floor route to an existing destination."""

    sink_id: int = Field(gt=0)
    alert_severity: Literal["*", "info", "warning", "critical"]
    enabled: bool = True


class RouteOut(BaseModel):
    """A persisted notification route."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    sink_id: int
    alert_severity: str
    enabled: bool


class AlertEnvelope(BaseModel):
    """Validated alert content sent to configured notification destinations."""

    event_id: str | None = Field(default=None, min_length=1, max_length=160)
    sink_id: int | None = Field(default=None, gt=0)
    severity: str = Field(default="info", min_length=1, max_length=32)
    title: str = Field(min_length=1, max_length=500)
    message: str = Field(default="", max_length=20_000)

    @field_validator("title", "message")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        """Remove NULs while preserving operator-authored alert text."""
        return value.replace("\x00", "")


class DeliveryOutcome(BaseModel):
    """Safe result of attempting one destination one or more times."""

    state: DeliveryState
    reason_code: str
    safe_message: str
    provider: str
    sink_id: int | None = None
    event_id: str | None = None
    attempt_count: int = Field(ge=0)
    http_status: int | None = None
    retry_after: int | None = Field(default=None, ge=0)
    accepted_at: datetime | None = None


class TestResult(BaseModel):
    """Delivery test result; acceptance never implies human receipt."""

    ok: bool
    state: DeliveryState
    reason_code: str
    message: str
    error: str | None = None
    provider: str
    sink_id: int
    attempt_count: int = Field(ge=0)
    http_status: int | None = None
    retry_after: int | None = Field(default=None, ge=0)

    @classmethod
    def from_outcome(cls, outcome: DeliveryOutcome) -> TestResult:
        """Project a delivery outcome onto the Test button contract."""
        accepted = outcome.state == "accepted"
        # A Test request has no later JetStream redelivery. Once its bounded
        # attempts are exhausted, it is a completed failed test, not a promise
        # that the UI should keep showing as actively retrying.
        state = (
            "terminal"
            if outcome.state == "retryable" and outcome.reason_code == "retry_exhausted"
            else outcome.state
        )
        return cls(
            ok=accepted,
            state=state,
            reason_code=outcome.reason_code,
            message=outcome.safe_message,
            error=None if accepted else outcome.safe_message,
            provider=outcome.provider,
            sink_id=outcome.sink_id or 0,
            attempt_count=outcome.attempt_count,
            http_status=outcome.http_status,
            retry_after=outcome.retry_after,
        )


class DispatchSummary(BaseModel):
    """Aggregate persisted disposition for one alert event."""

    event_id: str
    state: DeliveryState
    target_count: int = Field(ge=0)
    accepted_count: int = Field(ge=0)
    terminal_count: int = Field(ge=0)
    retryable_count: int = Field(ge=0)
    outcomes: list[DeliveryOutcome]
