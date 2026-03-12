from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class TelemetryResponse(BaseModel):
    hardware_id: int
    name: str | None = None
    status: str = "unknown"
    data: dict[str, Any] = Field(default_factory=dict)
    source: str = "unknown"
    last_polled: datetime | None = None
    error_msg: str | None = None
    telemetry_profile: str | None = None
