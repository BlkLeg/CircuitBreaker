import ipaddress
import json
import logging
from typing import TYPE_CHECKING, Any

from apscheduler.triggers.cron import CronTrigger
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.discovery_scan_types import validate_scan_types
from app.core.scheduler import reload_discovery_jobs
from app.core.time import utcnow_iso
from app.db.models import DiscoveryProfile
from app.schemas.discovery import DiscoveryProfileCreate, DiscoveryProfileUpdate
from app.services.credential_vault import CredentialVault, get_vault
from app.services.log_service import write_log

if TYPE_CHECKING:  # pragma: no cover - import cycle: agent_discovery imports this package
    from app.services.agent_discovery import DiscoveryCancellation

logger = logging.getLogger(__name__)


def _get_vault() -> CredentialVault:
    return get_vault()


def get_profiles(db: Session) -> list[DiscoveryProfile]:
    return db.query(DiscoveryProfile).order_by(DiscoveryProfile.name).all()


def get_profile(db: Session, profile_id: int) -> DiscoveryProfile:
    profile = db.query(DiscoveryProfile).filter(DiscoveryProfile.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Discovery profile not found")
    return profile


def _validate_cron(cron_expr: str | None) -> None:
    """Raise ValueError if schedule_cron is non-empty and invalid."""
    if not cron_expr or not cron_expr.strip():
        return
    try:
        CronTrigger.from_crontab(cron_expr.strip())
    except Exception as e:
        raise ValueError(f"Invalid cron expression: {e}") from e


def _normalize_cidr(cidr: str | None) -> str | None:
    """Return the canonical form of `cidr`, or None when there is no network in it.

    Server-derived and never read off a request: `normalized_cidr` is the key
    the partial unique index for system-managed profiles is enforced on, so a
    client that could set it could park a row on the slot the discovery
    bootstrap owns. `strict=False` because an administrator types the subnet
    they live on ("10.0.0.5/24"), not its network address.
    """
    if not cidr or not cidr.strip():
        return None
    try:
        return str(ipaddress.ip_network(cidr.strip(), strict=False))
    except ValueError:
        # `cidr` is free text on this table — an IP range or a bare host is
        # accepted today. Refusing here would reject profiles that scan fine;
        # only the uniqueness key is lost, and that key is for agent-executed
        # profiles, which always carry a real network.
        return None


# The request fields the execution-location decision is made from. An update that
# names none of them is not re-decided, and that is deliberate: it has to stay
# possible to rename, re-schedule or — the edit D-14 turns into a cancellation
# trigger — *disable* a profile whose agent has since been revoked or lost its
# collectors. An unconditional re-check would strand every profile naming such an
# agent in the enabled state, with no way to stop it. What stops it from running
# is the dispatch-time re-check, which is where plan §7's later checkpoints sit.
_EXECUTION_LOCATION_FIELDS = frozenset(
    {"scan_agent_id", "cidr", "vlan_ids", "nmap_arguments", "scan_types"}
)

# The pair that decides which scan types are legal, and the only pair: §3's rule
# is a function of the requested types and the execution location alone, so a
# payload naming neither is not re-judged. That is what keeps D-6's write-only
# promise — a row written before the vocabulary existed may hold any string at
# all, and re-checking it on an unrelated `cidr` edit would make it uneditable.
_SCAN_TYPE_FIELDS = frozenset({"scan_types", "scan_agent_id"})

# One value, because `validate_scan_types` reports one thing: the requested types
# cannot execute at the requested location — whether because a type is unknown,
# belongs to the other executor, or leaves an agent dispatch with nothing to run.
# Which type offended is in the human `message`; the frontend switches on `reason`.
REASON_SCAN_TYPE_INVALID = "scan_type_invalid"


def _validate_execution_location(
    db: Session,
    *,
    scan_agent_id: int | None,
    cidr: str | None,
    vlan_ids: list[int] | None,
    nmap_arguments: str | None,
) -> None:
    """Refuse a profile the named agent could not run (plan §3, §7 checkpoint 1).

    Delegates to `discovery_service.validate_agent_execution_location`, which is
    also what job creation calls: plan §3 requires the *same* preconditions at
    profile save and at job creation, and two implementations of them would be
    two answers. Imported inside the function because that module is a large one
    this service otherwise has no need of.

    VLAN ids are resolved to CIDRs first, exactly as `create_scan_job` does, so
    the indirection cannot be a way past the agent's scope.

    Translated to a **422** rather than the 400 the endpoint gives a `ValueError`:
    the request is well formed and the profile it describes is unprocessable,
    which is already the status the scan-type vocabulary returns for an
    incompatible execution location — the frontend has one status and one
    `reason` vocabulary to render either way. The structured detail carries
    `reason` (the closed vocabulary a UI switches on), `detail` (the specific that
    produced it) and `message` (one sentence for a human).
    """
    if scan_agent_id is None:
        return

    from app.services.discovery_network import resolve_vlans_to_cidrs
    from app.services.discovery_service import (
        AgentExecutionLocationError,
        validate_agent_execution_location,
    )

    targets, _ = resolve_vlans_to_cidrs(db, list(vlan_ids or []))
    if cidr and cidr.strip():
        targets.append(cidr.strip())

    try:
        validate_agent_execution_location(
            db,
            scan_agent_id=scan_agent_id,
            targets=targets,
            nmap_arguments=nmap_arguments,
        )
    except AgentExecutionLocationError as exc:
        raise HTTPException(
            status_code=422,
            detail={"reason": exc.reason, "detail": exc.detail, "message": str(exc)},
        ) from exc


def _validate_merged_scan_types(
    profile: DiscoveryProfile,
    data: dict[str, Any],
    merged_agent_id: int | None,
) -> list[str] | None:
    """Judge the scan types the profile *would have* against where it would run.

    Returns the normalized list, or None when there was nothing judgeable — an
    unreadable legacy `scan_types` column that this payload does not replace.
    Refusing on that would strand the row (D-6 validates on write only, and the
    column is free text on rows that predate the vocabulary).

    Raises the same structured 422 as the other execution-location refusals so
    the frontend has one status and one `reason` vocabulary to render.
    """
    requested = data.get("scan_types")
    if requested is None:
        # Not named, or explicitly null — either way the stored list stands, and
        # it is the stored list the new agent has to be able to run.
        try:
            stored = json.loads(profile.scan_types or "[]")
        except ValueError:
            logger.warning("Malformed scan_types JSON in profile %s", profile.id)
            return None
        if not isinstance(stored, list):
            return None
        requested = stored

    try:
        return validate_scan_types(requested, scan_agent_id=merged_agent_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "reason": REASON_SCAN_TYPE_INVALID,
                # The types as judged, merged: the payload alone would not show a
                # reader which stored value the refusal is actually about.
                "detail": ",".join(str(t) for t in requested),
                "message": str(exc),
            },
        ) from exc


def create_profile(
    db: Session,
    payload: DiscoveryProfileCreate,
    actor: str,
    *,
    managed_by: str | None = None,
) -> DiscoveryProfile:
    """Create a profile. `managed_by` is keyword-only and server-set: it marks a
    profile the discovery bootstrap owns and may re-upsert, and no request
    schema carries it."""
    _validate_cron(payload.schedule_cron)
    _validate_execution_location(
        db,
        scan_agent_id=payload.scan_agent_id,
        cidr=payload.cidr,
        vlan_ids=payload.vlan_ids,
        nmap_arguments=payload.nmap_arguments,
    )
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
        normalized_cidr=_normalize_cidr(payload.cidr),
        # None means the server scanner, which is every profile predating Slice 4.
        scan_agent_id=payload.scan_agent_id,
        managed_by=managed_by,
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
    db: Session,
    profile_id: int,
    payload: DiscoveryProfileUpdate,
    actor: str,
    *,
    managed_by: str | None = None,
) -> DiscoveryProfile:
    """Update a profile. `managed_by` is keyword-only and server-set; None means
    "leave the marker as it is", so an ordinary API edit never disowns a
    system-managed profile."""
    if getattr(payload, "schedule_cron", None) is not None:
        _validate_cron(payload.schedule_cron)
    profile = get_profile(db, profile_id)
    vault = _get_vault()
    old_cron = profile.schedule_cron
    old_enabled = profile.enabled
    changed_schedule = False

    data = payload.model_dump(exclude_unset=True)

    if _EXECUTION_LOCATION_FIELDS & set(data):
        # Judged as the profile *would be*, not as the payload alone reads: the
        # agent already on the row decides a new `cidr`, and the CIDR already on
        # the row decides a new agent, so the two halves cannot be moved one at a
        # time to get past the check.
        stored_vlan_ids: list[int] = []
        if profile.vlan_ids:
            try:
                stored_vlan_ids = json.loads(profile.vlan_ids)
            except ValueError:
                # An unreadable stored list is no evidence of a target and must
                # not be read as one; the column is free text on old rows.
                logger.warning("Malformed VLAN JSON in profile %s", profile.id)
        merged_agent_id = data.get("scan_agent_id", profile.scan_agent_id)
        if _SCAN_TYPE_FIELDS & set(data):
            # Normalized back into `data`, so the dedupe `validate_scan_types`
            # performs still reaches the column: `discovery_service` compares the
            # stored list by equality (`scan_types == ["docker"]`), and a repeated
            # entry would silently change how the profile executes.
            normalized = _validate_merged_scan_types(profile, data, merged_agent_id)
            if normalized is not None and data.get("scan_types") is not None:
                data["scan_types"] = normalized
        _validate_execution_location(
            db,
            scan_agent_id=merged_agent_id,
            cidr=data.get("cidr", profile.cidr),
            vlan_ids=data.get("vlan_ids", stored_vlan_ids),
            nmap_arguments=data.get("nmap_arguments", profile.nmap_arguments),
        )

    for field, value in data.items():
        if field == "cidr":
            profile.cidr = value
            # Re-derived with `cidr` and only with it: a stale normalized value
            # would leave the system-profile uniqueness key naming the old subnet.
            profile.normalized_cidr = _normalize_cidr(value)
        elif field == "scan_types":
            # An explicit `null` means "leave the stored types alone", the same as
            # omitting the field: writing `json.dumps(None)` would put the string
            # "null" in the column and every later read of the profile would fail.
            if value is not None:
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

    if managed_by is not None:
        profile.managed_by = managed_by

    profile.updated_at = utcnow_iso()

    if profile.schedule_cron != old_cron or profile.enabled != old_enabled:
        changed_schedule = True

    # D-14. Disabling a profile is a cancellation trigger, and the one an
    # implementation forgets: nothing else stops the dispatches it already has in
    # flight, and once the profile is off nobody is going to look at them again.
    # Closed inside this transaction and published only after it commits, so an
    # agent is never told to abandon work a rollback would reinstate. Imported
    # inside the function because `agent_discovery` imports the discovery
    # services this one already pulls in.
    cancellation = (
        _cancel_in_flight_jobs(db, profile) if _was_disabled(old_enabled, profile) else None
    )

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

    if cancellation is not None:
        from app.services.agent_discovery import schedule_discovery_cancels

        schedule_discovery_cancels(cancellation)

    return profile


def _was_disabled(old_enabled: int | None, profile: DiscoveryProfile) -> bool:
    """Did this edit turn the profile off? Only the enabled -> disabled
    transition cancels: a rename, a re-schedule or a second disable of an
    already-disabled profile must not retire anything."""
    return bool(old_enabled) and not profile.enabled


def _cancel_in_flight_jobs(db: Session, profile: DiscoveryProfile) -> "DiscoveryCancellation":
    from app.services.agent_discovery import ERROR_PROFILE_DISABLED, cancel_profile_dispatches

    return cancel_profile_dispatches(db, profile.id, reason=ERROR_PROFILE_DISABLED)


def disable_profile(db: Session, profile_id: int, actor: str) -> DiscoveryProfile:
    """Turn a profile off, cancelling whatever it has in flight (D-14).

    Task 24's subnet-disappearance entry point: a system-managed profile whose
    subnet the agent stopped reporting is disabled rather than deleted, so its
    history survives. It routes through `update_profile` rather than writing
    `enabled = 0` itself, because that is where the cancellation, the audit row
    and the scheduler reload live and two implementations of "disable a profile"
    would be two answers to D-14.
    """
    # `model_validate` rather than the constructor, and it is load-bearing:
    # `update_profile` re-checks the execution location only for the fields the
    # payload actually names, and a keyword-constructed model would name every
    # optional one. Disabling a profile whose agent has since been revoked has to
    # keep working — it is the one edit that stops it.
    payload = DiscoveryProfileUpdate.model_validate({"enabled": False})
    return update_profile(db, profile_id, payload, actor)


def delete_profile(db: Session, profile_id: int, actor: str) -> None:
    profile = get_profile(db, profile_id)

    # Must nullify foreign keys first based on cascading rules
    # (Assuming cascade in db not setup automatically for now, but jobs is set back_populates)
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
