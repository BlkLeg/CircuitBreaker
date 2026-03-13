import asyncio
import hashlib
import hmac
import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from app.core.nats_client import nats_client
from app.core.url_validation import reject_ssrf_url
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
    resp,
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


def _effective_events(rule: WebhookRule) -> list[str]:
    try:
        return json.loads(rule.events_enabled or "[]")
    except Exception:
        return [t.strip() for t in (rule.topics or "").split(",") if t.strip()]


def _build_headers(rule: WebhookRule, payload_bytes: bytes) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    try:
        custom_headers = json.loads(rule.headers_json or "{}")
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
    retry_count = max(0, min(int(rule.retries or 0), len(_RETRY_BACKOFF_S)))
    max_attempts = retry_count + 1
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
            await asyncio.sleep(_RETRY_BACKOFF_S[attempt])
        # Best-effort send rate cap (~10 req/sec) per worker.
        await asyncio.sleep(0.1)


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


async def process_event(msg):
    subject = msg.subject
    # Skip JetStream internal subjects (e.g. $JS.API.STREAM.INFO.KV_dashboard_cache)
    if subject.startswith("$JS."):
        return
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
        for rule in active_rules:
            await _dispatch_with_retries(client, rule, subject, body_bytes, body_text)


async def run_worker(shutdown_event: asyncio.Event = None):
    backoff = 1
    while not nats_client.is_connected:
        await nats_client.connect()
        if nats_client.is_connected:
            break
        logger.warning("Waiting for NATS... retrying in %ds", backoff)
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, 60)

    await nats_client.subscribe(">", handler=process_event)
    logger.info("Webhook worker started and listening on all events")
    _touch_healthy()

    while not (shutdown_event and shutdown_event.is_set()):
        try:
            if shutdown_event:
                await asyncio.wait_for(shutdown_event.wait(), timeout=30.0)
            else:
                await asyncio.sleep(30)
        except TimeoutError:
            pass

        _touch_healthy()
        if not nats_client.is_connected:
            logger.warning("Webhook worker: NATS not connected — waiting for auto-reconnect")


if __name__ == "__main__":
    from app.workers import run_with_graceful_shutdown

    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_with_graceful_shutdown(run_worker))
