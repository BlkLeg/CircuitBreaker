"""Admin endpoint for audit log chain verification."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.audit_chain import verify_audit_chain
from app.core.rbac import require_role
from app.db.session import get_db

router = APIRouter(tags=["admin-audit"])


@router.get("/audit-log/verify-chain")
def audit_log_verify_chain(
    _=require_role("admin"),
    db: Session = Depends(get_db),
):
    """Verify the audit log hash chain. Admin-only. Returns valid, first_failure_id, message, checked_count."""
    result = verify_audit_chain(db)
    return result
