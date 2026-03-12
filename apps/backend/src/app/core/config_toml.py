"""Load config.toml and set env vars (env vars take precedence)."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

# Map config.toml keys -> environment variable names
_KEY_MAP: dict[str, str] = {
    "server.host": "CB_HOST",
    "server.port": "CB_PORT",
    "database.url": "CB_DB_URL",
    "database.pool_size": "DB_POOL_SIZE",
    "database.max_overflow": "DB_MAX_OVERFLOW",
    "redis.url": "CB_REDIS_URL",
    "nats.url": "CB_NATS_URL",
    "nats.auth_token": "NATS_AUTH_TOKEN",
    "security.vault_key": "CB_VAULT_KEY",
    "security.cors_origins": "CORS_ORIGINS",
    "discovery.docker_host": "CB_DOCKER_HOST",
    "discovery.proxmox_url": "CB_PROXMOX_URL",
    "paths.data_dir": "CB_DATA_DIR",
    "paths.log_dir": "CB_LOG_DIR",
    "paths.static_dir": "STATIC_DIR",
    "paths.alembic_ini": "CB_ALEMBIC_INI",
    "updates.check_on_startup": "CB_UPDATE_CHECK",
}


def _flatten(data: dict, prefix: str = "") -> dict[str, str]:
    """Flatten nested dict to dotted keys with string values."""
    result: dict[str, str] = {}
    for key, value in data.items():
        full_key = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            result.update(_flatten(value, full_key))
        else:
            result[full_key] = str(value)
    return result


def load_config_toml(config_path: str | Path | None = None) -> int:
    """Load config.toml and set env vars for unset keys.

    Returns the number of env vars set from the config file.
    """
    if config_path is None:
        # Search standard locations
        candidates = [
            Path(os.environ.get("CB_CONFIG", "")),
            Path("/etc/circuit-breaker/config.toml"),
            Path.home() / ".config" / "circuitbreaker" / "config.toml",
            Path.cwd() / "config.toml",
        ]
        for candidate in candidates:
            if candidate.is_file():
                config_path = candidate
                break
        else:
            return 0
    else:
        config_path = Path(config_path)
        if not config_path.is_file():
            return 0

    with open(config_path, "rb") as f:
        data = tomllib.load(f)

    flat = _flatten(data)
    count = 0
    for toml_key, env_var in _KEY_MAP.items():
        if toml_key in flat and env_var not in os.environ:
            value = flat[toml_key]
            if value and value.lower() not in ("", "none", "null"):
                os.environ[env_var] = value
                count += 1

    return count
