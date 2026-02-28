"""Admin endpoints: full backup export, restore import, and recent-changes feed."""
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.security import require_write_auth
from app.db.session import get_db
from app.db import models

_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


# ── Serialisation helpers ─────────────────────────────────────────────────

def _dt(v: Any) -> Optional[str]:
    """Convert datetime to ISO string; pass through strings or None."""
    if isinstance(v, datetime):
        return v.isoformat()
    return v


def _hw_to_dict(r: models.Hardware) -> dict:
    return dict(
        id=r.id, name=r.name, role=r.role, vendor=r.vendor,
        vendor_icon_slug=r.vendor_icon_slug, model=r.model, cpu=r.cpu,
        memory_gb=r.memory_gb, location=r.location, notes=r.notes,
        ip_address=r.ip_address, wan_uplink=r.wan_uplink, cpu_brand=r.cpu_brand,
        created_at=_dt(r.created_at), updated_at=_dt(r.updated_at),
    )


def _cu_to_dict(r: models.ComputeUnit) -> dict:
    return dict(
        id=r.id, name=r.name, kind=r.kind, hardware_id=r.hardware_id,
        os=r.os, icon_slug=r.icon_slug, cpu_cores=r.cpu_cores, cpu_brand=r.cpu_brand,
        memory_mb=r.memory_mb, disk_gb=r.disk_gb, ip_address=r.ip_address,
        environment=r.environment, notes=r.notes,
        created_at=_dt(r.created_at), updated_at=_dt(r.updated_at),
    )


def _svc_to_dict(r: models.Service) -> dict:
    return dict(
        id=r.id, name=r.name, slug=r.slug, compute_id=r.compute_id,
        hardware_id=r.hardware_id, icon_slug=r.icon_slug, category=r.category,
        url=r.url, ports=r.ports, description=r.description,
        environment=r.environment, status=r.status, ip_address=r.ip_address,
        created_at=_dt(r.created_at), updated_at=_dt(r.updated_at),
    )


def _st_to_dict(r: models.Storage) -> dict:
    return dict(
        id=r.id, name=r.name, kind=r.kind, hardware_id=r.hardware_id,
        capacity_gb=r.capacity_gb, used_gb=r.used_gb, path=r.path,
        protocol=r.protocol, notes=r.notes,
        created_at=_dt(r.created_at), updated_at=_dt(r.updated_at),
    )


def _net_to_dict(r: models.Network) -> dict:
    return dict(
        id=r.id, name=r.name, cidr=r.cidr, vlan_id=r.vlan_id,
        gateway=r.gateway, description=r.description,
        gateway_hardware_id=r.gateway_hardware_id,
        created_at=_dt(r.created_at), updated_at=_dt(r.updated_at),
    )


def _misc_to_dict(r: models.MiscItem) -> dict:
    return dict(
        id=r.id, name=r.name, kind=r.kind, url=r.url, description=r.description,
        created_at=_dt(r.created_at), updated_at=_dt(r.updated_at),
    )


def _doc_to_dict(r: models.Doc) -> dict:
    return dict(
        id=r.id, title=r.title, body_md=r.body_md, body_html=r.body_html,
        created_at=_dt(r.created_at), updated_at=_dt(r.updated_at),
    )


def _tag_to_dict(r: models.Tag) -> dict:
    return dict(id=r.id, name=r.name)


def _entity_tag_to_dict(r: models.EntityTag) -> dict:
    return dict(id=r.id, entity_type=r.entity_type, entity_id=r.entity_id, tag_id=r.tag_id)


def _entity_doc_to_dict(r: models.EntityDoc) -> dict:
    return dict(id=r.id, entity_type=r.entity_type, entity_id=r.entity_id, doc_id=r.doc_id)


def _svc_dep_to_dict(r: models.ServiceDependency) -> dict:
    return dict(id=r.id, service_id=r.service_id, depends_on_id=r.depends_on_id)


def _svc_st_to_dict(r: models.ServiceStorage) -> dict:
    return dict(id=r.id, service_id=r.service_id, storage_id=r.storage_id, purpose=r.purpose)


def _svc_misc_to_dict(r: models.ServiceMisc) -> dict:
    return dict(id=r.id, service_id=r.service_id, misc_id=r.misc_id, purpose=r.purpose)


def _hw_net_to_dict(r: models.HardwareNetwork) -> dict:
    return dict(id=r.id, hardware_id=r.hardware_id, network_id=r.network_id, ip_address=r.ip_address)


def _cu_net_to_dict(r: models.ComputeNetwork) -> dict:
    return dict(id=r.id, compute_id=r.compute_id, network_id=r.network_id, ip_address=r.ip_address)


def _cluster_to_dict(r: models.HardwareCluster) -> dict:
    return dict(
        id=r.id, name=r.name, description=r.description,
        environment=r.environment, location=r.location,
        created_at=_dt(r.created_at), updated_at=_dt(r.updated_at),
    )


def _cluster_member_to_dict(r: models.HardwareClusterMember) -> dict:
    return dict(id=r.id, cluster_id=r.cluster_id, hardware_id=r.hardware_id, role=r.role)


def _ext_to_dict(r: models.ExternalNode) -> dict:
    return dict(
        id=r.id, name=r.name, provider=r.provider, kind=r.kind,
        region=r.region, ip_address=r.ip_address, icon_slug=r.icon_slug,
        notes=r.notes, environment=r.environment,
        created_at=_dt(r.created_at), updated_at=_dt(r.updated_at),
    )


def _ext_net_to_dict(r: models.ExternalNodeNetwork) -> dict:
    return dict(
        id=r.id, external_node_id=r.external_node_id,
        network_id=r.network_id, link_type=r.link_type, notes=r.notes,
    )


def _svc_ext_to_dict(r: models.ServiceExternalNode) -> dict:
    return dict(
        id=r.id, service_id=r.service_id,
        external_node_id=r.external_node_id, purpose=r.purpose,
    )


# ── Export ────────────────────────────────────────────────────────────────

@router.get("/export")
def export_backup(db: Session = Depends(get_db), _=Depends(require_write_auth)):
    """Export a full JSON snapshot of all entities, tags, docs, and relationships.

    Does NOT export: users, app_settings, audit logs, or graph layouts — these are
    considered per-instance operational data, not portable entity data.
    """
    return {
        "version": 2,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "hardware":             [_hw_to_dict(r)   for r in db.query(models.Hardware).all()],
        "compute_units":        [_cu_to_dict(r)   for r in db.query(models.ComputeUnit).all()],
        "services":             [_svc_to_dict(r)  for r in db.query(models.Service).all()],
        "storage":              [_st_to_dict(r)   for r in db.query(models.Storage).all()],
        "networks":             [_net_to_dict(r)  for r in db.query(models.Network).all()],
        "misc_items":           [_misc_to_dict(r) for r in db.query(models.MiscItem).all()],
        "docs":                 [_doc_to_dict(r)  for r in db.query(models.Doc).all()],
        "tags":                 [_tag_to_dict(r)  for r in db.query(models.Tag).all()],
        "entity_tags":          [_entity_tag_to_dict(r)  for r in db.query(models.EntityTag).all()],
        "entity_docs":          [_entity_doc_to_dict(r)  for r in db.query(models.EntityDoc).all()],
        "service_dependencies": [_svc_dep_to_dict(r)     for r in db.query(models.ServiceDependency).all()],
        "service_storage":      [_svc_st_to_dict(r)      for r in db.query(models.ServiceStorage).all()],
        "service_misc":         [_svc_misc_to_dict(r)    for r in db.query(models.ServiceMisc).all()],
        "hardware_networks":    [_hw_net_to_dict(r)      for r in db.query(models.HardwareNetwork).all()],
        "compute_networks":     [_cu_net_to_dict(r)      for r in db.query(models.ComputeNetwork).all()],
        "hardware_clusters":    [_cluster_to_dict(r)        for r in db.query(models.HardwareCluster).all()],
        "hardware_cluster_members": [_cluster_member_to_dict(r) for r in db.query(models.HardwareClusterMember).all()],
        "external_nodes":           [_ext_to_dict(r)     for r in db.query(models.ExternalNode).all()],
        "external_node_networks":   [_ext_net_to_dict(r) for r in db.query(models.ExternalNodeNetwork).all()],
        "service_external_nodes":   [_svc_ext_to_dict(r) for r in db.query(models.ServiceExternalNode).all()],
    }


# ── Import ────────────────────────────────────────────────────────────────

class ImportPayload(BaseModel):
    wipe_before_import: bool = False
    data: dict[str, Any]


def _wipe_entities(db: Session) -> None:
    """Delete all entity rows in reverse FK order to avoid constraint violations."""
    for model_cls in [
        models.HardwareClusterMember,
        models.HardwareCluster,
        models.ServiceExternalNode,
        models.ExternalNodeNetwork,
        models.ExternalNode,
        models.ServiceMisc,
        models.ServiceStorage,
        models.ServiceDependency,
        models.HardwareNetwork,
        models.ComputeNetwork,
        models.EntityTag,
        models.EntityDoc,
        models.Service,
        models.ComputeUnit,
        models.Storage,
        models.Network,
        models.MiscItem,
        models.Hardware,
        models.Doc,
        models.Tag,
    ]:
        db.query(model_cls).delete()


def _insert_rows(db: Session, model_cls: Any, rows: list[dict]) -> None:
    """Upsert rows by primary key using SQLAlchemy merge."""
    for row in rows:
        db.merge(model_cls(**row))


def _restore_entities(db: Session, data: dict) -> None:
    """Insert backup data in FK-safe order (parents before children)."""
    _insert_rows(db, models.Tag,               data.get("tags", []))
    _insert_rows(db, models.Doc,               data.get("docs", []))
    _insert_rows(db, models.Hardware,          data.get("hardware", []))
    _insert_rows(db, models.ComputeUnit,       data.get("compute_units", []))
    _insert_rows(db, models.Service,           data.get("services", []))
    _insert_rows(db, models.Storage,           data.get("storage", []))
    _insert_rows(db, models.Network,           data.get("networks", []))
    _insert_rows(db, models.MiscItem,          data.get("misc_items", []))
    _insert_rows(db, models.EntityTag,         data.get("entity_tags", []))
    _insert_rows(db, models.EntityDoc,         data.get("entity_docs", []))
    _insert_rows(db, models.ServiceDependency, data.get("service_dependencies", []))
    _insert_rows(db, models.ServiceStorage,    data.get("service_storage", []))
    _insert_rows(db, models.ServiceMisc,       data.get("service_misc", []))
    _insert_rows(db, models.HardwareNetwork,        data.get("hardware_networks", []))
    _insert_rows(db, models.ComputeNetwork,         data.get("compute_networks", []))
    _insert_rows(db, models.HardwareCluster,        data.get("hardware_clusters", []))
    _insert_rows(db, models.HardwareClusterMember,  data.get("hardware_cluster_members", []))
    _insert_rows(db, models.ExternalNode,            data.get("external_nodes", []))
    _insert_rows(db, models.ExternalNodeNetwork,     data.get("external_node_networks", []))
    _insert_rows(db, models.ServiceExternalNode,     data.get("service_external_nodes", []))


@router.post("/import", status_code=201)
def import_backup(
    payload: ImportPayload,
    db: Session = Depends(get_db),
    _=Depends(require_write_auth),
):
    """Restore a backup snapshot.

    Set ``wipe_before_import=true`` to delete all current entity data before
    restoring.  The operation is wrapped in a single transaction; failure rolls
    back completely.
    """
    data = payload.data
    if payload.wipe_before_import:
        _wipe_entities(db)
    try:
        _restore_entities(db, data)
        db.commit()
    except Exception as exc:
        db.rollback()
        _logger.exception("Import failed: %s", exc)
        raise HTTPException(status_code=422, detail=f"Import failed: {exc}") from exc

    return {"imported": True}


# ── Clear Lab ─────────────────────────────────────────────────────────────

def _wipe_entities_keep_docs(db: Session) -> None:
    """Delete all entity rows except docs and doc-attachment links."""
    for model_cls in [
        models.HardwareClusterMember,
        models.HardwareCluster,
        models.ServiceExternalNode,
        models.ExternalNodeNetwork,
        models.ExternalNode,
        models.ServiceMisc,
        models.ServiceStorage,
        models.ServiceDependency,
        models.HardwareNetwork,
        models.ComputeNetwork,
        models.EntityTag,
        models.EntityDoc,
        models.Service,
        models.ComputeUnit,
        models.Storage,
        models.Network,
        models.MiscItem,
        models.Hardware,
        models.Tag,
        # models.Doc intentionally omitted — docs survive Clear Lab
    ]:
        db.query(model_cls).delete()


@router.post("/clear-lab", status_code=200)
def clear_lab(db: Session = Depends(get_db), _=Depends(require_write_auth)):
    """Wipe all lab entities (hardware, compute, services, storage, networks, misc,
    clusters, external nodes, tags, and their relationships) while preserving all
    documents and their content.
    """
    try:
        _wipe_entities_keep_docs(db)
        db.commit()
    except Exception as exc:
        db.rollback()
        _logger.exception("Clear lab failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Clear lab failed: {exc}") from exc
    return {"cleared": True}


# ── Recent Changes ────────────────────────────────────────────────────────

_ENTITY_SOURCES = [
    ("hardware", models.Hardware,    "name"),
    ("compute",  models.ComputeUnit, "name"),
    ("service",  models.Service,     "name"),
    ("storage",  models.Storage,     "name"),
    ("network",  models.Network,     "name"),
    ("misc",     models.MiscItem,    "name"),
    ("external", models.ExternalNode, "name"),
]


@router.get("/recent-changes")
def recent_changes(
    limit: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
):
    """Return the *limit* most-recently modified entities across all entity types."""
    entries: list[dict] = []

    for entity_type, model_cls, name_attr in _ENTITY_SOURCES:
        rows = (
            db.query(model_cls)
            .order_by(model_cls.updated_at.desc())
            .limit(limit)
            .all()
        )
        for row in rows:
            entries.append({
                "entity_type": entity_type,
                "entity_id":   row.id,
                "name":        getattr(row, name_attr),
                "updated_at":  _dt(row.updated_at),
            })

    # Sort all gathered rows by updated_at desc, return top N
    entries.sort(key=lambda x: x["updated_at"] or "", reverse=True)
    return entries[:limit]
