import json
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.core.rbac import require_role
from app.core.url_validation import outbound_async_client, safe_async_request
from app.db.models import NotificationRoute, NotificationSink
from app.db.session import get_db
from app.services.notification_secrets import decrypt_config, encrypt_config, redact_config

router = APIRouter(tags=["notifications"])

_SINK_NOT_FOUND = "Notification sink not found"
_ROUTE_NOT_FOUND = "Notification route not found"
_WEBHOOK_URL_NOT_CONFIGURED = "webhook_url not configured"
_TEST_MESSAGE = "Circuit Breaker test notification"
_TEST_BODY = "If you received this, this sink can deliver alerts. Real alerts take this exact path."
_EMAIL_NEEDS_RECIPIENT = (
    "An email sink needs a recipient — set the 'to' address. "
    "SMTP server, credentials, and sender come from Settings → SMTP."
)


def _email_recipient(config: dict[str, Any]) -> str:
    """The address an email sink delivers to, or '' if it has none.

    ``to_address`` is accepted alongside ``to`` because sinks created before the
    form settled on ``to`` still carry it.
    """
    return str(config.get("to") or config.get("to_address") or "").strip()


def _validate_provider_config(provider_type: str, config: dict[str, Any]) -> None:
    """Reject a sink that could never deliver, at write time.

    An email sink with no recipient is not a partially-configured sink — it is a
    sink that silently drops every alert routed to it, discovered at 3am. The
    webhook providers are deliberately not checked here: their URL is a secret
    the client may legitimately omit on PATCH to carry the stored one forward.
    """
    if provider_type == "email" and not _email_recipient(config):
        raise HTTPException(status_code=422, detail=_EMAIL_NEEDS_RECIPIENT)


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
    # A floor, not an exact match (INC-03) — and a closed set, so a typo is a 422
    # rather than a route that looks configured and delivers nothing. Spelled as
    # a Literal so the four values reach the OpenAPI schema; kept in step with
    # ROUTE_SEVERITIES by test_notification_routes_api.py. RouteOut stays a bare
    # ``str``: legacy rows still have to serialise.
    alert_severity: Literal["*", "info", "warning", "critical"]
    enabled: bool = True


class RouteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sink_id: int
    alert_severity: str
    enabled: bool


def _provider_config(sink: NotificationSink) -> dict:
    """Read provider_config as a mapping, tolerating legacy double-encoded rows.

    The column became JSONB in v0.2.0, but this module kept ``json.dumps``-ing the
    payload on write, so rows created before that was fixed hold a JSON *string*
    inside the JSONB column. Everything downstream — SinkOut, test_sink,
    notification_worker._dispatch — subscripts it as a dict, so those rows raise on
    read. Decode them here rather than leaving installs with unreadable sinks.
    """
    # Typed ``object`` because the mapped column claims ``dict``: the legacy rows
    # this function exists for violate that annotation, so the isinstance checks
    # below would otherwise be narrowed away as unreachable.
    config: object = sink.provider_config
    if isinstance(config, str):
        try:
            decoded = json.loads(config)
        except ValueError:
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return config if isinstance(config, dict) else {}


def _sink_to_out(sink: NotificationSink) -> SinkOut:
    """Serialise a sink for the API — never with a usable credential in it.

    ``GET /sinks`` is admin-only and a webhook URL is a bearer credential, so
    ``provider_config`` is masked on the way out (INC-06) regardless.
    """
    return SinkOut(
        id=sink.id,
        name=sink.name,
        provider_type=sink.provider_type,
        provider_config=redact_config(sink.provider_type, _provider_config(sink)),
        enabled=sink.enabled,
    )


# ── Sinks ──────────────────────────────────────────────────────────────────


@router.get("/sinks", response_model=list[SinkOut])
def list_sinks(
    db: Session = Depends(get_db), current_user: Any = require_role("admin")
) -> list[SinkOut]:
    sinks = db.query(NotificationSink).all()
    return [_sink_to_out(s) for s in sinks]


@router.post("/sinks", response_model=SinkOut)
def create_sink(
    sink_in: SinkCreate, db: Session = Depends(get_db), current_user: Any = require_role("admin")
) -> SinkOut:
    _validate_provider_config(sink_in.provider_type, sink_in.provider_config)
    sink = NotificationSink(
        name=sink_in.name,
        provider_type=sink_in.provider_type,
        # provider_config is JSONB — hand SQLAlchemy the dict. Serialising it here
        # stored a JSON string inside the JSONB column, which every reader then
        # choked on (SinkOut wants a dict, and the worker subscripts it).
        # Credentials inside it are encrypted first (INC-06).
        provider_config=encrypt_config(sink_in.provider_type, sink_in.provider_config),
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
    current_user: Any = require_role("admin"),
) -> SinkOut:
    sink = db.query(NotificationSink).filter(NotificationSink.id == sink_id).first()
    if not sink:
        raise HTTPException(status_code=404, detail=_SINK_NOT_FOUND)
    updates = sink_in.model_dump(exclude_unset=True)
    if "provider_config" in updates and updates["provider_config"] is not None:
        provider_type = updates.get("provider_type") or sink.provider_type
        _validate_provider_config(provider_type, updates["provider_config"])
        # Carry the stored ciphertext forward when the client sends back the
        # mask it was served, or omits the secret entirely — otherwise editing
        # a sink's name would destroy its webhook URL.
        updates["provider_config"] = encrypt_config(
            provider_type,
            updates["provider_config"],
            existing=_provider_config(sink),
        )
    for field, value in updates.items():
        setattr(sink, field, value)
    db.commit()
    db.refresh(sink)
    return _sink_to_out(sink)


@router.delete("/sinks/{sink_id}")
def delete_sink(
    sink_id: int, db: Session = Depends(get_db), current_user: Any = require_role("admin")
) -> dict[str, str]:
    sink = db.query(NotificationSink).filter(NotificationSink.id == sink_id).first()
    if not sink:
        raise HTTPException(status_code=404, detail=_SINK_NOT_FOUND)
    db.delete(sink)
    db.commit()
    return {"status": "ok"}


@router.put("/sinks/{sink_id}/toggle", response_model=SinkOut)
def toggle_sink(
    sink_id: int, db: Session = Depends(get_db), current_user: Any = require_role("admin")
) -> SinkOut:
    sink = db.query(NotificationSink).filter(NotificationSink.id == sink_id).first()
    if not sink:
        raise HTTPException(status_code=404, detail=_SINK_NOT_FOUND)
    sink.enabled = not sink.enabled
    db.commit()
    db.refresh(sink)
    return _sink_to_out(sink)


def _ok_from_resp(resp: Any) -> dict[str, Any]:
    """Report the status of a webhook Test, never the body it returned.

    This used to hand back ``resp.text`` verbatim for any status >= 400. That
    echo is what would turn any residual SSRF on this surface into a read
    primitive: an admin who can point a sink at an internal URL gets whatever
    that endpoint said rendered in the Test result. The status code is what an
    operator needs in order to debug a webhook; the body is what an attacker
    needs. Do not put it back.
    """

    if resp.status_code < 400:
        return {"ok": True, "error": None}
    return {"ok": False, "error": f"Webhook endpoint returned HTTP {resp.status_code}"}


async def _test_webhook_sink(webhook_url: str | None, body: dict[str, Any]) -> dict[str, Any]:
    if not webhook_url:
        return {"ok": False, "error": _WEBHOOK_URL_NOT_CONFIGURED}
    async with outbound_async_client() as client:
        resp = await safe_async_request(client, "POST", webhook_url, json=body, timeout=10.0)
    return _ok_from_resp(resp)


async def _test_email_sink(config: dict[str, Any], db: Session) -> dict[str, Any]:
    """Send a test alert down the *delivery* path, not a parallel one.

    This used to call ``send_test_email``, which shares nothing with dispatch
    beyond the SMTP connection — so a green Test proved only that SMTP worked,
    while ``notify_email`` read connection details from ``provider_config`` and
    dropped every real alert (INC-02). Both now go through ``send_alert``.
    """
    from app.services.settings_service import get_or_create_settings
    from app.services.smtp_service import SMTP_NOT_CONFIGURED, SmtpService, smtp_is_configured

    to_addr = _email_recipient(config)
    if not to_addr:
        return {"ok": False, "error": _EMAIL_NEEDS_RECIPIENT}

    cfg = get_or_create_settings(db)
    if not smtp_is_configured(cfg):
        return {"ok": False, "error": SMTP_NOT_CONFIGURED}

    try:
        await SmtpService(cfg).send_alert(to_addr, _TEST_MESSAGE, _TEST_BODY, "info")
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "error": None}


@router.post("/sinks/{sink_id}/test")
async def test_sink(
    sink_id: int, db: Session = Depends(get_db), current_user: Any = require_role("admin")
) -> dict[str, Any]:
    sink = db.query(NotificationSink).filter(NotificationSink.id == sink_id).first()
    if not sink:
        raise HTTPException(status_code=404, detail=_SINK_NOT_FOUND)

    # Delivery needs the real credential, not the masked view SinkOut serves.
    config = decrypt_config(_provider_config(sink))
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
def list_routes(db: Session = Depends(get_db), current_user: Any = require_role("admin")) -> Any:
    return db.query(NotificationRoute).all()


@router.post("/routes", response_model=RouteOut)
def create_route(
    route_in: RouteCreate, db: Session = Depends(get_db), current_user: Any = require_role("admin")
) -> Any:
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
def delete_route(
    route_id: int,
    db: Session = Depends(get_db),
    current_user: Any = require_role("admin"),
) -> dict[str, str]:
    route = db.query(NotificationRoute).filter(NotificationRoute.id == route_id).first()
    if not route:
        raise HTTPException(status_code=404, detail=_ROUTE_NOT_FOUND)
    db.delete(route)
    db.commit()
    return {"status": "ok"}
