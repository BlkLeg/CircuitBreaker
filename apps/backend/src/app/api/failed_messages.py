"""Operator surface over parked JetStream work (route F14).

Route §1's objective is "0 silent poison-message loops: every JetStream
max-deliver exhaustion produces an operator-visible record". The table alone
does not satisfy that — a row nobody can reach is the same silent failure with a
tidier schema. These three routes are the "visible" half.

Admin-only, and that is a security property rather than tidiness: a parked row
carries the raw payload of whatever the producing system sent, which is exactly
the data an operator would not want a read-only account browsing.

The routes stay thin (CLAUDE.md) — `failed_message_service` holds the logic and
owns the state transitions, including refusing to act twice on one row.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.core.nats_client import nats_client
from app.core.rbac import require_role
from app.db.models_failed_message import FailedMessage
from app.db.session import get_db
from app.services import failed_message_service as svc

router = APIRouter(tags=["failed-messages"])


class FailedMessageOut(BaseModel):
    """One parked message.

    The payload is deliberately **not** serialised. It is arbitrary bytes from a
    message that often failed precisely because it was malformed, so there is no
    encoding that is both honest and safe to hand a browser by default; the
    fields below are what an operator triages on. Recovering the payload is what
    requeue is for.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    stream: str
    subject: str
    consumer: str
    error: str
    delivered_count: int
    parked_at: datetime
    requeued_at: datetime | None
    discarded_at: datetime | None


@router.get("", response_model=list[FailedMessageOut])
def list_failed_messages(
    db: Annotated[Session, Depends(get_db)],
    include_resolved: bool = False,
    _: Annotated[None, require_role("admin")] = None,
) -> list[FailedMessage]:
    """Parked messages, newest first. Resolved rows are hidden unless asked for."""
    return svc.list_parked(db, include_resolved=include_resolved)


@router.post("/{message_id}/requeue", response_model=FailedMessageOut)
async def requeue_failed_message(
    message_id: int,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[None, require_role("admin")] = None,
) -> FailedMessage:
    """Put a parked message back on its stream.

    The service marks the row and publishes inside one transaction, so a
    publisher that raises leaves the message parked rather than marked-and-lost.
    """
    try:
        return await svc.requeue_and_publish(db, message_id, nats_client.publish)
    except svc.MessageNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except svc.MessageAlreadyResolved as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except svc.RepublishFailed as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.post("/{message_id}/discard", response_model=FailedMessageOut)
def discard_failed_message(
    message_id: int,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[None, require_role("admin")] = None,
) -> FailedMessage:
    """Abandon a parked message, keeping the row as a record that it happened."""
    try:
        return svc.discard(db, message_id)
    except svc.MessageNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except svc.MessageAlreadyResolved as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
