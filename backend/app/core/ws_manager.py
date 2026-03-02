import json
import logging
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        self._connections: set[WebSocket] = set()

    async def connect(self, ws: WebSocket):
        # Socket is already accepted by the route handler before this is called
        self._connections.add(ws)

    def disconnect(self, ws: WebSocket):
        self._connections.discard(ws)

    async def broadcast(self, message: dict):
        """Send message to all connected clients. Remove dead connections silently."""
        dead = set()
        for ws in self._connections:
            try:
                await ws.send_text(json.dumps(message))
            except Exception:
                dead.add(ws)
        self._connections -= dead

    @property
    def connection_count(self) -> int:
        return len(self._connections)


ws_manager = ConnectionManager()
