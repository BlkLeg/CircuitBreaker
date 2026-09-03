"""Certificate management service.

Handles CRUD for TLS certificates and automated self-signed renewal.
Let's Encrypt renewal delegates to certbot (if installed) via subprocess.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import tempfile
from datetime import UTC, datetime, timedelta
from importlib import import_module
from pathlib import Path
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from sqlalchemy.orm import Session

from app.core.audit import log_audit
from app.core.nats_client import nats_client
from app.core.time import utcnow
from app.db.models import Certificate
from app.schemas.certificate import CertificateCreate, CertificateUpdate
from app.services.credential_vault import get_vault

_logger = logging.getLogger(__name__)

_SELFSIGNED_DAYS = 90
_RSA_KEY_SIZE = 4096
_RENEWAL_THRESHOLD_DAYS = 30
_CERTBOT_TIMEOUT_SECONDS = 120


class CertificateRenewalError(RuntimeError):
    """A renewal did not happen. The message is shown to the operator verbatim."""


class CertificateCreationError(ValueError):
    """A certificate could not be created. Shown to the operator verbatim."""


def _run_certbot(
    argv: list[str], timeout: int = _CERTBOT_TIMEOUT_SECONDS
) -> subprocess.CompletedProcess[str]:
    """The single seam where this codebase meets certbot. Tests replace this."""
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)


def _certbot_tmp_root() -> Path:
    """Scratch space for certbot's output.

    The container root filesystem is read-only, so this lives under $CB_DATA_DIR rather than
    the system temp dir. Where that is not writable we fall back instead of turning a renewal
    into an unrelated OSError.
    """
    root = Path(os.environ.get("CB_DATA_DIR", "/data")) / "tmp"
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError:
        return Path(tempfile.gettempdir())
    return root


def generate_selfsigned(domain: str) -> tuple[str, str, datetime]:
    """Generate a self-signed RSA cert/key pair.

    Returns (cert_pem, key_pem, expires_at).
    """
    key = rsa.generate_private_key(public_exponent=65537, key_size=_RSA_KEY_SIZE)
    now = datetime.now(UTC)
    expires = now + timedelta(days=_SELFSIGNED_DAYS)

    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, domain),
        ]
    )

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(expires)
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(domain)]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )

    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode()
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ).decode()

    return cert_pem, key_pem, expires


def list_certificates(db: Session) -> list[Certificate]:
    return db.query(Certificate).order_by(Certificate.domain).all()


def get_certificate(db: Session, cert_id: int) -> Certificate | None:
    return db.get(Certificate, cert_id)


def _acme_issuer() -> Any:
    """Resolve ACME issuance at call time (INC-07).

    A module-level ``issue_acme_certificate`` wins when one is bound; otherwise
    ``services/acme_service`` is imported dynamically and its ImportError surfaces. There is
    deliberately no stub and no fallback: a fallback is how "silently self-sign instead" gets
    reintroduced.
    """
    override = globals().get("issue_acme_certificate")
    if override is not None:
        return override
    return import_module("app.services.acme_service").issue_acme_certificate


def create_certificate(db: Session, data: CertificateCreate) -> Certificate:
    """Create the type that was asked for, or refuse.

    The decision is ``data.type`` and never "was a PEM pasted". Branching on the pasted PEM
    is what stored a generated self-signed certificate under ``type="letsencrypt"``, which the
    page then rendered as a CA-issued certificate.
    """
    vault = get_vault()

    if data.type == "imported":
        if not (data.cert_pem and data.key_pem):
            raise CertificateCreationError(
                "An imported certificate needs both cert_pem and key_pem."
            )
        cert_pem = data.cert_pem
        key_pem_encrypted = vault.encrypt(data.key_pem)
        try:
            parsed = x509.load_pem_x509_certificate(cert_pem.encode())
        except ValueError as exc:
            raise CertificateCreationError(
                f"cert_pem is not a readable PEM certificate: {exc}"
            ) from exc
        expires_at = parsed.not_valid_after_utc

    elif data.type == "letsencrypt":
        # Raises rather than falling back. Storing a self-signed certificate under this
        # type is the defect this branch exists to prevent.
        cert_pem, raw_key_pem, expires_at = _acme_issuer()(
            data.domain, challenge=data.challenge, staging=data.use_staging
        )
        key_pem_encrypted = vault.encrypt(raw_key_pem)

    else:  # selfsigned
        cert_pem, raw_key_pem, expires_at = generate_selfsigned(data.domain)
        key_pem_encrypted = vault.encrypt(raw_key_pem)

    cert = Certificate(
        domain=data.domain,
        type=data.type,
        cert_pem=cert_pem,
        key_pem=key_pem_encrypted,
        expires_at=expires_at,
        auto_renew=data.auto_renew,
        # Recorded only for the type they describe: renewal reads them back, and a
        # self-signed row carrying "http-01" would claim an issuance path it never used.
        acme_challenge=data.challenge if data.type == "letsencrypt" else None,
        acme_staging=data.use_staging if data.type == "letsencrypt" else False,
    )
    db.add(cert)
    db.commit()
    db.refresh(cert)
    return cert


def update_certificate(db: Session, cert_id: int, data: CertificateUpdate) -> Certificate | None:
    cert = db.get(Certificate, cert_id)
    if cert is None:
        return None

    vault = get_vault()

    if data.auto_renew is not None:
        cert.auto_renew = data.auto_renew
    if data.cert_pem is not None:
        cert.cert_pem = data.cert_pem
        parsed = x509.load_pem_x509_certificate(data.cert_pem.encode())
        cert.expires_at = parsed.not_valid_after_utc
    if data.key_pem is not None:
        cert.key_pem = vault.encrypt(data.key_pem)

    db.commit()
    db.refresh(cert)
    return cert


def delete_certificate(db: Session, cert_id: int) -> bool:
    cert = db.get(Certificate, cert_id)
    if cert is None:
        return False
    db.delete(cert)
    db.commit()
    return True


def _activate_if_served(db: Session, cert: Certificate) -> None:
    """Re-write the TLS directory when *cert* is the one this install serves.

    Guarded on ``is_active`` in both directions. A renewed certificate that is not
    activated sits in the database while nginx keeps presenting the expired bytes — the
    row says renewed and the browser says expired. Activating one that was *not* active
    would change what the server presents without anyone asking for it.

    A failure here does not undo the renewal. Written-but-not-served is a real state, and
    losing the renewal on top of it would make the next attempt re-issue a certificate the
    CA has already handed out — straight into a rate limit.
    """
    if not cert.is_active:
        return
    from app.services.certificate_activation import ActivationBlocked, activate_certificate

    try:
        result = activate_certificate(db, cert)
        if not result.reloaded:
            _logger.warning("Renewed %s but TLS did not reload: %s", cert.domain, result.detail)
    except ActivationBlocked as exc:
        # A self-signed renewal generates a fresh keypair, so a fresh pin.
        # Serving it underneath agents that are still pinned to the old one
        # breaks every dial path they have, including the update channel that
        # would otherwise carry a fix — so the renewed bytes stay in the
        # database and nginx keeps presenting the expiring certificate. That
        # is recoverable (rotate, then activate); the alternative is not.
        _logger.error(
            "[certificate_service] Renewed %s but did not activate it: %s",
            cert.domain,
            exc.reason,
        )
        log_audit(
            db,
            None,
            user_id=None,
            action="certificate_activation_blocked",
            resource=f"certificate:{cert.id}",
            status="fail",
            details=f"domain={cert.domain} reason={exc.reason}",
            severity="error",
        )
    except Exception as exc:  # noqa: BLE001 — the renewal succeeded; say so and keep it
        _logger.error(
            "Renewed %s but could not write it to the TLS directory: %s", cert.domain, exc
        )


def renew_certificate(db: Session, cert: Certificate) -> Certificate:
    """Renew a certificate — self-signed generates a new pair, Let's Encrypt re-issues.

    Both paths raise rather than returning the unchanged certificate: reporting a renewal
    that did not happen as a 200 with the old expiry is what made INC-07 dangerous rather
    than merely incomplete.
    """
    vault = get_vault()

    if cert.type == "selfsigned":
        cert_pem, raw_key_pem, expires_at = generate_selfsigned(cert.domain)
        cert.cert_pem = cert_pem
        cert.key_pem = vault.encrypt(raw_key_pem)
        cert.expires_at = expires_at
        db.commit()
        db.refresh(cert)
        _logger.info("Self-signed cert renewed for %s (expires %s)", cert.domain, expires_at)
        _publish_renewal(cert)
        _activate_if_served(db, cert)
        return cert

    if cert.type == "letsencrypt":
        # The same call issuance makes. Renewal *is* issuance to a CA — there is no
        # separate operation — and the code this replaced was a second, older invocation
        # that could not work: `--standalone` binds port 80 as a process that runs as
        # breaker:1000, and the account email was the hardcoded admin@localhost that
        # INC-07 recorded as its third cause. Keeping two invocations would have left the
        # working path reachable only from creation.
        cert_pem, raw_key_pem, expires_at = _acme_issuer()(
            cert.domain,
            # NULL on rows written before the column existed; the default lives here
            # rather than in the schema so those rows read as "not recorded".
            challenge=cert.acme_challenge or "http-01",
            staging=bool(cert.acme_staging),
        )
        cert.cert_pem = cert_pem
        cert.key_pem = vault.encrypt(raw_key_pem)
        cert.expires_at = expires_at
        db.commit()
        db.refresh(cert)
        _logger.info("Let's Encrypt cert renewed for %s (expires %s)", cert.domain, cert.expires_at)
        _publish_renewal(cert)
        _activate_if_served(db, cert)
        return cert

    # An imported certificate has no renewal path: the operator holds the private key and
    # whatever issued it. Returning it unchanged is honest here in a way it never was for
    # the two types above, which is why it is not an error.
    return cert


def _publish_renewal(cert: Certificate) -> None:
    """Publish renewed cert to Redis for real-time consumers."""

    async def _pub() -> None:
        from app.core.redis import get_redis

        r = await get_redis()
        if r is None:
            return
        await r.publish(
            f"cert:{cert.domain}",
            json.dumps({"domain": cert.domain, "expires_at": cert.expires_at.isoformat()}),
        )

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_pub())
    except RuntimeError:
        pass


def check_and_renew_expiring(db: Session) -> int:
    """Check all certs for expiration. Renew if auto_renew=True, else alert.

    Returns the count of renewed certificates.
    """
    now = utcnow()
    threshold = now + timedelta(days=_RENEWAL_THRESHOLD_DAYS)

    # 1. Automated Renewals (auto_renew=True)
    expiring_auto = (
        db.query(Certificate)
        .filter(
            Certificate.auto_renew.is_(True),
            Certificate.expires_at <= threshold,
        )
        .all()
    )

    renewed = 0
    for cert in expiring_auto:
        try:
            renew_certificate(db, cert)
            renewed += 1
            log_audit(
                db,
                None,
                user_id=None,
                action="certificate_auto_renewed",
                resource=f"certificate:{cert.id}",
                details=f"domain={cert.domain} status=ok",
            )
        except Exception as exc:
            _logger.error("Failed to auto-renew cert for %s: %s", cert.domain, exc)
            log_audit(
                db,
                None,
                user_id=None,
                action="certificate_auto_renew_failed",
                resource=f"certificate:{cert.id}",
                status="fail",
                details=f"domain={cert.domain} error={exc}",
                severity="error",
            )

    # 2. Expiration Alerts (for all certs near expiry)
    all_expiring = db.query(Certificate).filter(Certificate.expires_at <= threshold).all()

    for cert in all_expiring:
        days_left = (cert.expires_at - now).days
        # Only alert on specific milestones to avoid daily spam
        if days_left in (30, 14, 7, 3, 1, 0):
            severity = "critical" if days_left <= 3 else "warning"
            msg = (
                f"Certificate for {cert.domain} expires in {days_left} days "
                f"({cert.expires_at.date()})."
            )
            if cert.auto_renew and days_left > 0:
                msg += " Automated renewal will be attempted."

            _publish_alert(cert, severity, msg)

    if renewed:
        _logger.info(
            "Renewed %d certificate(s) expiring within %d days", renewed, _RENEWAL_THRESHOLD_DAYS
        )
    return renewed


def _publish_alert(cert: Certificate, severity: str, message: str) -> None:
    """Publish an alert to NATS for the notification worker."""
    payload = {
        "title": "Certificate Expiration Warning",
        "message": message,
        "severity": severity,
        "domain": cert.domain,
        "expires_at": cert.expires_at.isoformat(),
        "certificate_id": cert.id,
    }

    async def _pub() -> None:
        await nats_client.js_publish(f"alert.certificate.expiring.{cert.id}", payload)

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_pub())
    except RuntimeError:
        # Fallback for sync contexts if no loop is running
        try:
            asyncio.run(_pub())
        except Exception:
            pass
