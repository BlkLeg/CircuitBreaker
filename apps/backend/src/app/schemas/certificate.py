"""Pydantic schemas for certificate management."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class CertificateCreate(BaseModel):
    domain: str = Field(..., min_length=1, max_length=253)
    type: str = Field(default="selfsigned", pattern="^(letsencrypt|selfsigned)$")
    auto_renew: bool = True
    cert_pem: str | None = Field(
        default=None, description="PEM cert — omit for auto-generated self-signed"
    )
    key_pem: str | None = Field(
        default=None, description="PEM key — omit for auto-generated self-signed"
    )


class CertificateUpdate(BaseModel):
    auto_renew: bool | None = None
    cert_pem: str | None = None
    key_pem: str | None = None


class CertificateRead(BaseModel):
    id: int
    domain: str
    type: str
    expires_at: datetime
    auto_renew: bool
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class CertificateDetailRead(CertificateRead):
    """Includes the PEM bodies — only returned on explicit single-cert GET."""

    cert_pem: str
