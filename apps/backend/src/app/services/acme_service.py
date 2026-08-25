"""ACME issuance and renewal.

INC-07. The previous implementation shelled out to ``certbot certonly --standalone``, which
could not work: certbot was in neither image, ``--standalone`` binds port 80 while application
processes run as breaker:1000, the account email was hardcoded to admin@localhost while
docker/.env.example advertised a CB_TLS_EMAIL nothing read, and every failure returned the
unchanged certificate.

This uses ``--webroot`` instead, which deletes the port-80 and non-root problems rather than
solving them: the shipped deployment publishes 80:8080 to a container whose nginx listens on
8080, so a CA reaching http://domain/ arrives at nginx, and certbot only has to drop a file
where nginx will serve it. DNS-01 covers installs with no public inbound, which for a homelab
inventory tool is most of them.
"""

from __future__ import annotations

import ipaddress
import logging
import os
import secrets
import subprocess
import tempfile
from datetime import datetime
from importlib import import_module
from pathlib import Path
from typing import Any

import httpx
from cryptography import x509

from app.services.certificate_service import (
    CertificateRenewalError,
    _certbot_tmp_root,
    _run_certbot,
)

_logger = logging.getLogger(__name__)

STAGING_DIRECTORY = "https://acme-staging-v02.api.letsencrypt.org/directory"

_CERTBOT_TIMEOUT_SECONDS = 300

# Suffixes no public CA will ever issue for. Refusing instantly is the difference between
# a clear answer and a mysterious timeout on the LAN installs that are most of the field.
_NON_PUBLIC_SUFFIXES = (
    ".local",
    ".internal",
    ".lan",
    ".home",
    ".arpa",
    ".test",
    ".invalid",
    ".localhost",
    ".example",
)


def data_dir() -> Path:
    return Path(os.environ.get("CB_DATA_DIR", "/data"))


def webroot() -> Path:
    return data_dir() / "acme-challenge"


def _letsencrypt_dirs() -> list[str]:
    """certbot writes to /etc/letsencrypt and /var/log/letsencrypt by default, which a
    non-root process cannot create. Everything goes under the data volume instead."""
    base = data_dir() / "letsencrypt"
    return [
        "--config-dir",
        str(base / "config"),
        "--work-dir",
        str(base / "work"),
        "--logs-dir",
        str(base / "logs"),
    ]


def _is_non_public(domain: str) -> bool:
    candidate = domain.strip().lower().rstrip(".")
    try:
        ipaddress.ip_address(candidate)
        return True
    except ValueError:
        pass
    if "." not in candidate:
        return True
    return any(candidate.endswith(suffix) for suffix in _NON_PUBLIC_SUFFIXES)


def _self_check_http01(domain: str) -> tuple[bool, str]:
    """Write a token under the webroot and fetch it through the public name.

    This is what catches the single most common webroot failure: an HTTP server block that
    301s /.well-known/acme-challenge/ to HTTPS before serving it.
    """
    challenge_dir = webroot() / ".well-known" / "acme-challenge"
    challenge_dir.mkdir(parents=True, exist_ok=True)
    token = f"cb-preflight-{secrets.token_urlsafe(16)}"
    probe = challenge_dir / token
    probe.write_text(token, encoding="utf-8")
    try:
        resp = httpx.get(
            f"http://{domain}/.well-known/acme-challenge/{token}",
            timeout=10.0,
            follow_redirects=False,
        )
        if resp.status_code != 200:
            return False, f"HTTP {resp.status_code}"
        if resp.text.strip() != token:
            return False, "served different content"
        return True, "ok"
    except httpx.HTTPError as exc:
        return False, str(exc)
    finally:
        probe.unlink(missing_ok=True)


def _dns_credentials() -> Any:
    """Seam. Returns the decrypted DNS-01 credentials, or None. Implemented in Task 8."""
    return import_module("app.services.acme_secrets").load_dns_credentials()


def _dns_argv(tmp_dir: str) -> list[str]:
    """The provider-specific certbot arguments for DNS-01. Implemented in Task 8.

    Unreachable until then: the DNS-01 preflight refuses without credentials, and there is
    no code path that stores any.
    """
    raise NotImplementedError("DNS-01 provider support has not landed yet.")


def preflight(domain: str, challenge: str = "http-01") -> None:
    """Raise CertificateRenewalError naming the specific unmet condition, or return."""
    if _is_non_public(domain):
        raise CertificateRenewalError(
            f"No public certificate authority will issue for '{domain}'. Let's Encrypt "
            "requires a publicly-resolvable domain name. Keep using a self-signed "
            "certificate for this install, or configure a public domain."
        )

    if not os.environ.get("CB_TLS_EMAIL", "").strip():
        raise CertificateRenewalError(
            "CB_TLS_EMAIL is not set. Let's Encrypt requires an account email for expiry "
            "notices; set it in your environment file and restart."
        )

    if challenge == "http-01":
        ok, detail = _self_check_http01(domain)
        if not ok:
            raise CertificateRenewalError(
                f"http://{domain}/.well-known/acme-challenge/ did not serve a file this "
                f"install just wrote ({detail}). Let's Encrypt would fail the same way. "
                "Check that port 80 reaches this host and that the HTTP server does not "
                "redirect the ACME path to HTTPS. Use --staging to test safely."
            )
    elif challenge == "dns-01":
        if not _dns_credentials():
            raise CertificateRenewalError(
                "DNS-01 needs provider credentials. Configure Cloudflare or RFC2136 "
                "credentials in Settings before requesting a certificate."
            )
    else:
        raise CertificateRenewalError(f"Unknown ACME challenge type '{challenge}'.")


def issue_acme_certificate(
    domain: str, *, challenge: str = "http-01", staging: bool = False
) -> tuple[str, str, datetime]:
    """Obtain a certificate. Returns (cert_pem, key_pem, expires_at). Never falls back."""
    preflight(domain, challenge)

    base = data_dir() / "letsencrypt" / "config" / "live" / domain
    argv = [
        "certbot",
        "certonly",
        "--non-interactive",
        "--agree-tos",
        "--email",
        os.environ["CB_TLS_EMAIL"].strip(),
        "-d",
        domain,
        *_letsencrypt_dirs(),
    ]
    if staging:
        argv += ["--server", STAGING_DIRECTORY]

    with tempfile.TemporaryDirectory(dir=str(_certbot_tmp_root())) as tmp:
        if challenge == "http-01":
            argv += ["--webroot", "--webroot-path", str(webroot())]
        else:
            argv += _dns_argv(tmp)

        try:
            result = _run_certbot(argv, timeout=_CERTBOT_TIMEOUT_SECONDS)
        except FileNotFoundError as exc:
            raise CertificateRenewalError(
                "certbot is not available in this image, so a Let's Encrypt certificate "
                "cannot be issued here."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise CertificateRenewalError(
                f"certbot timed out after {exc.timeout}s for {domain}."
            ) from exc

    if result.returncode != 0:
        raise CertificateRenewalError(
            f"certbot failed for {domain}: {(result.stderr or '').strip()[:500]}"
        )

    try:
        cert_pem = (base / "fullchain.pem").read_text(encoding="utf-8")
        key_pem = (base / "privkey.pem").read_text(encoding="utf-8")
    except OSError as exc:
        raise CertificateRenewalError(
            f"certbot reported success but its output for {domain} could not be read: {exc}"
        ) from exc

    parsed = x509.load_pem_x509_certificate(cert_pem.encode())
    _logger.info(
        "ACME certificate issued for %s via %s (expires %s)",
        domain,
        challenge,
        parsed.not_valid_after_utc,
    )
    return cert_pem, key_pem, parsed.not_valid_after_utc
