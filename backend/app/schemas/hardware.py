from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict

VendorSlug = Literal[
    "amd", "intel", "nvidia", "arm", "apple",
    "dell", "hp", "lenovo", "supermicro", "asus",
    "gigabyte", "asrock", "cisco", "ubiquiti", "mikrotik",
    "synology", "qnap", "proxmox", "pfsense", "opnsense",
    "apc", "cyberpower", "truenas", "raspberry_pi", "other",
]


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


class HardwareBase(BaseModel):
    name: str
    role: Optional[str] = None
    vendor: Optional[VendorSlug] = None
    model: Optional[str] = None
    cpu: Optional[str] = None
    memory_gb: Optional[int] = None
    location: Optional[str] = None
    notes: Optional[str] = None
    ip_address: Optional[str] = None
    wan_uplink: Optional[str] = None
    cpu_brand: Optional[str] = None
    vendor_icon_slug: Optional[str] = None
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


class HardwareCreate(HardwareBase):
    pass


class HardwareUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    vendor: Optional[VendorSlug] = None
    model: Optional[str] = None
    cpu: Optional[str] = None
    memory_gb: Optional[int] = None
    location: Optional[str] = None
    notes: Optional[str] = None
    ip_address: Optional[str] = None
    wan_uplink: Optional[str] = None
    cpu_brand: Optional[str] = None
    vendor_icon_slug: Optional[str] = None
    tags: Optional[list[str]] = None
    vendor_catalog_key: Optional[str] = None
    model_catalog_key: Optional[str] = None
    u_height: Optional[int] = None
    rack_unit: Optional[int] = None
    telemetry_config: Optional[TelemetryConfig] = None
    # v0.1.4: environment registry
    environment_id: Optional[int] = None
    environment: Optional[str] = None


class Hardware(HardwareBase):
    model_config = ConfigDict(from_attributes=True)

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
