from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator


class MonitorCreate(BaseModel):
    hardware_id: int
    probe_methods: list[str] = ["icmp", "tcp", "http"]
    interval_secs: int = 60
    enabled: bool = True

    @field_validator("probe_methods")
    @classmethod
    def validate_methods(cls, v: list[str]) -> list[str]:
        valid = {"icmp", "tcp", "http", "snmp"}
        for m in v:
            if m not in valid:
                raise ValueError(f"Unknown probe method: {m!r}. Must be one of {sorted(valid)}")
        return v

    @field_validator("interval_secs")
    @classmethod
    def validate_interval(cls, v: int) -> int:
        if v < 10:
            raise ValueError("interval_secs must be at least 10")
        return v


class MonitorUpdate(BaseModel):
    enabled: bool | None = None
    probe_methods: list[str] | None = None
    interval_secs: int | None = None

    @field_validator("probe_methods")
    @classmethod
    def validate_methods(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        valid = {"icmp", "tcp", "http", "snmp"}
        for m in v:
            if m not in valid:
                raise ValueError(f"Unknown probe method: {m!r}. Must be one of {sorted(valid)}")
        return v


class MonitorRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    hardware_id: int
    enabled: bool
    interval_secs: int
    probe_methods: list[str]
    last_status: str
    last_checked_at: str | None
    latency_ms: float | None
    consecutive_failures: int
    uptime_pct_24h: float | None
    created_at: str
    updated_at: str

    @field_validator("probe_methods", mode="before")
    @classmethod
    def parse_probe_methods(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            try:
                return list(json.loads(v))
            except Exception:
                return ["icmp", "tcp", "http"]
        return list(v) if v else []


class UptimeEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    hardware_id: int
    status: str
    latency_ms: float | None
    probe_method: str | None
    checked_at: str
