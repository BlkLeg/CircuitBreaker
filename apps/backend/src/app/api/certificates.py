"""Certificate management API.

Routes:
  GET    /api/v1/certificates           — list all certs (summary)
  POST   /api/v1/certificates           — create (auto-generate self-signed if no PEM provided)
  GET    /api/v1/certificates/{id}      — detail (includes cert_pem)
  PUT    /api/v1/certificates/{id}      — update
  DELETE /api/v1/certificates/{id}      — delete
  POST   /api/v1/certificates/{id}/renew — manual renewal trigger
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.audit import log_audit
from app.core.rbac import require_role
from app.db.models import User
from app.db.session import get_db
from app.schemas.certificate import (
    CertificateCreate,
    CertificateDetailRead,
    CertificateRead,
    CertificateUpdate,
)
from app.services import certificate_service as svc

router = APIRouter(tags=["certificates"])


@router.get("", response_model=list[CertificateRead])
def list_certificates(db: Session = Depends(get_db)):
    return svc.list_certificates(db)


@router.post("", response_model=CertificateRead)
def create_certificate(
    body: CertificateCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = require_role("admin"),
):
    cert = svc.create_certificate(db, body)
    log_audit(
        db,
        request,
        user_id=current_user.id,
        action="certificate_created",
        resource=f"certificate:{cert.id}",
        status="ok",
    )
    return cert


@router.get("/{cert_id}", response_model=CertificateDetailRead)
def get_certificate(
    cert_id: int,
    db: Session = Depends(get_db),
    _current_user: User = require_role("admin"),
):
    cert = svc.get_certificate(db, cert_id)
    if cert is None:
        raise HTTPException(status_code=404, detail="Certificate not found")
    return cert


@router.put("/{cert_id}", response_model=CertificateRead)
def update_certificate(
    cert_id: int,
    body: CertificateUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = require_role("admin"),
):
    cert = svc.update_certificate(db, cert_id, body)
    if cert is None:
        raise HTTPException(status_code=404, detail="Certificate not found")
    log_audit(
        db,
        request,
        user_id=current_user.id,
        action="certificate_updated",
        resource=f"certificate:{cert_id}",
        status="ok",
    )
    return cert


@router.delete("/{cert_id}")
def delete_certificate(
    cert_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = require_role("admin"),
):
    if not svc.delete_certificate(db, cert_id):
        raise HTTPException(status_code=404, detail="Certificate not found")
    log_audit(
        db,
        request,
        user_id=current_user.id,
        action="certificate_deleted",
        resource=f"certificate:{cert_id}",
        status="ok",
    )
    return {"detail": "deleted"}


@router.post("/{cert_id}/renew", response_model=CertificateRead)
def renew_certificate(
    cert_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = require_role("admin"),
):
    cert = svc.get_certificate(db, cert_id)
    if cert is None:
        raise HTTPException(status_code=404, detail="Certificate not found")
    renewed = svc.renew_certificate(db, cert)
    log_audit(
        db,
        request,
        user_id=current_user.id,
        action="certificate_renewed",
        resource=f"certificate:{cert_id}",
        status="ok",
    )
    return renewed
