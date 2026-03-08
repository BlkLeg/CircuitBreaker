"""NATS client abstraction — scaffold for Phase 3 messaging integration.

Provides connection management and publish/subscribe helpers.  Degrades
gracefully to a no-op when NATS is unavailable so the rest of the app
never crashes due to a missing message bus.
"""

import json
import logging
import os
from collections.abc import Awaitable, Callable
from typing import Any

_logger = logging.getLogger(__name__)

NATS_URL = os.getenv("NATS_URL", "nats://localhost:4222")


class NATSClient:
    """Thin wrapper around nats-py with graceful degradation."""

    def __init__(self, url: str = NATS_URL) -> None:
        self._url = url
        self._nc: Any = None
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        try:
            import nats

            self._nc = await nats.connect(
                self._url,
                # Fail fast so the app starts even without NATS.
                connect_timeout=3,
                max_reconnect_attempts=0,  # do not retry background reconnects
            )
            self._connected = True
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

    async def publish(self, subject: str, payload: dict | str | bytes) -> None:
        if not self._connected or not self._nc:
            return
        try:
            if isinstance(payload, dict):
                data = json.dumps(payload).encode()
            elif isinstance(payload, str):
                data = payload.encode()
            else:
                data = payload
            await self._nc.publish(subject, data)
        except Exception as exc:
            _logger.warning("NATS publish to %s failed: %s", subject, exc)

    async def subscribe(
        self,
        subject: str,
        handler: Callable[..., Awaitable[None]],
    ) -> Any:
        if not self._connected or not self._nc:
            _logger.warning("NATS not connected — skipping subscribe to %s", subject)
            return None
        try:
            sub = await self._nc.subscribe(subject, cb=handler)
            _logger.info("NATS subscribed to %s", subject)
            return sub
        except Exception as exc:
            _logger.warning("NATS subscribe to %s failed: %s", subject, exc)
            return None


nats_client = NATSClient()
