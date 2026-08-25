"""Certificate management API.

Routes:
  GET    /api/v1/certificates           — list all certs (summary)
  POST   /api/v1/certificates           — create (selfsigned | letsencrypt | imported)
  GET    /api/v1/certificates/{id}      — detail (includes cert_pem)
  PUT    /api/v1/certificates/{id}      — update
  DELETE /api/v1/certificates/{id}      — delete
  POST   /api/v1/certificates/{id}/renew — manual renewal trigger
  POST   /api/v1/certificates/{id}/activate — write it to $CB_DATA_DIR/tls and reload TLS
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.audit import log_audit
from app.core.rbac import require_role
from app.db.models import User
from app.db.session import get_db
from app.schemas.certificate import (
    CertificateActivateResponse,
    CertificateCreate,
    CertificateDetailRead,
    CertificateRead,
    CertificateUpdate,
)
from app.services import certificate_service as svc

router = APIRouter(tags=["certificates"])


@router.get("", response_model=list[CertificateRead])
def list_certificates(
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, require_role("admin")],
) -> list[Any]:
    return svc.list_certificates(db)


@router.post("", response_model=CertificateRead)
def create_certificate(
    body: CertificateCreate,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, require_role("admin")],
) -> Any:
    try:
        cert = svc.create_certificate(db, body)
    except svc.CertificateCreationError as exc:
        # 422: the request asked for something this payload cannot produce — an imported
        # certificate with no PEM, or a PEM that will not parse.
        log_audit(
            db,
            request,
            user_id=current_user.id,
            action="certificate_created",
            resource=f"certificate:{body.domain}",
            status="error",
            details=str(exc),
        )
        db.commit()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except svc.CertificateRenewalError as exc:
        # Let's Encrypt issuance refused. 502 for the same reason renewal does: the failure
        # is upstream, and no row is written for a certificate that was never issued.
        log_audit(
            db,
            request,
            user_id=current_user.id,
            action="certificate_created",
            resource=f"certificate:{body.domain}",
            status="error",
            details=str(exc),
        )
        db.commit()
        raise HTTPException(status_code=502, detail=str(exc)) from exc

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
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, require_role("admin")],
) -> Any:
    cert = svc.get_certificate(db, cert_id)
    if cert is None:
        raise HTTPException(status_code=404, detail="Certificate not found")
    return cert


@router.put("/{cert_id}", response_model=CertificateRead)
def update_certificate(
    cert_id: int,
    body: CertificateUpdate,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, require_role("admin")],
) -> Any:
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
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, require_role("admin")],
) -> dict[str, str]:
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
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, require_role("admin")],
) -> Any:
    cert = svc.get_certificate(db, cert_id)
    if cert is None:
        raise HTTPException(status_code=404, detail="Certificate not found")
    try:
        renewed = svc.renew_certificate(db, cert)
    except svc.CertificateRenewalError as exc:
        # The audit entry used to say "ok" unconditionally, recording renewals that never
        # happened. 502 rather than 500: the failure is in an upstream certificate authority
        # or a missing external tool, not in this application.
        log_audit(
            db,
            request,
            user_id=current_user.id,
            action="certificate_renewed",
            resource=f"certificate:{cert_id}",
            status="error",
            details=str(exc),
        )
        db.commit()
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    log_audit(
        db,
        request,
        user_id=current_user.id,
        action="certificate_renewed",
        resource=f"certificate:{cert_id}",
        status="ok",
    )
    return renewed


@router.post("/{cert_id}/activate", response_model=CertificateActivateResponse)
def activate_certificate_route(
    cert_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, require_role("admin")],
) -> Any:
    """Make this certificate the one the install serves.

    A reload that did not happen is audited as "partial" and returned as `reloaded: false`,
    not raised: the files are on disk either way and the operator needs both facts.
    """
    cert = svc.get_certificate(db, cert_id)
    if cert is None:
        raise HTTPException(status_code=404, detail="Certificate not found")

    from app.services import certificate_activation

    result = certificate_activation.activate_certificate(db, cert)
    log_audit(
        db,
        request,
        user_id=current_user.id,
        action="certificate_activated",
        resource=f"certificate:{cert_id}",
        status="ok" if result.reloaded else "partial",
        details=result.detail,
    )
    return {
        "certificate": cert,
        "written": result.written,
        "reloaded": result.reloaded,
        "detail": result.detail,
    }
