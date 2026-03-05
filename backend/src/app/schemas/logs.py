from datetime import datetime

from pydantic import BaseModel, ConfigDict


class LogEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    timestamp: datetime
    level: str
    category: str
    action: str
    actor: str | None = None
    actor_gravatar_hash: str | None = None
    entity_type: str | None = None
    entity_id: int | None = None
    old_value: str | None = None
    new_value: str | None = None
    user_agent: str | None = None
    ip_address: str | None = None
    details: str | None = None
    # Canonical UTC ISO 8601 string for frontend display (may be None for very old rows)
    created_at_utc: str | None = None
    # Seconds elapsed since created_at_utc, computed at response time
    elapsed_seconds: float | None = None
    # Feature 6: structured audit fields
    actor_name: str | None = None
    entity_name: str | None = None
    diff: str | None = None
    severity: str | None = None


class LogsResponse(BaseModel):
    logs: list[LogEntry]
    total_count: int
    has_more: bool
