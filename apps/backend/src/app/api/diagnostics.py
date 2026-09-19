"""Admin diagnostics endpoint — normalized install/runtime checks."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from app.core.rbac import require_role
from app.services.diagnostics import collect_diagnostics

router = APIRouter(tags=["admin-diagnostics"])

DiagnosticStatus = Literal["pass", "warn", "fail", "unknown", "skipped"]
DiagnosticSeverity = Literal["info", "warning", "error", "critical"]


class DiagnosticCheckModel(BaseModel):
    """One normalized diagnostic check (see specs/install/diagnostic-result.schema.json)."""

    model_config = ConfigDict(from_attributes=True)

    component: str
    check: str
    status: DiagnosticStatus
    severity: DiagnosticSeverity
    evidence: str
    remediation: str
    safe_to_retry: bool


class DiagnosticsResponse(BaseModel):
    """Admin diagnostics payload."""

    checks: list[DiagnosticCheckModel]
    generated_at: datetime


@router.get("/diagnostics", response_model=DiagnosticsResponse)
async def get_diagnostics(_: Any = require_role("admin")) -> DiagnosticsResponse:
    """Return normalized diagnostic checks. Admin-only."""
    checks = await collect_diagnostics()
    return DiagnosticsResponse(
        checks=[DiagnosticCheckModel.model_validate(item) for item in checks],
        generated_at=datetime.now(tz=UTC),
    )
