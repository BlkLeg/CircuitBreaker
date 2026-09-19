"""Normalized install/runtime diagnostics for operators.

Builds bounded, redacted check dicts matching
``specs/install/diagnostic-result.schema.json``. Application dependency
verdicts come from ``app.core.health``; worker heartbeats, storage, and
install identity are local filesystem checks that never dump secrets.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import time
from pathlib import Path
from typing import Literal, TypedDict

from app.core.constants import (
    DIAGNOSTIC_EVIDENCE_MAX_CHARS,
    DIAGNOSTIC_STORAGE_FREE_WARN_BYTES,
    DIAGNOSTIC_WORKER_HEARTBEAT_STALE_SECONDS,
)
from app.core.install_identity import (
    InstallIdentityError,
    load_install_identity,
    repair_hint_for_mode,
)

_logger = logging.getLogger(__name__)

DiagnosticStatus = Literal["pass", "warn", "fail", "unknown", "skipped"]
DiagnosticSeverity = Literal["info", "warning", "error", "critical"]

#: Workers that write ``<name>.healthy`` heartbeat files under the data dir.
EXPECTED_WORKER_HEARTBEATS: frozenset[str] = frozenset(
    {
        "worker-discovery",
        "worker-notification",
        "worker-monitor-scheduler",
        "worker-monitor-poll",
        "worker-monitor-probe-dispatch",
    }
)

#: Env vars whose values must never appear in evidence, even mid-string.
_SECRET_ENV_KEYS: tuple[str, ...] = (
    "CB_VAULT_KEY",
    "CB_JWT_SECRET",
    "CB_JWT_SECRET_KEY",
    "CB_DB_PASSWORD",
    "SECRET_KEY",
)

#: Lines matching these patterns are replaced wholesale with ``[REDACTED]``.
_SECRET_LINE_RE = re.compile(r"(?i).*(?:password\s*=|token\s*=|CB_VAULT|CB_JWT|\bSECRET\b).*")

#: Connection strings with embedded credentials.
_URI_SECRET_RE = re.compile(r"(?i)(postgresql|mysql|redis|nats)://([^:/@]+):([^@/\s]+)@")


class DiagnosticCheck(TypedDict):
    """One normalized diagnostic result."""

    component: str
    check: str
    status: DiagnosticStatus
    severity: DiagnosticSeverity
    evidence: str
    remediation: str
    safe_to_retry: bool


def resolve_data_dir(data_dir: Path | str | None = None) -> Path:
    """Resolve the data directory used for heartbeats and free-space checks."""
    if data_dir is not None:
        return Path(data_dir).expanduser()
    raw = (os.environ.get("CB_DATA_DIR") or "").strip()
    return Path(raw).expanduser() if raw else Path("/data")


def bound_evidence(text: str) -> str:
    """Redact secret-bearing lines, scrub known env secret values, and cap length."""
    if not text:
        return ""

    redacted_lines: list[str] = []
    for line in text.splitlines():
        if _SECRET_LINE_RE.search(line):
            redacted_lines.append("[REDACTED]")
        else:
            redacted_lines.append(_URI_SECRET_RE.sub(r"\1://\2:[REDACTED]@", line))
    out = "\n".join(redacted_lines) if redacted_lines else text

    for env_key in _SECRET_ENV_KEYS:
        value = os.environ.get(env_key)
        if value and len(value) >= 4 and value in out:
            out = out.replace(value, "[REDACTED]")

    if len(out) > DIAGNOSTIC_EVIDENCE_MAX_CHARS:
        out = out[: DIAGNOSTIC_EVIDENCE_MAX_CHARS - 1] + "…"
    return out


def _check(
    *,
    component: str,
    check: str,
    status: DiagnosticStatus,
    severity: DiagnosticSeverity,
    evidence: str,
    remediation: str,
    safe_to_retry: bool,
) -> DiagnosticCheck:
    return {
        "component": component,
        "check": check,
        "status": status,
        "severity": severity,
        "evidence": bound_evidence(evidence),
        "remediation": remediation,
        "safe_to_retry": safe_to_retry,
    }


def _dependency_checks(dep_status: dict[str, str]) -> list[DiagnosticCheck]:
    """Map health probe verdicts onto postgres/redis diagnostic checks."""
    checks: list[DiagnosticCheck] = []

    db = dep_status.get("db", "error")
    if db == "ok":
        checks.append(
            _check(
                component="postgres",
                check="ready",
                status="pass",
                severity="info",
                evidence="database probe returned ok (connectivity and schema readiness)",
                remediation="",
                safe_to_retry=True,
            )
        )
    else:
        checks.append(
            _check(
                component="postgres",
                check="ready",
                status="fail",
                severity="critical",
                evidence=f"database probe returned {db!r}",
                remediation=(
                    "Verify PostgreSQL is running and CB_DB_URL credentials are correct, "
                    "then run: cb doctor"
                ),
                safe_to_retry=True,
            )
        )

    redis = dep_status.get("redis", "error")
    if redis == "ok":
        checks.append(
            _check(
                component="redis",
                check="ready",
                status="pass",
                severity="info",
                evidence="redis probe returned ok",
                remediation="",
                safe_to_retry=True,
            )
        )
    else:
        checks.append(
            _check(
                component="redis",
                check="ready",
                status="warn",
                severity="warning",
                evidence=f"redis probe returned {redis!r}",
                remediation=(
                    "Redis is optional for inventory but required for shared rate limits "
                    "and pub/sub. Restart Redis or check CB_REDIS_URL, then retry."
                ),
                safe_to_retry=True,
            )
        )

    return checks


def _parse_heartbeat_epoch(path: Path) -> float | None:
    """Read an epoch timestamp from a ``*.healthy`` file, or None if unreadable."""
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        _logger.warning("[diagnostics] cannot read heartbeat %s: %s", path, exc)
        return None
    try:
        return float(raw)
    except ValueError:
        _logger.warning("[diagnostics] non-numeric heartbeat in %s", path)
        return None


def _worker_heartbeat_checks(
    data_dir: Path,
    *,
    install_mode: str | None = None,
) -> list[DiagnosticCheck]:
    """Check expected worker heartbeat files.

    Workers currently write under ``/data/*.healthy`` (mono layout). Native and
    package installs often have no such files under ``CB_DATA_DIR``, so missing
    heartbeats are ``skipped`` outside mono unless files are present.
    """
    search_dirs: list[Path] = [data_dir]
    mono_dir = Path("/data")
    if mono_dir.resolve() != data_dir.resolve() and mono_dir.is_dir():
        search_dirs.append(mono_dir)

    found: dict[str, Path] = {}
    list_errors: list[str] = []
    for directory in search_dirs:
        try:
            for path in directory.glob("*.healthy"):
                if path.is_file() and path.stem not in found:
                    found[path.stem] = path
        except OSError as exc:
            list_errors.append(f"{directory}: {exc}")

    if list_errors and not found:
        return [
            _check(
                component="workers",
                check="heartbeat",
                status="unknown",
                severity="warning",
                evidence="; ".join(list_errors),
                remediation="Ensure CB_DATA_DIR is mounted and readable by the API process.",
                safe_to_retry=True,
            )
        ]

    # Outside mono, absence of heartbeat files is expected when workers have not
    # yet written under CB_DATA_DIR (and no legacy /data files exist).
    if not found and install_mode not in {None, "mono"}:
        return [
            _check(
                component="workers",
                check="heartbeat",
                status="skipped",
                severity="info",
                evidence=(f"no *.healthy files under {data_dir} or /data (mode={install_mode})"),
                remediation="",
                safe_to_retry=True,
            )
        ]

    checks: list[DiagnosticCheck] = []
    now = time.time()
    for worker_name in sorted(EXPECTED_WORKER_HEARTBEATS):
        heartbeat_path = found.get(worker_name)
        if heartbeat_path is None:
            checks.append(
                _check(
                    component="workers",
                    check="heartbeat",
                    status="fail",
                    severity="error",
                    evidence=f"{worker_name}.healthy missing under {data_dir}",
                    remediation=(
                        f"Restart the {worker_name} worker (cb restart) and confirm supervisord "
                        "is running the worker programs."
                    ),
                    safe_to_retry=True,
                )
            )
            continue

        epoch = _parse_heartbeat_epoch(heartbeat_path)
        if epoch is None:
            checks.append(
                _check(
                    component="workers",
                    check="heartbeat",
                    status="fail",
                    severity="error",
                    evidence=(f"{heartbeat_path.name} exists but has no readable epoch timestamp"),
                    remediation=(
                        f"Restart {worker_name}; the worker should rewrite its heartbeat file."
                    ),
                    safe_to_retry=True,
                )
            )
            continue

        age_s = max(0.0, now - epoch)
        if age_s > DIAGNOSTIC_WORKER_HEARTBEAT_STALE_SECONDS:
            checks.append(
                _check(
                    component="workers",
                    check="heartbeat",
                    status="warn",
                    severity="warning",
                    evidence=(
                        f"{heartbeat_path.name} age={age_s:.0f}s "
                        f"(stale threshold={DIAGNOSTIC_WORKER_HEARTBEAT_STALE_SECONDS}s)"
                    ),
                    remediation=(f"Worker {worker_name} may be stuck — check logs and restart it."),
                    safe_to_retry=True,
                )
            )
        else:
            checks.append(
                _check(
                    component="workers",
                    check="heartbeat",
                    status="pass",
                    severity="info",
                    evidence=f"{heartbeat_path.name} age={age_s:.0f}s",
                    remediation="",
                    safe_to_retry=True,
                )
            )

    return checks


def _storage_free_space_check(data_dir: Path) -> DiagnosticCheck:
    """Warn when free space on the data volume falls below 1 GiB."""
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        usage = shutil.disk_usage(data_dir)
    except OSError as exc:
        _logger.warning("[diagnostics] disk_usage failed for %s: %s", data_dir, exc)
        return _check(
            component="storage",
            check="free_space",
            status="unknown",
            severity="warning",
            evidence=f"cannot measure free space on {data_dir}: {exc}",
            remediation="Ensure CB_DATA_DIR exists and is accessible.",
            safe_to_retry=True,
        )

    free = usage.free
    evidence = (
        f"path={data_dir} free_bytes={free} "
        f"total_bytes={usage.total} warn_below={DIAGNOSTIC_STORAGE_FREE_WARN_BYTES}"
    )
    if free < DIAGNOSTIC_STORAGE_FREE_WARN_BYTES:
        return _check(
            component="storage",
            check="free_space",
            status="warn",
            severity="warning",
            evidence=evidence,
            remediation=(
                "Under 1 GiB free on the data volume — prune old backups "
                "(cb snapshots) or grow the volume."
            ),
            safe_to_retry=True,
        )
    return _check(
        component="storage",
        check="free_space",
        status="pass",
        severity="info",
        evidence=evidence,
        remediation="",
        safe_to_retry=True,
    )


def _identity_check(
    *,
    data_dir: Path,
    home: Path | None,
) -> DiagnosticCheck:
    """Validate install identity presence and schema."""
    try:
        identity = load_install_identity(data_dir=data_dir, home=home)
    except InstallIdentityError as exc:
        return _check(
            component="identity",
            check="valid",
            status="fail",
            severity="error",
            evidence=str(exc),
            remediation=repair_hint_for_mode(None),
            safe_to_retry=True,
        )

    mode = str(identity.get("mode") or "")
    version = str(identity.get("version") or "")
    path = str(identity.get("_path") or "")
    return _check(
        component="identity",
        check="valid",
        status="pass",
        severity="info",
        evidence=f"mode={mode} version={version} path={path}",
        remediation="",
        safe_to_retry=True,
    )


async def collect_diagnostics(
    *,
    data_dir: Path | str | None = None,
    home: Path | None = None,
) -> list[DiagnosticCheck]:
    """Run all diagnostic providers and return normalized check dicts.

    Parameters
    ----------
    data_dir:
        Override for ``CB_DATA_DIR`` (heartbeats, storage, identity candidate).
    home:
        Override for ``Path.home()`` when resolving install-identity candidates
        (tests only).
    """
    from app.core.health import current_health, probe_dependencies

    resolved = resolve_data_dir(data_dir)
    checks: list[DiagnosticCheck] = []

    install_mode: str | None = None
    try:
        identity_preview = load_install_identity(data_dir=resolved, home=home)
        install_mode = str(identity_preview.get("mode") or "") or None
    except InstallIdentityError:
        install_mode = None

    health_suffix = ""
    try:
        snapshot = await current_health(max_age_s=0.0)
        health_suffix = f"; health_state={snapshot.state.value}"
        if snapshot.reason:
            health_suffix += f" reason={snapshot.reason}"
    except Exception as exc:
        _logger.warning("[diagnostics] current_health failed: %s", exc)
        health_suffix = f"; health_state=unknown ({exc})"

    try:
        dep_status = await probe_dependencies()
    except Exception as exc:
        _logger.warning("[diagnostics] probe_dependencies failed: %s", exc)
        checks.append(
            _check(
                component="postgres",
                check="ready",
                status="unknown",
                severity="error",
                evidence=f"dependency probe raised: {exc}{health_suffix}",
                remediation="Check backend logs and dependency connectivity, then retry.",
                safe_to_retry=True,
            )
        )
        checks.append(
            _check(
                component="redis",
                check="ready",
                status="unknown",
                severity="warning",
                evidence=f"dependency probe raised: {exc}{health_suffix}",
                remediation="Check Redis connectivity (CB_REDIS_URL) and retry.",
                safe_to_retry=True,
            )
        )
    else:
        for item in _dependency_checks(dep_status):
            if health_suffix and item["status"] != "pass":
                item["evidence"] = bound_evidence(f"{item['evidence']}{health_suffix}")
            checks.append(item)

    checks.extend(_worker_heartbeat_checks(resolved, install_mode=install_mode))
    checks.append(_storage_free_space_check(resolved))
    checks.append(_identity_check(data_dir=resolved, home=home))
    return checks
