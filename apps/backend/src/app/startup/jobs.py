"""Every scheduled job the API process registers at startup.

One function, called once from ``main.lifespan`` between constructing the
scheduler and starting it.  Extracted from the lifespan because this is where
almost all of its length was: a job list is read and edited far more often than
the startup sequence around it, and the two do not need to share a file.

``SingleOwnerScheduler`` takes an advisory lock keyed on the job id, so every
job below runs on exactly one process however many replicas the deployment has.
The cron minutes are chosen so the nightly purges do not queue behind each
other; the comments at each registration say which neighbour a time is avoiding.
"""

import logging
import os
from datetime import timedelta
from typing import TYPE_CHECKING

import sqlalchemy as sa
from apscheduler.triggers.cron import CronTrigger

from app.core.sql_hardening import build_audit_partition_sql
from app.core.time import utcnow
from app.db import models
from app.db.models import IntegrationConfig
from app.db.session import get_session_context
from app.services import discovery_service
from app.startup.scheduler import register_discovery_profile_crons

if TYPE_CHECKING:
    from app.core.scheduler import SingleOwnerScheduler

_logger = logging.getLogger(__name__)


def register_scheduled_jobs(scheduler: "SingleOwnerScheduler") -> None:
    """Add every startup-registered job to `scheduler`, before it is started."""
    # Daily purge of old scan results — and the *only* registration of it.
    # `core.scheduler.reload_discovery_jobs` used to register the same callable
    # on the same 03:00 trigger under a second id, `discovery_purge` (B43), so
    # every discovery-profile write left two jobs running one purge.
    # `SingleOwnerScheduler` keys its advisory lock on the job id, so two ids
    # meant two locks and the copies did not exclude each other; what kept the
    # DELETE from actually running twice at once was the callable's own inner
    # `run_with_advisory_lock("discovery_purge")`, which is not a guarantee the
    # scheduler makes and not one a reader of this call site can see. The visible
    # cost was two `background_job_runs_total{outcome="ran"}` samples a night for
    # one purge; the latent cost was that deleting that inner lock — a reasonable
    # cleanup, since `SingleOwnerScheduler` is meant to make it redundant — turned
    # a duplicate registration into a concurrent double purge.
    #
    # `misfire_grace_time` matches the other nightly crons; see the
    # `daily_db_snapshot` registration below for what it does and does not cover.
    scheduler.add_job(
        discovery_service.purge_old_scan_results,
        trigger=CronTrigger(hour=3, minute=0),
        id="purge_old_scan_results",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # hardware_live_metrics and telemetry_timeseries retention is now managed by
    # TimescaleDB retention policies (migration 0050). Manual DELETE jobs have been
    # removed. If TimescaleDB is not installed, fallback functions remain available
    # in app.services.telemetry_service and app.workers.cleanup.

    # Daily purge of old audit log entries based on retention setting
    from app.services.log_purge import purge_old_audit_logs

    scheduler.add_job(
        purge_old_audit_logs,
        trigger=CronTrigger(hour=3, minute=15),
        id="audit_log_purge",
        replace_existing=True,
    )

    # listener_events is the only discovery table fed directly by unauthenticated
    # LAN traffic: every mDNS advertisement and every SSDP datagram that clears
    # the rate gate appends a row, and nothing removed them. The listener's own
    # admission control bounds the rate, not the total, so on a noisy network the
    # table grows without limit on the same volume that holds pgdata (B13).
    #
    # 03:30 keeps it clear of its neighbours, which matter because
    # SingleOwnerScheduler takes an advisory lock keyed on the job id and a purge
    # that overlaps another purge just queues behind it: scan results run at
    # 03:00, audit logs at 03:15, probe runs at 03:20.
    from app.services.listener_purge import purge_old_listener_events

    scheduler.add_job(
        purge_old_listener_events,
        trigger=CronTrigger(hour=3, minute=30),
        id="listener_event_purge",
        replace_existing=True,
    )

    # Slice 3 §1: probe runs are audit for checks the server did not perform
    # itself and are retained for seven days. Long-term availability stays in
    # telemetry_timeseries and the monitor rollups, so nothing here is the
    # system of record for uptime.
    from app.services.monitoring.probe_reconcile import purge_old_probe_runs

    scheduler.add_job(
        purge_old_probe_runs,
        trigger=CronTrigger(hour=3, minute=20),
        id="monitor_probe_run_purge",
        replace_existing=True,
    )

    # Monthly audit_log partition maintenance — ensures partitions exist ahead of time
    def _ensure_audit_partitions() -> None:
        try:
            with get_session_context() as db:
                now = utcnow()
                for offset in range(3):
                    dt = now + timedelta(days=30 * offset)
                    db.execute(sa.text(build_audit_partition_sql(dt)))
                db.commit()
        except Exception:
            _logger.debug("audit partition maintenance skipped (table may not exist yet)")

    scheduler.add_job(
        _ensure_audit_partitions,
        trigger=CronTrigger(day=28, hour=2, minute=0),
        id="audit_partition_maintenance",
        replace_existing=True,
    )

    # Disable expired demo accounts (M-18: demo user expiration enforcement)
    def _disable_expired_demo_users() -> None:
        from app.db.models import User

        try:
            with get_session_context() as db:
                now = utcnow()
                expired = (
                    db.query(User)
                    .filter(
                        User.role == "demo",
                        User.demo_expires.isnot(None),
                        User.demo_expires <= now,
                        User.is_active.is_(True),
                    )
                    .all()
                )
                for u in expired:
                    u.is_active = False
                if expired:
                    db.commit()
                    _logger.info("Disabled %d expired demo user(s)", len(expired))
                    from app.core.worker_audit import log_worker_audit

                    for u in expired:
                        log_worker_audit(
                            action="disable_expired_demo_user",
                            entity_type="user",
                            entity_id=u.id,
                            severity="warn",
                            details=f"email={u.email} demo_expires={u.demo_expires}",
                            worker_name="scheduler",
                        )
        except Exception as exc:
            _logger.warning("Expired demo user cleanup failed: %s", exc)

    scheduler.add_job(
        _disable_expired_demo_users,
        trigger=CronTrigger(hour=4, minute=0),
        id="disable_expired_demo_users",
        replace_existing=True,
    )

    # Auto-reject agents left pending approval for too long (Task 22 gap:
    # expire_stale_pending_agents existed and was unit-tested but was never
    # actually scheduled).
    def _expire_pending_agents_job() -> None:
        from app.services import agent_registry

        with get_session_context() as db:
            count = agent_registry.expire_stale_pending_agents(db)
            if count:
                _logger.info("expired %d stale pending agent(s)", count)

    scheduler.add_job(
        _expire_pending_agents_job,
        trigger=CronTrigger(hour=3, minute=30),
        id="expire_pending_agents",
        replace_existing=True,
    )

    # Daily uptime rollup for fast historical uptime reads.
    from app.workers.rollup_worker import run_rollup_job

    scheduler.add_job(
        run_rollup_job,
        trigger=CronTrigger(hour=0, minute=5),
        id="daily_uptime_rollup",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # Chain any audit entries that a contended audit-chain lock forced into the
    # spool (services/audit_spool.py). Runs often because the spool window is
    # the one stretch where an audit record exists but carries no tamper
    # evidence of its own — the shorter it is, the better. Cheap when idle: one
    # indexed COUNT-shaped read that finds nothing and returns.
    from apscheduler.triggers.interval import IntervalTrigger

    from app.services.audit_spool import drain as drain_audit_spool

    scheduler.add_job(
        drain_audit_spool,
        trigger=IntervalTrigger(minutes=1),
        id="audit_spool_drain",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=300,
    )

    # Daily PostgreSQL backup (skipped when pg_dump is not on PATH)
    from app.services.db_backup import backup_postgres

    scheduler.add_job(
        backup_postgres,
        trigger=CronTrigger(hour=3, minute=30),
        id="pg_backup",
        replace_existing=True,
    )

    # Daily full-state snapshot at 02:00 — the tarball that carries the vault
    # key, the uploads and the config, and the only artifact `cb restore`
    # accepts. Registered here rather than in `core.scheduler.reload_discovery_jobs`,
    # which runs only when an administrator writes a discovery profile and first
    # removes every job it registered: a snapshot job added there exists only in
    # the stretch between a profile write and the next restart. Nothing surfaces
    # the gap, because `latest_backup_info()` reports the `pg_backup` artifact
    # scheduled just above — the absence is discovered at restore time, which is
    # the one moment it cannot be repaired.
    #
    # What `misfire_grace_time` buys, precisely, because the first version of
    # this comment got it wrong (R11): it covers a *running* process whose
    # scheduler wakeup lands late — a stalled event loop, a saturated thread
    # pool, a host that was suspended and resumed. APScheduler's default grace
    # is one second, so without it a two-second hiccup at 02:00 drops the
    # night's snapshot and leaves nothing but a log line. It does **not** cover a
    # restart. The scheduler above is constructed fresh on every boot and keeps
    # its jobs in APScheduler's default in-memory store, so a process that was
    # down at 02:00 holds no record that 02:00 happened; misfire grace forgives a
    # fire time the scheduler is holding, and there is none to forgive.
    #
    # Making the restart claim true would take a persistent job store, and that
    # is not a parameter change here: `SingleOwnerScheduler.add_job` hands
    # APScheduler a `functools.wraps` closure, and a persistent store serialises
    # a job by `__module__:__qualname__` — which `wraps` has already rewritten to
    # name the *unwrapped* function. Every job would come back from the store
    # without its advisory lock, and SRV-02 would be silently gone. If a boot-time
    # catch-up is ever wanted, it belongs in an explicit "was last night's
    # snapshot taken?" check, not in this parameter.
    from app.core.scheduler import run_scheduled_snapshot

    scheduler.add_job(
        run_scheduled_snapshot,
        trigger=CronTrigger(hour=2, minute=0),
        id="daily_db_snapshot",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # Uptime Kuma integration sync — every 60 seconds
    from apscheduler.triggers.interval import IntervalTrigger

    from app.workers.integration_sync_worker import run_integration_sync_job

    scheduler.add_job(
        run_integration_sync_job,
        trigger=IntervalTrigger(seconds=60),
        id="integration_sync_job",
        replace_existing=True,
    )

    # CVE sync — only scheduled when enabled in settings
    from app.services.cve_service import sync_nvd_feed

    with get_session_context() as cve_db:
        cve_settings = cve_db.query(models.AppSettings).first()
        if cve_settings and cve_settings.cve_sync_enabled:
            interval_hours = cve_settings.cve_sync_interval_hours or 24
            scheduler.add_job(
                sync_nvd_feed,
                trigger=IntervalTrigger(hours=interval_hours),
                id="cve_sync",
                replace_existing=True,
                misfire_grace_time=3600,
            )
            _logger.info("CVE sync scheduled every %d hours", interval_hours)

    # Privacy periodic pass — feed refresh + hostile-network checks + snapshot.
    # Always scheduled; the job itself honors windscribe_enabled and the
    # windscribe_feed_refresh_hours feed-age gate at runtime, so the in-app
    # toggle applies without a restart.
    from app.core.constants import PRIVACY_PERIODIC_INTERVAL_MINUTES
    from app.services.privacy_score import run_privacy_periodic_job

    scheduler.add_job(
        run_privacy_periodic_job,
        trigger=IntervalTrigger(minutes=PRIVACY_PERIODIC_INTERVAL_MINUTES),
        id="privacy_periodic",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=300,
    )

    # Discovery-readiness Phase 2 — self-healing reconciliation. Always
    # scheduled; the job itself no-ops when cb-helperd isn't installed, so
    # the in-app LAN-discovery toggle applies without a restart once it is.
    from app.core.constants import DISCOVERY_RECONCILE_INTERVAL_MINUTES
    from app.services.discovery_reconciler import run_discovery_reconciliation

    scheduler.add_job(
        run_discovery_reconciliation,
        trigger=IntervalTrigger(minutes=DISCOVERY_RECONCILE_INTERVAL_MINUTES),
        id="discovery_reconciler",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=300,
    )

    # Slice 4 D-5 — agent discovery job reconciliation. A *different* concern
    # from the readiness reconciler above, which shares nothing with it but a
    # word: this one expires dispatch leases whose agent went silent, retries
    # jobs parked in `waiting_for_agent` when their agent reconnects, and drains
    # the `queued` backlog that `_schedule_queued_scan_jobs` otherwise strands.
    # Registered here rather than in `core.scheduler.reload_discovery_jobs`,
    # which is re-invoked on every profile write and first removes every job it
    # registered — a job added there is silently unregistered the next time an
    # administrator saves a profile. It holds its own advisory lock.
    from app.services.agent_discovery_reconcile import (
        RECONCILE_INTERVAL_S as AGENT_DISCOVERY_RECONCILE_INTERVAL_S,
    )
    from app.services.agent_discovery_reconcile import (
        run_agent_discovery_reconciliation,
    )

    scheduler.add_job(
        run_agent_discovery_reconciliation,
        trigger=IntervalTrigger(seconds=AGENT_DISCOVERY_RECONCILE_INTERVAL_S),
        id="agent_discovery_reconcile",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=300,
    )

    # IP Pool refresh every hour
    scheduler.add_job(
        discovery_service.refresh_ip_pool,
        trigger=CronTrigger(minute=0),
        id="refresh_ip_pool",
        replace_existing=True,
        max_instances=1,
    )

    # Load the discovery profiles that are due a cron and schedule them.
    with get_session_context() as sched_db:
        register_discovery_profile_crons(scheduler, sched_db)

    # Uptime monitoring is handled by the item-based polling engine
    # (workers: monitor_scheduler + monitor_poll). The legacy run_all_monitors_job
    # APScheduler loop was retired in the polling-engine migration.
    from apscheduler.triggers.interval import IntervalTrigger as _IT

    # Docker topology sync — only when docker_discovery_enabled
    with get_session_context() as docker_db:
        docker_settings = docker_db.query(models.AppSettings).first()
        if docker_settings and getattr(docker_settings, "docker_discovery_enabled", False):
            interval_mins = getattr(docker_settings, "docker_sync_interval_minutes", 5) or 5
            from app.services.docker_discovery import run_docker_sync_job

            scheduler.add_job(
                run_docker_sync_job,
                trigger=_IT(minutes=interval_mins),
                id="docker_topology_sync",
                replace_existing=True,
                max_instances=1,
                misfire_grace_time=60,
            )
            _logger.info("Docker topology sync scheduled every %d minutes.", interval_mins)

    # ── Proxmox telemetry polling ────────────────────────────────────────
    # Route F9: these five were closures defined here in the lifespan, so
    # nothing could import or test them. They now live in app/jobs/proxmox.py
    # with their health writers; the bodies are unchanged.
    from app.jobs.proxmox import (
        proxmox_full_sync,
        proxmox_node_poll,
        proxmox_rrd_poll,
        proxmox_storage_refresh,
        proxmox_vm_poll,
    )

    with get_session_context() as pxmx_db:
        from sqlalchemy import func

        has_proxmox = (
            pxmx_db.query(IntegrationConfig)
            .filter(
                IntegrationConfig.type == "proxmox",
                IntegrationConfig.auto_sync.is_(True),
            )
            .first()
        )
        if has_proxmox:
            _pxmx_node_s = int(os.environ.get("PROXMOX_NODE_POLL_SECONDS", "30"))
            _pxmx_vm_s = int(os.environ.get("PROXMOX_VM_POLL_SECONDS", "120"))
            scheduler.add_job(
                proxmox_node_poll,
                trigger=_IT(seconds=_pxmx_node_s),
                id="proxmox_node_telemetry",
                replace_existing=True,
                max_instances=1,
                coalesce=True,
                misfire_grace_time=15,
            )
            scheduler.add_job(
                proxmox_vm_poll,
                trigger=_IT(seconds=_pxmx_vm_s),
                id="proxmox_vm_telemetry",
                replace_existing=True,
                max_instances=1,
                coalesce=True,
                misfire_grace_time=60,
            )
            _pxmx_rrd_s = int(os.environ.get("PROXMOX_RRD_POLL_SECONDS", "300"))

            scheduler.add_job(
                proxmox_rrd_poll,
                trigger=_IT(seconds=_pxmx_rrd_s),
                id="proxmox_rrd_telemetry",
                replace_existing=True,
                max_instances=1,
            )

            scheduler.add_job(
                proxmox_storage_refresh,
                trigger=_IT(seconds=300),
                id="proxmox_storage_refresh",
                replace_existing=True,
                max_instances=1,
            )
            sync_interval = (
                pxmx_db.query(func.min(IntegrationConfig.sync_interval_s))
                .filter(
                    IntegrationConfig.type == "proxmox",
                    IntegrationConfig.auto_sync.is_(True),
                )
                .scalar()
                or 300
            )
            scheduler.add_job(
                proxmox_full_sync,
                trigger=_IT(seconds=sync_interval),
                id="proxmox_full_sync",
                replace_existing=True,
                max_instances=1,
                misfire_grace_time=120,
            )
            _logger.info(
                "Proxmox scheduled: telemetry (nodes 30s, VMs 120s, RRD %ds), full sync every %ds.",
                _pxmx_rrd_s,
                sync_interval,
            )

    # ── Phase 4: ARP Prober — scheduled subnet sweep ───────────────────────
    with get_session_context() as phase4_db:
        phase4_settings = phase4_db.query(models.AppSettings).first()
        if phase4_settings and getattr(phase4_settings, "arp_enabled", False):
            prober_interval = getattr(phase4_settings, "prober_interval_minutes", 15) or 15
            from app.services.prober_service import run_prober_job

            scheduler.add_job(
                run_prober_job,
                trigger=_IT(minutes=prober_interval),
                id="arp_prober",
                replace_existing=True,
                max_instances=1,
                misfire_grace_time=120,
            )
            _logger.info("ARP prober scheduled every %d minutes.", prober_interval)

    # ── Certificate auto-renewal (daily at 3:45 AM) ─────────────────────
    def _cert_renewal_job() -> None:
        from app.services.certificate_service import check_and_renew_expiring

        with get_session_context() as cert_db:
            check_and_renew_expiring(cert_db)

    scheduler.add_job(
        _cert_renewal_job,
        trigger=CronTrigger(hour=3, minute=45),
        id="cert_auto_renewal",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # ── Vault key auto-rotation (daily at 4:30 AM) ────────────────────
    def _vault_rotation_check() -> None:
        from app.services.vault_service import rotate_vault_key

        with get_session_context() as vault_db:
            from app.db.models import AppSettings

            cfg = vault_db.get(AppSettings, 1)
            if not cfg:
                return
            rotation_days = getattr(cfg, "vault_key_rotation_days", 90) or 90
            rotated_at = getattr(cfg, "vault_key_rotated_at", None)
            if rotated_at is None or (utcnow() - rotated_at) > timedelta(days=rotation_days):
                _logger.info(
                    "Vault key rotation due (last rotated: %s, interval: %d days)",
                    rotated_at,
                    rotation_days,
                )
                try:
                    rotate_vault_key(vault_db)
                    from app.core.worker_audit import log_worker_audit

                    log_worker_audit(
                        action="vault_key_rotated",
                        entity_type="vault",
                        severity="warn",
                        details=f"rotation_days={rotation_days}",
                        worker_name="scheduler",
                    )
                except Exception as exc:
                    _logger.error("Vault key auto-rotation failed: %s", exc)

    scheduler.add_job(
        _vault_rotation_check,
        trigger=CronTrigger(hour=4, minute=30),
        id="vault_rotation_check",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=3600,
    )

    from app.workers.analytics_worker import run_analytics_job, run_retention_job

    scheduler.add_job(
        run_analytics_job,
        trigger=CronTrigger(hour=2, minute=30),
        id="analytics_job",
        replace_existing=True,
    )
    scheduler.add_job(
        run_retention_job,
        trigger=CronTrigger(hour=3, minute=30),
        id="retention_job",
        replace_existing=True,
    )
