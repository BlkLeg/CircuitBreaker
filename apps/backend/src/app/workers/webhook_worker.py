import asyncio
import hashlib
import hmac
import json
import logging
import random
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.core.nats_client import nats_client
from app.core.otel import get_tracer
from app.core.url_validation import reject_ssrf_url
from app.core.worker_audit import log_worker_audit
from app.db.models import WebhookDelivery, WebhookRule
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)

_HEALTHY_FILE = Path("/data/worker-webhook.healthy")


def _touch_healthy() -> None:
    """Update heartbeat file so the container healthcheck can verify liveness."""
    try:
        _HEALTHY_FILE.parent.mkdir(parents=True, exist_ok=True)
        _HEALTHY_FILE.write_text(str(time.time()))
    except OSError:
        pass


_RETRY_BACKOFF_S = [1, 5, 30]

_JS_STREAM = "CB_EVENTS"
_JS_CONSUMER_DURABLE = "webhook_dispatch"
_JS_BATCH_SIZE = 10
_JS_FETCH_TIMEOUT_S = 1.0


def _safe_target_url_for_log(url: str) -> str:
    """Return origin-only URL for logs so credentials and query strings never leak."""
    parts = urlsplit(url)
    if not parts.scheme or not parts.hostname:
        return "[invalid-webhook-url]"
    if parts.port:
        return f"{parts.scheme}://{parts.hostname}:{parts.port}"
    return f"{parts.scheme}://{parts.hostname}"


def _subject_matches(subject: str, enabled_events: list[str]) -> bool:
    if not enabled_events:
        return False
    for event in enabled_events:
        event = (event or "").strip()
        if not event:
            continue
        if event == "*":
            return True
        if event.endswith(".>") and subject.startswith(event[:-2]):
            return True
        if subject == event:
            return True
    return False


def _write_delivery(
    rule_id: int,
    subject: str,
    payload: str,
    resp: Any,
    error: Exception | None,
    response_time_ms: int | None,
) -> None:
    with SessionLocal() as db:
        delivery = WebhookDelivery(
            rule_id=rule_id,
            subject=subject,
            payload=payload,
            status_code=resp.status_code if resp is not None else None,
            response_time_ms=response_time_ms,
            ok=resp is not None and resp.status_code < 400,
            error=str(error) if error else None,
            delivered_at=datetime.now(UTC).isoformat(),
        )
        db.add(delivery)
        db.commit()

        if not delivery.ok:
            from app.core.worker_audit import log_worker_audit

            log_worker_audit(
                action="webhook_delivery_failed",
                entity_type="webhook",
                entity_id=rule_id,
                details=f"subject={subject} status={delivery.status_code} error={error}",
                severity="warn",
                worker_name="webhook_worker",
            )


def _mark_dlq(rule_id: int, subject: str) -> int | None:
    """Mark the most recent failed delivery for rule+subject as DLQ. Returns delivery id."""
    with SessionLocal() as db:
        delivery = (
            db.query(WebhookDelivery)
            .filter(
                WebhookDelivery.rule_id == rule_id,
                WebhookDelivery.subject == subject,
                WebhookDelivery.ok == False,  # noqa: E712
            )
            .order_by(WebhookDelivery.id.desc())
            .first()
        )
        if delivery is None:
            return None
        delivery.is_dlq = True
        delivery.dlq_at = datetime.now(UTC).isoformat()
        db.commit()
        return delivery.id


def _effective_events(rule: WebhookRule) -> list[str]:
    try:
        events = rule.events_enabled or "[]"
        if isinstance(events, list):
            return list(events)
        return list(json.loads(events))
    except Exception:
        return [t.strip() for t in (rule.topics or "").split(",") if t.strip()]


def _build_headers(rule: WebhookRule, payload_bytes: bytes) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    try:
        headers_json = rule.headers_json or "{}"
        custom_headers = (
            headers_json if isinstance(headers_json, dict) else json.loads(headers_json)
        )
    except Exception:
        custom_headers = {}
    for key, value in custom_headers.items():
        headers[str(key)] = str(value)
    if rule.secret:
        signature = hmac.new(
            rule.secret.encode("utf-8"),
            payload_bytes,
            hashlib.sha256,
        ).hexdigest()
        headers["X-Hub-Signature-256"] = f"sha256={signature}"
    return headers


async def _dispatch_with_retries(
    client: httpx.AsyncClient,
    rule: WebhookRule,
    subject: str,
    body_bytes: bytes,
    body_text: str,
) -> None:
    try:
        reject_ssrf_url(rule.target_url)
    except ValueError as e:
        logger.warning("Webhook SSRF rejected for rule %s: %s", rule.id, e)
        _write_delivery(rule.id, subject, body_text, None, e, None)
        return
    headers = _build_headers(rule, body_bytes)
    safe_target = _safe_target_url_for_log(rule.target_url)
    with get_tracer().start_as_current_span("webhook.dispatch") as span:
        span.set_attribute("webhook.rule_id", rule.id)
        span.set_attribute("nats.subject", subject)

    retry_count = max(0, min(int(rule.retries or 0), len(_RETRY_BACKOFF_S)))
    max_attempts = retry_count + 1
    succeeded = False
    for attempt in range(max_attempts):
        resp = None
        error = None
        started = time.perf_counter()
        try:
            resp = await client.post(
                rule.target_url,
                content=body_bytes,
                headers=headers,
                timeout=10.0,
            )
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            logger.info(
                "Webhook dispatched to %s for %s: %s (attempt %d/%d)",
                safe_target,
                subject,
                resp.status_code,
                attempt + 1,
                max_attempts,
            )
            _write_delivery(rule.id, subject, body_text, resp, None, elapsed_ms)
            if resp.status_code < 400:
                succeeded = True
                break
        except Exception as exc:
            error = exc
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            logger.error(
                "Failed dispatch to %s (attempt %d/%d): %s",
                safe_target,
                attempt + 1,
                max_attempts,
                exc,
            )
            _write_delivery(rule.id, subject, body_text, None, error, elapsed_ms)

        if attempt < max_attempts - 1:
            jitter = 0.5 + random.random() * 0.5
            await asyncio.sleep(_RETRY_BACKOFF_S[attempt] * jitter)
        # Best-effort send rate cap (~10 req/sec) per worker.
        await asyncio.sleep(0.1)

    if not succeeded:
        delivery_id = _mark_dlq(rule.id, subject)
        log_worker_audit(
            action="webhook_dlq_enqueued",
            entity_type="webhook",
            entity_id=rule.id,
            details=f"subject={subject} delivery={delivery_id}",
            severity="warn",
            worker_name="webhook_worker",
        )
        await nats_client.js_publish(
            f"webhook.dlq.{rule.id}",
            {
                "delivery_id": delivery_id,
                "rule_id": rule.id,
                "subject": subject,
                "payload": body_text,
                "failed_at": datetime.now(UTC).isoformat(),
            },
        )


def _normalize_webhook_body(subject: str, payload_obj: dict) -> tuple[bytes, str]:
    """Build a consistent webhook body: event, timestamp, source, data."""
    body = {
        "event": subject,
        "timestamp": datetime.now(UTC).isoformat(),
        "source": "circuitbreaker",
        "data": payload_obj,
    }
    text = json.dumps(body)
    return text.encode("utf-8"), text


def _apply_body_template(template: str, subject: str, payload_obj: dict) -> tuple[bytes, str]:
    """Render a user-defined body template with {{var}} substitution.

    Available variables: {{event}}, {{timestamp}}, {{source}}, {{data}},
    {{data.fieldname}}. Unknown variables are left as-is.
    """
    now = datetime.now(UTC).isoformat()

    def _resolve(match: re.Match[str]) -> str:
        key = match.group(1).strip()
        if key == "event":
            return subject
        if key == "timestamp":
            return now
        if key == "source":
            return "circuitbreaker"
        if key == "data":
            return json.dumps(payload_obj)
        if key.startswith("data."):
            val = payload_obj.get(key[5:], "")
            return json.dumps(val) if isinstance(val, (dict, list)) else str(val)
        return match.group(0)  # leave unknown vars unchanged

    rendered = re.sub(r"\{\{([^}]+)\}\}", _resolve, template)
    return rendered.encode("utf-8"), rendered


async def process_event(msg: Any) -> None:
    subject = msg.subject
    payload_bytes = msg.data
    try:
        payload_obj = json.loads(payload_bytes.decode())
    except json.JSONDecodeError:
        logger.error("Failed to decode message on %s", subject)
        return
    body_bytes, body_text = _normalize_webhook_body(subject, payload_obj)

    with SessionLocal() as db:
        rules = db.query(WebhookRule).filter(WebhookRule.enabled == True).all()  # noqa: E712
        active_rules = []
        for rule in rules:
            events_enabled = _effective_events(rule)
            if _subject_matches(subject, events_enabled):
                active_rules.append(rule)

    if not active_rules:
        return

    async with httpx.AsyncClient() as client:
        tasks = []
        for rule in active_rules:
            if rule.body_template:
                rb, rt = _apply_body_template(rule.body_template, subject, payload_obj)
            else:
                rb, rt = body_bytes, body_text
            tasks.append(_dispatch_with_retries(client, rule, subject, rb, rt))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, BaseException):
                logger.error("Concurrent webhook dispatch error: %s", result, exc_info=result)


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

    logger.info("Webhook worker starting (JetStream durable consumer)")
    psub: Any = None
    was_connected = False

    while not (shutdown_event and shutdown_event.is_set()):
        now_connected = nats_client.is_connected and nats_client._nc is not None

        if now_connected and not was_connected:
            try:
                await nats_client._ensure_events_stream()
                js = nats_client._nc.jetstream()
                psub = await js.pull_subscribe(
                    ">",
                    durable=_JS_CONSUMER_DURABLE,
                    stream=_JS_STREAM,
                )
                logger.info(
                    "Webhook worker subscribed to %s stream (durable=%s)",
                    _JS_STREAM,
                    _JS_CONSUMER_DURABLE,
                )
                _touch_healthy()
            except Exception as exc:
                logger.warning("Webhook worker JetStream setup failed: %s", exc)
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
                    "Webhook worker fetch error (%s): %s — resetting subscription",
                    exc_name,
                    exc,
                )
                psub = None
                was_connected = False
            continue

        for msg in msgs:
            try:
                await msg.in_progress()
                await process_event(msg)
                await msg.ack()
            except Exception as exc:
                logger.error(
                    "Webhook worker: unhandled error processing message: %s",
                    exc,
                    exc_info=True,
                )
                try:
                    await msg.nak()
                except Exception:
                    pass

        _touch_healthy()

    logger.info("Webhook worker stopped")


if __name__ == "__main__":
    from app.workers import run_with_graceful_shutdown

    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_with_graceful_shutdown(run_worker))
