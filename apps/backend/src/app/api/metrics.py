"""Prometheus-compatible metrics endpoint.

Exposes inventory counts, per-service status, and configured resource data
from the Circuit Breaker database in Prometheus text exposition format.

Endpoint: GET /api/v1/metrics

Auth: when auth_enabled=True or CB_API_TOKEN is set, a valid Bearer token
is required (same model as the rest of the protected API). When auth is off
the endpoint is public, consistent with the unauthenticated read API.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Gauge,
    Info,
    generate_latest,
)
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings as _app_settings
from app.core.security import get_optional_user
from app.db.models import (
    ComputeUnit,
    Doc,
    ExternalNode,
    Hardware,
    HardwareCluster,
    Log,
    MiscItem,
    Network,
    Service,
    ServiceDependency,
    Storage,
    Tag,
    User,
)
from app.db.session import get_db

_logger = logging.getLogger(__name__)
router = APIRouter()

# All possible service status values — used to emit 0-valued series for
# inactive states so Prometheus can alert on absence of a state.
_SERVICE_STATUSES = ("running", "stopped", "degraded", "maintenance")


def _check_metrics_auth(
    user_id: int | None = Depends(get_optional_user),
) -> None:
    """Require authentication for metrics access."""
    if user_id is None:
        raise HTTPException(status_code=401, detail="Authentication required")


@router.get(
    "/metrics",
    response_class=Response,
    include_in_schema=False,
    summary="Prometheus metrics",
)
def prometheus_metrics(
    db: Session = Depends(get_db),
    _auth: None = Depends(_check_metrics_auth),
) -> Response:
    """Return all Circuit Breaker inventory metrics in Prometheus text format."""
    reg = CollectorRegistry(auto_describe=False)

    # ------------------------------------------------------------------
    # App metadata
    # ------------------------------------------------------------------
    app_info = Info("circuitbreaker", "Circuit Breaker application metadata", registry=reg)
    app_info.info({"version": _app_settings.app_version})

    # ------------------------------------------------------------------
    # Inventory counts — simple aggregates, one query per entity type
    # ------------------------------------------------------------------

    # Hardware
    hw_total = Gauge(
        "circuitbreaker_hardware_total",
        "Total hardware nodes in inventory",
        registry=reg,
    )
    hw_total.set(db.query(func.count(Hardware.id)).scalar() or 0)

    # Compute units — labelled by kind (vm / container)
    cu_total = Gauge(
        "circuitbreaker_compute_units_total",
        "Compute units in inventory grouped by kind",
        ["kind"],
        registry=reg,
    )
    for kind, count in (
        db.query(ComputeUnit.kind, func.count(ComputeUnit.id)).group_by(ComputeUnit.kind).all()
    ):
        cu_total.labels(kind=kind or "unknown").set(count)

    # Services — unlabelled total
    svc_total = Gauge(
        "circuitbreaker_services_total",
        "Total services in inventory",
        registry=reg,
    )
    svc_total.set(db.query(func.count(Service.id)).scalar() or 0)

    # Services — grouped by operational status
    svc_by_status = Gauge(
        "circuitbreaker_services_by_status_total",
        "Services in inventory grouped by operational status",
        ["status"],
        registry=reg,
    )
    status_counts: dict[str, int] = {}
    for status, count in (
        db.query(Service.status, func.count(Service.id)).group_by(Service.status).all()
    ):
        status_counts[status or "unknown"] = count
    for status in _SERVICE_STATUSES:
        svc_by_status.labels(status=status).set(status_counts.get(status, 0))

    # Storage items — grouped by kind
    storage_items = Gauge(
        "circuitbreaker_storage_items_total",
        "Storage items in inventory grouped by kind",
        ["kind"],
        registry=reg,
    )
    for kind, count in db.query(Storage.kind, func.count(Storage.id)).group_by(Storage.kind).all():
        storage_items.labels(kind=kind or "unknown").set(count)

    # Storage — aggregate capacity and usage
    capacity_total = Gauge(
        "circuitbreaker_storage_capacity_gb_total",
        "Sum of all configured storage capacity in GB",
        registry=reg,
    )
    capacity_total.set(db.query(func.coalesce(func.sum(Storage.capacity_gb), 0)).scalar() or 0)

    used_total = Gauge(
        "circuitbreaker_storage_used_gb_total",
        "Sum of all reported storage usage in GB",
        registry=reg,
    )
    used_total.set(db.query(func.coalesce(func.sum(Storage.used_gb), 0)).scalar() or 0)

    # Networks
    net_total = Gauge(
        "circuitbreaker_networks_total",
        "Total network segments in inventory",
        registry=reg,
    )
    net_total.set(db.query(func.count(Network.id)).scalar() or 0)

    # Hardware clusters
    cluster_total = Gauge(
        "circuitbreaker_hardware_clusters_total",
        "Total hardware clusters defined",
        registry=reg,
    )
    cluster_total.set(db.query(func.count(HardwareCluster.id)).scalar() or 0)

    # External nodes — labelled by provider and kind
    ext_total = Gauge(
        "circuitbreaker_external_nodes_total",
        "External nodes grouped by provider and kind",
        ["provider", "kind"],
        registry=reg,
    )
    for provider, kind, count in (
        db.query(ExternalNode.provider, ExternalNode.kind, func.count(ExternalNode.id))
        .group_by(ExternalNode.provider, ExternalNode.kind)
        .all()
    ):
        ext_total.labels(provider=provider or "unknown", kind=kind or "unknown").set(count)

    # Misc items
    misc_total = Gauge(
        "circuitbreaker_misc_items_total",
        "Total miscellaneous items in inventory",
        registry=reg,
    )
    misc_total.set(db.query(func.count(MiscItem.id)).scalar() or 0)

    # Docs
    docs_total = Gauge(
        "circuitbreaker_docs_total",
        "Total documentation entries",
        registry=reg,
    )
    docs_total.set(db.query(func.count(Doc.id)).scalar() or 0)

    # Users
    users_total = Gauge(
        "circuitbreaker_users_total",
        "Total registered users",
        registry=reg,
    )
    users_total.set(db.query(func.count(User.id)).scalar() or 0)

    # Tags
    tags_total = Gauge(
        "circuitbreaker_tags_total",
        "Total unique tags in use",
        registry=reg,
    )
    tags_total.set(db.query(func.count(Tag.id)).scalar() or 0)

    # Service dependency edges
    deps_total = Gauge(
        "circuitbreaker_service_dependencies_total",
        "Total service-to-service dependency edges",
        registry=reg,
    )
    deps_total.set(db.query(func.count(ServiceDependency.service_id)).scalar() or 0)

    # Audit log entries — labelled by level and category
    log_entries = Gauge(
        "circuitbreaker_audit_log_entries_total",
        "Audit log entries grouped by level and category",
        ["level", "category"],
        registry=reg,
    )
    for level, category, count in (
        db.query(Log.level, Log.category, func.count(Log.id))
        .group_by(Log.level, Log.category)
        .all()
    ):
        log_entries.labels(level=level or "unknown", category=category or "unknown").set(count)

    # ------------------------------------------------------------------
    # Per-resource state — high-cardinality labeled gauges
    # ------------------------------------------------------------------

    # Service status: emit a series for every (service × possible_status)
    # combination. The active state gets value 1, all others get 0.
    # This mirrors the kube-state-metrics pattern so users can alert with:
    #   circuitbreaker_service_status{status="stopped"} == 1
    svc_status = Gauge(
        "circuitbreaker_service_status",
        "Current operational status of each service (1 = active state, 0 = inactive)",
        ["name", "slug", "environment", "status"],
        registry=reg,
    )
    services = db.query(Service.name, Service.slug, Service.environment, Service.status).all()
    for svc_name, svc_slug, svc_env, svc_current_status in services:
        for possible_status in _SERVICE_STATUSES:
            svc_status.labels(
                name=svc_name or "",
                slug=svc_slug or "",
                environment=svc_env or "",
                status=possible_status,
            ).set(1 if svc_current_status == possible_status else 0)

    # Hardware configured memory
    hw_memory = Gauge(
        "circuitbreaker_hardware_memory_configured_gb",
        "Configured memory per hardware node in GB",
        ["name", "role"],
        registry=reg,
    )
    for hw_name, hw_role, hw_mem in (
        db.query(Hardware.name, Hardware.role, Hardware.memory_gb)
        .filter(Hardware.memory_gb.isnot(None))
        .all()
    ):
        hw_memory.labels(name=hw_name or "", role=hw_role or "").set(hw_mem)

    # Compute unit configured memory
    cu_memory = Gauge(
        "circuitbreaker_compute_unit_memory_configured_mb",
        "Configured memory per compute unit in MB",
        ["name", "kind"],
        registry=reg,
    )
    for cu_name, cu_kind, cu_mem in (
        db.query(ComputeUnit.name, ComputeUnit.kind, ComputeUnit.memory_mb)
        .filter(ComputeUnit.memory_mb.isnot(None))
        .all()
    ):
        cu_memory.labels(name=cu_name or "", kind=cu_kind or "").set(cu_mem)

    # Compute unit configured CPU cores
    cu_cpu = Gauge(
        "circuitbreaker_compute_unit_cpu_cores_configured",
        "Configured CPU cores per compute unit",
        ["name", "kind"],
        registry=reg,
    )
    for cu_name, cu_kind, cu_cores in (
        db.query(ComputeUnit.name, ComputeUnit.kind, ComputeUnit.cpu_cores)
        .filter(ComputeUnit.cpu_cores.isnot(None))
        .all()
    ):
        cu_cpu.labels(name=cu_name or "", kind=cu_kind or "").set(cu_cores)

    # Storage item capacity
    storage_cap = Gauge(
        "circuitbreaker_storage_capacity_gb",
        "Configured capacity per storage item in GB",
        ["name", "kind"],
        registry=reg,
    )
    for st_name, st_kind, st_cap in (
        db.query(Storage.name, Storage.kind, Storage.capacity_gb)
        .filter(Storage.capacity_gb.isnot(None))
        .all()
    ):
        storage_cap.labels(name=st_name or "", kind=st_kind or "").set(st_cap)

    # Storage item used space
    storage_used = Gauge(
        "circuitbreaker_storage_used_gb",
        "Reported used space per storage item in GB",
        ["name", "kind"],
        registry=reg,
    )
    for st_name, st_kind, st_used in (
        db.query(Storage.name, Storage.kind, Storage.used_gb)
        .filter(Storage.used_gb.isnot(None))
        .all()
    ):
        storage_used.labels(name=st_name or "", kind=st_kind or "").set(st_used)

    # ------------------------------------------------------------------
    # Serialise and return
    # ------------------------------------------------------------------
    return Response(content=generate_latest(reg), media_type=CONTENT_TYPE_LATEST)
