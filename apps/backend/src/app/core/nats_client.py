"""NATS client abstraction — scaffold for Phase 3 messaging integration.

Provides connection management and publish/subscribe helpers.  Degrades
gracefully to a no-op when NATS is unavailable so the rest of the app
never crashes due to a missing message bus.
"""

import json
import logging
import os
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Any

_logger = logging.getLogger(__name__)

NATS_URL = os.getenv("CB_NATS_URL", os.getenv("NATS_URL", "nats://localhost:4222"))
NATS_AUTH_TOKEN = os.getenv("CB_NATS_TOKEN", os.getenv("NATS_AUTH_TOKEN", "")).strip()
NATS_USER = os.getenv("NATS_USER", "").strip()
NATS_PASSWORD = os.getenv("NATS_PASSWORD", "").strip()
NATS_TLS = os.getenv("NATS_TLS", "").strip().lower() in ("1", "true", "yes")


class NATSClient:
    """Thin wrapper around nats-py with graceful degradation and auto-reconnect."""

    def __init__(self, url: str = NATS_URL) -> None:
        self._url = url
        self._nc: Any = None
        self._js: Any = None
        self._connected = False
        # subject → callback registry for resubscription after reconnect
        self._subs: dict[str, Callable] = {}
        # buffer for messages published while disconnected (maxlen caps memory)
        self._publish_buffer: deque[tuple[str, bytes]] = deque(maxlen=200)
        # counter for dropped messages when buffer is full
        self._dropped = 0

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        try:
            import nats

            async def _on_disconnected() -> None:
                self._connected = False
                _logger.warning("NATS disconnected from %s", self._url)

            async def _on_reconnected() -> None:
                self._connected = True
                self._js = self._nc.jetstream()
                _logger.info(
                    "NATS reconnected to %s — resubscribing %d subjects",
                    self._url,
                    len(self._subs),
                )
                for subject, cb in self._subs.copy().items():
                    try:
                        await self._nc.subscribe(subject, cb=cb)
                        _logger.debug("Resubscribed to %s", subject)
                    except Exception as exc:
                        _logger.error("Resubscribe failed for %s: %s", subject, exc)
                await self._ensure_kv_bucket()
                await self._flush_publish_buffer()

            async def _on_error(exc: Exception) -> None:
                _logger.error("NATS error: %s", exc)

            connect_url = self._url
            if NATS_TLS and connect_url.startswith("nats://"):
                connect_url = "tls://" + connect_url[7:]

            connect_kw: dict[str, Any] = dict(
                connect_timeout=3,
                max_reconnect_attempts=-1,
                reconnect_time_wait=5,
                disconnected_cb=_on_disconnected,
                reconnected_cb=_on_reconnected,
                error_cb=_on_error,
            )
            if NATS_AUTH_TOKEN:
                connect_kw["token"] = NATS_AUTH_TOKEN
            elif NATS_USER and NATS_PASSWORD:
                from urllib.parse import quote_plus, urlparse

                parsed = urlparse(connect_url)
                netloc = (
                    f"{quote_plus(NATS_USER)}:{quote_plus(NATS_PASSWORD)}"
                    f"@{parsed.hostname or 'localhost'}:{parsed.port or 4222}"
                )

                connect_url = f"{parsed.scheme}://{netloc}"
            if NATS_TLS:
                connect_kw["tls"] = True

            self._nc = await nats.connect(
                connect_url,
                **connect_kw,
            )
            self._js = self._nc.jetstream()
            self._connected = True
            await self._ensure_kv_bucket()
            _logger.info("NATS connected to %s", self._url)
        except Exception as exc:
            self._connected = False
            _logger.warning("NATS unavailable at %s: %s — running in no-op mode", self._url, exc)

    async def disconnect(self) -> None:
        if self._nc and self._connected:
            try:
                await self._nc.drain()
            except Exception as exc:
                _logger.warning("Error draining NATS connection: %s", exc)
            finally:
                self._connected = False
                self._nc = None

    async def _flush_publish_buffer(self) -> None:
        """Drain buffered messages accumulated during a disconnect period."""
        flushed = 0
        while self._publish_buffer and self._connected and self._nc:
            try:
                subject, data = self._publish_buffer.popleft()
                await self._nc.publish(subject, data)
                flushed += 1
            except Exception as exc:
                _logger.warning("NATS buffer flush failed: %s", exc)
                break
        if flushed:
            _logger.info("NATS flushed %d buffered messages", flushed)

    async def publish(self, subject: str, payload: dict | str | bytes) -> None:
        if isinstance(payload, dict):
            data = json.dumps(payload).encode()
        elif isinstance(payload, str):
            data = payload.encode()
        else:
            data = payload

        if not self._connected or not self._nc:
            if len(self._publish_buffer) == self._publish_buffer.maxlen:
                self._dropped += 1
                _logger.warning(
                    "NATS publish buffer full — dropping message. Total dropped: %d",
                    self._dropped,
                )
            self._publish_buffer.append((subject, data))
            _logger.debug(
                "NATS not connected — buffered message to %s (%d buffered)",
                subject,
                len(self._publish_buffer),
            )
            return
        try:
            await self._nc.publish(subject, data)
        except Exception as exc:
            _logger.warning("NATS publish to %s failed: %s", subject, exc)
            self._publish_buffer.append((subject, data))

    async def subscribe(
        self,
        subject: str,
        handler: Callable[..., Awaitable[None]],
    ) -> Any:
        # Always register for resubscription on reconnect
        self._subs[subject] = handler

        if not self._connected or not self._nc:
            _logger.warning(
                "NATS not connected — subscribe to %s deferred until reconnect", subject
            )
            return None
        try:
            sub = await self._nc.subscribe(subject, cb=handler)
            _logger.info("NATS subscribed to %s", subject)
            return sub
        except Exception as exc:
            _logger.warning("NATS subscribe to %s failed: %s", subject, exc)
            return None

    async def _ensure_kv_bucket(self) -> None:
        """Create the dashboard_cache KV bucket if it does not exist."""
        if not self._connected or not self._js:
            return
        try:
            await self._js.create_key_value(bucket="dashboard_cache")
            _logger.info("NATS KV bucket dashboard_cache created")
        except Exception as exc:
            msg = str(exc).lower()
            if "already in use" in msg or "already exists" in msg or "name already in use" in msg:
                _logger.debug("NATS KV bucket dashboard_cache already exists")
            else:
                _logger.warning("NATS KV bucket dashboard_cache ensure failed: %s", exc)

    async def kv_put(self, bucket: str, key: str, value: dict | str | bytes) -> None:
        if not self._connected or not self._js:
            return
        try:
            if isinstance(value, dict):
                data = json.dumps(value).encode()
            elif isinstance(value, str):
                data = value.encode()
            else:
                data = value
            kv = await self._js.key_value(bucket)
            await kv.put(key, data)
        except Exception as exc:
            _logger.warning("NATS KV put %s.%s failed: %s", bucket, key, exc)

    async def kv_get(self, bucket: str, key: str) -> bytes | None:
        if not self._connected or not self._js:
            return None
        try:
            kv = await self._js.key_value(bucket)
            entry = await kv.get(key)
            return entry.value if entry else None
        except Exception:
            return None


def get_nc() -> NATSClient:
    return nats_client


nats_client = NATSClient()
