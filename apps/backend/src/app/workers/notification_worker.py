import asyncio
import json
import logging
import smtplib
import time
from email.message import EmailMessage
from pathlib import Path

import httpx

from app.core.nats_client import nats_client
from app.db.models import NotificationRoute
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)

_HEALTHY_FILE = Path("/tmp/worker.healthy")  # noqa: S108


def _touch_healthy() -> None:
    """Update heartbeat file so the container healthcheck can verify liveness."""
    try:
        _HEALTHY_FILE.write_text(str(time.time()))
    except OSError:
        pass


async def notify_slack(provider_config, title, message, severity):
    config = json.loads(provider_config)
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


async def notify_email(provider_config, title, message, severity):
    config = json.loads(provider_config)
    # config: {"smtp_host": "...", "smtp_port": 587, "user": "...", "pass": "...", "to": "..."}
    try:
        msg = EmailMessage()
        msg.set_content(message)
        msg["Subject"] = f"[{severity.upper()}] {title}"
        msg["From"] = config.get("from", "circuitbreaker@localhost")
        msg["To"] = config.get("to")

        # blocking call - should ideally run in executor
        loop = asyncio.get_event_loop()

        def _send():
            with smtplib.SMTP(config.get("smtp_host"), config.get("smtp_port", 587)) as s:
                if config.get("user") and config.get("pass"):
                    s.starttls()
                    s.login(config["user"], config["pass"])
                s.send_message(msg)

        await loop.run_in_executor(None, _send)
    except Exception as e:
        logger.error(f"Failed to send email: {e}")


async def notify_discord(provider_config, title, message, severity):
    config = json.loads(provider_config)
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


async def notify_teams(provider_config, title, message, severity):
    config = json.loads(provider_config)
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


async def process_alert(msg):
    subject = msg.subject
    try:
        data = json.loads(msg.data.decode())
    except json.JSONDecodeError:
        return

    severity = data.get("severity", "info")
    title = data.get("title", subject)
    message = data.get("message", json.dumps(data))

    with SessionLocal() as db:
        routes = db.query(NotificationRoute).filter(NotificationRoute.enabled).all()
        # Find matching routes
        active_routes = [
            r for r in routes if r.alert_severity == severity or r.alert_severity == "*"
        ]

        for route in active_routes:
            provider_type = route.sink.provider_type
            provider_config = route.sink.provider_config

            logger.info(f"Routing alert '{title}' to {provider_type} sink")
            if provider_type == "slack":
                await notify_slack(provider_config, title, message, severity)
            elif provider_type == "discord":
                await notify_discord(provider_config, title, message, severity)
            elif provider_type == "teams":
                await notify_teams(provider_config, title, message, severity)
            elif provider_type == "email":
                await notify_email(provider_config, title, message, severity)


async def run_worker(shutdown_event: asyncio.Event = None):
    backoff = 1
    while not nats_client.is_connected:
        await nats_client.connect()
        if nats_client.is_connected:
            break
        logger.warning("Waiting for NATS... retrying in %ds", backoff)
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, 60)

    await nats_client.subscribe("alert.>", handler=process_alert)
    logger.info("Notification worker started and listening on alert.>")
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
            logger.warning("Notification worker: NATS not connected — waiting for auto-reconnect")


if __name__ == "__main__":
    from app.workers import run_with_graceful_shutdown

    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_with_graceful_shutdown(run_worker))
