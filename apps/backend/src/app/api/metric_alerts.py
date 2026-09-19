"""Metric alert rule catalog, preview, state, and CRUD API."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.core.rbac import require_role
from app.db import models
from app.db.session import get_db
from app.schemas.metric_alerts import (
    MetricAlertPreview,
    MetricAlertPreviewRequest,
    MetricAlertRuleCreate,
    MetricAlertRuleOut,
    MetricAlertRuleUpdate,
    MetricDefinition,
)
from app.services.monitoring import metric_rules
from app.services.monitoring.metric_catalog import list_metric_definitions

router = APIRouter(tags=["metric-alerts"])


@router.get("/catalog", response_model=list[MetricDefinition])
def metric_catalog() -> list[MetricDefinition]:
    return list_metric_definitions()


@router.post("/preview", response_model=MetricAlertPreview)
def preview_metric_rule(
    payload: MetricAlertPreviewRequest,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[models.User, require_role("admin")],
) -> MetricAlertPreview:
    return metric_rules.preview_rule(db, payload.rule, window_seconds=payload.window_seconds)


@router.get("", response_model=list[MetricAlertRuleOut])
def list_metric_rules(db: Annotated[Session, Depends(get_db)]) -> list[MetricAlertRuleOut]:
    return metric_rules.list_rules(db)


@router.post("", response_model=MetricAlertRuleOut, status_code=201)
def create_metric_rule(
    payload: MetricAlertRuleCreate,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[models.User, require_role("admin")],
) -> MetricAlertRuleOut:
    result = metric_rules.create_rule(db, payload, actor_id=user.id)
    db.commit()
    return result


@router.get("/{rule_id}", response_model=MetricAlertRuleOut)
def get_metric_rule(rule_id: int, db: Annotated[Session, Depends(get_db)]) -> MetricAlertRuleOut:
    return metric_rules.get_rule(db, rule_id)


@router.put("/{rule_id}", response_model=MetricAlertRuleOut)
def update_metric_rule(
    rule_id: int,
    payload: MetricAlertRuleUpdate,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[models.User, require_role("admin")],
) -> MetricAlertRuleOut:
    result = metric_rules.update_rule(db, rule_id, payload)
    db.commit()
    return result


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_metric_rule(
    rule_id: int,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[models.User, require_role("admin")],
) -> Response:
    metric_rules.delete_rule(db, rule_id)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
