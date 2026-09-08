import asyncio
import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from nats.js.api import ConsumerConfig

from app.core.nats_client import nats_client
from app.core.redis import get_redis
from app.core.worker_audit import log_worker_audit
from app.db.session import SessionLocal
from app.schemas.notifications import AlertEnvelope, DeliveryOutcome
from app.services.credential_vault import get_vault
from app.services.notification_delivery import (
    DeliveryPolicy,
    EmailRecipientMissingError,
    SmtpNotConfiguredError,
    UnsupportedProviderError,
    deliver_with_policy,
    send_once,
)
from app.services.notification_routing import dispatch_event, stable_event_id
from app.workers.dead_letter import handle_failed_delivery

logger = logging.getLogger(__name__)

_HEALTHY_FILE = Path("/data/worker-notification.healthy")

_DEDUP_WINDOW_S = int(os.getenv("CB_ALERT_DEBOUNCE_S", "60"))
_NOTIFICATION_RETRIES = int(os.getenv("CB_NOTIFICATION_RETRIES", "2"))

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
) -> Any:
    event = AlertEnvelope(title=title, message=message, severity=severity)
    return await send_once("slack", provider_config, event)


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
        raise EmailRecipientMissingError(
            "Email sink has no recipient — set a 'to' address on the sink before routing to it."
        )

    with SessionLocal() as db:
        cfg = get_or_create_settings(db)
        if not smtp_is_configured(cfg):
            raise SmtpNotConfiguredError(SMTP_NOT_CONFIGURED)
        # Inside the session block on purpose: SmtpService reads cfg attributes
        # lazily during connect, and a detached AppSettings would raise there.
        await SmtpService(cfg).send_alert(str(to_addr), title, message, severity)


async def notify_discord(
    provider_config: dict[str, Any], title: str, message: str, severity: str
) -> Any:
    event = AlertEnvelope(title=title, message=message, severity=severity)
    return await send_once("discord", provider_config, event)


async def notify_teams(
    provider_config: dict[str, Any], title: str, message: str, severity: str
) -> Any:
    event = AlertEnvelope(title=title, message=message, severity=severity)
    return await send_once("teams", provider_config, event)


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
    key = f"cb:alert:dedup:{hashlib.md5(raw.encode(), usedforsecurity=False).hexdigest()}"
    result = await r.set(key, 1, ex=_DEDUP_WINDOW_S, nx=True)
    return result is None  # None = key already existed = duplicate


async def _dispatch_notification(
    provider_type: str,
    provider_config: dict[str, Any],
    title: str,
    message: str,
    severity: str,
) -> DeliveryOutcome:
    """Dispatch through the shared bounded acceptance/retry policy."""
    _DISPATCH = {
        "slack": notify_slack,
        "discord": notify_discord,
        "teams": notify_teams,
        "email": notify_email,
    }
    fn = _DISPATCH.get(provider_type)
    if fn is None:

        async def unsupported() -> Any:
            raise UnsupportedProviderError("unsupported notification provider")

        attempt = unsupported
    else:

        async def attempt() -> Any:
            return await fn(provider_config, title, message, severity)

    event = AlertEnvelope(title=title, message=message, severity=severity)
    return await deliver_with_policy(
        provider_type,
        provider_config,
        event,
        policy=DeliveryPolicy(max_attempts=max(1, min(_NOTIFICATION_RETRIES + 1, 5))),
        send_attempt=attempt,
    )


class RetryableNotificationError(RuntimeError):
    """Signal that JetStream must redeliver outstanding destinations."""

    def __init__(self, message: str, *, retry_after: int = 1) -> None:
        super().__init__(message)
        self.retry_after = max(1, min(retry_after, 30))


class InvalidAlertError(ValueError):
    """Safe poison-message error that does not reproduce the raw payload."""


async def process_alert(msg: Any) -> None:
    subject = msg.subject
    try:
        data = json.loads(msg.data.decode())
        if not isinstance(data, dict):
            raise TypeError
        candidate = dict(data)
        candidate.setdefault("severity", "info")
        candidate.setdefault("title", subject)
        candidate.setdefault("message", json.dumps(data, default=str))
        event = AlertEnvelope.model_validate(candidate)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        raise InvalidAlertError("Alert payload is invalid and cannot be delivered.") from None

    event_id = stable_event_id(msg, event)

    async def sender(
        provider: str,
        config: dict[str, Any],
        routed_event: AlertEnvelope,
        sink_id: int,
        routed_event_id: str,
    ) -> DeliveryOutcome:
        outcome = await _dispatch_notification(
            provider,
            config,
            routed_event.title,
            routed_event.message,
            routed_event.severity,
        )
        return outcome.model_copy(update={"sink_id": sink_id, "event_id": routed_event_id})

    summary = await dispatch_event(
        event,
        event_id,
        session_factory=SessionLocal,
        sender=sender,
    )
    for outcome in summary.outcomes:
        if outcome.state != "accepted":
            logger.warning(
                "Notification disposition provider=%s sink=%s state=%s reason=%s",
                outcome.provider,
                outcome.sink_id,
                outcome.state,
                outcome.reason_code,
            )
            log_worker_audit(
                action="notification_delivery_failed",
                entity_type="notification_sink",
                entity_id=outcome.sink_id,
                details=(
                    f"provider={outcome.provider} severity={event.severity} "
                    f"state={outcome.state} reason={outcome.reason_code}"
                ),
                severity="error" if outcome.state == "retryable" else "warn",
                worker_name="notification_worker",
            )
    if summary.state == "retryable":
        retry_after = max(
            (outcome.retry_after or 1)
            for outcome in summary.outcomes
            if outcome.state == "retryable"
        )
        raise RetryableNotificationError(
            f"Notification event {event_id} has retryable destinations.",
            retry_after=retry_after,
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
                    nak_delay=(
                        exc.retry_after if isinstance(exc, RetryableNotificationError) else None
                    ),
                )

        _touch_healthy()

    logger.info("Notification worker stopped")


if __name__ == "__main__":
    from app.workers import run_with_graceful_shutdown

    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_with_graceful_shutdown(run_worker))
