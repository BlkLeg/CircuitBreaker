"""Worker heartbeat file paths under CB_DATA_DIR.

Historically mono workers wrote ``/data/<worker>.healthy``. Native and package
layouts use other data dirs; always prefer ``CB_DATA_DIR`` and fall back to
``/data`` only when the env var is unset (mono image default).
"""

from __future__ import annotations

import os
import time
from pathlib import Path


def heartbeat_data_dir() -> Path:
    """Directory that holds ``*.healthy`` heartbeat files."""
    raw = (os.environ.get("CB_DATA_DIR") or "").strip()
    return Path(raw).expanduser() if raw else Path("/data")


def heartbeat_path(worker_name: str) -> Path:
    """Return ``$CB_DATA_DIR/<worker_name>.healthy`` (default base ``/data``)."""
    name = worker_name.strip()
    if not name:
        raise ValueError("worker_name must be non-empty")
    if "/" in name or name.startswith("."):
        raise ValueError(f"invalid worker_name: {worker_name!r}")
    return heartbeat_data_dir() / f"{name}.healthy"


def touch_heartbeat(worker_name: str) -> None:
    """Write an epoch timestamp heartbeat; ignore filesystem errors."""
    path = heartbeat_path(worker_name)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(time.time()), encoding="utf-8")
    except OSError:
        pass
