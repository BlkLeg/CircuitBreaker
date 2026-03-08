import json

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.core.rbac import require_role
from app.db.models import NotificationRoute, NotificationSink
from app.db.session import get_db

router = APIRouter(tags=["notifications"])

_SINK_NOT_FOUND = "Notification sink not found"
_ROUTE_NOT_FOUND = "Notification route not found"
_WEBHOOK_URL_NOT_CONFIGURED = "webhook_url not configured"
_TEST_MESSAGE = "Circuit Breaker test notification"


class SinkCreate(BaseModel):
    name: str
    provider_type: str  # slack|discord|teams|email
    provider_config: dict
    enabled: bool = True


class SinkUpdate(BaseModel):
    name: str | None = None
    provider_type: str | None = None
    provider_config: dict | None = None
    enabled: bool | None = None


class SinkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    provider_type: str
    provider_config: dict
    enabled: bool


class RouteCreate(BaseModel):
    sink_id: int
    alert_severity: str  # info|warning|critical|*
    enabled: bool = True


class RouteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sink_id: int
    alert_severity: str
    enabled: bool


def _sink_to_out(sink: NotificationSink) -> SinkOut:
    return SinkOut(
        id=sink.id,
        name=sink.name,
        provider_type=sink.provider_type,
        provider_config=json.loads(sink.provider_config)
        if isinstance(sink.provider_config, str)
        else sink.provider_config,
        enabled=sink.enabled,
    )


# ── Sinks ──────────────────────────────────────────────────────────────────


@router.get("/sinks", response_model=list[SinkOut])
def list_sinks(db: Session = Depends(get_db), current_user=require_role("viewer")):
    sinks = db.query(NotificationSink).all()
    return [_sink_to_out(s) for s in sinks]


@router.post("/sinks", response_model=SinkOut)
def create_sink(
    sink_in: SinkCreate, db: Session = Depends(get_db), current_user=require_role("editor")
):
    sink = NotificationSink(
        name=sink_in.name,
        provider_type=sink_in.provider_type,
        provider_config=json.dumps(sink_in.provider_config),
        enabled=sink_in.enabled,
    )
    db.add(sink)
    db.commit()
    db.refresh(sink)
    return _sink_to_out(sink)


@router.patch("/sinks/{sink_id}", response_model=SinkOut)
def update_sink(
    sink_id: int,
    sink_in: SinkUpdate,
    db: Session = Depends(get_db),
    current_user=require_role("editor"),
):
    sink = db.query(NotificationSink).filter(NotificationSink.id == sink_id).first()
    if not sink:
        raise HTTPException(status_code=404, detail=_SINK_NOT_FOUND)
    updates = sink_in.model_dump(exclude_unset=True)
    for field, value in updates.items():
        if field == "provider_config" and isinstance(value, dict):
            setattr(sink, field, json.dumps(value))
        else:
            setattr(sink, field, value)
    db.commit()
    db.refresh(sink)
    return _sink_to_out(sink)


@router.delete("/sinks/{sink_id}")
def delete_sink(sink_id: int, db: Session = Depends(get_db), current_user=require_role("editor")):
    sink = db.query(NotificationSink).filter(NotificationSink.id == sink_id).first()
    if not sink:
        raise HTTPException(status_code=404, detail=_SINK_NOT_FOUND)
    db.delete(sink)
    db.commit()
    return {"status": "ok"}


@router.put("/sinks/{sink_id}/toggle", response_model=SinkOut)
def toggle_sink(sink_id: int, db: Session = Depends(get_db), current_user=require_role("editor")):
    sink = db.query(NotificationSink).filter(NotificationSink.id == sink_id).first()
    if not sink:
        raise HTTPException(status_code=404, detail=_SINK_NOT_FOUND)
    sink.enabled = not sink.enabled
    db.commit()
    db.refresh(sink)
    return _sink_to_out(sink)


def _ok_from_resp(resp) -> dict:
    return {"ok": resp.status_code < 400, "error": None if resp.status_code < 400 else resp.text}


async def _test_webhook_sink(webhook_url: str | None, body: dict) -> dict:
    if not webhook_url:
        return {"ok": False, "error": _WEBHOOK_URL_NOT_CONFIGURED}
    async with httpx.AsyncClient() as client:
        resp = await client.post(webhook_url, json=body, timeout=10.0)
    return _ok_from_resp(resp)


async def _test_email_sink(config: dict, db: Session) -> dict:
    try:
        from app.services.settings_service import get_or_create_settings
        from app.services.smtp_service import SmtpService

        to_addr = config.get("to") or config.get("to_address")
        if not to_addr:
            return {"ok": False, "error": "No 'to' address configured in sink"}
        cfg = get_or_create_settings(db)
        result = await SmtpService(cfg).send_test_email(to_addr)
        return {
            "ok": result.get("status") == "ok",
            "error": result.get("message") if result.get("status") != "ok" else None,
        }
    except Exception as e:
        return {"ok": False, "error": f"Use SMTP settings: {e}"}


@router.post("/sinks/{sink_id}/test")
async def test_sink(
    sink_id: int, db: Session = Depends(get_db), current_user=require_role("editor")
):
    sink = db.query(NotificationSink).filter(NotificationSink.id == sink_id).first()
    if not sink:
        raise HTTPException(status_code=404, detail=_SINK_NOT_FOUND)

    config = (
        json.loads(sink.provider_config)
        if isinstance(sink.provider_config, str)
        else sink.provider_config
    )
    provider_type = sink.provider_type
    webhook_url = config.get("webhook_url")

    try:
        if provider_type == "slack":
            return await _test_webhook_sink(webhook_url, {"text": _TEST_MESSAGE})
        if provider_type == "discord":
            return await _test_webhook_sink(webhook_url, {"content": _TEST_MESSAGE})
        if provider_type == "teams":
            body = {
                "@type": "MessageCard",
                "@context": "http://schema.org/extensions",
                "text": _TEST_MESSAGE,
            }
            return await _test_webhook_sink(webhook_url, body)
        if provider_type == "email":
            return await _test_email_sink(config, db)
        return {"ok": False, "error": f"Unknown provider type: {provider_type}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── Routes ─────────────────────────────────────────────────────────────────


@router.get("/routes", response_model=list[RouteOut])
def list_routes(db: Session = Depends(get_db), current_user=require_role("viewer")):
    return db.query(NotificationRoute).all()


@router.post("/routes", response_model=RouteOut)
def create_route(
    route_in: RouteCreate, db: Session = Depends(get_db), current_user=require_role("editor")
):
    sink = db.query(NotificationSink).filter(NotificationSink.id == route_in.sink_id).first()
    if not sink:
        raise HTTPException(status_code=404, detail=_SINK_NOT_FOUND)
    route = NotificationRoute(
        sink_id=route_in.sink_id,
        alert_severity=route_in.alert_severity,
        enabled=route_in.enabled,
    )
    db.add(route)
    db.commit()
    db.refresh(route)
    return route


@router.delete("/routes/{route_id}")
def delete_route(route_id: int, db: Session = Depends(get_db), current_user=require_role("editor")):
    route = db.query(NotificationRoute).filter(NotificationRoute.id == route_id).first()
    if not route:
        raise HTTPException(status_code=404, detail=_ROUTE_NOT_FOUND)
    db.delete(route)
    db.commit()
    return {"status": "ok"}
