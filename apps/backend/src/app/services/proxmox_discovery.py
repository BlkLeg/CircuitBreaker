"""Proxmox cluster discovery — node, VM, network, and storage import pipeline."""

from __future__ import annotations

import asyncio
import json
import logging
import random
from typing import Any

from sqlalchemy.orm import Session

from app.core.retry import INTEGRATION_RETRY_ATTEMPTS, INTEGRATION_RETRY_BASE_DELAY_S
from app.core.subjects import (
    DISCOVERY_SCAN_COMPLETED,
    DISCOVERY_SCAN_PROGRESS,
    DISCOVERY_SCAN_STARTED,
    PROXMOX_NODE_REMOVED,
    PROXMOX_STORAGE_REMOVED,
    PROXMOX_VM_REMOVED,
)
from app.core.time import utcnow
from app.db.models import (
    ComputeUnit,
    Hardware,
    HardwareCluster,
    HardwareClusterMember,
    IntegrationConfig,
    ProxmoxDiscoverRun,
    ScanJob,
    ScanResult,
    Storage,
    TopologyNode,
)
from app.integrations.proxmox_client import ProxmoxIntegration
from app.services.proxmox_client import (
    _check_token_privsep,
    _get_client,
    _proxmox_error_message,
    _publish,
)

_logger = logging.getLogger(__name__)


# ── Discovery & Import ───────────────────────────────────────────────────────


def _create_proxmox_review_job(
    db: Session,
    config: IntegrationConfig,
    started_at_iso: str,
) -> ScanJob:
    """Create a completed ScanJob row used to anchor pending Proxmox ScanResults."""
    job = ScanJob(
        profile_id=None,
        label=f"Proxmox Discovery — {config.name}",
        target_cidr=f"proxmox://integration/{config.id}",
        vlan_ids="[]",
        network_ids="[]",
        scan_types_json='["proxmox"]',
        status="completed",
        started_at=started_at_iso,
        completed_at=started_at_iso,
        hosts_found=0,
        hosts_new=0,
        hosts_updated=0,
        hosts_conflict=0,
        triggered_by="proxmox",
        source_type="proxmox",
        progress_phase="done",
        progress_message="Queued for review",
        created_at=started_at_iso,
    )
    db.add(job)
    db.flush()
    return job


def _queue_proxmox_results(
    db: Session,
    config: IntegrationConfig,
    nodes: list[dict],
    qemu_vms: list[dict],
    lxc_cts: list[dict],
) -> tuple[ScanJob, dict[str, int]]:
    """Queue discovered Proxmox entities as pending ScanResult rows."""
    now_iso = utcnow().isoformat()
    job = _create_proxmox_review_job(db, config, now_iso)

    queued_nodes = 0
    queued_vms = 0
    queued_cts = 0

    for node in nodes:
        node_name = (node.get("node") or "").strip()
        node_ip = (node.get("ip") or "").strip() or f"node:{node_name or 'unknown'}"
        metadata = {
            "source": "proxmox",
            "kind": "node",
            "integration_id": config.id,
            "node_name": node_name or None,
            "status": node.get("status"),
            "cpu": node.get("cpu"),
            "maxmem": node.get("maxmem"),
            "mem": node.get("mem"),
            "uptime": node.get("uptime"),
            "ip": node.get("ip"),
        }
        db.add(
            ScanResult(
                scan_job_id=job.id,
                ip_address=node_ip,
                hostname=node_name or node_ip,
                os_family="hypervisor",
                os_vendor="Proxmox",
                raw_nmap_xml=json.dumps(metadata),
                source_type="proxmox",
                state="new",
                merge_status="pending",
                created_at=now_iso,
            )
        )
        queued_nodes += 1

    for vm in qemu_vms:
        node_name = (vm.get("node") or "").strip()
        vmid = vm.get("vmid")
        vm_name = (vm.get("name") or "").strip() or f"qemu-{vmid}"
        vm_ip = (vm.get("ip") or "").strip() or f"qemu:{node_name}:{vmid}"
        metadata = {
            "source": "proxmox",
            "kind": "vm",
            "integration_id": config.id,
            "vm_type": "qemu",
            "vmid": vmid,
            "name": vm_name,
            "node_name": node_name or None,
            "status": vm.get("status"),
            "cpu": vm.get("cpu"),
            "maxcpu": vm.get("maxcpu"),
            "maxmem": vm.get("maxmem"),
            "mem": vm.get("mem"),
            "maxdisk": vm.get("maxdisk"),
            "ip": vm.get("ip"),
        }
        db.add(
            ScanResult(
                scan_job_id=job.id,
                ip_address=vm_ip,
                hostname=vm_name,
                os_family="vm",
                os_vendor="Proxmox",
                raw_nmap_xml=json.dumps(metadata),
                source_type="proxmox",
                state="new",
                merge_status="pending",
                created_at=now_iso,
            )
        )
        queued_vms += 1

    for ct in lxc_cts:
        node_name = (ct.get("node") or "").strip()
        vmid = ct.get("vmid")
        ct_name = (ct.get("name") or "").strip() or f"lxc-{vmid}"
        ct_ip = (ct.get("ip") or "").strip() or f"lxc:{node_name}:{vmid}"
        metadata = {
            "source": "proxmox",
            "kind": "vm",
            "integration_id": config.id,
            "vm_type": "lxc",
            "vmid": vmid,
            "name": ct_name,
            "node_name": node_name or None,
            "status": ct.get("status"),
            "cpu": ct.get("cpu"),
            "maxcpu": ct.get("maxcpu"),
            "maxmem": ct.get("maxmem"),
            "mem": ct.get("mem"),
            "maxdisk": ct.get("maxdisk"),
            "ip": ct.get("ip"),
        }
        db.add(
            ScanResult(
                scan_job_id=job.id,
                ip_address=ct_ip,
                hostname=ct_name,
                os_family="container",
                os_vendor="Proxmox",
                raw_nmap_xml=json.dumps(metadata),
                source_type="proxmox",
                state="new",
                merge_status="pending",
                created_at=now_iso,
            )
        )
        queued_cts += 1

    queued_total = queued_nodes + queued_vms + queued_cts
    job.hosts_found = queued_total
    job.hosts_new = queued_total
    job.completed_at = utcnow().isoformat()
    job.progress_message = f"Queued {queued_total} Proxmox discovery result(s) for review"
    db.flush()

    return job, {"nodes": queued_nodes, "vms": queued_vms, "cts": queued_cts, "total": queued_total}


async def _import_storage_without_hardware(
    db: Session,
    config: IntegrationConfig,
    client: ProxmoxIntegration,
    nodes: list[dict],
) -> int:
    """Import storage pools even when node entities are queued for review."""
    count = 0
    for node_res in nodes:
        node_name = (node_res.get("node") or "").strip()
        if not node_name:
            continue
        try:
            storage_list = await client.get_node_storage(node_name)
        except Exception:
            continue
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
                    Storage.hardware_id.is_(None),
                    Storage.integration_config_id == config.id,
                    Storage.name == cb_name,
                )
                .first()
            )
            cap_gb = round(total_bytes / (1024**3)) if total_bytes else None
            used_gb = round(used_bytes / (1024**3)) if used_bytes else None

            if not existing:
                db.add(
                    Storage(
                        name=cb_name,
                        kind=kind,
                        hardware_id=None,
                        capacity_gb=cap_gb,
                        used_gb=used_gb,
                        protocol=pve_type,
                        integration_config_id=config.id,
                        proxmox_storage_name=storage_name,
                        notes=f"content: {st_data.get('content', '')}",
                    )
                )
                count += 1
            else:
                existing.kind = kind
                existing.capacity_gb = cap_gb
                existing.used_gb = used_gb
                existing.protocol = pve_type
                if not active:
                    existing.notes = f"[inactive] content: {st_data.get('content', '')}"
    db.flush()
    return count


async def discover_and_import(
    db: Session, config: IntegrationConfig, *, queue_for_review: bool = False
) -> dict:
    """Full cluster discovery: nodes, VMs, CTs, networks."""
    config.last_sync_status = "syncing"
    db.commit()

    run = ProxmoxDiscoverRun(
        integration_id=config.id,
        status="running",
        started_at=utcnow(),
        nodes_imported=0,
        vms_imported=0,
        cts_imported=0,
        storage_imported=0,
        networks_imported=0,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    result: dict[str, Any] = {
        "ok": True,
        "cluster_name": None,
        "nodes_imported": 0,
        "vms_imported": 0,
        "cts_imported": 0,
        "networks_imported": 0,
        "storage_imported": 0,
        "storage_removed": 0,
        "nodes_removed": 0,
        "vms_removed": 0,
        "results_queued": 0,
        "review_job_id": None,
        "errors": [],
    }

    try:
        for attempt in range(INTEGRATION_RETRY_ATTEMPTS):
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

                cluster = None
                if not queue_for_review:
                    # Upsert HardwareCluster only for direct-import mode.
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

                # cluster/resources has no IP; cluster/status does — inject them
                node_ip_map: dict[str, str] = {}
                for item in cluster_status:
                    if item.get("type") == "node" and item.get("ip"):
                        node_ip_map[item.get("name", "")] = item["ip"]
                for node_res in nodes:
                    nn = node_res.get("node", "")
                    if nn and nn in node_ip_map and not node_res.get("ip"):
                        node_res["ip"] = node_ip_map[nn]

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
                            _logger.warning("Per-node qemu query failed for %s: %s", nn, e)
                        try:
                            per_node_lxc = await client.get_node_vms(nn, "lxc")
                            for ct in per_node_lxc:
                                ct.setdefault("node", nn)
                            lxc_cts.extend(per_node_lxc)
                        except Exception as e:
                            _logger.warning("Per-node lxc query failed for %s: %s", nn, e)

                    if not qemu_vms and not lxc_cts:
                        privsep_hint = await _check_token_privsep(client)
                        if privsep_hint:
                            result["errors"].append(privsep_hint)

                await _publish(
                    DISCOVERY_SCAN_PROGRESS,
                    {
                        "source": "proxmox",
                        "integration_id": config.id,
                        "phase": "importing_nodes",
                        "message": (
                            f"Found {len(nodes)} nodes, {len(qemu_vms)} VMs, {len(lxc_cts)} CTs"
                        ),
                    },
                )

                if queue_for_review:
                    review_job, queued = _queue_proxmox_results(
                        db, config, nodes, qemu_vms, lxc_cts
                    )
                    result["nodes_imported"] = queued["nodes"]
                    result["vms_imported"] = queued["vms"]
                    result["cts_imported"] = queued["cts"]
                    result["results_queued"] = queued["total"]
                    result["review_job_id"] = review_job.id

                    await _publish(
                        DISCOVERY_SCAN_PROGRESS,
                        {
                            "source": "proxmox",
                            "integration_id": config.id,
                            "phase": "queued_for_review",
                            "message": (
                                f"Queued {queued['total']} item(s) for Review Queue "
                                f"(nodes={queued['nodes']},"
                                f" vms={queued['vms']}, cts={queued['cts']})"
                            ),
                        },
                    )

                    try:
                        result["storage_imported"] += await _import_storage_without_hardware(
                            db, config, client, nodes
                        )
                    except Exception as e:
                        result["errors"].append(f"Storage import: {e}")
                else:
                    from sqlalchemy import select as _sel

                    from app.services.discovery_merge import _assign_to_default_map

                    # Remove stale "compute_unit" entries inserted by earlier buggy runs
                    stale_tn = (
                        db.execute(
                            _sel(TopologyNode).where(TopologyNode.entity_type == "compute_unit")
                        )
                        .scalars()
                        .all()
                    )
                    for _row in stale_tn:
                        db.delete(_row)
                    if stale_tn:
                        db.flush()

                    # ── Import nodes ─────────────────────────────────────────────
                    node_hw_map: dict[str, Hardware] = {}
                    if cluster is not None:
                        for node_res in nodes:
                            node_name = node_res.get("node", "")
                            try:
                                hw = _upsert_node(db, config, cluster, node_name, node_res)
                                node_hw_map[node_name] = hw
                                result["nodes_imported"] += 1
                            except Exception as e:
                                result["errors"].append(f"Node {node_name}: {e}")
                                _logger.warning("Failed to import node %s: %s", node_name, e)

                    # Reconcile: remove nodes that disappeared from Proxmox
                    if node_hw_map:
                        try:
                            result["nodes_removed"] = await _reconcile_nodes(
                                db, config, set(node_hw_map.keys())
                            )
                        except Exception as e:
                            result["errors"].append(f"Node reconciliation: {e}")
                    else:
                        _logger.warning(
                            "Proxmox integration %d: skipping node reconciliation"
                            " — no nodes imported this run",
                            config.id,
                        )

                    # ── Import VMs ───────────────────────────────────────────────
                    total_vms = len(qemu_vms) + len(lxc_cts)
                    imported = 0
                    for vm_res in qemu_vms:
                        try:
                            cu = _upsert_vm(db, config, vm_res, "qemu", node_hw_map, client)
                            _assign_to_default_map(db, "compute", cu.id)
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

                    # ── Import CTs ───────────────────────────────────────────────
                    for ct_res in lxc_cts:
                        try:
                            cu = _upsert_vm(db, config, ct_res, "lxc", node_hw_map, client)
                            _assign_to_default_map(db, "compute", cu.id)
                            result["cts_imported"] += 1
                        except Exception as e:
                            vmid = ct_res.get("vmid", "?")
                            result["errors"].append(f"CT {vmid}: {e}")
                            _logger.warning("Failed to import CT %s: %s", vmid, e)
                        imported += 1

                    # Reconcile: remove VMs/CTs that disappeared from Proxmox
                    seen_vmids = {
                        int(v["vmid"]) for v in qemu_vms + lxc_cts if v.get("vmid") is not None
                    }
                    if seen_vmids:
                        try:
                            result["vms_removed"] = await _reconcile_vms(db, config, seen_vmids)
                        except Exception as e:
                            result["errors"].append(f"VM reconciliation: {e}")
                    else:
                        _logger.warning(
                            "Proxmox integration %d: skipping VM reconciliation"
                            " — API returned 0 VMs/CTs (token permission issue or empty cluster?)",
                            config.id,
                        )

                    # ── Assign all imported nodes + cluster to the default topology map ─
                    if cluster is not None:
                        try:
                            _assign_to_default_map(db, "cluster", cluster.id)
                        except Exception as e:
                            result["errors"].append(f"Map assignment for cluster: {e}")
                    for hw in node_hw_map.values():
                        try:
                            _assign_to_default_map(db, "hardware", hw.id)
                        except Exception as e:
                            result["errors"].append(f"Map assignment for node {hw.name}: {e}")

                    # ── Import networks ──────────────────────────────────────────
                    for node_name, hw in node_hw_map.items():
                        try:
                            nets = await _import_node_networks(db, config, client, node_name, hw)
                            result["networks_imported"] += nets
                        except Exception as e:
                            result["errors"].append(f"Networks for {node_name}: {e}")

                    # ── Import storage pools ────────────────────────────────────
                    for node_name, hw in node_hw_map.items():
                        try:
                            upserted, removed = await _import_node_storage(
                                db, config, client, node_name, hw
                            )
                            result["storage_imported"] += upserted
                            result["storage_removed"] += removed
                            # Assign this node's storage pools to the default topology map
                            for st in db.query(Storage).filter(Storage.hardware_id == hw.id).all():
                                _assign_to_default_map(db, "storage", st.id)
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
                        "storage_removed": result["storage_removed"],
                        "nodes_removed": result["nodes_removed"],
                        "vms_removed": result["vms_removed"],
                    },
                )
                run.status = "completed"
                run.completed_at = utcnow()
                run.nodes_imported = result["nodes_imported"]
                run.vms_imported = result["vms_imported"]
                run.cts_imported = result["cts_imported"]
                run.storage_imported = result["storage_imported"]
                run.networks_imported = result["networks_imported"]
                run.errors = result["errors"] if result["errors"] else None
                db.commit()
                return result

            except ValueError as e:
                result["ok"] = False
                result["errors"].append(_proxmox_error_message(e))
                config.last_sync_status = "error"
                config.last_sync_at = utcnow()
                run.status = "failed"
                run.completed_at = utcnow()
                run.errors = result["errors"]
                db.commit()
                _logger.warning(  # nosemgrep: python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure  # noqa: E501
                    # Logs integration ID and exception message — no credential value
                    "Proxmox discovery failed (invalid config/token) for integration %d: %s",
                    config.id,
                    e,
                )
                return result
            except Exception as e:
                if attempt < INTEGRATION_RETRY_ATTEMPTS - 1:
                    delay = (
                        INTEGRATION_RETRY_BASE_DELAY_S
                        * (2**attempt)
                        * (0.5 + random.random() * 0.5)
                    )
                    _logger.warning(
                        "Proxmox discover attempt %s/%s failed, retrying in %.1fs: %s",
                        attempt + 1,
                        INTEGRATION_RETRY_ATTEMPTS,
                        delay,
                        e,
                    )
                    await asyncio.sleep(delay)
                else:
                    raise

    except Exception as e:
        result["ok"] = False
        result["errors"].append(_proxmox_error_message(e))
        config.last_sync_status = "error"
        config.last_sync_at = utcnow()
        run.status = "failed"
        run.completed_at = utcnow()
        run.nodes_imported = result.get("nodes_imported", 0)
        run.vms_imported = result.get("vms_imported", 0)
        run.cts_imported = result.get("cts_imported", 0)
        run.storage_imported = result.get("storage_imported", 0)
        run.networks_imported = result.get("networks_imported", 0)
        run.errors = result["errors"]
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
    cpu_raw = node_res.get("cpu", 0)
    maxmem = node_res.get("maxmem", 0)
    mem = node_res.get("mem", 0)
    uptime = node_res.get("uptime", 0)

    # Proxmox API returns CPU as decimal fraction (0.0-1.0);
    # convert to percentage and clamp to 0-100
    cpu_pct = min(100, round(cpu_raw * 100, 1)) if cpu_raw else 0

    if status_str != "online":
        t_status = "unknown"
    elif cpu_pct >= 90:
        t_status = "critical"
    elif cpu_pct >= 70:
        t_status = "degraded"
    else:
        t_status = "healthy"

    telemetry = {
        "cpu_pct": cpu_pct,
        "mem_used_bytes": mem,
        "mem_total_bytes": maxmem,
        "mem_used_gb": round(mem / (1024**3), 1) if mem else 0,
        "mem_total_gb": round(maxmem / (1024**3), 1) if maxmem else 0,
        "uptime_s": uptime,
        "status": status_str,
    }

    if not hw:
        hw = Hardware(
            name=node_name,
            hostname=node_name,
            role="hypervisor",
            vendor="Proxmox",
            vendor_icon_slug="proxmox-dark",
            proxmox_node_name=node_name,
            integration_config_id=config.id,
            status="active" if status_str == "online" else "inactive",
            source="discovery",
            telemetry_data=telemetry,
            telemetry_status=t_status,
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
        hw.telemetry_status = t_status
        hw.telemetry_last_polled = utcnow()
        hw.memory_gb = round(maxmem / (1024**3)) if maxmem else hw.memory_gb
        if not hw.vendor_icon_slug:
            hw.vendor_icon_slug = "proxmox-dark"
        node_ip = node_res.get("ip")
        if node_ip:
            hw.ip_address = node_ip
        if not hw.hostname:
            hw.hostname = node_name

    db.flush()
    return hw


async def _reconcile_nodes(
    db: Session,
    config: IntegrationConfig,
    seen_node_names: set[str],
) -> int:
    """Delete Hardware records for Proxmox nodes no longer present in the cluster."""
    stale = (
        db.query(Hardware)
        .filter(
            Hardware.integration_config_id == config.id,
            Hardware.proxmox_node_name.notin_(seen_node_names),
            Hardware.proxmox_node_name.isnot(None),
        )
        .all()
    )
    removed = 0
    for hw in stale:
        _logger.info(
            "Proxmox sync: removing stale node '%s' (id=%d, integration=%d)",
            hw.proxmox_node_name,
            hw.id,
            config.id,
        )
        await _publish(
            PROXMOX_NODE_REMOVED,
            {
                "integration_id": config.id,
                "hardware_id": hw.id,
                "node_name": hw.proxmox_node_name,
            },
        )
        db.delete(hw)
        removed += 1
    db.flush()
    return removed


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
        # Node wasn't imported this run (offline, failed, or VM migrated to unknown node).
        # Create a minimal placeholder so the VM is never silently dropped.
        now_dt = utcnow()
        now_iso = now_dt.isoformat()
        hw = Hardware(
            name=node_name or f"Proxmox node {config.id}",
            role="hypervisor",
            vendor="Proxmox",
            vendor_icon_slug="proxmox-dark",
            proxmox_node_name=node_name or None,
            integration_config_id=config.id,
            status="unknown",
            source="discovery",
            discovered_at=now_iso,
            last_seen=now_iso,
            created_at=now_dt,
            updated_at=now_dt,
        )
        db.add(hw)
        db.flush()
        node_hw_map[node_name] = hw
        _logger.info(
            "Created placeholder node '%s' for VM %s (node not found in this sync run)",
            node_name,
            vm_res.get("vmid"),
        )

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
    cpu_raw = vm_res.get("cpu", 0)
    maxcpu = vm_res.get("maxcpu", 0)
    maxmem = vm_res.get("maxmem", 0)
    mem = vm_res.get("mem", 0)
    maxdisk = vm_res.get("maxdisk", 0)

    # Proxmox API returns CPU as decimal fraction (0.0-1.0);
    # convert to percentage and clamp to 0-100
    cpu_pct = min(100, round(cpu_raw * 100, 1)) if cpu_raw else 0

    pve_status = {
        "status": status_str,
        "cpu_pct": cpu_pct,
        "mem_used_bytes": mem,
        "mem_total_bytes": maxmem,
        "disk_total_bytes": maxdisk,
        "netin": vm_res.get("netin", 0),
        "netout": vm_res.get("netout", 0),
    }

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


async def _reconcile_vms(
    db: Session,
    config: IntegrationConfig,
    seen_vmids: set[int],
) -> int:
    """Delete ComputeUnit records for VMs/CTs no longer reported by Proxmox."""
    stale = (
        db.query(ComputeUnit)
        .filter(
            ComputeUnit.integration_config_id == config.id,
            ComputeUnit.proxmox_vmid.notin_(seen_vmids),
            ComputeUnit.proxmox_vmid.isnot(None),
        )
        .all()
    )
    removed = 0
    for cu in stale:
        _logger.info(
            "Proxmox sync: removing stale VM/CT vmid=%s (id=%d, integration=%d)",
            cu.proxmox_vmid,
            cu.id,
            config.id,
        )
        await _publish(
            PROXMOX_VM_REMOVED,
            {
                "integration_id": config.id,
                "compute_unit_id": cu.id,
                "proxmox_vmid": cu.proxmox_vmid,
                "name": cu.name,
            },
        )
        db.delete(cu)
        removed += 1
    db.flush()
    return removed


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
) -> tuple[int, int]:
    """Import PVE storage pools as CB Storage entries. Returns (upserted, removed)."""
    try:
        storage_list = await client.get_node_storage(node_name)
    except Exception:
        return 0, 0

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

    # Reconcile: delete Storage records Proxmox no longer reports for this node
    seen_names = {st_data.get("storage", "") for st_data in storage_list if st_data.get("storage")}
    stale = (
        db.query(Storage)
        .filter(
            Storage.hardware_id == hw.id,
            Storage.integration_config_id == config.id,
            Storage.proxmox_storage_name.notin_(seen_names),
            Storage.proxmox_storage_name.isnot(None),
        )
        .all()
    )
    removed = 0
    for s in stale:
        _logger.info(
            "Proxmox sync: removing stale storage '%s' (id=%d, node=%s, integration=%d)",
            s.proxmox_storage_name,
            s.id,
            node_name,
            config.id,
        )
        await _publish(
            PROXMOX_STORAGE_REMOVED,
            {
                "integration_id": config.id,
                "hardware_id": hw.id,
                "storage_id": s.id,
                "storage_name": s.proxmox_storage_name,
                "node_name": node_name,
            },
        )
        db.delete(s)
        removed += 1

    db.flush()
    return count, removed
