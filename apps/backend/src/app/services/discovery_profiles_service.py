import json
import logging

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.scheduler import reload_discovery_jobs
from app.core.time import utcnow_iso
from app.db.models import DiscoveryProfile
from app.schemas.discovery import DiscoveryProfileCreate, DiscoveryProfileUpdate
from app.services.credential_vault import get_vault
from app.services.log_service import write_log

logger = logging.getLogger(__name__)


def _get_vault():
    return get_vault()


def get_profiles(db: Session) -> list[DiscoveryProfile]:
    return db.query(DiscoveryProfile).order_by(DiscoveryProfile.name).all()


def get_profile(db: Session, profile_id: int) -> DiscoveryProfile:
    profile = db.query(DiscoveryProfile).filter(DiscoveryProfile.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Discovery profile not found")
    return profile


def create_profile(db: Session, payload: DiscoveryProfileCreate, actor: str) -> DiscoveryProfile:
    vault = _get_vault()
    encrypted_community = None

    if payload.snmp_community:
        encrypted_community = vault.encrypt(payload.snmp_community)

    scan_types_json = json.dumps(payload.scan_types)
    docker_network_types_json = json.dumps(payload.docker_network_types)
    vlan_ids_json = json.dumps(payload.vlan_ids)
    now_iso = utcnow_iso()

    profile = DiscoveryProfile(
        name=payload.name,
        cidr=payload.cidr,
        vlan_ids=vlan_ids_json,
        scan_types=scan_types_json,
        nmap_arguments=payload.nmap_arguments,
        snmp_community_encrypted=encrypted_community,
        snmp_version=payload.snmp_version,
        snmp_port=payload.snmp_port,
        docker_network_types=docker_network_types_json,
        docker_port_scan=1 if payload.docker_port_scan else 0,
        docker_socket_path=payload.docker_socket_path,
        schedule_cron=payload.schedule_cron,
        enabled=1 if payload.enabled else 0,
        created_at=now_iso,
        updated_at=now_iso,
    )

    db.add(profile)
    db.commit()
    db.refresh(profile)

    write_log(
        db=db,
        action="create_discovery_profile",
        category="discovery",
        entity_type="discovery_profile",
        entity_id=profile.id,
        entity_name=profile.name,
        actor_name=actor,
        severity="info",
    )

    if profile.schedule_cron and profile.enabled:
        reload_discovery_jobs(db)

    return profile


def update_profile(
    db: Session, profile_id: int, payload: DiscoveryProfileUpdate, actor: str
) -> DiscoveryProfile:
    profile = get_profile(db, profile_id)
    vault = _get_vault()
    old_cron = profile.schedule_cron
    old_enabled = profile.enabled
    changed_schedule = False

    data = payload.model_dump(exclude_unset=True)

    for field, value in data.items():
        if field == "scan_types":
            profile.scan_types = json.dumps(value)
        elif field == "vlan_ids":
            profile.vlan_ids = json.dumps(value)
        elif field == "docker_network_types":
            profile.docker_network_types = json.dumps(value)
        elif field == "docker_port_scan":
            profile.docker_port_scan = 1 if value else 0
        elif field == "snmp_community":
            if value is not None:
                if value == "":
                    profile.snmp_community_encrypted = None
                else:
                    profile.snmp_community_encrypted = vault.encrypt(value)
        elif field == "enabled":
            profile.enabled = 1 if value else 0
        else:
            setattr(profile, field, value)

    profile.updated_at = utcnow_iso()

    if profile.schedule_cron != old_cron or profile.enabled != old_enabled:
        changed_schedule = True

    db.commit()
    db.refresh(profile)

    write_log(
        db=db,
        action="update_discovery_profile",
        category="discovery",
        entity_type="discovery_profile",
        entity_id=profile.id,
        entity_name=profile.name,
        actor_name=actor,
        severity="info",
    )

    if changed_schedule:
        reload_discovery_jobs(db)

    return profile


def delete_profile(db: Session, profile_id: int, actor: str) -> None:
    profile = get_profile(db, profile_id)

    # Must nullify foreign keys first based on cascading rules (Assuming cascade in db not setup automatically for now, but jobs is set back_populates)
    from app.db.models import ScanJob

    jobs = db.query(ScanJob).filter(ScanJob.profile_id == profile_id).all()
    for job in jobs:
        job.profile_id = None

    db.delete(profile)
    db.commit()

    write_log(
        db=db,
        action="delete_discovery_profile",
        category="discovery",
        entity_type="discovery_profile",
        entity_id=profile_id,
        entity_name=profile.name,
        actor_name=actor,
        severity="info",
    )

    reload_discovery_jobs(db)
