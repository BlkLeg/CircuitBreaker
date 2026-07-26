"""Monitor API schemas with per-check-type config validation."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

CheckType = Literal["icmp", "tcp", "http", "dns"]
TargetType = Literal["hardware", "compute_unit", "external_node", "service", "ip"]


class _StrictConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IcmpConfig(_StrictConfig):
    packet_count: int = Field(default=5, ge=1, le=20)
    timeout: float = Field(default=1.5, gt=0, le=30)


class TcpConfig(_StrictConfig):
    port: int | None = Field(default=None, ge=1, le=65535)
    ports: list[int] | None = None
    timeout: float = Field(default=1.0, gt=0, le=30)


class HttpConfig(_StrictConfig):
    url: str | None = None
    method: Literal["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"] = "GET"
    headers: dict[str, str] = Field(default_factory=dict)
    body: str | None = None
    timeout: float = Field(default=10.0, gt=0, le=120)
    auth_type: Literal["none", "basic", "bearer"] = "none"
    username: str | None = None
    password: str | None = None
    token: str | None = None
    accepted_statuses: list[str] = Field(default_factory=lambda: ["200-299"])
    keyword: str | None = None
    keyword_invert: bool = False
    json_path: str | None = None
    expected_value: str | None = None
    verify_tls: bool = True
    follow_redirects: bool = True


class DnsConfig(_StrictConfig):
    record_type: Literal["A", "AAAA", "CNAME", "MX", "TXT", "NS", "SOA", "PTR", "SRV", "CAA"] = "A"
    resolver: str | None = None
    port: int = Field(default=53, ge=1, le=65535)
    expected_values: list[str] = Field(default_factory=list)
    timeout: float = Field(default=5.0, gt=0, le=30)


CONFIG_MODELS: dict[str, type[BaseModel]] = {
    "icmp": IcmpConfig,
    "tcp": TcpConfig,
    "http": HttpConfig,
    "dns": DnsConfig,
}


class _MonitorBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    check_type: CheckType
    host: str = Field(min_length=1, max_length=255)
    config: dict = Field(default_factory=dict)
    interval_secs: int = Field(default=60, ge=10, le=86400)
    max_retries: int = Field(default=0, ge=0, le=10)
    retry_interval_secs: int | None = Field(default=None, ge=5, le=86400)
    enabled: bool = True
    target_type: TargetType | None = None
    target_id: int | None = None

    @model_validator(mode="after")
    def _validate_config(self) -> _MonitorBase:
        # Validate against the per-type model but persist only the fields the
        # caller set — collectors apply their own defaults via params.get(...).
        model = CONFIG_MODELS[self.check_type]
        self.config = model(**self.config).model_dump(exclude_unset=True)
        return self


class MonitorCreate(_MonitorBase):
    pass


class MonitorUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    host: str | None = Field(default=None, min_length=1, max_length=255)
    config: dict | None = None
    interval_secs: int | None = Field(default=None, ge=10, le=86400)
    max_retries: int | None = Field(default=None, ge=0, le=10)
    retry_interval_secs: int | None = Field(default=None, ge=5, le=86400)
    enabled: bool | None = None
    target_type: TargetType | None = None
    target_id: int | None = None


class MonitorRead(BaseModel):
    id: int
    name: str
    check_type: str
    host: str
    config: dict
    interval_secs: int
    max_retries: int
    retry_interval_secs: int | None
    enabled: bool
    target_type: str | None
    target_id: int | None
    status: str
    retries: int
    last_polled_at: datetime | None
    last_status_change_at: datetime | None
    uptime_pct_24h: float | None = None
    latency_ms: float | None = None
    created_at: datetime
    updated_at: datetime


class MonitorEventRead(BaseModel):
    id: int
    monitor_id: int
    event_type: str
    status_from: str | None
    status_to: str
    msg: str
    duration_secs: float | None
    created_at: datetime


class MonitorHistoryPoint(BaseModel):
    ts: datetime
    value: float


class TargetMonitorCreate(BaseModel):
    """Optional overrides when quick-creating a monitor for an inventory entity.

    Omit both and the target resolver picks a sensible default per entity type.
    """

    check_type: CheckType | None = None
    config: dict | None = None


class TargetMonitorSummary(BaseModel):
    """Per-target monitor rollup for the inventory pages, drawers, and map."""

    target_type: str
    target_id: int
    monitor_id: int
    monitor_ids: list[int]
    enabled: bool
    status: str
    latency_ms: float | None = None
    uptime_pct_24h: float | None = None
    last_polled_at: datetime | None = None
