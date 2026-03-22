import ipaddress
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator


class NetworkBase(BaseModel):
    name: str
    icon_slug: str | None = None
    cidr: str | None = None

    @field_validator("cidr", mode="before")
    @classmethod
    def validate_cidr(cls, v: object) -> object:
        if v is None:
            return v
        try:
            ipaddress.ip_network(str(v), strict=False)
        except ValueError as exc:
            raise ValueError(f"Invalid CIDR notation: {v}") from exc
        return v

    vlan_id: int | None = None
    gateway: str | None = None
    description: str | None = None
    gateway_hardware_id: int | None = None


class NetworkCreate(NetworkBase):
    tags: list[str] = []


class NetworkUpdate(BaseModel):
    name: str | None = None
    icon_slug: str | None = None
    cidr: str | None = None
    vlan_id: int | None = None
    gateway: str | None = None
    description: str | None = None
    gateway_hardware_id: int | None = None
    tags: list[str] | None = None


class Network(NetworkBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tags: list[str] = []
    created_at: datetime
    updated_at: datetime


class ComputeNetworkLink(BaseModel):
    compute_id: int
    ip_address: str | None = None


class ComputeNetworkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    compute_id: int
    network_id: int
    ip_address: str | None = None


class HardwareNetworkLink(BaseModel):
    hardware_id: int
    ip_address: str | None = None


class HardwareNetworkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    hardware_id: int
    network_id: int
    ip_address: str | None = None


class NetworkPeerCreate(BaseModel):
    peer_network_id: int


class NetworkPeerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    network_a_id: int
    network_b_id: int
    relation: str = "peers_with"
    created_at: datetime
