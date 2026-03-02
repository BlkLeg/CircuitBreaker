from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


class LogEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    timestamp: datetime
    level: str
    category: str
    action: str
    actor: Optional[str] = None
    actor_gravatar_hash: Optional[str] = None
    entity_type: Optional[str] = None
    entity_id: Optional[int] = None
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    user_agent: Optional[str] = None
    ip_address: Optional[str] = None
    details: Optional[str] = None
    # Canonical UTC ISO 8601 string for frontend display (may be None for very old rows)
    created_at_utc: Optional[str] = None
    # Seconds elapsed since created_at_utc, computed at response time
    elapsed_seconds: Optional[float] = None
    # Feature 6: structured audit fields
    actor_name: Optional[str] = None
    entity_name: Optional[str] = None
    diff: Optional[str] = None
    severity: Optional[str] = None


class LogsResponse(BaseModel):
    logs: list[LogEntry]
    total_count: int
    has_more: bool
