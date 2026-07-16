"""Self-healing reconciliation for discovery readiness (Phase 2).

Runs on a schedule (wired into APScheduler in main.py). Class-1 capabilities
(nmap_present, nmap_raw) are healed unconditionally on drift — no user
consent needed, matching Phase 1's own "should just always be true"
philosophy. Class-2 (LAN discovery) converges actual state toward the
persisted lan_discovery_desired setting, which only the user's explicit
toggle changes — the reconciler never enables LAN discovery on its own
initiative, only maintains or reverts what was already approved.

Per-capability failure counters are in-memory and reset on process restart;
this is a deliberate simplification (a missed backoff window after a
restart just means one extra retry at normal cadence, never incorrect
behavior).
"""

import logging
import time
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.core.constants import (
    DISCOVERY_RECONCILE_BACKOFF_MINUTES,
    DISCOVERY_RECONCILE_FAILURE_THRESHOLD,
    DISCOVERY_RECONCILE_INTERVAL_MINUTES,
)
from app.core.job_lock import run_with_advisory_lock
from app.core.worker_audit import log_worker_audit
from app.db.session import SessionLocal
from app.services import helper_client
from app.services.discovery_readiness import CapState, get_discovery_readiness
from app.services.settings_service import get_or_create_settings

logger = logging.getLogger(__name__)

_CLASS1_ACTIONS = {
    "nmap_present": "ensure_nmap",
    "nmap_raw": "grant_nmap_caps",
}

# capability_key -> {"failures": int, "next_attempt": float (time.monotonic())}
_STATE: dict[str, dict[str, float]] = {}


def reset_reconciler_state_for_tests() -> None:
    _STATE.clear()


def _due(key: str) -> bool:
    state = _STATE.get(key)
    if state is None:
        return True
    return time.monotonic() >= state["next_attempt"]


def _record(key: str, *, success: bool) -> None:
    state = _STATE.setdefault(key, {"failures": 0, "next_attempt": 0.0})
    if success:
        state["failures"] = 0
        state["next_attempt"] = time.monotonic() + DISCOVERY_RECONCILE_INTERVAL_MINUTES * 60
    else:
        state["failures"] += 1
        interval = (
            DISCOVERY_RECONCILE_BACKOFF_MINUTES
            if state["failures"] >= DISCOVERY_RECONCILE_FAILURE_THRESHOLD
            else DISCOVERY_RECONCILE_INTERVAL_MINUTES
        )
        state["next_attempt"] = time.monotonic() + interval * 60


def _attempt_heal(key: str, action_name: str, action_fn: Callable[[], object]) -> None:
    try:
        action_fn()
        _record(key, success=True)
        log_worker_audit(
            action=f"discovery_auto_heal_{action_name}",
            entity_type="discovery_capability",
            details=f"capability={key}",
            severity="info",
            worker_name="discovery_reconciler",
        )
    except Exception as exc:
        _record(key, success=False)
        log_worker_audit(
            action=f"discovery_auto_heal_{action_name}_failed",
            entity_type="discovery_capability",
            details=f"capability={key} error={exc}",
            severity="warn",
            worker_name="discovery_reconciler",
        )


def _reconcile_class1() -> None:
    if not helper_client.helper_installed():
        return
    caps_by_key = {c.key: c for c in get_discovery_readiness()}
    for key, action_name in _CLASS1_ACTIONS.items():
        cap = caps_by_key.get(key)
        if cap is None or cap.state != CapState.AUTO_FIXABLE:
            continue
        if not _due(key):
            continue
        action_fn = getattr(helper_client, action_name)
        _attempt_heal(key, action_name, action_fn)


def _reconcile_class2(db: Session) -> None:
    if not helper_client.helper_installed():
        return
    settings = get_or_create_settings(db)
    desired = bool(getattr(settings, "lan_discovery_desired", False))
    caps_by_key = {c.key: c for c in get_discovery_readiness()}
    arp = caps_by_key.get("arp_l2")
    actual_on = arp is not None and arp.state == CapState.READY

    key = "lan_discovery"
    if desired and not actual_on:
        if _due(key):
            _attempt_heal(key, "enable_lan_discovery", helper_client.enable_lan_discovery)
    elif not desired and actual_on:
        if _due(key):
            _attempt_heal(key, "disable_lan_discovery", helper_client.disable_lan_discovery)


def _reconcile_once() -> None:
    db = SessionLocal()
    try:
        _reconcile_class1()
        _reconcile_class2(db)
    except Exception:
        logger.exception("discovery reconciliation pass failed")
    finally:
        db.close()


def run_discovery_reconciliation() -> None:
    """APScheduler entry point. Guarded by a Postgres advisory lock so only
    one backend replica reconciles at a time — required because
    enable/disable_lan_discovery recreate the container and must never run
    concurrently from two processes."""
    run_with_advisory_lock("discovery_reconciler", job_fn=_reconcile_once)
