"""ARP Prober — scheduled subnet sweep for Phase 4 Discovery Engine 2.0.

Creates a ScanJob with source_type='prober' and scan_types=['arp'], then
runs it using the existing run_scan_job() infrastructure so all progress
events, NATS messages, and WebSocket broadcasts work automatically.
"""

import asyncio
import logging

from app.db.models import AppSettings
from app.db.session import SessionLocal
from app.services.discovery_service import _arp_available, create_scan_job, run_scan_job

_logger = logging.getLogger(__name__)


async def run_prober_job(cidr: str | None = None) -> int | None:
    """
    Create and run an ARP-only ScanJob triggered by the prober scheduler.

    The DB setup phase runs in a thread executor so the sync SQLAlchemy
    calls do not block the asyncio event loop before the async scan begins.

    Args:
        cidr: Target CIDR to sweep. Defaults to settings.discovery_default_cidr.

    Returns:
        job_id if a job was created, None otherwise.
    """
    if not _arp_available():
        _logger.info("ARP prober skipped: scapy not available or insufficient privileges.")
        return None

    def _create_job() -> int | None:
        db = SessionLocal()
        try:
            settings = db.query(AppSettings).first()
            target_cidr = cidr or (settings.discovery_default_cidr if settings else None)
            if not target_cidr:
                _logger.info("ARP prober skipped: no target CIDR configured.")
                return None
            job = create_scan_job(
                db=db,
                target_cidr=target_cidr,
                scan_types=["arp"],
                triggered_by="prober",
                label="ARP Prober",
            )
            # Stamp source_type so the UI can distinguish prober jobs from manual ones
            job.source_type = "prober"
            db.commit()
            job_id = job.id
            _logger.info("ARP prober job %d created for %s.", job_id, target_cidr)
            return job_id
        finally:
            db.close()

    loop = asyncio.get_running_loop()
    job_id = await loop.run_in_executor(None, _create_job)
    if not job_id:
        return None

    await run_scan_job(job_id)
    return job_id
