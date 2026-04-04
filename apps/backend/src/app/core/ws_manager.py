import asyncio
import json
import logging
import os

from fastapi import WebSocket

logger = logging.getLogger(__name__)

# Hard cap on simultaneous WebSocket connections (DoS guard).
# Raise via CB_WS_MAX_CONNECTIONS env var if needed.
_MAX_CONNECTIONS: int = int(os.getenv("CB_WS_MAX_CONNECTIONS", "50"))
# Max connections allowed from a single IP address.
_MAX_PER_IP: int = int(os.getenv("CB_WS_MAX_PER_IP", "5"))


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        # metadata keyed by websocket: {"user_id": int|None, "ip": str, "connected_at": str}
        self._meta: dict[WebSocket, dict] = {}
        # ip -> count of active connections from that ip
        self._ip_counts: dict[str, int] = {}
        self._lock = asyncio.Lock()

    async def connect(
        self,
        ws: WebSocket,
        *,
        user_id: int | None = None,
        client_ip: str = "unknown",
    ) -> bool:
        """Register an already-accepted WebSocket.

        Returns True on success, False when the connection was rejected due to
        the global cap or per-IP cap being exceeded (caller should close with
        1008).
        """
        async with self._lock:
            total = len(self._connections)
            if total >= _MAX_CONNECTIONS:
                logger.warning(
                    "WS connection rejected: global cap %d reached (ip=%s)",
                    _MAX_CONNECTIONS,
                    client_ip,
                )
                return False
            ip_count = self._ip_counts.get(client_ip, 0)
            if ip_count >= _MAX_PER_IP:
                logger.warning(
                    "WS connection rejected: per-IP cap %d reached (ip=%s)",
                    _MAX_PER_IP,
                    client_ip,
                )
                return False

            from app.core.time import utcnow_iso  # avoid circular at module level

            self._connections.add(ws)
            self._meta[ws] = {
                "user_id": user_id,
                "ip": client_ip,
                "connected_at": utcnow_iso(),
            }
            self._ip_counts[client_ip] = ip_count + 1
            logger.info(
                "WS connected (user=%s ip=%s total=%d)",
                user_id,
                client_ip,
                len(self._connections),
            )
            return True

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(ws)
            meta = self._meta.pop(ws, None)
            if meta:
                ip = meta.get("ip", "unknown")
                current = self._ip_counts.get(ip, 0)
                if current <= 1:
                    self._ip_counts.pop(ip, None)
                else:
                    self._ip_counts[ip] = current - 1
                logger.info(
                    "WS disconnected (user=%s ip=%s remaining=%d)",
                    meta.get("user_id"),
                    ip,
                    len(self._connections),
                )

    async def broadcast(self, message: dict) -> None:
        """Send message to all connected clients. Remove dead connections silently."""
        try:
            payload = json.dumps(message, default=str)
        except (TypeError, ValueError) as exc:
            logger.warning("WS broadcast skipped — payload not JSON-serializable: %s", exc)
            return
        async with self._lock:
            snapshot = list(self._connections)

        dead: list[WebSocket] = []
        for ws in snapshot:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)

        if dead:
            async with self._lock:
                for ws in dead:
                    self._connections.discard(ws)
                    meta = self._meta.pop(ws, None)
                    if meta:
                        ip = meta.get("ip", "unknown")
                        current = self._ip_counts.get(ip, 0)
                        if current <= 1:
                            self._ip_counts.pop(ip, None)
                        else:
                            self._ip_counts[ip] = current - 1

    @property
    def connection_count(self) -> int:
        return len(self._connections)

    def status_snapshot(self) -> dict:
        """Return a safe read-only summary for the /ws/status endpoint."""
        return {
            "connections": len(self._connections),
            "max_connections": _MAX_CONNECTIONS,
            "max_per_ip": _MAX_PER_IP,
            "ip_counts": dict(self._ip_counts),
        }


ws_manager = ConnectionManager()
