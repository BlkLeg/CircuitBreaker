"""The one path from a raw discovery observation to a classified `ScanResult` (§5, D-9).

`_scan_import` owned this inline until Slice 4. The agent path needs exactly the
same row shape and exactly the same match/conflict verdict for a *single*
incremental finding, and the rest of `_scan_import` cannot give it: that function
opens its own `SessionLocal`, needs the `setup` dict `_scan_setup` builds,
de-duplicates IPs across the whole batch, suppresses prober rows, and finally
**overwrites** `job.hosts_*` instead of incrementing them. Calling it with
fabricated raw scan data would therefore reset a live job's counters once per
finding. So the row-building and the matcher move here, `db` arrives as a
parameter, and both callers share one classification.

Two things differ on the agent path, and only those two:

* **Identity is normalized before it is matched, never by relaxing the match.**
  The Linux neighbour cache reports `net.HardwareAddr.String()`, which is
  lowercase; every Hardware row the nmap scanner has ever written is uppercase.
  Making the lookup case-insensitive would change the server path's SQL and
  drop its index, so the *input* is canonicalised instead and the lookup stays
  what it was.
* **The Hardware lookups are filtered by the job's tenant.** The server matcher
  carries no tenant predicate and keeps none — `hardware` predates tenants and
  narrowing it would stop matching every untenanted row on installs that never
  created a tenant. But an agent is an untrusted remote executor: without the
  predicate a tenant-A agent's finding matches a tenant-B Hardware row, and
  auto-merge then writes the reported hostname, IP and MAC into it.

Everything else — the docker `network_id` resolution, the override fields, the
conflict vocabulary — is the server behaviour moved verbatim.
"""

from __future__ import annotations

import ipaddress
import json
from collections.abc import Mapping
from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.core.time import utcnow_iso
from app.db.models import Hardware, ScanJob, ScanResult
from app.services.discovery_network import _match_ip_to_network

# The three verdicts `_scan_import` has always counted, returned instead of
# incremented so the batch caller can keep writing `job.hosts_*` absolutely and
# the agent caller can increment them (D-10).
CLASSIFICATION_NEW = "new"
CLASSIFICATION_MATCHED = "matched"
CLASSIFICATION_CONFLICT = "conflict"


def normalize_mac(mac: str | None) -> str | None:
    """Canonicalise a reported MAC to the uppercase colon form Hardware stores.

    Only the case is touched. Re-punctuating `aabb.ccdd.eeff` into colons would
    make this a parser, and a finding whose MAC this module cannot recognise
    must stay unmatched rather than be silently reshaped into some other host's
    address.
    """
    if not mac:
        return mac
    return mac.strip().upper()


def normalize_ip(ip: str | None) -> str | None:
    """Canonicalise a reported address to its compressed textual form.

    IPv4 is almost always already canonical; IPv6 is the case that matters,
    where `2001:0DB8::0001` and `2001:db8::1` are the same host and only one of
    them is what `hardware.ip_address` holds. An unparseable address is returned
    unchanged: rejecting it is the ingest caller's job, and quietly dropping it
    here would turn a bad finding into a matchless one with no trace.
    """
    if not ip:
        return ip
    try:
        return ipaddress.ip_address(ip.strip()).compressed
    except ValueError:
        return ip


def build_and_classify_result(
    db: Session,
    job: ScanJob,
    raw: Mapping[str, Any],
    *,
    discovery_agent_id: int | None = None,
    finding_id: str | None = None,
) -> tuple[ScanResult, str]:
    """Add one pending `ScanResult` for `raw` to `db` and say what it is.

    Returns the row (added but not flushed — the caller owns the transaction)
    and one of `"new"` / `"matched"` / `"conflict"`. `discovery_agent_id` being
    set is what marks this an agent finding and turns on both agent-path rules
    described in the module docstring.
    """
    ip = raw.get("ip")
    mac_address = raw.get("mac_address")
    hostname = raw.get("hostname")
    snmp_data = raw.get("snmp_data", {})
    source = raw.get("source", "nmap")
    network_id = raw.get("network_id")
    vlan_id = raw.get("vlan_id")

    from_agent = discovery_agent_id is not None
    if from_agent:
        ip = normalize_ip(ip)
        mac_address = normalize_mac(mac_address)

    # For docker results, resolve network_id/vlan_id if not already set
    if source == "docker" and network_id is None and ip:
        network_id, vlan_id = _match_ip_to_network(db, ip)

    res = ScanResult(
        scan_job_id=job.id,
        discovery_agent_id=discovery_agent_id,
        finding_id=finding_id,
        # Always the owning job's tenant, never anything the payload claims —
        # `scan_jobs` is where the tenant was established and a finding is not
        # a place to re-assert it.
        tenant_id=job.tenant_id,
        ip_address=ip,
        mac_address=mac_address,
        hostname=hostname or snmp_data.get("sys_name"),
        open_ports_json=raw.get("open_ports_json"),
        os_family=raw.get("os_family"),
        os_vendor=raw.get("os_vendor"),
        os_accuracy=raw.get("os_accuracy"),
        device_type=raw.get("device_type"),
        device_confidence=raw.get("device_confidence"),
        banner=raw.get("banner"),
        source_type=raw.get("source_type", source),
        snmp_sys_name=snmp_data.get("sys_name"),
        snmp_sys_descr=snmp_data.get("sys_descr"),
        raw_nmap_xml=raw.get("raw_nmap_xml", ""),
        network_id=network_id,
        vlan_id=vlan_id,
        lldp_neighbors_json=raw.get("lldp_neighbors"),
        state="new",
        merge_status="pending",
        created_at=utcnow_iso(),
    )

    # docker-sourced results have os_vendor/os_family/hostname preset via override fields
    if raw.get("os_vendor_override"):
        res.os_vendor = raw["os_vendor_override"]
    if raw.get("os_family_override"):
        res.os_family = raw["os_family_override"]
    if raw.get("hostname_override"):
        res.hostname = raw["hostname_override"]

    db.add(res)

    # Match against existing hardware
    matched_hardware = _match_hardware(
        db, job, ip=ip, mac_address=mac_address, from_agent=from_agent
    )

    if not matched_hardware:
        return res, CLASSIFICATION_NEW

    res.matched_entity_type = "hardware"
    res.matched_entity_id = matched_hardware.id

    conflict_fields: list[dict[str, Any]] = []
    if (
        mac_address
        and matched_hardware.mac_address
        and mac_address.upper() != matched_hardware.mac_address.upper()
    ):
        conflict_fields.append(
            {
                "field": "mac_address",
                "stored": matched_hardware.mac_address,
                "discovered": mac_address,
            }
        )
    discovered_hostname = hostname or snmp_data.get("sys_name")
    if (
        discovered_hostname
        and matched_hardware.name
        and discovered_hostname.lower() != matched_hardware.name.lower()
    ):
        conflict_fields.append(
            {
                "field": "hostname",
                "stored": matched_hardware.name,
                "discovered": discovered_hostname,
            }
        )

    if conflict_fields:
        res.state = "conflict"
        res.conflicts_json = json.dumps(conflict_fields)  # type: ignore[assignment]
        return res, CLASSIFICATION_CONFLICT

    res.state = "matched"
    return res, CLASSIFICATION_MATCHED


def _match_hardware(
    db: Session,
    job: ScanJob,
    *,
    ip: str | None,
    mac_address: str | None,
    from_agent: bool,
) -> Hardware | None:
    """MAC first, then IP — the server matcher's order, with the agent-only tenant predicate.

    `tenant_filters` is empty on the server path, so the emitted SQL there is
    the same two equality lookups it has always been.
    """
    tenant_filters: list[ColumnElement[bool]] = []
    if from_agent:
        # The NULL case is branched out rather than left to SQLAlchemy's
        # implicit `== None` -> `IS NULL` coercion. That coercion is invisible
        # and only fires for a literal; the day this predicate becomes a bound
        # parameter or a `text()` fragment it silently degrades to `= NULL`,
        # which is never true — and on a single-tenant install, where both
        # sides are NULL, that classifies every agent finding "new" forever.
        tenant_filters.append(
            Hardware.tenant_id.is_(None)
            if job.tenant_id is None
            else Hardware.tenant_id == job.tenant_id
        )

    matched: Hardware | None = None
    if mac_address:
        matched = (
            db.query(Hardware).filter(Hardware.mac_address == mac_address, *tenant_filters).first()
        )
    if not matched and ip:
        matched = db.query(Hardware).filter(Hardware.ip_address == ip, *tenant_filters).first()
    return matched
