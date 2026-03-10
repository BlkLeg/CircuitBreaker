import hashlib
import hmac
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


class WebhookRuleUpdate(BaseModel):
    label: str | None = None
    url: HttpUrl | None = None
    events_enabled: list[str] | None = None
    headers: dict[str, str] | None = None
    retries: int | None = None
    enabled: bool | None = None
    secret: str | None = None


class WebhookRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    label: str
    url: str
    events_enabled: list[str]
    headers: dict[str, str] | None
    retries: int
    enabled: bool
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


def _json_loads(text: str | None, fallback: Any) -> Any:
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
def list_event_groups(current_user=require_role("viewer")):
    return {"groups": WEBHOOK_EVENT_GROUPS}


@router.get("", response_model=WebhookListResponse)
def list_webhooks(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user=require_role("viewer"),
):
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
    current_user=require_role("editor"),
):
    try:
        reject_ssrf_url(str(rule_in.url))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    rule = WebhookRule(
        name=rule_in.label.strip(),
        target_url=str(rule_in.url),
        topics=",".join(rule_in.events_enabled),
        events_enabled=json.dumps(rule_in.events_enabled),
        headers_json=json.dumps(rule_in.headers or {}),
        retries=max(0, min(rule_in.retries, 5)),
        enabled=rule_in.enabled,
        secret=rule_in.secret,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return _rule_to_out(rule, {})


@router.patch("/{rule_id}", response_model=WebhookRuleOut)
def update_webhook(
    rule_id: int,
    rule_in: WebhookRuleUpdate,
    db: Session = Depends(get_db),
    current_user=require_role("editor"),
):
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
        rule.events_enabled = json.dumps(events)
        rule.topics = ",".join(events)
    if "headers" in updates:
        rule.headers_json = json.dumps(updates["headers"] or {})
    if "retries" in updates and updates["retries"] is not None:
        rule.retries = max(0, min(int(updates["retries"]), 5))
    if "enabled" in updates:
        rule.enabled = bool(updates["enabled"])
    if "secret" in updates:
        rule.secret = updates["secret"]

    db.commit()
    db.refresh(rule)
    return _rule_to_out(rule, {})


@router.post("/{rule_id}/test")
async def test_webhook(
    rule_id: int, db: Session = Depends(get_db), current_user=require_role("editor")
):
    rule = db.query(WebhookRule).filter(WebhookRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)

    payload = {
        "event": "test.ping",
        "timestamp": datetime.now(UTC).isoformat(),
        "source": "settings.webhooks",
        "environment": "manual",
        "data": {"message": "Circuit Breaker test webhook"},
        "webhook_id": f"wh-{rule.id}",
    }
    payload_bytes = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    for key, value in (_json_loads(rule.headers_json, {}) or {}).items():
        headers[str(key)] = str(value)
    if rule.secret:
        sig = hmac.new(rule.secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()
        headers["X-Hub-Signature-256"] = f"sha256={sig}"

    try:
        reject_ssrf_url(rule.target_url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    response = None
    error = None
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                rule.target_url, content=payload_bytes, headers=headers, timeout=10.0
            )
            return {
                "ok": response.status_code < 400,
                "status_code": response.status_code,
                "error": None,
            }
    except Exception as exc:
        error = str(exc)
        return {"ok": False, "status_code": None, "error": error}
    finally:
        delivery = WebhookDelivery(
            rule_id=rule.id,
            subject="test.ping",
            payload=json.dumps(payload),
            status_code=response.status_code if response is not None else None,
            response_time_ms=None,
            ok=response is not None and response.status_code < 400,
            error=error,
            delivered_at=datetime.now(UTC).isoformat(),
        )
        db.add(delivery)
        db.commit()


@router.get("/{rule_id}/deliveries", response_model=list[WebhookDeliveryOut])
def list_webhook_deliveries(
    rule_id: int,
    db: Session = Depends(get_db),
    current_user=require_role("viewer"),
):
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
    current_user=require_role("viewer"),
):
    q = db.query(WebhookDelivery)
    if rule_id is not None:
        q = q.filter(WebhookDelivery.rule_id == rule_id)
    rows = q.order_by(WebhookDelivery.id.desc()).limit(100).all()
    return [_delivery_to_out(r) for r in rows]


@router.delete("/{rule_id}")
def delete_webhook(
    rule_id: int, db: Session = Depends(get_db), current_user=require_role("editor")
):
    rule = db.query(WebhookRule).filter(WebhookRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    db.delete(rule)
    db.commit()
    return {"status": "ok"}
