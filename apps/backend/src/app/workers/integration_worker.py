"""Integration sync worker — polls external tools (Uptime Kuma, etc.) on a schedule.

Each enabled Integration is synced at its configured sync_interval_s.
The worker runs in-process as an asyncio task (registered in main.py lifespan).
Heavy sync work runs in a thread pool via asyncio.to_thread to avoid blocking the event loop.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import UTC, timedelta

from app.core.nats_client import nats_client
from app.core.otel import get_tracer
from app.core.time import utcnow
from app.core.worker_audit import log_worker_audit
from app.db.models import (
    Integration,
    IntegrationMonitor,
    IntegrationMonitorEvent,
    StatusGroup,
    StatusPage,
)
from app.db.session import get_session_context
from app.integrations.registry import get_plugin

_logger = logging.getLogger(__name__)
_LOOP_INTERVAL_S = 10.0  # how often to check which integrations are due


def _is_due(integ: Integration) -> bool:
    """Return True if this integration hasn't been synced within its configured interval."""
    if integ.last_synced_at is None:
        return True
    now = utcnow()
    due_at = integ.last_synced_at.replace(tzinfo=UTC) + timedelta(seconds=integ.sync_interval_s)
    return now >= due_at


def _upsert_monitors(db, integ: Integration, monitors) -> None:
    """Create/update/delete IntegrationMonitor rows based on the synced monitor list.

    - Rows whose external_id is in the sync result are upserted.
    - Rows no longer returned by the integration are deleted.
    """
    from app.core.time import utcnow as _utcnow

    synced_ids = {m.external_id for m in monitors}

    # Delete monitors no longer present in the integration
    existing = (
        db.query(IntegrationMonitor).filter(IntegrationMonitor.integration_id == integ.id).all()
    )
    for row in existing:
        if row.external_id not in synced_ids:
            db.delete(row)

    # Upsert each synced monitor
    existing_map = {row.external_id: row for row in existing}
    now = _utcnow()
    for m in monitors:
        existing_row = existing_map.get(m.external_id)
        if existing_row is None:
            row = IntegrationMonitor(
                integration_id=integ.id,
                external_id=m.external_id,
            )
            db.add(row)
        else:
            row = existing_row
            if row.status != m.status:
                event = IntegrationMonitorEvent(
                    monitor_id=row.id,
                    previous_status=row.status,
                    new_status=m.status,
                    detected_at=now,
                )
                db.add(event)
        row.name = m.name
        row.url = m.url
        row.status = m.status
        row.uptime_7d = m.uptime_7d
        row.uptime_30d = m.uptime_30d
        row.last_checked_at = now


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "page"


def _ensure_status_page(db, integ: Integration) -> None:
    """Auto-provision a status page for this integration if one doesn't exist.

    On every sync the group nodes are kept in sync with current monitors so
    newly-added or removed monitors appear automatically.
    """
    monitor_ids = [
        row.id
        for row in db.query(IntegrationMonitor)
        .filter(IntegrationMonitor.integration_id == integ.id)
        .all()
    ]

    page = db.query(StatusPage).filter(StatusPage.integration_id == integ.id).first()
    if page is None:
        slug = _slugify(integ.name)
        if db.query(StatusPage).filter(StatusPage.slug == slug).first():
            slug = f"{slug}-{integ.id}"
        page = StatusPage(name=integ.name, slug=slug, is_public=False, integration_id=integ.id)
        db.add(page)
        db.flush()

    group = db.query(StatusGroup).filter(StatusGroup.status_page_id == page.id).first()
    if group is None:
        group = StatusGroup(name="Monitors", status_page_id=page.id, nodes=[])
        db.add(group)
        db.flush()

    group.nodes = [{"type": "integration_monitor", "id": mid} for mid in monitor_ids]


def _sync_one(integration_id: int) -> bool:
    """Sync a single integration. Runs in a thread pool.

    Returns True if sync succeeded, False on error.
    """
    with get_session_context() as db:
        integ = db.get(Integration, integration_id)
        if integ is None or not integ.enabled:
            return False

        plugin_cls = get_plugin(integ.type)
        if plugin_cls is None:
            _logger.warning(
                "Integration %d has unknown type %r — skipping", integration_id, integ.type
            )
            return False

        config: dict = {"base_url": integ.base_url}
        if integ.slug:
            config["slug"] = integ.slug
        if integ.api_key:
            try:
                from app.services.credential_vault import get_vault

                config["api_key"] = get_vault().decrypt(integ.api_key)
            except Exception as exc:
                _logger.error("Integration %d: vault decrypt failed: %s", integration_id, exc)
                log_worker_audit(
                    action="integration_vault_error",
                    entity_type="integration",
                    entity_id=integration_id,
                    details=str(exc)[:200],
                    severity="error",
                    worker_name="integration_worker",
                )
                integ.sync_status = "error"
                integ.sync_error = f"vault: {exc}"
                integ.last_synced_at = utcnow()
                db.commit()
                return False

        plugin = plugin_cls()
        monitors = plugin.sync(config)  # never raises — returns [] on error

        _upsert_monitors(db, integ, monitors)
        _ensure_status_page(db, integ)

        if monitors:
            integ.sync_status = "ok"
            integ.sync_error = None
        else:
            # Empty result could mean zero monitors or a silent error in the plugin
            integ.sync_status = "ok"
            integ.sync_error = None
            log_worker_audit(
                action="integration_sync_empty",
                entity_type="integration",
                entity_id=integration_id,
                details="plugin returned no monitors",
                severity="warn",
                worker_name="integration_worker",
            )

        integ.last_synced_at = utcnow()
        db.commit()
        return True


async def run_integration_worker(stop_event: asyncio.Event) -> None:
    """In-process async worker: syncs all enabled integrations on their configured intervals.

    Registered in main.py lifespan alongside webhook_worker, discovery_worker, etc.
    """
    _logger.info("Integration worker starting")

    while not stop_event.is_set():
        try:
            with get_session_context() as db:
                integrations = (
                    db.query(Integration)
                    .filter(Integration.enabled == True)  # noqa: E712
                    .all()
                )
                due_ids = [i.id for i in integrations if _is_due(i)]

            for integration_id in due_ids:
                try:
                    with get_tracer().start_as_current_span("integration.sync_one") as span:
                        span.set_attribute("integration.id", integration_id)
                        await asyncio.to_thread(_sync_one, integration_id)
                    # Notify status_worker via NATS so it can recompute affected groups
                    try:
                        import json as _json

                        await nats_client.publish(
                            f"integrations.synced.{integration_id}",
                            _json.dumps({"integration_id": integration_id}).encode(),
                        )
                    except Exception as exc:
                        _logger.debug(
                            "Integration worker: NATS publish failed for %d: %s",
                            integration_id,
                            exc,
                        )
                except Exception as exc:
                    _logger.error(
                        "Integration worker: unhandled error syncing %d: %s",
                        integration_id,
                        exc,
                        exc_info=True,
                    )
        except Exception as exc:
            _logger.error("Integration worker: loop error: %s", exc, exc_info=True)

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=_LOOP_INTERVAL_S)
        except TimeoutError:
            pass

    _logger.info("Integration worker stopped")
