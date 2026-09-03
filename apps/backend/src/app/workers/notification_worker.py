import asyncio
import hashlib
import json
import logging
import os
import random
import time
from pathlib import Path
from typing import Any

from nats.js.api import ConsumerConfig

from app.core.nats_client import nats_client
from app.core.redis import get_redis
from app.core.url_validation import outbound_async_client, safe_async_request
from app.core.worker_audit import log_worker_audit
from app.db.models import NotificationRoute
from app.db.session import SessionLocal
from app.services.credential_vault import get_vault
from app.services.notification_secrets import decrypt_config
from app.services.notification_severity import route_matches
from app.workers.dead_letter import handle_failed_delivery

logger = logging.getLogger(__name__)

_HEALTHY_FILE = Path("/data/worker-notification.healthy")

_DEDUP_WINDOW_S = int(os.getenv("CB_ALERT_DEBOUNCE_S", "60"))
_NOTIFICATION_RETRIES = int(os.getenv("CB_NOTIFICATION_RETRIES", "2"))
_NOTIFICATION_RETRY_BASE_S = 1.0

_JS_STREAM = "CB_EVENTS"
_JS_CONSUMER_DURABLE = "notification_dispatch"
#: Matches the monitor-poll and telemetry-ingest consumers. Without it this
#: worker naked on every handler exception forever, so one poison alert
#: nak-looped until CB_EVENTS aged it out 24h later with no operator record —
#: F14 verbatim, on the one consumer slice 3.3 did not reach.
_MAX_DELIVER = 5
_JS_SUBJECT_FILTER = "alert.>"
_JS_BATCH_SIZE = 5
_JS_FETCH_TIMEOUT_S = 1.0


def _init_vault() -> None:
    """Load the vault key into this process.

    Sink credentials are stored Fernet-encrypted (INC-06), and the workers run
    as their own process — ``workers/main.py`` never initializes the vault the
    way ``main.py``'s lifespan does. Without this every dispatch would fail to
    decrypt and no alert would ever be delivered.
    """
    from app.db.session import get_session_context
    from app.services.vault_service import load_vault_key

    with get_session_context() as db:
        key = load_vault_key(db)
    if key:
        get_vault().reinitialize(key)
        logger.info("Notification worker vault initialized.")
    else:
        logger.warning(
            "Notification worker could not load CB_VAULT_KEY from env/file/db; "
            "sinks with encrypted credentials cannot be delivered."
        )


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
    async with outbound_async_client() as client:
        await safe_async_request(client, "POST", webhook_url, json=payload)


async def notify_email(
    provider_config: dict[str, Any], title: str, message: str, severity: str
) -> None:
    """Deliver an alert over the globally configured SMTP server (INC-02).

    An email sink carries the recipient and nothing else. Connection details and
    credentials come from ``AppSettings`` — the same source the sink's *Test*
    button uses — because the sink form has never collected SMTP fields. Reading
    ``smtp_host`` out of ``provider_config`` meant connecting to ``""``, so every
    routed alert was dropped while *Test* reported success.

    Both failure modes raise rather than return: ``_dispatch_notification``'s
    retry loop and the ``notification_delivery_failed`` audit entry key off the
    exception, and an operator reading that entry needs the real cause in it.
    """
    from app.services.settings_service import get_or_create_settings
    from app.services.smtp_service import SMTP_NOT_CONFIGURED, SmtpService, smtp_is_configured

    to_addr = provider_config.get("to") or provider_config.get("to_address")
    if not to_addr:
        raise RuntimeError(
            "Email sink has no recipient — set a 'to' address on the sink before routing to it."
        )

    with SessionLocal() as db:
        cfg = get_or_create_settings(db)
        if not smtp_is_configured(cfg):
            raise RuntimeError(SMTP_NOT_CONFIGURED)
        # Inside the session block on purpose: SmtpService reads cfg attributes
        # lazily during connect, and a detached AppSettings would raise there.
        await SmtpService(cfg).send_alert(str(to_addr), title, message, severity)


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
    async with outbound_async_client() as client:
        await safe_async_request(client, "POST", webhook_url, json=payload, timeout=10.0)


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
    async with outbound_async_client() as client:
        await safe_async_request(client, "POST", webhook_url, json=payload, timeout=10.0)


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
    key = f"cb:alert:dedup:{hashlib.md5(raw.encode(), usedforsecurity=False).hexdigest()}"  # noqa: S324
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
    # A sink is posted to once per alert however many routes select it. Under
    # exact matching at most one route per sink could match; a floor means
    # several can, and operators who worked around INC-03 by adding one route
    # per severity have exactly that. `_is_duplicate` keys on the alert, not on
    # the sink, so it would not catch this.
    claimed_sink_ids: set[int] = set()
    with SessionLocal() as db:
        routes = db.query(NotificationRoute).filter(NotificationRoute.enabled).all()
        for route in routes:
            # A route's severity is a floor, not an exact match: a route set to
            # info must also receive warning and critical (INC-03).
            if route_matches(route.alert_severity, severity):
                sink_id = getattr(route.sink, "id", None)
                if sink_id in claimed_sink_ids:
                    continue
                if sink_id is not None:
                    claimed_sink_ids.add(sink_id)
                try:
                    # Sink credentials are stored encrypted; delivery needs the
                    # plaintext. A sink whose secret cannot be decrypted is
                    # skipped loudly rather than posted nowhere.
                    config = decrypt_config(route.sink.provider_config)
                except Exception as exc:
                    logger.error(
                        "Sink %s: cannot decrypt credentials (CB_VAULT_KEY may have "
                        "changed since the sink was saved — re-save it): %s",
                        sink_id,
                        type(exc).__name__,
                    )
                    log_worker_audit(
                        action="notification_delivery_failed",
                        entity_type="notification_sink",
                        entity_id=sink_id,
                        details=(
                            f"provider={route.sink.provider_type} severity={severity} "
                            f"error=credentials could not be decrypted ({type(exc).__name__})"
                        ),
                        severity="error",
                        worker_name="notification_worker",
                    )
                    continue
                dispatch_tasks.append((route.sink.provider_type, config, sink_id))

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
    _init_vault()

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
                    config=ConsumerConfig(max_deliver=_MAX_DELIVER),
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
                await handle_failed_delivery(
                    msg,
                    stream=_JS_STREAM,
                    consumer=_JS_CONSUMER_DURABLE,
                    error=str(exc),
                    max_deliver=_MAX_DELIVER,
                    session_factory=SessionLocal,
                )

        _touch_healthy()

    logger.info("Notification worker stopped")


if __name__ == "__main__":
    from app.workers import run_with_graceful_shutdown

    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_with_graceful_shutdown(run_worker))
