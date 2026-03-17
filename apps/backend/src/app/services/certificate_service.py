"""Certificate management service.

Handles CRUD for TLS certificates and automated self-signed renewal.
Let's Encrypt renewal delegates to certbot (if installed) via subprocess.
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.db.models import Certificate
from app.schemas.certificate import CertificateCreate, CertificateUpdate
from app.services.credential_vault import get_vault

_logger = logging.getLogger(__name__)

_SELFSIGNED_DAYS = 90
_RSA_KEY_SIZE = 4096
_RENEWAL_THRESHOLD_DAYS = 30


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


def create_certificate(db: Session, data: CertificateCreate) -> Certificate:
    vault = get_vault()

    if data.cert_pem and data.key_pem:
        cert_pem = data.cert_pem
        key_pem_encrypted = vault.encrypt(data.key_pem)
        parsed = x509.load_pem_x509_certificate(cert_pem.encode())
        expires_at = parsed.not_valid_after_utc
    else:
        cert_pem, raw_key_pem, expires_at = generate_selfsigned(data.domain)
        key_pem_encrypted = vault.encrypt(raw_key_pem)

    cert = Certificate(
        domain=data.domain,
        type=data.type,
        cert_pem=cert_pem,
        key_pem=key_pem_encrypted,
        expires_at=expires_at,
        auto_renew=data.auto_renew,
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


def renew_certificate(db: Session, cert: Certificate) -> Certificate:
    """Renew a certificate — self-signed generates a new pair, LE calls certbot."""
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
        return cert

    if cert.type == "letsencrypt":
        try:
            tmp_root = Path("/data/tmp")
            tmp_root.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(dir=str(tmp_root)) as tmp_dir:
                cert_path = Path(tmp_dir) / "cb_cert.pem"
                key_path = Path(tmp_dir) / "cb_key.pem"

                result = subprocess.run(
                    [
                        "certbot",
                        "certonly",
                        "--standalone",
                        "--non-interactive",
                        "--agree-tos",
                        "--email",
                        "admin@localhost",
                        "-d",
                        cert.domain,
                        "--cert-path",
                        str(cert_path),
                        "--key-path",
                        str(key_path),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                if result.returncode != 0:
                    _logger.error("certbot renewal failed for %s: %s", cert.domain, result.stderr)
                    return cert

                new_cert_pem = cert_path.read_text(encoding="utf-8")
                new_key_pem = key_path.read_text(encoding="utf-8")

            parsed = x509.load_pem_x509_certificate(new_cert_pem.encode())
            cert.cert_pem = new_cert_pem
            cert.key_pem = vault.encrypt(new_key_pem)
            cert.expires_at = parsed.not_valid_after_utc
            db.commit()
            db.refresh(cert)
            _logger.info(
                "Let's Encrypt cert renewed for %s (expires %s)", cert.domain, cert.expires_at
            )
            _publish_renewal(cert)
        except FileNotFoundError:
            _logger.warning(
                "certbot not found — cannot renew Let's Encrypt cert for %s", cert.domain
            )
        except subprocess.TimeoutExpired:
            _logger.error("certbot timed out renewing %s", cert.domain)

        return cert

    return cert


def _publish_renewal(cert: Certificate) -> None:
    """Publish renewed cert to Redis for real-time consumers."""
    import asyncio

    async def _pub():
        from app.core.redis import get_redis

        r = await get_redis()
        if r is None:
            return
        import json

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
    """Check all auto_renew certs expiring within 30 days and renew them.

    Returns the count of renewed certificates.
    """
    threshold = utcnow() + timedelta(days=_RENEWAL_THRESHOLD_DAYS)
    expiring = (
        db.query(Certificate)
        .filter(
            Certificate.auto_renew.is_(True),
            Certificate.expires_at <= threshold,
        )
        .all()
    )

    renewed = 0
    for cert in expiring:
        try:
            renew_certificate(db, cert)
            renewed += 1
        except Exception as exc:
            _logger.error("Failed to renew cert for %s: %s", cert.domain, exc)

    if renewed:
        _logger.info(
            "Renewed %d certificate(s) expiring within %d days", renewed, _RENEWAL_THRESHOLD_DAYS
        )
    return renewed
