import json
from datetime import UTC, datetime
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, HttpUrl
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.rbac import require_role
from app.core.url_validation import reject_ssrf_url
from app.db.models import WebhookDelivery, WebhookRule
from app.db.session import get_db

router = APIRouter(tags=["webhooks"])

_NOT_FOUND = "Webhook not found"
_MASK = "********"

WEBHOOK_EVENT_GROUPS = {
    "proxmox": [
        "proxmox.vm.created",
        "proxmox.vm.deleted",
        "proxmox.vm.started",
        "proxmox.vm.stopped",
        "proxmox.node.offline",
        "proxmox.sync.failed",
    ],
    "truenas": [
        "truenas.pool.degraded",
        "truenas.pool.healthy",
        "truenas.disk.smart.warning",
        "truenas.disk.smart.critical",
    ],
    "unifi": [
        "unifi.switch.offline",
        "unifi.ap.offline",
        "unifi.new.client",
        "unifi.sync.failed",
    ],
    "telemetry": [
        "telemetry.cpu.warning",
        "telemetry.cpu.critical",
        "telemetry.ups.low.battery",
        "telemetry.ups.on.battery",
        "telemetry.poll.failed",
        "telemetry.status.changed",
    ],
    "discovery": [
        "discovery.scan.started",
        "discovery.scan.completed",
        "discovery.new.host",
        "discovery.conflict.detected",
        "discovery.profile.failed",
    ],
    "topology": [
        "topology.hardware.created",
        "topology.service.created",
        "topology.entity.deleted",
        "topology.environment.changed",
    ],
    "users_security": [
        "user.invited",
        "user.role.changed",
        "user.login.success",
        "user.login.failed",
        "api.token.created",
    ],
    "uptime_kuma": [
        "uptimekuma.down",
        "uptimekuma.up",
        "uptimekuma.flapping",
    ],
}


class WebhookRuleCreate(BaseModel):
    label: str
    url: HttpUrl
    events_enabled: list[str] = []
    headers: dict[str, str] | None = None
    retries: int = 3
    enabled: bool = True
    secret: str | None = None
    body_template: str | None = None


class WebhookRuleUpdate(BaseModel):
    label: str | None = None
    url: HttpUrl | None = None
    events_enabled: list[str] | None = None
    headers: dict[str, str] | None = None
    retries: int | None = None
    enabled: bool | None = None
    secret: str | None = None
    body_template: str | None = None


class WebhookRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    label: str
    url: str
    events_enabled: list[str]
    headers: dict[str, str] | None
    retries: int
    enabled: bool
    body_template: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    last_delivery_status: str | None = None


class WebhookListResponse(BaseModel):
    items: list[WebhookRuleOut]
    total: int
    page: int
    per_page: int


class WebhookDeliveryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    webhook_id: int
    event_type: str
    payload: dict[str, Any] | None
    status_code: int | None
    response_time_ms: int | None
    error: str | None
    delivered_at: str
    ok: bool


class WebhookDLQOut(BaseModel):
    id: int
    rule_id: int
    subject: str
    payload: str | None
    status_code: int | None
    error: str | None
    dlq_at: str | None
    replayed_at: str | None
    rule_label: str


def _json_loads(text: str | list | dict | None, fallback: Any) -> Any:
    if text is None:
        return fallback
    if isinstance(text, (list, dict)):
        return text
    if not text:
        return fallback
    try:
        return json.loads(text)
    except Exception:
        return fallback


def _mask_headers(headers: dict[str, str] | None) -> dict[str, str] | None:
    if not headers:
        return None
    return dict.fromkeys(headers.keys(), _MASK)


def _rule_to_out(rule: WebhookRule, status_by_id: dict[int, str]) -> WebhookRuleOut:
    created = rule.created_at.isoformat() if getattr(rule, "created_at", None) else None
    updated = rule.updated_at.isoformat() if getattr(rule, "updated_at", None) else None
    return WebhookRuleOut(
        id=rule.id,
        label=rule.name,
        url=rule.target_url,
        events_enabled=_json_loads(rule.events_enabled, []),
        headers=_mask_headers(_json_loads(rule.headers_json, None)),
        retries=max(0, int(rule.retries or 0)),
        enabled=rule.enabled,
        created_at=created,
        updated_at=updated,
        body_template=rule.body_template,
        last_delivery_status=status_by_id.get(rule.id),
    )


def _delivery_to_out(row: WebhookDelivery) -> WebhookDeliveryOut:
    return WebhookDeliveryOut(
        id=row.id,
        webhook_id=row.rule_id,
        event_type=row.subject,
        payload=_json_loads(row.payload, None),
        status_code=row.status_code,
        response_time_ms=row.response_time_ms,
        error=row.error,
        delivered_at=row.delivered_at,
        ok=row.ok,
    )


@router.get("/event-groups")
def list_event_groups(current_user: Any = require_role("viewer")) -> dict[str, Any]:
    return {"groups": WEBHOOK_EVENT_GROUPS}


@router.get("", response_model=WebhookListResponse)
def list_webhooks(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: Any = require_role("viewer"),
) -> WebhookListResponse:
    base_q = db.query(WebhookRule).order_by(WebhookRule.id.desc())
    total = base_q.count()
    items = base_q.offset((page - 1) * per_page).limit(per_page).all()

    latest = (
        db.query(WebhookDelivery.rule_id, func.max(WebhookDelivery.id).label("max_id"))
        .group_by(WebhookDelivery.rule_id)
        .all()
    )
    max_map = {r.rule_id: r.max_id for r in latest}
    status_by_id: dict[int, str] = {}
    if max_map:
        rows = (
            db.query(WebhookDelivery).filter(WebhookDelivery.id.in_(list(max_map.values()))).all()
        )
        for d in rows:
            status_by_id[d.rule_id] = "ok" if d.ok else "failed"

    return WebhookListResponse(
        items=[_rule_to_out(rule, status_by_id) for rule in items],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.post("", response_model=WebhookRuleOut)
def create_webhook(
    rule_in: WebhookRuleCreate,
    db: Session = Depends(get_db),
    current_user: Any = require_role("editor"),
) -> WebhookRuleOut:
    try:
        reject_ssrf_url(str(rule_in.url))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    rule = WebhookRule(
        name=rule_in.label.strip(),
        target_url=str(rule_in.url),
        topics=",".join(rule_in.events_enabled),
        events_enabled=rule_in.events_enabled,
        headers_json=rule_in.headers or {},
        retries=max(0, min(rule_in.retries, 5)),
        enabled=rule_in.enabled,
        secret=rule_in.secret,
        body_template=rule_in.body_template or None,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return _rule_to_out(rule, {})


@router.get("/dlq", response_model=list[WebhookDLQOut])
def list_dlq(
    db: Session = Depends(get_db),
    current_user: Any = require_role("viewer"),
) -> list[WebhookDLQOut]:
    rows = (
        db.query(WebhookDelivery, WebhookRule.name)
        .join(WebhookRule, WebhookDelivery.rule_id == WebhookRule.id)
        .filter(WebhookDelivery.is_dlq == True)  # noqa: E712
        .order_by(WebhookDelivery.id.desc())
        .limit(200)
        .all()
    )
    return [
        WebhookDLQOut(
            id=d.id,
            rule_id=d.rule_id,
            subject=d.subject,
            payload=d.payload,
            status_code=d.status_code,
            error=d.error,
            dlq_at=d.dlq_at,
            replayed_at=d.replayed_at,
            rule_label=name,
        )
        for d, name in rows
    ]


@router.post("/dlq/{delivery_id}/replay")
async def replay_dlq(
    delivery_id: int,
    db: Session = Depends(get_db),
    current_user: Any = require_role("editor"),
) -> dict[str, Any]:
    delivery = db.query(WebhookDelivery).filter(WebhookDelivery.id == delivery_id).first()
    if not delivery:
        raise HTTPException(status_code=404, detail="DLQ delivery not found")
    rule = db.query(WebhookRule).filter(WebhookRule.id == delivery.rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Webhook rule not found")

    from app.workers.webhook_worker import _dispatch_with_retries, _normalize_webhook_body

    try:
        payload_obj = json.loads(delivery.payload or "{}")
    except Exception:
        payload_obj = {}
    body_bytes, body_text = _normalize_webhook_body(delivery.subject, payload_obj)

    async with httpx.AsyncClient() as client:
        await _dispatch_with_retries(client, rule, delivery.subject, body_bytes, body_text)

    delivery.replayed_at = datetime.now(UTC).isoformat()
    delivery.is_dlq = False
    db.commit()

    return {"status": "ok", "delivery_id": delivery_id}


@router.patch("/{rule_id}", response_model=WebhookRuleOut)
def update_webhook(
    rule_id: int,
    rule_in: WebhookRuleUpdate,
    db: Session = Depends(get_db),
    current_user: Any = require_role("editor"),
) -> WebhookRuleOut:
    rule = db.query(WebhookRule).filter(WebhookRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)

    updates = rule_in.model_dump(exclude_unset=True)
    if "label" in updates:
        rule.name = str(updates["label"]).strip()
    if "url" in updates:
        try:
            reject_ssrf_url(str(updates["url"]))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        rule.target_url = str(updates["url"])
    if "events_enabled" in updates:
        events = updates["events_enabled"] or []
        rule.events_enabled = events
        rule.topics = ",".join(events)
    if "headers" in updates:
        rule.headers_json = updates["headers"] or {}
    if "retries" in updates and updates["retries"] is not None:
        rule.retries = max(0, min(int(updates["retries"]), 5))
    if "enabled" in updates:
        rule.enabled = bool(updates["enabled"])
    if "secret" in updates:
        rule.secret = updates["secret"]
    if "body_template" in updates:
        rule.body_template = updates["body_template"] or None

    db.commit()
    db.refresh(rule)
    return _rule_to_out(rule, {})


@router.post("/{rule_id}/test")
async def test_webhook(
    rule_id: int, db: Session = Depends(get_db), current_user: Any = require_role("editor")
) -> dict[str, Any]:
    rule = db.query(WebhookRule).filter(WebhookRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)

    try:
        reject_ssrf_url(rule.target_url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    from app.workers.webhook_worker import (
        _apply_body_template,
        _dispatch_with_retries,
        _normalize_webhook_body,
    )

    test_payload = {
        "message": "Circuit Breaker test webhook",
        "source": "settings.webhooks",
        "webhook_id": f"wh-{rule.id}",
    }
    body_bytes, body_text = _normalize_webhook_body("test.ping", test_payload)
    if rule.body_template:
        body_bytes, body_text = _apply_body_template(rule.body_template, "test.ping", test_payload)

    async with httpx.AsyncClient() as client:
        await _dispatch_with_retries(client, rule, "test.ping", body_bytes, body_text)

    # Read back the most recent delivery created by _dispatch_with_retries
    latest = (
        db.query(WebhookDelivery)
        .filter(WebhookDelivery.rule_id == rule_id, WebhookDelivery.subject == "test.ping")
        .order_by(WebhookDelivery.id.desc())
        .first()
    )
    if latest:
        return {"ok": latest.ok, "status_code": latest.status_code, "error": latest.error}
    return {"ok": False, "status_code": None, "error": "No delivery record found"}


@router.get("/{rule_id}/deliveries", response_model=list[WebhookDeliveryOut])
def list_webhook_deliveries(
    rule_id: int,
    db: Session = Depends(get_db),
    current_user: Any = require_role("viewer"),
) -> list[WebhookDeliveryOut]:
    rule = db.query(WebhookRule).filter(WebhookRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    rows = (
        db.query(WebhookDelivery)
        .filter(WebhookDelivery.rule_id == rule_id)
        .order_by(WebhookDelivery.id.desc())
        .limit(100)
        .all()
    )
    return [_delivery_to_out(r) for r in rows]


@router.get("/deliveries", response_model=list[WebhookDeliveryOut])
def list_deliveries(
    rule_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: Any = require_role("viewer"),
) -> list[WebhookDeliveryOut]:
    q = db.query(WebhookDelivery)
    if rule_id is not None:
        q = q.filter(WebhookDelivery.rule_id == rule_id)
    rows = q.order_by(WebhookDelivery.id.desc()).limit(100).all()
    return [_delivery_to_out(r) for r in rows]


@router.delete("/{rule_id}")
def delete_webhook(
    rule_id: int, db: Session = Depends(get_db), current_user: Any = require_role("editor")
) -> dict[str, str]:
    rule = db.query(WebhookRule).filter(WebhookRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    db.delete(rule)
    db.commit()
    return {"status": "ok"}
