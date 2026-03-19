from typing import Any

import psutil
from fastapi import APIRouter, Depends

from app.core.security import require_write_auth

router = APIRouter(tags=["system"])


@router.get("/stats")
def get_system_stats(_id: int = Depends(require_write_auth)) -> dict[str, Any]:
    net_io = psutil.net_io_counters()
    return {
        "cpu_pct": psutil.cpu_percent(interval=0.5),
        "mem": psutil.virtual_memory()._asdict(),
        "disk": psutil.disk_usage("/")._asdict(),
        "net": net_io._asdict() if net_io else None,
    }
