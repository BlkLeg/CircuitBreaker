"""Server lifecycle state registry.

A thread-safe module-level singleton that tracks the server's current
lifecycle state. Updated by the lifespan context manager; read by the
health endpoint so the frontend always knows where the server is in its
startup / shutdown cycle.
"""

from enum import StrEnum
from threading import Lock


class ServerState(StrEnum):
    STARTING = "starting"
    READY = "ready"
    STOPPING = "stopping"


_state: ServerState = ServerState.STARTING
_state_lock: Lock = Lock()


def get_state() -> ServerState:
    with _state_lock:
        return _state


def set_state(state: ServerState) -> None:
    with _state_lock:
        global _state
        _state = state
