"""Admin endpoint for audit log chain verification."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.audit_chain import REPAIR_AUTHORIZATION, repair_audit_chain, verify_audit_chain
from app.core.rbac import require_role
from app.db.models import User
from app.db.session import get_db

router = APIRouter(tags=["admin-audit"])


class AuditChainRepairRequest(BaseModel):
    authorization: str = Field(..., description=f"Must exactly equal {REPAIR_AUTHORIZATION!r}.")
    reason: str = Field(..., min_length=12, max_length=500)


@router.get("/audit-log/verify-chain")
def audit_log_verify_chain(
    _: Any = require_role("admin"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Verify the audit log hash chain. Admin-only.

    Returns valid, first_failure_id, message, checked_count.
    """
    result = verify_audit_chain(db)
    return result


@router.post("/audit-log/repair-chain")
def audit_log_repair_chain(
    payload: AuditChainRepairRequest,
    user: Annotated[User, require_role("admin")],
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Explicitly repair audit log hash-chain links and append a repair event."""
    return repair_audit_chain(
        db,
        authorization=payload.authorization,
        actor_id=user.id,
        reason=payload.reason,
    )
