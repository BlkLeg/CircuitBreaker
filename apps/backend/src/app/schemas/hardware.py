import json
import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_serializer, field_validator

VendorSlug = Literal[
    "amd",
    "intel",
    "nvidia",
    "arm",
    "apple",
    "dell",
    "hp",
    "lenovo",
    "supermicro",
    "asus",
    "gigabyte",
    "asrock",
    "cisco",
    "ubiquiti",
    "mikrotik",
    "synology",
    "qnap",
    "proxmox",
    "pfsense",
    "opnsense",
    "apc",
    "cyberpower",
    "truenas",
    "raspberry_pi",
    "other",
]

# Set of known vendor slugs used for coercion validation
_KNOWN_VENDORS: set[str] = set(VendorSlug.__args__)  # type: ignore[attr-defined]


def _coerce_vendor(v: str | None) -> str | None:
    """Normalise vendor values on write.

    - None / empty string  → None
    - Known VendorSlug     → returned as-is
    - Any other string     → coerced to 'other' (prevents Literal validation
      failures when discovery writes OS strings like 'Linux' into the vendor
      column and the frontend echoes them back on PATCH)
    """
    if not v:
        return None
    return v if v in _KNOWN_VENDORS else "other"


# Allowed role slugs (enforced by frontend dropdown; kept as str for DB compatibility)
# router | firewall | hypervisor | server | nas | desktop | workstation | mini_pc
# raspberry_pi | switch | ap | ups | pdu | access_point | sbc | other


class TelemetryConfig(BaseModel):
    profile: str  # idrac9 | ilo5 | apc_ups | snmp_generic | ipmi_generic
    host: str
    port: int = 161
    protocol: str = "snmp"  # snmp | ipmi | rest
    snmp_community: str | None = "public"
    snmp_version: str | None = "v2c"
    username: str | None = None
    password: str | None = None  # encrypted before storage
    poll_interval_seconds: int = 60
    enabled: bool = True

    @field_validator("snmp_community")
    @classmethod
    def validate_snmp_community(cls, v: str | None) -> str | None:
        """Reject shell metacharacters and enforce length limit."""
        if v is None:
            return v
        if len(v) > 64:
            raise ValueError("SNMP community string must be <= 64 characters")
        if re.search(r'[;&|$`"><\\()&]', v):
            raise ValueError("SNMP community string contains illegal characters")
        return v

    @field_serializer("password", when_used="json")
    def _mask_password(self, v: str | None) -> str | None:
        """Mask password in API responses. Internal .model_dump() calls are unaffected."""
        return "****" if v else v

    @field_serializer("snmp_community", when_used="json")
    def _mask_community(self, v: str | None) -> str | None:
        """Mask SNMP community string in API responses."""
        return "****" if v else v


class PortEntry(BaseModel):
    port_id: int
    label: str | None = None  # "LAN1", "WAN", "MGMT" etc.
    type: str = "ethernet"  # ethernet | sfp | sfp+ | usb | console
    speed_mbps: int | None = None  # 100, 1000, 2500, 10000
    connected_hardware_id: int | None = None
    connected_compute_id: int | None = None
    vlan_id: int | None = None
    notes: str | None = None


class LinkedDocument(BaseModel):
    id: int
    title: str
    category: str | None = None
    icon: str | None = None


class HardwareBase(BaseModel):
    name: str
    role: str | None = None
    # Accept any string on inbound payloads; unknown values are coerced to
    # 'other' by the validator below so the DB always stores a valid slug.
    vendor: str | None = None
    model: str | None = None
    cpu: str | None = None
    memory_gb: int | None = None
    location: str | None = None
    notes: str | None = None
    ip_address: str | None = None
    wan_uplink: str | None = None
    cpu_brand: str | None = None
    vendor_icon_slug: str | None = None
    custom_icon: str | None = None
    tags: list[str] = []
    # v0.1.2: catalog linkage
    vendor_catalog_key: str | None = None
    model_catalog_key: str | None = None
    # v0.1.2: rack positioning
    u_height: int | None = None
    rack_unit: int | None = None
    # v0.1.2: telemetry configuration
    telemetry_config: TelemetryConfig | None = None
    # v0.1.4: environment registry
    environment_id: int | None = None
    environment: str | None = None
    # v0.1.4-cortex: rack assignment + discovery lineage
    rack_id: int | None = None
    source_scan_result_id: int | None = None
    # Phase 2: mounting orientation
    mounting_orientation: str | None = None
    side_rail: str | None = None
    # v0.1.7: Networking (Router/AP) hardware extensions
    wifi_standards: list[str] | None = None
    wifi_bands: list[str] | None = None
    max_tx_power_dbm: int | None = None
    port_count: int | None = None
    software_platform: str | None = None
    download_speed_mbps: int | None = None
    upload_speed_mbps: int | None = None
    port_map: list[PortEntry] | None = None

    @field_validator("vendor", mode="before")
    @classmethod
    def normalise_vendor(cls, v: str | None) -> str | None:
        return _coerce_vendor(v)


class HardwareCreate(HardwareBase):
    pass


class HardwareUpdate(BaseModel):
    name: str | None = None
    role: str | None = None
    vendor: str | None = None
    model: str | None = None
    cpu: str | None = None
    memory_gb: int | None = None
    location: str | None = None
    notes: str | None = None
    ip_address: str | None = None
    wan_uplink: str | None = None
    cpu_brand: str | None = None
    vendor_icon_slug: str | None = None
    custom_icon: str | None = None
    tags: list[str] | None = None
    vendor_catalog_key: str | None = None
    model_catalog_key: str | None = None
    u_height: int | None = None
    rack_unit: int | None = None
    telemetry_config: TelemetryConfig | None = None
    # v0.1.4: environment registry
    environment_id: int | None = None
    environment: str | None = None
    # v0.1.4-cortex: rack assignment
    rack_id: int | None = None
    # Phase 2: mounting orientation
    mounting_orientation: str | None = None
    side_rail: str | None = None
    # v2: manual status override (clears auto-derivation when set)
    status_override: str | None = None
    # v0.1.7: Networking (Router/AP) hardware extensions
    wifi_standards: list[str] | None = None
    wifi_bands: list[str] | None = None
    max_tx_power_dbm: int | None = None
    port_count: int | None = None
    software_platform: str | None = None
    download_speed_mbps: int | None = None
    upload_speed_mbps: int | None = None
    port_map: list[PortEntry] | None = None

    @field_validator("vendor", mode="before")
    @classmethod
    def normalise_vendor(cls, v: str | None) -> str | None:
        return _coerce_vendor(v)


class HardwareConnectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    source_hardware_id: int
    target_hardware_id: int
    connection_type: str | None = None
    bandwidth_mbps: int | None = None


class Hardware(HardwareBase):
    model_config = ConfigDict(from_attributes=True)

    # Override vendor with plain Optional[str] for reads — the DB may contain
    # legacy or discovery-written values (e.g. 'Linux') outside the VendorSlug
    # Literal enum. Strict VendorSlug validation is still enforced on
    # HardwareCreate and HardwareUpdate (write paths).
    vendor: str | None = None

    id: int
    created_at: datetime
    updated_at: datetime
    storage_summary: dict | None = None
    # v0.1.2: telemetry read-only state
    telemetry_data: dict | None = None

    @field_validator("telemetry_data", mode="before")
    @classmethod
    def _parse_telemetry_data(cls, v: Any) -> dict | None:
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
                return parsed if isinstance(parsed, dict) else None
            except Exception:
                return None
        return v

    telemetry_status: str | None = "unknown"
    telemetry_last_polled: datetime | None = None
    # v0.1.4: environment registry
    environment_name: str | None = None
    # v0.1.4-cortex: rack info + discovery fields
    rack_name: str | None = None
    last_seen: str | None = None
    status: str | None = None
    source: str | None = None
    mac_address: str | None = None
    discovered_at: str | None = None
    os_version: str | None = None
    source_scan_result_id: int | None = None
    # v2: manual status override
    status_override: str | None = None
    documents: list[LinkedDocument] = []
