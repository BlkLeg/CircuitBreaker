"""Proxmox VE integration service — discovery, import, telemetry, and actions."""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import threading
from datetime import timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.core.nats_client import nats_client
from app.core.subjects import (
    DISCOVERY_SCAN_COMPLETED,
    DISCOVERY_SCAN_PROGRESS,
    DISCOVERY_SCAN_STARTED,
)
from app.core.time import utcnow
from app.db.models import (
    ComputeUnit,
    Credential,
    Hardware,
    HardwareCluster,
    HardwareClusterMember,
    IntegrationConfig,
    StatusGroup,
    Storage,
    TelemetryTimeseries,
)
from app.integrations.proxmox_client import ProxmoxIntegration, build_client_from_token
from app.services.credential_vault import get_vault

_logger = logging.getLogger(__name__)

# Reuse one Proxmox client per integration to avoid urllib3 connection pool exhaustion
# (many clients to the same host each create a pool; one client per host reuses connections).
_proxmox_client_cache: dict[int, ProxmoxIntegration] = {}
_proxmox_client_cache_lock = threading.Lock()


def _invalidate_proxmox_client_cache(config_id: int) -> None:
    """Remove cached client when config is updated or deleted."""
    with _proxmox_client_cache_lock:
        _proxmox_client_cache.pop(config_id, None)


def _get_client(db: Session, config: IntegrationConfig) -> ProxmoxIntegration:
    """Build or return cached ProxmoxIntegration for this integration (one per config to avoid pool exhaustion)."""
    config_id = config.id
    with _proxmox_client_cache_lock:
        if config_id in _proxmox_client_cache:
            return _proxmox_client_cache[config_id]
    vault = get_vault()
    cred = db.get(Credential, config.credential_id)
    if not cred:
        raise ValueError(f"Credential {config.credential_id} not found for integration {config.id}")

    token = vault.decrypt(cred.encrypted_value)
    extra = json.loads(config.extra_config) if config.extra_config else {}
    verify_ssl = extra.get("verify_ssl", False)
    client = build_client_from_token(config.config_url, token, verify_ssl=verify_ssl)
    with _proxmox_client_cache_lock:
        _proxmox_client_cache[config_id] = client
    return client


async def _check_token_privsep(client: ProxmoxIntegration) -> str:
    """Detect Privilege Separation and return a targeted hint."""
    try:
        perms = await client.get_permissions()
        has_vm_audit = any(
            "VM.Audit" in privs for privs in (perms.values() if isinstance(perms, dict) else [])
        )
    except Exception:
        has_vm_audit = False

    if not has_vm_audit:
        return (
            "0 VMs/containers returned — the API token likely has Privilege "
            "Separation enabled (the Proxmox default). When enabled, the token "
            "does NOT inherit the user's permissions and needs its own. Fix: "
            "Datacenter → Permissions → Add → API Token Permission, select "
            "your token, set Role = PVEAuditor, Path = /, Propagate = yes. "
            "Or, recreate the token with Privilege Separation unchecked."
        )
    return (
        "No VMs or containers found despite having VM.Audit. "
        "Verify the token has access to the /vms path."
    )


async def _publish(subject: str, payload: dict) -> None:
    try:
        await nats_client.publish(subject, payload)
    except Exception:
        pass


# ── Config CRUD ──────────────────────────────────────────────────────────────


def create_integration(
    db: Session,
    name: str,
    config_url: str,
    api_token: str,
    auto_sync: bool = True,
    sync_interval_s: int = 300,
    verify_ssl: bool = False,
) -> IntegrationConfig:
    vault = get_vault()
    cred = Credential(
        credential_type="proxmox_api",
        encrypted_value=vault.encrypt(api_token),
        label=f"Proxmox: {name}",
    )
    db.add(cred)
    db.flush()

    config = IntegrationConfig(
        type="proxmox",
        name=name,
        config_url=config_url.rstrip("/"),
        credential_id=cred.id,
        auto_sync=auto_sync,
        sync_interval_s=sync_interval_s,
        extra_config=json.dumps({"verify_ssl": verify_ssl}),
    )
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


def update_integration(
    db: Session,
    config: IntegrationConfig,
    name: str | None = None,
    config_url: str | None = None,
    api_token: str | None = None,
    auto_sync: bool | None = None,
    sync_interval_s: int | None = None,
    verify_ssl: bool | None = None,
) -> IntegrationConfig:
    if name is not None:
        config.name = name
    if config_url is not None:
        config.config_url = config_url.rstrip("/")
    if auto_sync is not None:
        config.auto_sync = auto_sync
    if sync_interval_s is not None:
        config.sync_interval_s = sync_interval_s

    if api_token:
        vault = get_vault()
        cred = db.get(Credential, config.credential_id)
        if cred:
            cred.encrypted_value = vault.encrypt(api_token)
        else:
            cred = Credential(
                credential_type="proxmox_api",
                encrypted_value=vault.encrypt(api_token),
                label=f"Proxmox: {config.name}",
            )
            db.add(cred)
            db.flush()
            config.credential_id = cred.id

    if verify_ssl is not None:
        extra = json.loads(config.extra_config) if config.extra_config else {}
        extra["verify_ssl"] = verify_ssl
        config.extra_config = json.dumps(extra)

    db.commit()
    db.refresh(config)
    _invalidate_proxmox_client_cache(config.id)
    return config


def delete_integration(db: Session, config: IntegrationConfig) -> None:
    _invalidate_proxmox_client_cache(config.id)
    if config.credential_id:
        cred = db.get(Credential, config.credential_id)
        if cred:
            db.delete(cred)
    db.delete(config)
    db.commit()


def get_integration(db: Session, integration_id: int) -> IntegrationConfig | None:
    return (
        db.query(IntegrationConfig)
        .filter(
            IntegrationConfig.id == integration_id,
            IntegrationConfig.type == "proxmox",
        )
        .first()
    )


def list_integrations(db: Session) -> list[IntegrationConfig]:
    return db.query(IntegrationConfig).filter(IntegrationConfig.type == "proxmox").all()


# ── Test connection ──────────────────────────────────────────────────────────


async def test_connection(db: Session, config: IntegrationConfig) -> dict:
    try:
        client = _get_client(db, config)
        result = await client.test_connection()
        return {"ok": True, **result}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── Discovery & Import ───────────────────────────────────────────────────────


async def discover_and_import(db: Session, config: IntegrationConfig) -> dict:
    """Full cluster discovery: nodes, VMs, CTs, networks."""
    config.last_sync_status = "syncing"
    db.commit()

    result: dict[str, Any] = {
        "ok": True,
        "cluster_name": None,
        "nodes_imported": 0,
        "vms_imported": 0,
        "cts_imported": 0,
        "networks_imported": 0,
        "storage_imported": 0,
        "errors": [],
    }

    try:
        client = _get_client(db, config)
        await _publish(
            DISCOVERY_SCAN_STARTED,
            {
                "source": "proxmox",
                "integration_id": config.id,
            },
        )

        cluster_data = await client.discover_cluster()
        resources = cluster_data.get("resources", [])
        cluster_status = cluster_data.get("cluster_status", [])

        # Extract cluster name
        cluster_name = next(
            (item.get("name") for item in cluster_status if item.get("type") == "cluster"),
            config.name,
        )
        config.cluster_name = cluster_name
        result["cluster_name"] = cluster_name

        # Upsert HardwareCluster
        cluster = (
            db.query(HardwareCluster)
            .filter(
                HardwareCluster.integration_config_id == config.id,
            )
            .first()
        )
        if not cluster:
            cluster = HardwareCluster(
                name=cluster_name or config.name,
                type="proxmox",
                integration_config_id=config.id,
            )
            db.add(cluster)
            db.flush()
        else:
            cluster.name = cluster_name or config.name

        # Classify resources
        nodes = [r for r in resources if r.get("type") == "node"]
        qemu_vms = [r for r in resources if r.get("type") == "qemu"]
        lxc_cts = [r for r in resources if r.get("type") == "lxc"]

        # Fallback: if cluster/resources returned nodes but no VMs/CTs,
        # query each node directly (handles tokens with limited Datacenter perms)
        if nodes and not qemu_vms and not lxc_cts:
            _logger.info("cluster/resources returned 0 VMs/CTs — trying per-node queries")
            for node_res in nodes:
                nn = node_res.get("node", "")
                if not nn:
                    continue
                try:
                    per_node_qemu = await client.get_node_vms(nn, "qemu")
                    for vm in per_node_qemu:
                        vm.setdefault("node", nn)
                    qemu_vms.extend(per_node_qemu)
                except Exception as e:
                    _logger.debug("Per-node qemu query failed for %s: %s", nn, e)
                try:
                    per_node_lxc = await client.get_node_vms(nn, "lxc")
                    for ct in per_node_lxc:
                        ct.setdefault("node", nn)
                    lxc_cts.extend(per_node_lxc)
                except Exception as e:
                    _logger.debug("Per-node lxc query failed for %s: %s", nn, e)

            if not qemu_vms and not lxc_cts:
                privsep_hint = await _check_token_privsep(client)
                result["errors"].append(privsep_hint)

        await _publish(
            DISCOVERY_SCAN_PROGRESS,
            {
                "source": "proxmox",
                "integration_id": config.id,
                "phase": "importing_nodes",
                "message": f"Found {len(nodes)} nodes, {len(qemu_vms)} VMs, {len(lxc_cts)} CTs",
            },
        )

        # ── Import nodes ─────────────────────────────────────────────────
        node_hw_map: dict[str, Hardware] = {}
        for node_res in nodes:
            node_name = node_res.get("node", "")
            try:
                hw = _upsert_node(db, config, cluster, node_name, node_res)
                node_hw_map[node_name] = hw
                result["nodes_imported"] += 1
            except Exception as e:
                result["errors"].append(f"Node {node_name}: {e}")
                _logger.warning("Failed to import node %s: %s", node_name, e)

        # ── Import VMs ───────────────────────────────────────────────────
        total_vms = len(qemu_vms) + len(lxc_cts)
        imported = 0
        for vm_res in qemu_vms:
            try:
                _upsert_vm(db, config, vm_res, "qemu", node_hw_map, client)
                result["vms_imported"] += 1
            except Exception as e:
                vmid = vm_res.get("vmid", "?")
                result["errors"].append(f"VM {vmid}: {e}")
                _logger.warning("Failed to import VM %s: %s", vmid, e)
            imported += 1
            if imported % 10 == 0:
                await _publish(
                    DISCOVERY_SCAN_PROGRESS,
                    {
                        "source": "proxmox",
                        "integration_id": config.id,
                        "phase": "importing_vms",
                        "percent": int(imported / max(total_vms, 1) * 100),
                        "message": f"{imported}/{total_vms} VMs/CTs imported",
                    },
                )

        # ── Import CTs ───────────────────────────────────────────────────
        for ct_res in lxc_cts:
            try:
                _upsert_vm(db, config, ct_res, "lxc", node_hw_map, client)
                result["cts_imported"] += 1
            except Exception as e:
                vmid = ct_res.get("vmid", "?")
                result["errors"].append(f"CT {vmid}: {e}")
                _logger.warning("Failed to import CT %s: %s", vmid, e)
            imported += 1

        # ── Import networks ──────────────────────────────────────────────
        for node_name, hw in node_hw_map.items():
            try:
                nets = await _import_node_networks(db, config, client, node_name, hw)
                result["networks_imported"] += nets
            except Exception as e:
                result["errors"].append(f"Networks for {node_name}: {e}")

        # ── Import storage pools ──────────────────────────────────────
        for node_name, hw in node_hw_map.items():
            try:
                st_count = await _import_node_storage(db, config, client, node_name, hw)
                result["storage_imported"] += st_count
            except Exception as e:
                result["errors"].append(f"Storage for {node_name}: {e}")

        # Finalize
        config.last_sync_at = utcnow()
        config.last_sync_status = "ok"
        db.commit()

        await _publish(
            DISCOVERY_SCAN_COMPLETED,
            {
                "source": "proxmox",
                "integration_id": config.id,
                "nodes": result["nodes_imported"],
                "vms": result["vms_imported"],
                "cts": result["cts_imported"],
                "storage": result["storage_imported"],
            },
        )

    except Exception as e:
        result["ok"] = False
        result["errors"].append(str(e))
        config.last_sync_status = "error"
        config.last_sync_at = utcnow()
        db.commit()
        _logger.exception("Proxmox discovery failed for integration %d", config.id)

    return result


def _upsert_node(
    db: Session,
    config: IntegrationConfig,
    cluster: HardwareCluster,
    node_name: str,
    node_res: dict,
) -> Hardware:
    hw = (
        db.query(Hardware)
        .filter(
            Hardware.proxmox_node_name == node_name,
            Hardware.integration_config_id == config.id,
        )
        .first()
    )

    status_str = node_res.get("status", "unknown")
    cpu_pct = node_res.get("cpu", 0)
    maxmem = node_res.get("maxmem", 0)
    mem = node_res.get("mem", 0)
    uptime = node_res.get("uptime", 0)

    telemetry = json.dumps(
        {
            "cpu_pct": round(cpu_pct * 100, 1) if cpu_pct else 0,
            "mem_used_bytes": mem,
            "mem_total_bytes": maxmem,
            "mem_used_gb": round(mem / (1024**3), 1) if mem else 0,
            "mem_total_gb": round(maxmem / (1024**3), 1) if maxmem else 0,
            "uptime_s": uptime,
            "status": status_str,
        }
    )

    if not hw:
        hw = Hardware(
            name=node_name,
            role="hypervisor",
            vendor="Proxmox",
            vendor_icon_slug="proxmox-dark",
            proxmox_node_name=node_name,
            integration_config_id=config.id,
            status="active" if status_str == "online" else "inactive",
            source="discovery",
            telemetry_data=telemetry,
            telemetry_status="healthy" if status_str == "online" else "unknown",
            telemetry_last_polled=utcnow(),
            ip_address=node_res.get("ip"),
            memory_gb=round(maxmem / (1024**3)) if maxmem else None,
        )
        db.add(hw)
        db.flush()

        # Add to cluster
        member = HardwareClusterMember(
            cluster_id=cluster.id,
            member_type="hardware",
            hardware_id=hw.id,
            role="hypervisor",
        )
        db.add(member)
    else:
        hw.status = "active" if status_str == "online" else "inactive"
        hw.telemetry_data = telemetry
        hw.telemetry_status = "healthy" if status_str == "online" else "unknown"
        hw.telemetry_last_polled = utcnow()
        hw.memory_gb = round(maxmem / (1024**3)) if maxmem else hw.memory_gb
        if not hw.vendor_icon_slug:
            hw.vendor_icon_slug = "proxmox-dark"

    db.flush()
    return hw


def _upsert_vm(
    db: Session,
    config: IntegrationConfig,
    vm_res: dict,
    vm_type: str,
    node_hw_map: dict[str, Hardware],
    _client: ProxmoxIntegration,
) -> ComputeUnit:
    vmid = vm_res.get("vmid")
    node_name = vm_res.get("node", "")
    name = vm_res.get("name", f"{vm_type}-{vmid}")

    hw = node_hw_map.get(node_name)
    if not hw:
        raise ValueError(f"Parent node '{node_name}' not found")

    cu = (
        db.query(ComputeUnit)
        .filter(
            ComputeUnit.proxmox_vmid == vmid,
            ComputeUnit.integration_config_id == config.id,
        )
        .first()
    )

    kind = "container" if vm_type == "lxc" else "vm"
    status_str = vm_res.get("status", "unknown")
    cpu = vm_res.get("cpu", 0)
    maxcpu = vm_res.get("maxcpu", 0)
    maxmem = vm_res.get("maxmem", 0)
    mem = vm_res.get("mem", 0)
    maxdisk = vm_res.get("maxdisk", 0)

    pve_status = json.dumps(
        {
            "status": status_str,
            "cpu_pct": round(cpu * 100, 1) if cpu else 0,
            "mem_used_bytes": mem,
            "mem_total_bytes": maxmem,
            "disk_total_bytes": maxdisk,
            "netin": vm_res.get("netin", 0),
            "netout": vm_res.get("netout", 0),
        }
    )

    cb_status = "active" if status_str == "running" else "inactive"

    if not cu:
        cu = ComputeUnit(
            name=name,
            kind=kind,
            hardware_id=hw.id,
            proxmox_vmid=vmid,
            proxmox_type=vm_type,
            proxmox_status=pve_status,
            integration_config_id=config.id,
            status=cb_status,
            cpu_cores=maxcpu or None,
            memory_mb=round(maxmem / (1024**2)) if maxmem else None,
            disk_gb=round(maxdisk / (1024**3)) if maxdisk else None,
        )
        db.add(cu)
    else:
        cu.name = name
        cu.hardware_id = hw.id
        cu.proxmox_type = vm_type
        cu.proxmox_status = pve_status
        cu.status = cb_status
        cu.cpu_cores = maxcpu or cu.cpu_cores
        cu.memory_mb = round(maxmem / (1024**2)) if maxmem else cu.memory_mb
        cu.disk_gb = round(maxdisk / (1024**3)) if maxdisk else cu.disk_gb

    db.flush()
    return cu


# ── Network import ───────────────────────────────────────────────────────────


async def _import_node_networks(
    db: Session,
    _config: IntegrationConfig,
    client: ProxmoxIntegration,
    node_name: str,
    hw: Hardware,
) -> int:
    """Import PVE bridge interfaces as CB Networks. Returns count imported."""
    from app.db.models import HardwareNetwork, Network

    try:
        net_list = await client.get_node_networks(node_name)
    except Exception:
        return 0

    count = 0
    for iface in net_list:
        iface_type = iface.get("type", "")
        if iface_type not in ("bridge", "bond", "OVSBridge"):
            continue

        bridge_name = iface.get("iface", "")
        cidr = iface.get("cidr") or iface.get("address")
        vlan_tag = iface.get("vlan-id") or iface.get("bridge_vlan_aware")

        # Upsert network
        net = (
            db.query(Network)
            .filter(
                Network.name == f"pve-{bridge_name}@{node_name}",
            )
            .first()
        )

        if not net:
            vlan_id = int(vlan_tag) if vlan_tag and str(vlan_tag).isdigit() else None
            net = Network(
                name=f"pve-{bridge_name}@{node_name}",
                cidr=cidr,
                vlan_id=vlan_id,
                description=f"Proxmox bridge {bridge_name} on {node_name}",
            )
            db.add(net)
            db.flush()
            count += 1

        # Link hardware to network
        existing = (
            db.query(HardwareNetwork)
            .filter(
                HardwareNetwork.hardware_id == hw.id,
                HardwareNetwork.network_id == net.id,
            )
            .first()
        )
        if not existing:
            db.add(
                HardwareNetwork(
                    hardware_id=hw.id,
                    network_id=net.id,
                    ip_address=cidr.split("/")[0] if cidr and "/" in cidr else cidr,
                )
            )

    db.flush()
    return count


# ── Storage import ───────────────────────────────────────────────────────────

_PVE_KIND_MAP = {
    "zfspool": "pool",
    "lvm": "pool",
    "lvmthin": "pool",
    "dir": "share",
    "nfs": "share",
    "cifs": "share",
    "glusterfs": "share",
    "iscsi": "dataset",
    "rbd": "dataset",
    "cephfs": "dataset",
}


async def _import_node_storage(
    db: Session,
    config: IntegrationConfig,
    client: ProxmoxIntegration,
    node_name: str,
    hw: Hardware,
) -> int:
    """Import PVE storage pools as CB Storage entries. Returns count upserted."""
    try:
        storage_list = await client.get_node_storage(node_name)
    except Exception:
        return 0

    count = 0
    for st_data in storage_list:
        storage_name = st_data.get("storage", "")
        if not storage_name:
            continue

        pve_type = st_data.get("type", "dir")
        total_bytes = st_data.get("total", 0)
        used_bytes = st_data.get("used", 0)
        active = st_data.get("active", 0)

        cb_name = f"{storage_name}@{node_name}"
        kind = _PVE_KIND_MAP.get(pve_type, "share")

        existing = (
            db.query(Storage)
            .filter(
                Storage.proxmox_storage_name == storage_name,
                Storage.hardware_id == hw.id,
                Storage.integration_config_id == config.id,
            )
            .first()
        )

        cap_gb = round(total_bytes / (1024**3)) if total_bytes else None
        used_gb = round(used_bytes / (1024**3)) if used_bytes else None

        if not existing:
            st = Storage(
                name=cb_name,
                kind=kind,
                hardware_id=hw.id,
                capacity_gb=cap_gb,
                used_gb=used_gb,
                protocol=pve_type,
                integration_config_id=config.id,
                proxmox_storage_name=storage_name,
                notes=f"content: {st_data.get('content', '')}",
            )
            db.add(st)
            count += 1
        else:
            existing.name = cb_name
            existing.kind = kind
            existing.capacity_gb = cap_gb
            existing.used_gb = used_gb
            existing.protocol = pve_type
            if not active:
                existing.notes = f"[inactive] content: {st_data.get('content', '')}"

    db.flush()
    return count


# ── Sync status ──────────────────────────────────────────────────────────────


def get_sync_status(db: Session, config: IntegrationConfig) -> dict:
    nodes_count = (
        db.query(Hardware)
        .filter(
            Hardware.integration_config_id == config.id,
        )
        .count()
    )
    vms_count = (
        db.query(ComputeUnit)
        .filter(
            ComputeUnit.integration_config_id == config.id,
            ComputeUnit.proxmox_type == "qemu",
        )
        .count()
    )
    cts_count = (
        db.query(ComputeUnit)
        .filter(
            ComputeUnit.integration_config_id == config.id,
            ComputeUnit.proxmox_type == "lxc",
        )
        .count()
    )
    storage_count = (
        db.query(Storage)
        .filter(
            Storage.integration_config_id == config.id,
        )
        .count()
    )

    return {
        "integration_id": config.id,
        "last_sync_at": config.last_sync_at,
        "last_sync_status": config.last_sync_status,
        "cluster_name": config.cluster_name,
        "nodes_count": nodes_count,
        "vms_count": vms_count,
        "cts_count": cts_count,
        "storage_count": storage_count,
    }


# ── Storage refresh (used/total for cluster overview) ──────────────────────────


async def refresh_proxmox_storage(db: Session) -> None:
    """Update used_gb/capacity_gb for all Proxmox Storage rows from PVE nodes.
    Lighter than full sync; run on a schedule so cluster overview has fresh storage data."""
    configs = (
        db.query(IntegrationConfig)
        .filter(
            IntegrationConfig.type == "proxmox",
            IntegrationConfig.auto_sync.is_(True),
        )
        .all()
    )
    for config in configs:
        try:
            client = _get_client(db, config)
            nodes = (
                db.query(Hardware)
                .filter(
                    Hardware.integration_config_id == config.id,
                    Hardware.proxmox_node_name.isnot(None),
                )
                .all()
            )
            for hw in nodes:
                try:
                    storage_list = await client.get_node_storage(hw.proxmox_node_name)
                except Exception as e:
                    _logger.debug("Storage refresh failed for node %s: %s", hw.proxmox_node_name, e)
                    continue
                for st_data in storage_list:
                    name = st_data.get("storage", "")
                    if not name:
                        continue
                    total_bytes = st_data.get("total", 0)
                    used_bytes = st_data.get("used", 0)
                    existing = (
                        db.query(Storage)
                        .filter(
                            Storage.proxmox_storage_name == name,
                            Storage.hardware_id == hw.id,
                            Storage.integration_config_id == config.id,
                        )
                        .first()
                    )
                    if existing:
                        existing.capacity_gb = (
                            round(total_bytes / (1024**3)) if total_bytes else None
                        )
                        existing.used_gb = round(used_bytes / (1024**3)) if used_bytes else None
            db.commit()
        except Exception as e:
            _logger.warning("Storage refresh failed for integration %d: %s", config.id, e)
            db.rollback()


# ── Telemetry polling ────────────────────────────────────────────────────────


async def poll_node_telemetry(db: Session) -> None:
    """Poll all active Proxmox nodes for CPU/RAM/load metrics (parallel per integration)."""
    configs = (
        db.query(IntegrationConfig)
        .filter(
            IntegrationConfig.type == "proxmox",
            IntegrationConfig.auto_sync.is_(True),
        )
        .all()
    )

    from app.core.circuit_breaker import get_breaker

    for config in configs:
        config_id = config.id
        breaker = get_breaker(f"proxmox:{config_id}:poll")
        if breaker.is_open():
            _logger.debug(
                "Proxmox integration %d circuit open — skipping telemetry poll", config_id
            )
            continue
        try:
            client = _get_client(db, config)
            nodes = (
                db.query(Hardware)
                .filter(
                    Hardware.integration_config_id == config_id,
                    Hardware.proxmox_node_name.isnot(None),
                )
                .all()
            )

            async def _fetch_node(hw: Hardware, _client=client):
                return hw, await _client.get_node_status(hw.proxmox_node_name)  # type: ignore[arg-type]

            results = await asyncio.gather(
                *[_fetch_node(hw) for hw in nodes],
                return_exceptions=True,
            )

            now = utcnow()
            for result in results:
                if isinstance(result, Exception):
                    _logger.debug("Telemetry poll failed for a node: %s", result)
                    continue
                hw, status = result  # type: ignore[misc]
                try:
                    cpu_pct = round(status.get("cpu", 0) * 100, 1)
                    # PVE can return memory as nested (memory.used/total) or top-level (mem, maxmem)
                    mem = status.get("memory", {})
                    mem_used = mem.get("used") or status.get("mem", 0)
                    mem_total = mem.get("total") or status.get("maxmem", 0)
                    load = status.get("loadavg", [0, 0, 0])
                    rootfs = status.get("rootfs", {})
                    root_used = rootfs.get("used") if isinstance(rootfs, dict) else 0
                    root_total = rootfs.get("total") if isinstance(rootfs, dict) else 0
                    if not root_used and "root" in status:
                        root_used = status.get("root", 0)
                    if not root_total and "maxroot" in status:
                        root_total = status.get("maxroot", 0)
                    netin = status.get("netin", 0)
                    netout = status.get("netout", 0)
                    swap_used = status.get("swap", 0)
                    maxswap = status.get("maxswap", 0)

                    telemetry = json.dumps(
                        {
                            "cpu_pct": cpu_pct,
                            "mem_used_gb": round(mem_used / (1024**3), 1) if mem_used else 0,
                            "mem_total_gb": round(mem_total / (1024**3), 1) if mem_total else 0,
                            "load_1m": load[0] if load else 0,
                            "load_5m": load[1] if len(load) > 1 else 0,
                            "load_15m": load[2] if len(load) > 2 else 0,
                            "disk_used_gb": round((root_used or 0) / (1024**3), 1),
                            "disk_total_gb": round((root_total or 0) / (1024**3), 1),
                            "uptime_s": status.get("uptime", 0),
                            "netin": netin,
                            "netout": netout,
                            "swap_gb": round(swap_used / (1024**3), 1) if swap_used else 0,
                            "maxswap_gb": round(maxswap / (1024**3), 1) if maxswap else 0,
                        }
                    )

                    hw.telemetry_data = telemetry
                    hw.telemetry_last_polled = now

                    if cpu_pct > 90 or (mem_used / max(mem_total, 1) > 0.95):
                        hw.telemetry_status = "critical"
                    elif cpu_pct > 70 or (mem_used / max(mem_total, 1) > 0.85):
                        hw.telemetry_status = "degraded"
                    else:
                        hw.telemetry_status = "healthy"

                    for metric_name, value in [
                        ("cpu_pct", cpu_pct),
                        ("mem_used_gb", round(mem_used / (1024**3), 1) if mem_used else 0),
                        ("netin", netin),
                        ("netout", netout),
                    ]:
                        db.add(
                            TelemetryTimeseries(
                                entity_type="hardware",
                                entity_id=hw.id,
                                metric=metric_name,
                                value=value,
                                source="proxmox",
                                ts=now,
                            )
                        )

                    await _publish(
                        "telemetry.proxmox.node",
                        {
                            "hardware_id": hw.id,
                            "node": hw.proxmox_node_name,
                            "telemetry": json.loads(telemetry),
                            "status": hw.telemetry_status,
                        },
                    )
                except Exception as e:
                    _logger.debug("Telemetry apply failed for node %s: %s", hw.proxmox_node_name, e)

            db.commit()
            breaker.record_success()
        except Exception as e:
            breaker.record_failure()
            _logger.warning("Telemetry poll failed for integration %d: %s", config_id, e)


async def poll_rrd_telemetry(db: Session) -> None:
    """Poll RRD data for each Proxmox node and store in TelemetryTimeseries (source=proxmox_rrd).
    Provides time-series for CPU, memory, disk, network, io_delay for cluster overview charts."""
    configs = (
        db.query(IntegrationConfig)
        .filter(
            IntegrationConfig.type == "proxmox",
            IntegrationConfig.auto_sync.is_(True),
        )
        .all()
    )
    for config in configs:
        try:
            client = _get_client(db, config)
            nodes = (
                db.query(Hardware)
                .filter(
                    Hardware.integration_config_id == config.id,
                    Hardware.proxmox_node_name.isnot(None),
                )
                .all()
            )
            for hw in nodes:
                node = hw.proxmox_node_name
                if not node:
                    continue
                try:
                    raw = await client.get_node_rrddata(node, timeframe="hour")
                except Exception as e:
                    _logger.debug("RRD poll failed for node %s: %s", node, e)
                    continue
                if not isinstance(raw, list):
                    continue
                # PVE returns list of dicts: time (unix), cpu, mem, maxmem, diskread, diskwrite, netin, netout, etc.
                for point in raw:
                    if not isinstance(point, dict):
                        continue
                    ts_unix = point.get("time")
                    if ts_unix is None:
                        continue
                    try:
                        ts = datetime.datetime.fromtimestamp(int(ts_unix), tz=datetime.UTC)
                    except (ValueError, TypeError, OSError):
                        continue
                    # Store metrics that are present (float or int)
                    metrics_to_store = [
                        (
                            "rrd_cpu",
                            point.get("cpu"),
                            lambda v: float(v) * 100 if v is not None else None,
                        ),
                        (
                            "rrd_memused",
                            point.get("mem"),
                            lambda v: float(v) if v is not None else None,
                        ),
                        (
                            "rrd_memtotal",
                            point.get("maxmem"),
                            lambda v: float(v) if v is not None else None,
                        ),
                        (
                            "rrd_netin",
                            point.get("netin"),
                            lambda v: float(v) if v is not None else None,
                        ),
                        (
                            "rrd_netout",
                            point.get("netout"),
                            lambda v: float(v) if v is not None else None,
                        ),
                        (
                            "rrd_diskread",
                            point.get("diskread"),
                            lambda v: float(v) if v is not None else None,
                        ),
                        (
                            "rrd_diskwrite",
                            point.get("diskwrite"),
                            lambda v: float(v) if v is not None else None,
                        ),
                        (
                            "rrd_io_delay",
                            point.get("io_delay"),
                            lambda v: float(v) if v is not None else None,
                        ),
                        (
                            "rrd_zfs_arc_size",
                            point.get("zfs_arc_size"),
                            lambda v: float(v) if v is not None else None,
                        ),
                    ]
                    for metric_name, raw_val, normalize in metrics_to_store:
                        val = normalize(raw_val)
                        if val is not None:
                            db.add(
                                TelemetryTimeseries(
                                    entity_type="hardware",
                                    entity_id=hw.id,
                                    metric=metric_name,
                                    value=val,
                                    source="proxmox_rrd",
                                    ts=ts,
                                )
                            )
            db.commit()
        except Exception as e:
            _logger.warning("RRD telemetry poll failed for integration %d: %s", config.id, e)
            db.rollback()


async def poll_vm_telemetry(db: Session) -> None:
    """Poll all active Proxmox VMs/CTs for live stats (parallel per integration)."""
    configs = (
        db.query(IntegrationConfig)
        .filter(
            IntegrationConfig.type == "proxmox",
            IntegrationConfig.auto_sync.is_(True),
        )
        .all()
    )

    for config in configs:
        config_id = config.id
        try:
            client = _get_client(db, config)
            compute_units = (
                db.query(ComputeUnit)
                .filter(
                    ComputeUnit.integration_config_id == config_id,
                    ComputeUnit.proxmox_vmid.isnot(None),
                )
                .all()
            )

            # Batch-load hardware for this integration to avoid N+1 per VM.
            hw_map = {
                hw.id: hw
                for hw in db.query(Hardware)
                .filter(
                    Hardware.integration_config_id == config_id,
                )
                .all()
            }

            async def _fetch_vm(cu: ComputeUnit, _hw_map=hw_map, _client=client):
                hw = _hw_map.get(cu.hardware_id)
                if not hw or not hw.proxmox_node_name:
                    return None
                vm_type = cu.proxmox_type or "qemu"
                status = await _client.get_vm_status(
                    hw.proxmox_node_name,
                    cu.proxmox_vmid,
                    vm_type,  # type: ignore[arg-type]
                )
                return cu, status

            results = await asyncio.gather(
                *[_fetch_vm(cu) for cu in compute_units],
                return_exceptions=True,
            )

            now = utcnow()
            for result in results:
                if isinstance(result, Exception):
                    _logger.debug("Telemetry poll failed for a VM: %s", result)
                    continue
                if result is None:
                    continue
                cu, status = result  # type: ignore[misc]
                try:
                    cpu_pct = round(status.get("cpu", 0) * 100, 1)
                    maxmem = status.get("maxmem", 0)
                    mem = status.get("mem", 0)
                    netin = status.get("netin", 0)
                    netout = status.get("netout", 0)
                    maxdisk = status.get("maxdisk", 0)
                    disk = status.get("disk", 0)

                    pve_status = json.dumps(
                        {
                            "status": status.get("status", "unknown"),
                            "cpu_pct": cpu_pct,
                            "mem_used_bytes": mem,
                            "mem_total_bytes": maxmem,
                            "disk_used_bytes": disk,
                            "disk_total_bytes": maxdisk,
                            "netin": netin,
                            "netout": netout,
                        }
                    )

                    cu.proxmox_status = pve_status
                    cu.status = "active" if status.get("status") == "running" else "inactive"

                    db.add(
                        TelemetryTimeseries(
                            entity_type="compute_unit",
                            entity_id=cu.id,
                            metric="cpu_pct",
                            value=cpu_pct,
                            source="proxmox",
                            ts=now,
                        )
                    )

                    await _publish(
                        "telemetry.proxmox.vm",
                        {
                            "compute_unit_id": cu.id,
                            "vmid": cu.proxmox_vmid,
                            "status": cu.status,
                            "telemetry": json.loads(pve_status),
                        },
                    )
                except Exception as e:
                    _logger.debug("Telemetry apply failed for VM %s: %s", cu.proxmox_vmid, e)

            db.commit()
        except Exception as e:
            _logger.warning("VM telemetry poll failed for integration %d: %s", config_id, e)


# ── Cluster overview (dashboard API) ──────────────────────────────────────────


async def get_cluster_overview(db: Session, integration_id: int) -> dict[str, Any]:
    """Build cluster overview payload for Proxmox dashboard: cluster info, problems, time-series, storage.
    Uses live PVE API for cluster status and DB for telemetry/storage/events."""
    from sqlalchemy import select

    from app.services import status_page_service as svc_status

    config = db.get(IntegrationConfig, integration_id)
    if not config or config.type != "proxmox":
        return {
            "cluster": {
                "name": "",
                "quorum": False,
                "nodes_online": 0,
                "nodes_total": 0,
                "vms": 0,
                "lxcs": 0,
                "uptime": "",
            },
            "problems": [],
            "time_series": {"cpu": {}, "memory": {}, "network_in": {}, "network_out": {}},
            "storage": [],
        }

    try:
        client = _get_client(db, config)
    except Exception as e:
        _logger.warning("Cluster overview: no client for integration %d: %s", integration_id, e)
        return {
            "cluster": {
                "name": "",
                "quorum": False,
                "nodes_online": 0,
                "nodes_total": 0,
                "vms": 0,
                "lxcs": 0,
                "uptime": "",
            },
            "problems": [],
            "time_series": {"cpu": {}, "memory": {}, "network_in": {}, "network_out": {}},
            "storage": [],
        }

    nodes = (
        db.query(Hardware)
        .filter(
            Hardware.integration_config_id == integration_id,
            Hardware.proxmox_node_name.isnot(None),
        )
        .all()
    )
    node_ids = [hw.id for hw in nodes]
    node_id_to_name = {hw.id: (hw.proxmox_node_name or f"hw-{hw.id}") for hw in nodes}

    # Cluster status from PVE (with circuit breaker to avoid overwhelming a down host)
    cluster_name = config.cluster_name or ""
    quorum = False
    nodes_online = 0
    nodes_total = 0
    try:
        from app.core.circuit_breaker import call_with_circuit_breaker

        cs_list = await call_with_circuit_breaker(
            f"proxmox:{integration_id}:cluster",
            lambda: client.get_cluster_status(),
            fallback=[],
        )
        for item in cs_list or []:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "cluster":
                cluster_name = item.get("name") or cluster_name
                quorum = bool(item.get("quorum", 0))
            elif item.get("type") == "node":
                nodes_total += 1
                if str(item.get("status", "")).lower() == "online":
                    nodes_online += 1
    except Exception as e:
        _logger.debug("Cluster status fetch failed: %s", e)

    vms = (
        db.query(ComputeUnit)
        .filter(
            ComputeUnit.integration_config_id == integration_id,
            ComputeUnit.proxmox_type == "qemu",
        )
        .count()
    )
    lxcs = (
        db.query(ComputeUnit)
        .filter(
            ComputeUnit.integration_config_id == integration_id,
            ComputeUnit.proxmox_type == "lxc",
        )
        .count()
    )

    uptime_str = ""
    if nodes:
        try:
            td = json.loads(nodes[0].telemetry_data or "{}") if nodes[0].telemetry_data else {}
            uptime_s = td.get("uptime_s", 0)
            if uptime_s:
                d = int(uptime_s) // 86400
                h = (int(uptime_s) % 86400) // 3600
                m = (int(uptime_s) % 3600) // 60
                uptime_str = f"{d}d {h}h {m}m"
        except Exception:
            pass

    # Time-series from TelemetryTimeseries (last 24h)
    since_ts = utcnow() - timedelta(hours=24)
    rows = (
        db.execute(
            select(TelemetryTimeseries)
            .where(
                TelemetryTimeseries.entity_type == "hardware",
                TelemetryTimeseries.entity_id.in_(node_ids),
                TelemetryTimeseries.ts >= since_ts,
                TelemetryTimeseries.metric.in_(
                    [
                        "cpu_pct",
                        "mem_used_gb",
                        "netin",
                        "netout",
                        "rrd_cpu",
                        "rrd_memused",
                        "rrd_netin",
                        "rrd_netout",
                    ]
                ),
            )
            .order_by(TelemetryTimeseries.ts.asc())
        )
        .scalars()
        .all()
    )
    cpu_series: dict[str, list[dict[str, float | str]]] = {}
    mem_series: dict[str, list[dict[str, float | str]]] = {}
    netin_series: dict[str, list[dict[str, float | str]]] = {}
    netout_series: dict[str, list[dict[str, float | str]]] = {}
    for r in rows:
        node_name = node_id_to_name.get(r.entity_id, f"hw-{r.entity_id}")
        ts_str = r.ts.isoformat() if r.ts else ""
        point = {"time": ts_str, "value": r.value}
        if r.metric in ("cpu_pct", "rrd_cpu"):
            cpu_series.setdefault(node_name, []).append(point)
        elif r.metric in ("mem_used_gb", "rrd_memused"):
            mem_series.setdefault(node_name, []).append(point)
        elif r.metric in ("netin", "rrd_netin"):
            netin_series.setdefault(node_name, []).append(point)
        elif r.metric in ("netout", "rrd_netout"):
            netout_series.setdefault(node_name, []).append(point)

    # Storage
    storage_rows = db.query(Storage).filter(Storage.integration_config_id == integration_id).all()
    storage_list = []
    for st in storage_rows:
        content = (st.notes or "").replace("content: ", "") if st.notes else ""
        storage_list.append(
            {
                "name": st.name or "",
                "used_gb": float(st.used_gb) if st.used_gb is not None else None,
                "total_gb": float(st.capacity_gb) if st.capacity_gb is not None else None,
                "content": content,
            }
        )

    # Problems: events from status groups that contain any of our nodes
    problems_list: list[dict[str, str]] = []
    seen_problems: set[tuple[str, str]] = set()
    try:
        all_groups = list(db.execute(select(StatusGroup)).scalars().all())
        for g in all_groups:
            hw_ids, _, _ = svc_status.resolve_group_entity_ids(g)
            if not any(hid in node_ids for hid in hw_ids):
                continue
            events = svc_status.list_events_for_group(db, g.id, since_param="7d", limit=50)
            for e in events:
                ts = e.get("ts") or e.get("timestamp", "")
                msg = e.get("message", "")
                key = (str(ts), msg)
                if key in seen_problems:
                    continue
                seen_problems.add(key)
                severity = e.get("severity", "info")
                problems_list.append(
                    {
                        "time": ts[:19] if isinstance(ts, str) and len(ts) > 19 else str(ts),
                        "severity": severity.title(),
                        "host": "",  # could resolve from event if we store host
                        "problem": msg,
                        "status": "RESOLVED" if severity == "info" else "PROBLEM",
                    }
                )
        problems_list.sort(key=lambda x: x.get("time", ""), reverse=True)
        problems_list = problems_list[:100]
    except Exception as e:
        _logger.debug("Problems aggregation failed: %s", e)

    return {
        "cluster": {
            "name": cluster_name,
            "quorum": quorum,
            "nodes_online": nodes_online,
            "nodes_total": nodes_total,
            "vms": vms,
            "lxcs": lxcs,
            "uptime": uptime_str,
        },
        "problems": problems_list,
        "time_series": {
            "cpu": cpu_series,
            "memory": mem_series,
            "network_in": netin_series,
            "network_out": netout_series,
        },
        "storage": storage_list,
    }


# ── VM Actions ───────────────────────────────────────────────────────────────


async def execute_vm_action(
    db: Session,
    config: IntegrationConfig,
    node: str,
    vmid: int,
    vm_type: str,
    action: str,
) -> dict:
    try:
        client = _get_client(db, config)
        upid = await client.vm_action(node, vmid, vm_type, action)
        return {"ok": True, "upid": str(upid)}
    except Exception as e:
        return {"ok": False, "error": str(e)}
