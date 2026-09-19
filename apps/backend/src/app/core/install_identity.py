"""Install identity record: path resolution and validation (no secrets).

The record is the operator-tooling source of truth written by installers.
Missing or malformed identity is a diagnosis result — never permission to
guess container names, ports, or config directories.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

IDENTITY_SCHEMA_VERSION: Final[int] = 1
VALID_MODES: Final[frozenset[str]] = frozenset({"native", "package", "mono", "proxmox"})

REQUIRED_FIELDS: Final[tuple[str, ...]] = (
    "schema_version",
    "mode",
    "version",
    "installed_at",
)

OPTIONAL_FIELDS: Final[tuple[str, ...]] = (
    "config_path",
    "data_dir",
    "env_file",
    "service_names",
    "container_name",
    "compose_file",
    "cli_path",
    "health_url",
)

# Well-known paths, in search order after $CB_IDENTITY_PATH.
_SYSTEM_IDENTITY_PATHS: Final[tuple[Path, ...]] = (
    Path("/etc/circuitbreaker/install-identity.json"),
    Path("/etc/circuit-breaker/install-identity.json"),
)

_LEGACY_INSTALL_CONF_PATHS: Final[tuple[Path, ...]] = (
    Path("/etc/circuit-breaker/install.conf"),
    Path.home() / ".circuit-breaker/install.conf",
)


class InstallIdentityError(ValueError):
    """Identity is missing, unreadable, or fails schema checks."""


def identity_candidate_paths(
    *,
    data_dir: str | Path | None = None,
    home: Path | None = None,
) -> list[Path]:
    """Ordered candidate paths for the install identity file."""
    paths: list[Path] = []
    override = (os.environ.get("CB_IDENTITY_PATH") or "").strip()
    if override:
        paths.append(Path(override).expanduser())
    paths.extend(_SYSTEM_IDENTITY_PATHS)
    resolved_data = data_dir or (os.environ.get("CB_DATA_DIR") or "").strip() or None
    if resolved_data:
        paths.append(Path(resolved_data).expanduser() / "install-identity.json")
    home_path = home if home is not None else Path.home()
    paths.append(home_path / ".circuit-breaker" / "install-identity.json")
    # Preserve order while dropping duplicates.
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        unique.append(path)
    return unique


def find_install_identity_path(
    *,
    data_dir: str | Path | None = None,
    home: Path | None = None,
) -> Path | None:
    """Return the first readable identity path, or None.

    When ``CB_IDENTITY_PATH`` is set, only that path is considered (fail closed
    if missing) — never fall through to guesses.
    """
    override = (os.environ.get("CB_IDENTITY_PATH") or "").strip()
    if override:
        path = Path(override).expanduser()
        try:
            if path.is_file() and os.access(path, os.R_OK):
                return path
        except OSError:
            return None
        return None

    for path in identity_candidate_paths(data_dir=data_dir, home=home):
        try:
            if path.is_file() and os.access(path, os.R_OK):
                return path
        except OSError:
            continue
    return None


def validate_install_identity(data: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and return a normalized identity dict.

    Raises InstallIdentityError when required fields are missing or invalid.
    """
    if not isinstance(data, Mapping):
        raise InstallIdentityError("install identity must be a JSON object")

    missing = [field for field in REQUIRED_FIELDS if field not in data]
    if missing:
        raise InstallIdentityError(
            "install identity missing required field(s): " + ", ".join(missing)
        )

    schema_version = data.get("schema_version")
    if schema_version != IDENTITY_SCHEMA_VERSION:
        raise InstallIdentityError(
            f"unsupported identity schema_version {schema_version!r}; "
            f"expected {IDENTITY_SCHEMA_VERSION}"
        )

    mode = data.get("mode")
    if mode not in VALID_MODES:
        raise InstallIdentityError(
            f"invalid identity mode {mode!r}; expected one of " + ", ".join(sorted(VALID_MODES))
        )

    version = str(data.get("version") or "").strip()
    if not version:
        raise InstallIdentityError("identity version must be a non-empty string")

    installed_at = str(data.get("installed_at") or "").strip()
    if not installed_at:
        raise InstallIdentityError("identity installed_at must be a non-empty string")

    normalized: dict[str, Any] = {
        "schema_version": IDENTITY_SCHEMA_VERSION,
        "mode": mode,
        "version": version,
        "installed_at": installed_at,
    }

    for field in OPTIONAL_FIELDS:
        if field not in data:
            continue
        value = data[field]
        if value is None or value == "":
            continue
        if field == "service_names":
            if not isinstance(value, list) or not all(
                isinstance(item, str) and item.strip() for item in value
            ):
                raise InstallIdentityError("service_names must be a list of strings")
            normalized[field] = [item.strip() for item in value]
        else:
            normalized[field] = str(value).strip()

    return normalized


def load_install_identity(
    path: Path | None = None,
    *,
    data_dir: str | Path | None = None,
    home: Path | None = None,
) -> dict[str, Any]:
    """Load and validate identity from ``path`` or the first candidate path.

    Raises InstallIdentityError when no file is found or validation fails.
    """
    resolved = path or find_install_identity_path(data_dir=data_dir, home=home)
    if resolved is None:
        raise InstallIdentityError(
            "install identity not found; expected one of: "
            + ", ".join(str(p) for p in identity_candidate_paths(data_dir=data_dir, home=home))
        )
    try:
        raw = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InstallIdentityError(f"cannot read install identity at {resolved}: {exc}") from exc
    normalized = validate_install_identity(raw)
    normalized["_path"] = str(resolved)
    return normalized


def legacy_install_conf_paths(*, home: Path | None = None) -> list[Path]:
    """Paths that may still hold CB_MODE during the one-release compat window."""
    home_path = home if home is not None else Path.home()
    return [
        Path("/etc/circuit-breaker/install.conf"),
        home_path / ".circuit-breaker" / "install.conf",
    ]


def repair_hint_for_mode(mode: str | None) -> str:
    """Mode-specific remediation when identity is missing or corrupt."""
    hints = {
        "native": (
            "Re-run the native installer so /etc/circuitbreaker/install-identity.json "
            "is written, then run: cb info"
        ),
        "mono": (
            "Restart the mono container so /data/install-identity.json is rewritten, "
            "and ensure ~/.circuit-breaker/install-identity.json exists on the host"
        ),
        "proxmox": (
            "Re-run cb-proxmox-deploy.sh or ensure the CT has mode=proxmox in "
            "/etc/circuitbreaker/install-identity.json"
        ),
        "package": (
            "Reinstall the circuit-breaker package so "
            "/etc/circuit-breaker/install-identity.json is written"
        ),
    }
    if mode and mode in hints:
        return hints[mode]
    return (
        "No install identity found. Re-run the installer for your deployment mode "
        "(native, mono, proxmox, or package) so install-identity.json is written, "
        "then run: cb info"
    )
