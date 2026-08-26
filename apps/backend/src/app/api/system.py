from typing import Annotated, Any

import psutil
from fastapi import APIRouter, Depends

from app.core import update_check
from app.core.install_method import detect_install_method, upgrade_command
from app.core.rbac import require_role
from app.core.security import require_write_auth

router = APIRouter(tags=["system"])

_RELEASE_TAG_URL = "https://github.com/BlkLeg/CircuitBreaker/releases/tag/v{version}"


@router.get("/stats")
def get_system_stats(_id: int = Depends(require_write_auth)) -> dict[str, Any]:
    net_io = psutil.net_io_counters()
    return {
        "cpu_pct": psutil.cpu_percent(interval=0.5),
        "mem": psutil.virtual_memory()._asdict(),
        "disk": psutil.disk_usage("/")._asdict(),
        "net": net_io._asdict() if net_io else None,
    }


@router.get("/update")
async def get_update_status(_: Annotated[None, require_role("admin")] = None) -> dict:
    """What the cached check last concluded, and what to run about it.

    Cache-only: reads the in-memory verdict from `update_check`, never
    triggers a refresh or opens a socket.
    """
    state = update_check.current_state()
    method = detect_install_method()
    release_url = _RELEASE_TAG_URL.format(version=state.available) if state.available else None
    return {
        "current": state.current or "",
        "available": state.available,
        "update_available": bool(state.available),
        "channel": state.channel,
        "install_method": method,
        "upgrade_command": upgrade_command(method, state.available),
        "release_url": release_url,
        "enabled": state.status not in ("disabled", "airgap"),
        "checked_at": state.checked_at,
        "status": state.status,
    }
