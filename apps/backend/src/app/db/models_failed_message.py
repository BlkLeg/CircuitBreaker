"""Parked JetStream work: messages that exhausted their delivery budget.

Route F14. Both JetStream consumers `nak()` on failure with no `max_deliver`, so
a message that can never succeed is redelivered forever — the "silent
poison-message loop" route §1 sets a target of zero for. Bounding delivery alone
would trade an infinite loop for a silent drop, which is worse: the operator
still learns nothing, and now the data is gone. The bound and this table are one
change.

`Base` comes from `app.db.session`, not `app.db.models` — `models` imports `Base`
from `session` too, so taking it from there keeps this module importable on its
own and lets `models` register it without a cycle. It **must** still be imported
by `app.db.models`, because `migrations/env.py` reads `Base.metadata` through
that module and the test fixtures build the schema with `create_all`; a model
nothing imports is a table that silently does not exist.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.time import utcnow
from app.db.session import Base


class FailedMessage(Base):
    """One message that exhausted `max_deliver` on a JetStream consumer.

    The payload is kept so the work is recoverable: an operator who fixes the
    cause can requeue it rather than having to reconstruct what was lost. It is
    stored as raw bytes rather than decoded JSON because a message that failed
    to parse is exactly the kind that lands here, and re-encoding it would
    destroy the evidence of why.
    """

    __tablename__ = "failed_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stream: Mapped[str] = mapped_column(String(128), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    consumer: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    error: Mapped[str] = mapped_column(Text, nullable=False)
    delivered_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: Indexed to match the migration. Declaring it here as well keeps
    #: `alembic check` from proposing to drop an index the migration creates —
    #: model and migration disagreeing is the kind of drift that stays invisible
    #: until an autogenerate run quietly removes it.
    parked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, index=True
    )
    #: Set when an operator sends the message back to its stream. The row is
    #: kept rather than deleted: "this failed and was retried" is a different
    #: fact from "this never happened", and the difference matters when the
    #: same message parks again.
    requeued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: Set when an operator decides the message is not worth recovering.
    discarded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def is_resolved(self) -> bool:
        """Whether an operator has already acted on this row."""
        return self.requeued_at is not None or self.discarded_at is not None
