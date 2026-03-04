from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, field_validator

VendorSlug = Literal[
    "amd", "intel", "nvidia", "arm", "apple",
    "dell", "hp", "lenovo", "supermicro", "asus",
    "gigabyte", "asrock", "cisco", "ubiquiti", "mikrotik",
    "synology", "qnap", "proxmox", "pfsense", "opnsense",
    "apc", "cyberpower", "truenas", "raspberry_pi", "other",
]

# Set of known vendor slugs used for coercion validation
_KNOWN_VENDORS: set[str] = set(VendorSlug.__args__)  # type: ignore[attr-defined]


def _coerce_vendor(v: Optional[str]) -> Optional[str]:
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
    profile: str                                    # idrac9 | ilo5 | apc_ups | snmp_generic | ipmi_generic
    host: str
    port: int = 161
    protocol: str = "snmp"                         # snmp | ipmi | rest
    snmp_community: Optional[str] = "public"
    snmp_version: Optional[str] = "v2c"
    username: Optional[str] = None
    password: Optional[str] = None                 # encrypted before storage
    poll_interval_seconds: int = 60
    enabled: bool = True


class PortEntry(BaseModel):
    port_id: int
    label: Optional[str] = None           # "LAN1", "WAN", "MGMT" etc.
    type: str = "ethernet"                # ethernet | sfp | sfp+ | usb | console
    speed_mbps: Optional[int] = None      # 100, 1000, 2500, 10000
    connected_hardware_id: Optional[int] = None
    connected_compute_id: Optional[int] = None
    vlan_id: Optional[int] = None
    notes: Optional[str] = None


class HardwareBase(BaseModel):
    name: str
    role: Optional[str] = None
    # Accept any string on inbound payloads; unknown values are coerced to
    # 'other' by the validator below so the DB always stores a valid slug.
    vendor: Optional[str] = None
    model: Optional[str] = None
    cpu: Optional[str] = None
    memory_gb: Optional[int] = None
    location: Optional[str] = None
    notes: Optional[str] = None
    ip_address: Optional[str] = None
    wan_uplink: Optional[str] = None
    cpu_brand: Optional[str] = None
    vendor_icon_slug: Optional[str] = None
    custom_icon: Optional[str] = None
    tags: list[str] = []
    # v0.1.2: catalog linkage
    vendor_catalog_key: Optional[str] = None
    model_catalog_key: Optional[str] = None
    # v0.1.2: rack positioning
    u_height: Optional[int] = None
    rack_unit: Optional[int] = None
    # v0.1.2: telemetry configuration
    telemetry_config: Optional[TelemetryConfig] = None
    # v0.1.4: environment registry
    environment_id: Optional[int] = None
    environment: Optional[str] = None
    # v0.1.4-cortex: rack assignment + discovery lineage
    rack_id: Optional[int] = None
    source_scan_result_id: Optional[int] = None
    # v0.1.7: Networking (Router/AP) hardware extensions
    wifi_standards: Optional[list[str]] = None
    wifi_bands: Optional[list[str]] = None
    max_tx_power_dbm: Optional[int] = None
    port_count: Optional[int] = None
    software_platform: Optional[str] = None
    download_speed_mbps: Optional[int] = None
    upload_speed_mbps: Optional[int] = None
    port_map: Optional[list[PortEntry]] = None

    @field_validator("vendor", mode="before")
    @classmethod
    def normalise_vendor(cls, v: Optional[str]) -> Optional[str]:
        return _coerce_vendor(v)


class HardwareCreate(HardwareBase):
    pass


class HardwareUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    vendor: Optional[str] = None
    model: Optional[str] = None
    cpu: Optional[str] = None
    memory_gb: Optional[int] = None
    location: Optional[str] = None
    notes: Optional[str] = None
    ip_address: Optional[str] = None
    wan_uplink: Optional[str] = None
    cpu_brand: Optional[str] = None
    vendor_icon_slug: Optional[str] = None
    custom_icon: Optional[str] = None
    tags: Optional[list[str]] = None
    vendor_catalog_key: Optional[str] = None
    model_catalog_key: Optional[str] = None
    u_height: Optional[int] = None
    rack_unit: Optional[int] = None
    telemetry_config: Optional[TelemetryConfig] = None
    # v0.1.4: environment registry
    environment_id: Optional[int] = None
    environment: Optional[str] = None
    # v0.1.4-cortex: rack assignment
    rack_id: Optional[int] = None
    # v2: manual status override (clears auto-derivation when set)
    status_override: Optional[str] = None
    # v0.1.7: Networking (Router/AP) hardware extensions
    wifi_standards: Optional[list[str]] = None
    wifi_bands: Optional[list[str]] = None
    max_tx_power_dbm: Optional[int] = None
    port_count: Optional[int] = None
    software_platform: Optional[str] = None
    download_speed_mbps: Optional[int] = None
    upload_speed_mbps: Optional[int] = None
    port_map: Optional[list[PortEntry]] = None

    @field_validator("vendor", mode="before")
    @classmethod
    def normalise_vendor(cls, v: Optional[str]) -> Optional[str]:
        return _coerce_vendor(v)


class Hardware(HardwareBase):
    model_config = ConfigDict(from_attributes=True)

    # Override vendor with plain Optional[str] for reads — the DB may contain
    # legacy or discovery-written values (e.g. 'Linux') outside the VendorSlug
    # Literal enum. Strict VendorSlug validation is still enforced on
    # HardwareCreate and HardwareUpdate (write paths).
    vendor: Optional[str] = None

    id: int
    created_at: datetime
    updated_at: datetime
    storage_summary: Optional[dict] = None
    # v0.1.2: telemetry read-only state
    telemetry_data: Optional[dict] = None
    telemetry_status: Optional[str] = "unknown"
    telemetry_last_polled: Optional[datetime] = None
    # v0.1.4: environment registry
    environment_name: Optional[str] = None
    # v0.1.4-cortex: rack info + discovery fields
    rack_name: Optional[str] = None
    last_seen: Optional[str] = None
    status: Optional[str] = None
    source: Optional[str] = None
    mac_address: Optional[str] = None
    discovered_at: Optional[str] = None
    os_version: Optional[str] = None
    source_scan_result_id: Optional[int] = None
    # v2: manual status override
    status_override: Optional[str] = None
