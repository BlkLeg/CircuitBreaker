"""Startup wrapper and native CLI for Circuit Breaker."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

# Ensure backend/src is on sys.path so 'import app' resolves correctly
# regardless of WORKDIR or whether the package is installed in site-packages.
# __file__ is backend/src/app/start.py → backend/src is 2 levels up.
_src_root = str(Path(__file__).resolve().parent.parent)
if _src_root not in sys.path:
    sys.path.insert(0, _src_root)

import socket  # noqa: E402

_orig_socketpair = socket.socketpair


def _tcp_socketpair():
    """Return a connected TCP socket pair as a drop-in replacement for socketpair."""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client.connect(("127.0.0.1", port))
    conn, _ = server.accept()
    server.close()
    return conn, client


def _safe_socketpair(family=socket.AF_UNIX, type=socket.SOCK_STREAM, proto=0):
    try:
        return _orig_socketpair(family, type, proto)
    except PermissionError:
        return _tcp_socketpair()


socket.socketpair = _safe_socketpair

import uvicorn  # noqa: E402

from app.core.config import resolve_app_version  # noqa: E402


def _coerce_value(raw: str | None) -> object:
    if raw is None:
        return ""
    value = raw.strip()
    if not value:
        return ""
    if value.startswith(("'", '"')) and value.endswith(value[0]):
        return value[1:-1]
    lowered = value.lower()
    if lowered in {"true", "yes", "on"}:
        return True
    if lowered in {"false", "no", "off"}:
        return False
    if lowered in {"null", "none"}:
        return None
    if lowered.isdigit():
        return int(lowered)
    return value


def load_native_config(path: str | Path | None) -> dict[str, object]:
    """Parse a minimal YAML-like config file for native installs."""
    if not path:
        return {}
    config_path = Path(path).expanduser()
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    config: dict[str, object] = {}
    for line_no, raw_line in enumerate(
        config_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in raw_line:
            raise ValueError(f"Invalid config line {line_no}: {raw_line}")
        key, raw_value = raw_line.split(":", 1)
        key = key.strip()
        value = raw_value.strip()
        if " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        config[key] = _coerce_value(value)
    return config


def _get_option(
    cli_value: object,
    env_key: str,
    config: dict[str, object],
    config_key: str,
    default: object,
) -> object:
    if cli_value is not None:
        return cli_value
    env_value = os.environ.get(env_key)
    if env_value not in {None, ""}:
        return _coerce_value(env_value)
    if config_key in config and config[config_key] is not None:
        return config[config_key]
    return default


def _set_default_env(name: str, value: str | None) -> None:
    if value and not os.environ.get(name):
        os.environ[name] = value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Circuit Breaker.")
    parser.add_argument(
        "--config",
        default=os.environ.get("CB_CONFIG_PATH") or "/etc/circuit-breaker/config.yaml",
        help="Path to the native runtime config file.",
    )
    parser.add_argument("--host", help="Override the listen host.")
    parser.add_argument("--port", type=int, help="Override the listen port.")
    parser.add_argument("--workers", type=int, help="Override the worker count.")
    parser.add_argument("--ssl-certfile", help="Path to the TLS certificate file.")
    parser.add_argument("--ssl-keyfile", help="Path to the TLS private key file.")
    parser.add_argument("--version", action="store_true", help="Print the app version and exit.")
    return parser


def configure_runtime(args: argparse.Namespace) -> dict[str, Any]:
    config_path = args.config if args.config and Path(args.config).exists() else None
    config = load_native_config(config_path)

    app_version = str(
        _get_option(None, "APP_VERSION", config, "app_version", resolve_app_version())
    )
    data_dir = Path(
        str(_get_option(None, "CB_DATA_DIR", config, "data_dir", str(Path.cwd() / "data")))
    ).expanduser()
    uploads_dir = Path(
        str(_get_option(None, "UPLOADS_DIR", config, "uploads_dir", str(data_dir / "uploads")))
    ).expanduser()
    static_dir = _get_option(None, "STATIC_DIR", config, "static_dir", None)
    database_url = _get_option(None, "DATABASE_URL", config, "database_url", None)
    analytics_db_path = _get_option(None, "ANALYTICS_DB_PATH", config, "analytics_db_path", None)
    share_dir = _get_option(None, "CB_SHARE_DIR", config, "share_dir", None)
    docs_seed_file = _get_option(None, "CB_DOCS_SEED_FILE", config, "docs_seed_file", None)
    alembic_ini = _get_option(None, "CB_ALEMBIC_INI", config, "alembic_ini", None)

    host = str(_get_option(args.host, "HOST", config, "host", "0.0.0.0"))
    port = int(str(_get_option(args.port, "PORT", config, "port", 8080)))
    workers = int(str(_get_option(args.workers, "UVICORN_WORKERS", config, "workers", 1)))
    tls_enabled = bool(_get_option(None, "CB_TLS_ENABLED", config, "tls_enabled", False))
    ssl_certfile = _get_option(args.ssl_certfile, "CB_TLS_CERT_FILE", config, "tls_cert_file", None)
    ssl_keyfile = _get_option(args.ssl_keyfile, "CB_TLS_KEY_FILE", config, "tls_key_file", None)

    data_dir.mkdir(parents=True, exist_ok=True)
    uploads_dir.mkdir(parents=True, exist_ok=True)

    if not database_url:
        import logging as _logging

        _logging.getLogger(__name__).error(
            "DATABASE_URL is not set. PostgreSQL is required. "
            "Set CB_DB_URL or DATABASE_URL to a postgresql:// connection string."
        )
        sys.exit(1)

    _set_default_env("APP_VERSION", app_version)
    _set_default_env("CB_DATA_DIR", str(data_dir))
    _set_default_env("DATABASE_URL", str(database_url))
    _set_default_env("UPLOADS_DIR", str(uploads_dir))
    _set_default_env("HOST", host)
    _set_default_env("PORT", str(port))
    _set_default_env("UVICORN_WORKERS", str(workers))
    if analytics_db_path:
        _set_default_env("ANALYTICS_DB_PATH", str(analytics_db_path))
    if static_dir:
        _set_default_env("STATIC_DIR", str(static_dir))
    if share_dir:
        _set_default_env("CB_SHARE_DIR", str(share_dir))
    if docs_seed_file:
        _set_default_env("CB_DOCS_SEED_FILE", str(docs_seed_file))
    if alembic_ini:
        _set_default_env("CB_ALEMBIC_INI", str(alembic_ini))

    tls: dict[str, Any] = {}
    if ssl_certfile or ssl_keyfile:
        if not ssl_certfile or not ssl_keyfile:
            raise SystemExit("Both TLS cert and key files are required when HTTPS is enabled.")
        tls["ssl_certfile"] = str(ssl_certfile)
        tls["ssl_keyfile"] = str(ssl_keyfile)
    elif tls_enabled:
        raise SystemExit("HTTPS is enabled but no TLS certificate/key paths were configured.")

    return {
        "host": host,
        "port": port,
        "workers": workers,
        **tls,
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.version:
        print(resolve_app_version())
        return 0

    # Load config.toml (env vars take precedence over TOML values)
    try:
        from app.core.config_toml import load_config_toml

        toml_path = (
            args.config
            if hasattr(args, "config") and args.config and args.config.endswith(".toml")
            else None
        )
        toml_count = load_config_toml(toml_path)
        if toml_count:
            print(f"[start] Loaded {toml_count} setting(s) from config.toml")
    except Exception:
        pass  # config.toml support is optional

    uvicorn_options = configure_runtime(args)

    from app.main import run_alembic_upgrade

    run_alembic_upgrade()

    uvicorn.run(
        "app.main:app",
        loop="asyncio",
        **uvicorn_options,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
