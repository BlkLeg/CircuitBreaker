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
    # Slice 3 §7: the vantage. NULL is server execution — today's behaviour and
    # the only value any pre-Slice-3 monitor has.
    probe_agent_id: int | None = None

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
    # Slice 3 §7: the vantage. NULL is server execution. Only meaningful when
    # the caller actually sets it — `exclude_unset` is what tells a reassignment
    # apart from a rename that happens to echo the field back.
    probe_agent_id: int | None = None


class ProbeAgentRef(BaseModel):
    """The assigned vantage, reduced to what a card and a link need."""

    id: int
    name: str | None = None


class _ProbeVantageRead(BaseModel):
    """The server-derived half of §7's probe block.

    Read-only on purpose: `probe_agent_id` is the one writable field, and
    `MonitorUpdate` deliberately does not accept any of these back. A frontend
    that sends its form verbatim therefore cannot echo a stale execution
    condition into the database — pinned by
    `test_patch_with_echoed_readonly_probe_fields_does_not_change_the_assignment`.
    """

    probe_agent_id: int | None = None
    # "server" | "agent" — derived from probe_agent_id, never stored.
    probe_mode: str = "server"
    probe_agent: ProbeAgentRef | None = None
    # ready|queued|running|unavailable|stale — whether the *vantage* can run the
    # check, which is orthogonal to `status` (whether the target is up).
    probe_execution_status: str | None = None
    probe_execution_reason: str | None = None
    probe_last_dispatched_at: datetime | None = None
    probe_last_result_at: datetime | None = None


class MonitorRead(_ProbeVantageRead):
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


class MonitorCheckPoint(BaseModel):
    """One past check, trimmed to what the dashboard's history bar draws."""

    id: int
    status_to: str
    msg: str
    created_at: datetime


class MonitorWindowCoverage(BaseModel):
    """How much of an uptime window the vantage actually observed (D-12).

    A vantage that cannot run a check writes no `avail` sample at all, so an
    unobserved stretch shrinks the uptime denominator instead of showing as
    downtime. `observed_minutes` against `window_minutes` is what makes the
    percentage beside it readable: 100% over 240 of 1440 minutes is not the
    same claim as 100% over 1440.
    """

    observed_minutes: int
    window_minutes: int
    pct: float


class MonitorUptimeRead(BaseModel):
    """Availability across every window the detail page renders.

    `coverage_*` accompanies the telemetry-backed windows only; 365d and total
    are computed from `MonitorDailyStats`, which keeps no row for a wholly
    unobserved day.
    """

    pct_24h: float | None = None
    pct_7d: float | None = None
    pct_30d: float | None = None
    pct_365d: float | None = None
    pct_total: float | None = None
    last_polled_at: datetime | None = None
    coverage_24h: MonitorWindowCoverage | None = None
    coverage_7d: MonitorWindowCoverage | None = None
    coverage_30d: MonitorWindowCoverage | None = None


class MonitorOverview(MonitorRead):
    """A monitor plus the compact series the dashboard cards render.

    latency_series is oldest → newest (the order a sparkline draws); recent_checks
    is newest first, matching GET /monitors/{id}/events.
    """

    latency_series: list[float] = Field(default_factory=list)
    recent_checks: list[MonitorCheckPoint] = Field(default_factory=list)


class TargetMonitorCreate(BaseModel):
    """Optional overrides when quick-creating a monitor for an inventory entity.

    Omit both and the target resolver picks a sensible default per entity type.
    """

    check_type: CheckType | None = None
    config: dict | None = None


class TargetMonitorSummary(_ProbeVantageRead):
    """Per-target monitor rollup for the inventory pages, drawers, and map.

    The probe block describes the *primary* monitor (the lowest-id one, the same
    one `latency_ms` and `uptime_pct_24h` come from); a target whose monitors
    disagree about their vantage is rendered from that one.
    """

    target_type: str
    target_id: int
    monitor_id: int
    monitor_ids: list[int]
    enabled: bool
    status: str
    latency_ms: float | None = None
    uptime_pct_24h: float | None = None
    last_polled_at: datetime | None = None


# ── Slice 3 §7: probe runs and per-agent assignments ─────────────────────────
# These describe monitor execution, not the agent itself, which is why they live
# beside the monitor schemas even though `api/agents.py` serves two of them.


class MonitorProbeRunRead(BaseModel):
    """One row of §7's bounded execution history.

    `result_metadata` is deliberately absent: it is the audit record behind a
    check (D-8) and the only place per-sample `error_reason` and `details` are
    kept, none of which the history table renders.
    """

    run_id: str
    agent_id: int
    status: str
    outcome: str | None = None
    msg: str | None = None
    error_code: str | None = None
    scheduled_at: datetime
    dispatched_at: datetime | None = None
    deadline_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    attempt_count: int = 0
    created_at: datetime


class AgentProbeAssignment(BaseModel):
    """One monitor assigned to an agent, as Agent Detail's probes section renders
    it: target state and execution condition side by side, never folded."""

    monitor_id: int
    name: str
    check_type: str
    host: str
    target_type: str | None = None
    target_id: int | None = None
    interval_secs: int
    enabled: bool
    status: str
    probe_execution_status: str | None = None
    probe_execution_reason: str | None = None
    probe_last_dispatched_at: datetime | None = None
    probe_last_result_at: datetime | None = None


class AgentProbesRead(BaseModel):
    """§7's Assigned Probes section: the assignments plus the concurrency the
    agent is using against the limit its `remote_probe` grant configures."""

    agent_id: int
    max_concurrent: int
    active_runs: int
    assignments: list[AgentProbeAssignment] = Field(default_factory=list)


class EligibleProbeAgent(BaseModel):
    """One candidate vantage for a monitor, with everything §7's "Run from"
    selector shows: liveness, grant, readiness, concurrency and whether this
    particular destination is inside the agent's derived scope.

    `reason` is `probe_eligibility`'s machine-readable vocabulary — the same
    string the 409 detail and `monitor_items.probe_execution_reason` carry — so
    the UI switches on it rather than parsing prose.
    """

    agent_id: int
    name: str | None = None
    online: bool
    granted: bool
    readiness: str | None = None
    readiness_collector: str | None = None
    max_concurrent: int
    active_runs: int
    assigned_monitors: int
    scope_version: str
    scope_networks: list[str] = Field(default_factory=list)
    excluded_networks: list[str] = Field(default_factory=list)
    in_scope: bool
    eligible: bool
    reason: str | None = None
