import asyncio
import hashlib
import json
import logging
import os
import random
import time
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import httpx

from app.core.nats_client import nats_client
from app.core.redis import get_redis
from app.core.worker_audit import log_worker_audit
from app.db.models import NotificationRoute
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)

_HEALTHY_FILE = Path("/data/worker-notification.healthy")

_DEDUP_WINDOW_S = int(os.getenv("CB_ALERT_DEBOUNCE_S", "60"))
_NOTIFICATION_RETRIES = int(os.getenv("CB_NOTIFICATION_RETRIES", "2"))
_NOTIFICATION_RETRY_BASE_S = 1.0

_JS_STREAM = "CB_EVENTS"
_JS_CONSUMER_DURABLE = "notification_dispatch"
_JS_SUBJECT_FILTER = "alert.>"
_JS_BATCH_SIZE = 5
_JS_FETCH_TIMEOUT_S = 1.0


def _touch_healthy() -> None:
    """Update heartbeat file so the container healthcheck can verify liveness."""
    try:
        _HEALTHY_FILE.parent.mkdir(parents=True, exist_ok=True)
        _HEALTHY_FILE.write_text(str(time.time()))
    except OSError:
        pass


async def notify_slack(
    provider_config: dict[str, Any], title: str, message: str, severity: str
) -> None:
    config = provider_config
    webhook_url = config.get("webhook_url")
    if not webhook_url:
        return

    color = (
        "#FF0000" if severity == "critical" else "#FFA500" if severity == "warning" else "#36a64f"
    )
    payload = {
        "text": f"*{title}*\n{message}",
        "attachments": [
            {"color": color, "fields": [{"title": "Severity", "value": severity, "short": True}]}
        ],
    }
    async with httpx.AsyncClient() as client:
        await client.post(webhook_url, json=payload)


async def notify_email(
    provider_config: dict[str, Any], title: str, message: str, severity: str
) -> None:
    import aiosmtplib

    msg = EmailMessage()
    msg.set_content(message)
    msg["Subject"] = f"[{severity.upper()}] {title}"
    msg["From"] = provider_config.get("from", "circuitbreaker@localhost")
    msg["To"] = provider_config.get("to")

    hostname = str(provider_config.get("smtp_host", ""))
    port = int(provider_config.get("smtp_port", 587))
    user = provider_config.get("user")
    password = provider_config.get("pass")

    await aiosmtplib.send(
        msg,
        hostname=hostname,
        port=port,
        username=user or None,
        password=password or None,
        start_tls=bool(user and password),
        timeout=30.0,
    )


async def notify_discord(
    provider_config: dict[str, Any], title: str, message: str, severity: str
) -> None:
    config = provider_config
    webhook_url = config.get("webhook_url")
    if not webhook_url:
        return
    if severity == "critical":
        color = 0xFF0000
    elif severity == "warning":
        color = 0xFFA500
    else:
        color = 0x36A64F
    payload = {
        "embeds": [
            {
                "title": title,
                "description": message,
                "color": color,
                "footer": {"text": f"Severity: {severity}"},
            }
        ]
    }
    async with httpx.AsyncClient() as client:
        await client.post(webhook_url, json=payload, timeout=10.0)


async def notify_teams(
    provider_config: dict[str, Any], title: str, message: str, severity: str
) -> None:
    config = provider_config
    webhook_url = config.get("webhook_url")
    if not webhook_url:
        return
    color_map = {"critical": "FF0000", "warning": "FFA500", "info": "36a64f"}
    payload = {
        "@type": "MessageCard",
        "@context": "http://schema.org/extensions",
        "themeColor": color_map.get(severity, "0076D7"),
        "summary": title,
        "sections": [
            {
                "activityTitle": title,
                "activityText": message,
                "facts": [{"name": "Severity", "value": severity}],
            }
        ],
    }
    async with httpx.AsyncClient() as client:
        await client.post(webhook_url, json=payload, timeout=10.0)


async def _is_duplicate(subject: str, severity: str, title: str) -> bool:
    """Return True if an identical alert was sent within the debounce window.

    Uses Redis SET NX (atomic): sets key with TTL on first occurrence (returns True →
    not duplicate); key already exists on repeat (returns None → duplicate).
    Gracefully degrades: if Redis unavailable, always returns False (never suppresses).
    """
    r = await get_redis()
    if r is None:
        return False
    raw = f"{subject}:{severity}:{title}"
    key = f"cb:alert:dedup:{hashlib.md5(raw.encode()).hexdigest()}"  # noqa: S324
    result = await r.set(key, 1, ex=_DEDUP_WINDOW_S, nx=True)
    return result is None  # None = key already existed = duplicate


async def _dispatch_notification(
    provider_type: str,
    provider_config: dict[str, Any],
    title: str,
    message: str,
    severity: str,
) -> None:
    """Dispatch to one notification sink with exponential backoff + jitter."""
    _DISPATCH = {
        "slack": notify_slack,
        "discord": notify_discord,
        "teams": notify_teams,
        "email": notify_email,
    }
    fn = _DISPATCH.get(provider_type)
    if fn is None:
        logger.warning("Unknown notification provider type: %s", provider_type)
        return

    last: BaseException | None = None
    max_attempts = _NOTIFICATION_RETRIES + 1
    for attempt in range(max_attempts):
        try:
            await fn(provider_config, title, message, severity)
            return
        except Exception as exc:
            last = exc
            if attempt < max_attempts - 1:
                delay = _NOTIFICATION_RETRY_BASE_S * (2**attempt) * (0.5 + random.random() * 0.5)
                logger.debug(
                    "Notification %s attempt %d/%d failed (%.1fs retry): %s",
                    provider_type,
                    attempt + 1,
                    max_attempts,
                    delay,
                    exc,
                )
                await asyncio.sleep(delay)
    assert last is not None
    raise last


async def process_alert(msg: Any) -> None:
    subject = msg.subject
    try:
        data = json.loads(msg.data.decode())
    except json.JSONDecodeError:
        return

    severity = data.get("severity", "info")
    title = data.get("title", subject)
    message = data.get("message", json.dumps(data))

    if await _is_duplicate(subject, severity, title):
        logger.debug(
            "Alert suppressed (dedup window %ds): severity=%s title=%r",
            _DEDUP_WINDOW_S,
            severity,
            title,
        )
        return

    dispatch_tasks: list[tuple[str, dict[str, Any], int | None]] = []
    with SessionLocal() as db:
        routes = db.query(NotificationRoute).filter(NotificationRoute.enabled).all()
        for route in routes:
            if route.alert_severity == severity or route.alert_severity == "*":
                dispatch_tasks.append(
                    (
                        route.sink.provider_type,
                        route.sink.provider_config,
                        getattr(route.sink, "id", None),
                    )
                )

    if not dispatch_tasks:
        return

    logger.info("Routing alert '%s' to %d sink(s) concurrently", title, len(dispatch_tasks))
    results = await asyncio.gather(
        *[_dispatch_notification(pt, pc, title, message, severity) for pt, pc, _ in dispatch_tasks],
        return_exceptions=True,
    )

    for (provider_type, _, sink_id), result in zip(dispatch_tasks, results):
        if isinstance(result, BaseException):
            logger.error("Notification delivery failed for %s sink: %s", provider_type, result)
            log_worker_audit(
                action="notification_delivery_failed",
                entity_type="notification_sink",
                entity_id=sink_id,
                details=f"provider={provider_type} severity={severity} error={str(result)[:150]}",
                severity="error",
                worker_name="notification_worker",
            )


async def run_worker(shutdown_event: asyncio.Event | None = None) -> None:
    if not nats_client.is_connected:
        backoff = 1
        while not nats_client.is_connected:
            if shutdown_event and shutdown_event.is_set():
                return
            await nats_client.connect()
            if not nats_client.is_connected:
                logger.warning("Waiting for NATS... retrying in %ds", backoff)
                try:
                    if shutdown_event:
                        await asyncio.wait_for(shutdown_event.wait(), timeout=float(backoff))
                    else:
                        await asyncio.sleep(backoff)
                except TimeoutError:
                    pass
                backoff = min(backoff * 2, 60)

    logger.info("Notification worker starting (JetStream durable consumer)")
    psub: Any = None
    was_connected = False

    while not (shutdown_event and shutdown_event.is_set()):
        now_connected = nats_client.is_connected and nats_client._nc is not None

        if now_connected and not was_connected:
            try:
                await nats_client._ensure_events_stream()
                js = nats_client._nc.jetstream()
                psub = await js.pull_subscribe(
                    _JS_SUBJECT_FILTER,
                    durable=_JS_CONSUMER_DURABLE,
                    stream=_JS_STREAM,
                )
                logger.info(
                    "Notification worker subscribed to %s stream filter=%s (durable=%s)",
                    _JS_STREAM,
                    _JS_SUBJECT_FILTER,
                    _JS_CONSUMER_DURABLE,
                )
                _touch_healthy()
            except Exception as exc:
                logger.warning("Notification worker JetStream setup failed: %s", exc)
                psub = None

        was_connected = now_connected

        if psub is None:
            try:
                if shutdown_event:
                    await asyncio.wait_for(shutdown_event.wait(), timeout=1.0)
                else:
                    await asyncio.sleep(1.0)
            except TimeoutError:
                pass
            continue

        try:
            msgs = await psub.fetch(_JS_BATCH_SIZE, timeout=_JS_FETCH_TIMEOUT_S)
        except Exception as exc:
            exc_name = type(exc).__name__
            if "Timeout" not in exc_name:
                logger.warning(
                    "Notification worker fetch error (%s): %s — resetting subscription",
                    exc_name,
                    exc,
                )
                psub = None
                was_connected = False
            continue

        for msg in msgs:
            try:
                await msg.in_progress()
                await process_alert(msg)
                await msg.ack()
            except Exception as exc:
                logger.error(
                    "Notification worker: unhandled error processing message: %s",
                    exc,
                    exc_info=True,
                )
                try:
                    await msg.nak()
                except Exception:
                    pass

        _touch_healthy()

    logger.info("Notification worker stopped")


if __name__ == "__main__":
    from app.workers import run_with_graceful_shutdown

    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_with_graceful_shutdown(run_worker))
