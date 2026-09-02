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
    force: bool = False,
) -> Any:
    """Make this certificate the one the install serves.

    A reload that did not happen is audited as "partial" and returned as `reloaded: false`,
    not raised: the files are on disk either way and the operator needs both facts.

    Slice 4.1: refused with 409 while any active agent has not confirmed the
    advertised successor TLS policy. An agent's `tls_pin` is loaded once from
    agent.toml and never rewritten, and it gates all four of its dial paths
    including the update download — so activating underneath an unconverged
    agent strands it with no way to push it a fix. `force=true` overrides,
    and audits the agents it is about to strand: the override exists so the
    operator can make that trade deliberately, not so the gate can be
    forgotten.
    """
    cert = svc.get_certificate(db, cert_id)
    if cert is None:
        raise HTTPException(status_code=404, detail="Certificate not found")

    from app.services import agent_tls_pin, certificate_activation

    rotation = agent_tls_pin.load_tls_pin_rotation_state(db)
    _, unconverged = agent_tls_pin.convergence_counts(db, rotation)
    if unconverged and not force:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{unconverged} active agent(s) have not confirmed the successor TLS "
                "policy and would be stranded by this activation. Check "
                "GET /api/v1/agents/tls-pin/pending, or re-send with force=true to "
                "activate anyway."
            ),
        )

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
    if unconverged and force:
        # Audited separately from the activation itself: this is the record
        # that someone knowingly stranded agents, and it must be findable
        # without reading every activation entry.
        log_audit(
            db,
            request,
            user_id=current_user.id,
            action="certificate_activated_forced",
            resource=f"certificate:{cert_id}",
            status="ok",
            details=(
                f"Activated with {unconverged} unconverged agent(s); "
                "they will be unable to reconnect until reinstalled."
            ),
        )
    if rotation.rotation_active:
        # The advertised successor is now the certificate being served, so
        # the advertisement has done its job. Leaving it running would keep
        # resending a rotation frame for a policy that is no longer the
        # successor but the current one.
        agent_tls_pin.complete_tls_pin_rotation(db)
    return {
        "certificate": cert,
        "written": result.written,
        "reloaded": result.reloaded,
        "detail": result.detail,
    }
