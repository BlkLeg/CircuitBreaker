"""Write the active certificate to disk and reload the TLS server.

INC-22. `nginx.mono.conf:81-82` serves $CB_DATA_DIR/tls/{fullchain,privkey}.pem. Those files
were written once by `docker/entrypoint-mono.sh` at first boot, only when absent, and never
again. `certificate_service.py` never wrote there at all — so creating, importing, renewing
or auto-renewing a certificate changed a database row and nothing else.

The reload is part of activation rather than a step an operator can forget: a certificate
written and not reloaded is the old certificate still being served. In the mono image that
means SIGHUP straight to nginx's master pid — see `_reload_tls` for why going through
supervisorctl could never work there.
"""

from __future__ import annotations

import logging
import os
import signal
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from app.db.models import Certificate

_logger = logging.getLogger(__name__)

_CHAIN_NAME = "fullchain.pem"
_KEY_NAME = "privkey.pem"

# nginx.mono.conf:5 — `pid /tmp/nginx.pid;`. The container root filesystem is read-only,
# so the pidfile lives on the /tmp tmpfs, and nginx's master writes it as `breaker`.
_DEFAULT_NGINX_PID_FILE = "/tmp/nginx.pid"


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


def _nginx_pid_file() -> Path:
    return Path(os.environ.get("CB_NGINX_PID_FILE", _DEFAULT_NGINX_PID_FILE))


def _nginx_pid() -> int | None:
    """The pid of the local nginx master, or None if this build is not running one.

    Absent pidfile, unreadable pidfile and garbage contents are all the same answer —
    "there is no nginx here I can address" — and each falls through to the next branch
    rather than being reported as a failed reload.
    """
    try:
        raw = _nginx_pid_file().read_text(encoding="utf-8").strip()
    except OSError:
        return None
    try:
        pid = int(raw)
    except ValueError:
        return None
    return pid if pid > 0 else None


def _helper_available() -> bool:
    from app.services.helper_client import helper_installed

    return helper_installed()


def _reload_tls() -> tuple[bool, str]:
    """Reload whatever is terminating TLS, if anything here can.

    Mono: signal nginx's master directly. It runs as `breaker` (supervisord.mono.conf
    `[program:nginx]`) and so does this process (`[program:backend-api]`), so a plain
    SIGHUP needs no privilege. What does NOT work — and what this replaced — is
    `supervisorctl signal HUP nginx`: supervisorctl speaks to supervisord's control
    socket, not to nginx, and that socket is root-owned `chmod=0700` with supervisord
    itself running as root. A breaker-uid caller gets EACCES on every invocation, so
    activation reported reloaded=false forever and kept serving the old certificate.
    Native: cb_helperd already reloads nginx.
    Plain image: no nginx — the operator's own proxy reads the files we just wrote.
    """
    pid = _nginx_pid()
    if pid is not None:
        try:
            os.kill(pid, signal.SIGHUP)
        except ProcessLookupError:
            return False, (
                f"nginx pid {pid} is not running (stale pidfile at {_nginx_pid_file()}); "
                "the certificate is on disk but nothing was reloaded"
            )
        except PermissionError:
            return False, (
                f"not permitted to signal nginx (pid {pid}); the certificate is on disk "
                "but nothing was reloaded"
            )
        except OSError as exc:
            return False, f"could not signal nginx (pid {pid}): {exc}"
        return True, f"nginx reloaded (SIGHUP to pid {pid})"

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
