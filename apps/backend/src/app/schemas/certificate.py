"""Pydantic schemas for certificate management."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# The two ACME challenges this build can actually run. A closed set rather than a free
# string, so a typo is a 422 instead of an issuance attempt that burns a rate-limit slot.
AcmeChallenge = Literal["http-01", "dns-01"]


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
    challenge: AcmeChallenge = Field(
        default="http-01",
        description=(
            "How to prove control of the domain. http-01 needs port 80 reachable from the "
            "internet; dns-01 needs DNS provider credentials in Settings. Ignored unless "
            "type=letsencrypt."
        ),
    )
    use_staging: bool = Field(
        default=False,
        description=(
            "Issue against Let's Encrypt's staging directory. The certificate will not be "
            "trusted by browsers; it is for testing credentials without spending production "
            "rate limits. Ignored unless type=letsencrypt."
        ),
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
    # Null for anything not issued by ACME. Renewal reads these back, so the page showing
    # them is showing what the next unattended renewal will actually do.
    acme_challenge: AcmeChallenge | None = None
    acme_staging: bool = False
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
