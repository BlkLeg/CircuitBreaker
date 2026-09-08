import json
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.rbac import require_role
from app.core.url_validation import safe_async_request
from app.db.models import NotificationRoute, NotificationSink
from app.db.session import get_db
from app.schemas.notifications import (
    AlertEnvelope,
    RouteCreate,
    RouteOut,
    SinkCreate,
    SinkOut,
    SinkUpdate,
    TestResult,
)
from app.services.notification_delivery import test_sink_delivery
from app.services.notification_secrets import decrypt_config, encrypt_config, redact_config

router = APIRouter(tags=["notifications"])

_SINK_NOT_FOUND = "Notification sink not found"
_ROUTE_NOT_FOUND = "Notification route not found"
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
    db.query(NotificationRoute).filter(NotificationRoute.sink_id == sink_id).delete(
        synchronize_session=False
    )
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


@router.post("/sinks/{sink_id}/test", response_model=TestResult)
async def test_sink(
    sink_id: int, db: Session = Depends(get_db), current_user: Any = require_role("admin")
) -> TestResult:
    sink = db.query(NotificationSink).filter(NotificationSink.id == sink_id).first()
    if not sink:
        raise HTTPException(status_code=404, detail=_SINK_NOT_FOUND)

    try:
        config = decrypt_config(_provider_config(sink))
    except Exception:
        return TestResult(
            ok=False,
            state="terminal",
            reason_code="credential_unavailable",
            message="Destination credentials are unavailable.",
            error="Destination credentials are unavailable.",
            provider=sink.provider_type,
            sink_id=sink.id,
            attempt_count=0,
        )

    email_sender: Callable[[str, str, str, str], Awaitable[None]] | None = None
    if sink.provider_type == "email":
        from app.services.settings_service import get_or_create_settings
        from app.services.smtp_service import SmtpService, smtp_is_configured

        cfg = get_or_create_settings(db)
        if smtp_is_configured(cfg):

            async def _send_email(recipient: str, title: str, message: str, severity: str) -> None:
                await SmtpService(cfg).send_alert(recipient, title, message, severity)

            email_sender = _send_email

    event = AlertEnvelope(severity="info", title=_TEST_MESSAGE, message=_TEST_BODY)
    return await test_sink_delivery(
        sink.provider_type,
        config,
        event,
        sink_id=sink.id,
        request_fn=safe_async_request,
        email_sender=email_sender,
    )


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
