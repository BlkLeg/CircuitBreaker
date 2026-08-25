"""Write the active certificate to disk and reload the TLS server.

INC-22. `nginx.mono.conf:81-82` serves $CB_DATA_DIR/tls/{fullchain,privkey}.pem. Those files
were written once by `docker/entrypoint-mono.sh` at first boot, only when absent, and never
again. `certificate_service.py` never wrote there at all — so creating, importing, renewing
or auto-renewing a certificate changed a database row and nothing else.

The reload is part of activation rather than a step an operator can forget: a certificate
written and not reloaded is the old certificate still being served.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from app.db.models import Certificate

_logger = logging.getLogger(__name__)

_CHAIN_NAME = "fullchain.pem"
_KEY_NAME = "privkey.pem"


@dataclass
class ActivationResult:
    written: bool
    reloaded: bool
    detail: str


def tls_dir() -> Path:
    return Path(os.environ.get("CB_DATA_DIR", "/data")) / "tls"


def _decrypt_key(key_pem: str) -> str:
    """Seam. `Certificate.key_pem` is vault-encrypted (certificate_service.py:90)."""
    from app.services.credential_vault import get_vault

    return get_vault().decrypt(key_pem)


def _write_atomic(path: Path, content: str, mode: int) -> None:
    """Write via a temp file in the same directory, then os.replace.

    A partial write here is a TLS server that will not start. os.replace is atomic within a
    filesystem, so a crash mid-write leaves the previous file untouched.
    """
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def _supervisorctl_available() -> bool:
    return shutil.which("supervisorctl") is not None


def _helper_available() -> bool:
    from app.services.helper_client import helper_installed

    return helper_installed()


def _reload_tls() -> tuple[bool, str]:
    """Reload whatever is terminating TLS, if anything here can.

    Mono: nginx runs under supervisord as `breaker` (supervisord.mono.conf) and so does this
    process, so signalling it needs no privilege. Native: cb_helperd already reloads nginx.
    Plain image: no nginx — the operator's own proxy reads the files we just wrote.
    """
    if _supervisorctl_available():
        result = subprocess.run(
            ["supervisorctl", "signal", "HUP", "nginx"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return True, "nginx reloaded via supervisorctl"
        return False, f"supervisorctl could not reload nginx: {result.stderr.strip()[:200]}"

    if _helper_available():
        from app.services.helper_client import call_helper

        try:
            call_helper("reload_nginx", {})
        except Exception as exc:  # noqa: BLE001 — reported, not raised: the write succeeded
            return False, f"host helper could not reload nginx: {exc}"
        return True, "nginx reloaded via cb-helperd"

    return False, (
        "Certificate written, but no TLS server was found to reload. This build serves the "
        "API directly and expects your own proxy in front of it — point it at "
        f"{tls_dir()} and reload it yourself."
    )


def activate_certificate(db: Session, cert: Certificate) -> ActivationResult:
    """Make *cert* the certificate this install serves.

    Raises if the key cannot be decrypted or the files cannot be written. A reload failure
    is reported in the result rather than raised: the bytes are on disk and the operator
    needs to know both facts separately.
    """
    key_plaintext = _decrypt_key(cert.key_pem)

    directory = tls_dir()
    directory.mkdir(parents=True, exist_ok=True)
    _write_atomic(directory / _CHAIN_NAME, cert.cert_pem, 0o644)
    _write_atomic(directory / _KEY_NAME, key_plaintext, 0o600)

    db.query(Certificate).filter(Certificate.is_active, Certificate.id != cert.id).update(
        {"is_active": False}, synchronize_session="fetch"
    )
    cert.is_active = True
    db.commit()
    db.refresh(cert)

    reloaded, detail = _reload_tls()
    _logger.info("Certificate for %s activated (reloaded=%s): %s", cert.domain, reloaded, detail)
    return ActivationResult(written=True, reloaded=reloaded, detail=detail)
