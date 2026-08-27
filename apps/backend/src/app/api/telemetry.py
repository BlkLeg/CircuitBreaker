import asyncio
import json
import logging
import os
from types import SimpleNamespace
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.core.audit import log_audit
from app.core.rate_limit import get_limit, limiter
from app.core.rbac import require_role, require_scope
from app.core.security import require_auth_always
from app.db.models import ComputeUnit, Hardware, Storage, TelemetryTimeseries, User
from app.db.session import get_db
from app.integrations.dispatcher import poll_hardware
from app.schemas.hardware import TelemetryConfig
from app.schemas.telemetry import TelemetryResponse
from app.services.credential_vault import CredentialVault, get_vault
from app.services.telemetry_service import get_telemetry_for_hardware, write_telemetry

_logger = logging.getLogger(__name__)

router = APIRouter(tags=["telemetry"])


_DEVICE_TIMEOUT_ENV = "CB_TELEMETRY_DEVICE_TIMEOUT_SECONDS"
_DEFAULT_DEVICE_TIMEOUT_SECONDS = 20
_MIN_DEVICE_TIMEOUT_SECONDS = 5


def _device_timeout_seconds() -> int:
    """Per-device cap for a telemetry poll, in seconds.

    Deliberately the same knob and the same default the background collector
    reads (app/workers/telemetry_collector.py), so an operator who widens the
    budget for a slow BMC gets the wider budget on the manual "poll now" button
    too rather than discovering the two paths disagree. The 5s floor is the
    collector's as well: a mistyped 0 would otherwise turn every poll into an
    instant "unreachable", which looks exactly like a dead device and sends the
    operator hunting the network instead of the config.

    Kept as a local read rather than a shared import because the collector is a
    worker-side module; the duplication is two lines and the coupling would be
    the wrong direction.

    The try/except is not defensive noise, and a maintainer must not collapse it
    back into a bare ``int(os.environ.get(...))``. This function is on the
    request path: it is called inside ``poll_now``, so a value ``int()`` refuses
    — ``"20s"``, ``"30.5"``, an empty assignment in a compose file, a trailing
    newline from a secrets mount — raises ValueError out of the endpoint and
    turns *every* manual poll into a 500. The operator sees "Internal Server
    Error" on a button that worked yesterday, with nothing pointing at their own
    environment file. A configuration typo is allowed to be ignored; it is not
    allowed to take the feature down, so a malformed value logs once at WARNING
    and falls back to the documented default. (The collector makes the same read
    at start-up, where a ValueError is a loud, immediate boot failure with the
    variable named in the traceback — that is a different and acceptable
    outcome, which is why only this copy is guarded.)
    """
    raw = os.environ.get(_DEVICE_TIMEOUT_ENV)
    if raw is None:
        return _DEFAULT_DEVICE_TIMEOUT_SECONDS
    try:
        parsed = int(raw)
    except ValueError:
        _logger.warning(
            "%s=%r is not an integer; falling back to %ss for this poll.",
            _DEVICE_TIMEOUT_ENV,
            raw,
            _DEFAULT_DEVICE_TIMEOUT_SECONDS,
        )
        return _DEFAULT_DEVICE_TIMEOUT_SECONDS
    return max(_MIN_DEVICE_TIMEOUT_SECONDS, parsed)


def _safe_json(val: Any) -> dict[str, Any] | None:
    """Parse a JSON string to dict, returning None on any failure."""
    if val is None:
        return None
    if isinstance(val, dict):
        return val
    if isinstance(val, str):
        try:
            return cast(dict, json.loads(val))
        except (json.JSONDecodeError, TypeError):
            return None
    return None


@router.get("/{hardware_id}/telemetry", response_model=TelemetryResponse)
@limiter.limit(lambda: get_limit("telemetry"))
async def get_telemetry(
    request: Request,
    response: Response,
    hardware_id: int,
    db: Annotated[Session, Depends(get_db)],
    _user_id: int = Depends(require_auth_always),
) -> TelemetryResponse:
    hw = db.query(Hardware).filter(Hardware.id == hardware_id).first()
    if hw is None:
        raise HTTPException(status_code=404, detail="Hardware not found")
    return await get_telemetry_for_hardware(hardware_id, db)


@router.post("/{hardware_id}/telemetry/config")
def configure_telemetry(
    hardware_id: int,
    config: TelemetryConfig,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    vault: Annotated[CredentialVault, Depends(get_vault)],
    current_user: Annotated[User, require_scope("write", "telemetry")],
) -> dict[str, Any]:
    hw = db.query(Hardware).filter(Hardware.id == hardware_id).first()
    if not hw:
        raise HTTPException(status_code=404, detail="Hardware not found")

    config_dict = config.model_dump()
    if config_dict.get("password"):
        config_dict["password"] = vault.encrypt(config_dict["password"])

    hw.telemetry_config = config_dict
    db.commit()
    log_audit(
        db,
        request,
        user_id=current_user.id,
        action="telemetry_config_updated",
        resource=f"hardware:{hardware_id}",
        status="ok",
    )
    return {"message": "Telemetry config saved.", "hardware_id": hardware_id}


@router.post("/{hardware_id}/telemetry/poll")
async def poll_now(
    hardware_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    vault: Annotated[CredentialVault, Depends(get_vault)],
    current_user: Annotated[User, require_role("admin")],
) -> dict[str, Any]:
    """Manual on-demand poll."""
    hw = db.query(Hardware).filter(Hardware.id == hardware_id).first()
    if not hw:
        raise HTTPException(status_code=404, detail="Hardware not found")

    # poll_hardware is synchronous and talks to the device — SNMP via blocking
    # subprocess.run, Redfish via blocking HTTP. Called inline from this async
    # endpoint it ran on the event loop, so one unreachable host stalled every
    # request the API process was serving, not just this one: the
    # snmp_network_device profile alone spends up to ~105s in the kernel (three
    # 5s snmpget calls plus nine 10s snmpwalk calls) before it gives up. Hand it
    # to a worker thread and cap it, exactly as the collector does.
    #
    # One deliberate consequence: poll_hardware's _fire_and_forget_publish is a
    # no-op off the loop (it needs a running loop and logs a debug line without
    # one). That publish was redundant here anyway — write_telemetry below is
    # the authoritative cache+publish for this path — so the manual poll now
    # emits one telemetry event instead of two racing ones.
    #
    # The thread gets a detached stub rather than the live ORM row, the same way
    # the collector does, and on the timeout path that is load-bearing rather
    # than tidiness: a timed-out poll leaks its thread (see below), and that
    # thread reads hardware.id at dispatcher.py:95 *after* the slow call
    # returns. By then this request has committed through write_telemetry, and a
    # commit expires the instance, so that read would fire a refresh SELECT on
    # this request's Session from a second thread. Sessions are not thread-safe.
    # The stub carries every attribute poll_hardware touches — telemetry_config,
    # ip_address, id — and carries no Session with it.
    hw_stub = SimpleNamespace(
        id=hw.id,
        telemetry_config=hw.telemetry_config,
        ip_address=hw.ip_address,
    )
    timeout_s = _device_timeout_seconds()
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(poll_hardware, hw_stub, vault),
            timeout=timeout_s,
        )
    except TimeoutError:
        # The worker thread is not cancelled by this — asyncio.to_thread cannot
        # interrupt blocking C calls — but it is orphaned rather than awaited,
        # so the request returns on time and the thread retires when the
        # underlying socket timeout fires.
        result = {
            "status": "unreachable",
            "error_msg": f"Timeout reaching hardware {hardware_id} after {timeout_s}s",
            "data": {},
        }
    if "status" not in result and "error" in result:
        result = {"status": "unreachable", "error_msg": str(result["error"]), "data": {}}
    elif result.get("status") == "unknown" and "error" in result:
        result["status"] = "unreachable"
        result["error_msg"] = str(result["error"])

    response = await write_telemetry(
        hardware_id=hardware_id,
        payload=result,
        source="manual_poll",
        db=db,
    )
    log_audit(
        db,
        request,
        user_id=current_user.id,
        action="telemetry_poll_triggered",
        resource=f"hardware:{hardware_id}",
        status="ok",
    )

    return response.model_dump()


# ── Generic entity telemetry (Proxmox sidebar) ──────────────────────────────

_ENTITY_TYPES = {"hardware", "compute_unit", "storage"}


@router.get("/entity/{entity_type}/{entity_id}")
def get_entity_telemetry(
    entity_type: str,
    entity_id: int,
    db: Annotated[Session, Depends(get_db)],
    _user: Annotated[User, require_scope("read", "*")],
) -> dict[str, Any]:
    if entity_type not in _ENTITY_TYPES:
        raise HTTPException(status_code=400, detail=f"entity_type must be one of {_ENTITY_TYPES}")

    try:
        return _get_entity_telemetry_inner(entity_type, entity_id, db)
    except HTTPException:
        raise
    except Exception as exc:
        _logger.warning("Entity telemetry %s:%d failed: %s", entity_type, entity_id, exc)
        return {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "status": "error",
            "error": "Telemetry temporarily unavailable",
        }


def _get_entity_telemetry_inner(entity_type: str, entity_id: int, db: Session) -> dict:
    result: dict = {"entity_type": entity_type, "entity_id": entity_id}

    if entity_type == "hardware":
        hw = db.get(Hardware, entity_id)
        if not hw:
            raise HTTPException(status_code=404, detail="Hardware not found")
        tdata = _safe_json(hw.telemetry_data) or {}
        result.update(
            {
                "name": hw.name,
                "status": hw.status,
                "telemetry_status": hw.telemetry_status,
                "telemetry_last_polled": hw.telemetry_last_polled,
                **tdata,
            }
        )
        vms_running = (
            db.query(ComputeUnit)
            .filter(
                ComputeUnit.hardware_id == hw.id,
                ComputeUnit.proxmox_type == "qemu",
                ComputeUnit.status == "active",
            )
            .count()
        )
        vms_stopped = (
            db.query(ComputeUnit)
            .filter(
                ComputeUnit.hardware_id == hw.id,
                ComputeUnit.proxmox_type == "qemu",
                ComputeUnit.status != "active",
            )
            .count()
        )
        cts_running = (
            db.query(ComputeUnit)
            .filter(
                ComputeUnit.hardware_id == hw.id,
                ComputeUnit.proxmox_type == "lxc",
                ComputeUnit.status == "active",
            )
            .count()
        )
        cts_stopped = (
            db.query(ComputeUnit)
            .filter(
                ComputeUnit.hardware_id == hw.id,
                ComputeUnit.proxmox_type == "lxc",
                ComputeUnit.status != "active",
            )
            .count()
        )
        result["child_vms"] = {"running": vms_running, "stopped": vms_stopped}
        result["child_cts"] = {"running": cts_running, "stopped": cts_stopped}

        storage_items = db.query(Storage).filter(Storage.hardware_id == hw.id).all()
        result["storage_summary"] = [
            {"name": s.name, "kind": s.kind, "capacity_gb": s.capacity_gb, "used_gb": s.used_gb}
            for s in storage_items
        ]

    elif entity_type == "compute_unit":
        cu = db.get(ComputeUnit, entity_id)
        if not cu:
            raise HTTPException(status_code=404, detail="Compute unit not found")
        pve_status = _safe_json(cu.proxmox_status) or {}
        result.update(
            {
                "name": cu.name,
                "status": cu.status,
                "proxmox_vmid": cu.proxmox_vmid,
                "proxmox_type": cu.proxmox_type,
                **pve_status,
            }
        )

    elif entity_type == "storage":
        st = db.get(Storage, entity_id)
        if not st:
            raise HTTPException(status_code=404, detail="Storage not found")
        result.update(
            {
                "name": st.name,
                "kind": st.kind,
                "protocol": st.protocol,
                "capacity_gb": st.capacity_gb,
                "used_gb": st.used_gb,
                "parent_node": st.hardware.name if st.hardware else None,
            }
        )

    # Attach recent timeseries if available
    recent = (
        db.query(TelemetryTimeseries)
        .filter(
            TelemetryTimeseries.entity_type == entity_type,
            TelemetryTimeseries.entity_id == entity_id,
        )
        .order_by(desc(TelemetryTimeseries.ts))
        .limit(20)
        .all()
    )
    result["timeseries"] = [
        {"metric": r.metric, "value": r.value, "ts": r.ts.isoformat() if r.ts else None}
        for r in recent
    ]

    return result
