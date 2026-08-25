"""Pydantic schemas for certificate management."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class CertificateCreate(BaseModel):
    domain: str = Field(..., min_length=1, max_length=253)
    type: str = Field(default="selfsigned", pattern="^(letsencrypt|selfsigned|imported)$")
    auto_renew: bool = True
    cert_pem: str | None = Field(
        default=None, description="PEM cert — required for type=imported, ignored otherwise"
    )
    key_pem: str | None = Field(
        default=None, description="PEM key — required for type=imported, ignored otherwise"
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
    is_active: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class CertificateDetailRead(CertificateRead):
    """Includes the PEM bodies — only returned on explicit single-cert GET."""

    cert_pem: str


class CertificateActivateResponse(BaseModel):
    """Three outcomes, reported separately.

    `written` without `reloaded` is a real state — the bytes are on disk and the running TLS
    server has not picked them up — and must not be collapsed into either success or error.
    """

    certificate: CertificateRead
    written: bool
    reloaded: bool
    detail: str
