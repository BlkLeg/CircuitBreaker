"""Server lifecycle state registry.

A thread-safe module-level singleton that tracks the server's current
lifecycle state. Updated by the lifespan context manager; read by the
health endpoint so the frontend always knows where the server is in its
startup / shutdown cycle.
"""

import logging
from enum import StrEnum
from threading import Lock

_logger = logging.getLogger(__name__)


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


# ── Subsystem status registry ─────────────────────────────────────────────
_subsystems: dict[str, str] = {}
_sub_errors: dict[str, str] = {}
_sub_lock: Lock = Lock()


def set_subsystem(name: str, status: str, *, error: str | None = None) -> None:
    """Record the status of a startup subsystem."""
    with _sub_lock:
        _subsystems[name] = status
        if error:
            _sub_errors[name] = error
            _logger.warning("Subsystem '%s' → %s: %s", name, status, error)
        elif status in ("failed", "error"):
            _logger.error("Subsystem '%s' → %s", name, status)


def get_subsystems() -> dict[str, str]:
    """Return a snapshot copy of subsystem statuses."""
    with _sub_lock:
        return dict(_subsystems)
