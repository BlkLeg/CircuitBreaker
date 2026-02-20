from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict

VendorSlug = Literal[
    "amd", "intel", "nvidia", "arm", "apple",
    "dell", "hp", "lenovo", "supermicro", "asus",
    "gigabyte", "asrock", "cisco", "ubiquiti", "mikrotik",
    "synology", "qnap", "proxmox", "other",
]


# Allowed role slugs (enforced by frontend dropdown; kept as str for DB compatibility)
# router | hypervisor | server | nas | desktop | workstation | mini_pc | raspberry_pi | switch | ap | other


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


class Hardware(HardwareBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
    storage_summary: Optional[dict] = None
