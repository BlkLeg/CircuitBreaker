"""The application log, the outbox for audit rows written outside a request, and the
trigger-populated audit table.
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models._shared import _now
from app.db.session import Base

# ── Audit Logs ────────────────────────────────────────────────────────────────


class Log(Base):
    __tablename__ = "logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    level: Mapped[str] = mapped_column(String, nullable=False, default="info")
    category: Mapped[str] = mapped_column(
        String, nullable=False
    )  # crud | settings | relationships | docs
    action: Mapped[str] = mapped_column(
        String, nullable=False
    )  # create_hardware, update_service, …
    actor: Mapped[str | None] = mapped_column(String, default="anonymous")
    actor_gravatar_hash: Mapped[str | None] = mapped_column(String)
    entity_type: Mapped[str | None] = mapped_column(String)
    entity_id: Mapped[int | None] = mapped_column(Integer)
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    user_agent: Mapped[str | None] = mapped_column(String)
    ip_address: Mapped[str | None] = mapped_column(String)
    details: Mapped[str | None] = mapped_column(Text)
    status_code: Mapped[int | None] = mapped_column(
        Integer
    )  # HTTP response status (added for error tracking)
    created_at_utc: Mapped[str | None] = mapped_column(
        String
    )  # ISO 8601 UTC string; canonical timestamp for frontend display
    # Feature 6: structured audit fields
    actor_id: Mapped[int | None] = mapped_column(Integer)
    actor_name: Mapped[str | None] = mapped_column(String, default="system")
    entity_name: Mapped[str | None] = mapped_column(String)  # denormalised name at write time
    diff: Mapped[str | None] = mapped_column(Text)  # JSON: {"before": {...}, "after": {...}}
    severity: Mapped[str | None] = mapped_column(String, default="info")  # info | warn | error
    # Phase 6.5: session and role context
    session_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("user_sessions.id"), nullable=True
    )
    role_at_time: Mapped[str | None] = mapped_column(String, nullable=True)

    # Phase 7: Non-repudiation
    previous_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    log_hash: Mapped[str | None] = mapped_column(String, unique=True, index=True, nullable=True)


class PendingAuditLog(Base):
    """An audit entry that occurred but could not be hash-chained yet.

    Appending to `logs` means reading the chain tail and writing the next link,
    which has to be serialised by the audit-chain advisory lock. A background
    writer that cannot take that lock within its deadline (see
    services/audit_spool.py for why the deadline exists) parks the entry here
    instead of discarding it: the action really happened, so losing the record
    would be a non-repudiation failure, and appending it unserialised would
    fork the chain.

    Deliberately carries no hash and no link to its neighbours. That is what
    lets the insert be an ordinary uncontended INSERT — a chained write is
    exactly the thing that could not be done at the time. Integrity for the
    spool window rests on the row being committed and drained promptly, not on
    the chain; audit_spool.drain moves rows into `logs` in id order, which is
    the order they occurred.
    """

    __tablename__ = "pending_audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # The full Log constructor payload, JSON-encoded at defer time so a drain
    # writes exactly the row the contended write would have written.
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # When the entry was spooled — operational metadata for alerting on spool
    # age. The time the audited action happened lives inside payload
    # (created_at_utc) and is what gets hashed.
    deferred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False, index=True
    )
    # Why it could not be chained inline, kept for forensics.
    reason: Mapped[str | None] = mapped_column(String)


# ── Audit Log (DB-trigger populated, read-only from Python) ──────────────────


class AuditLog(Base):
    """Partitioned audit table populated by DB triggers -- read-only from Python."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    entity_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    entity_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    action: Mapped[str | None] = mapped_column(String(16), nullable=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    old_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    new_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now, primary_key=True
    )
