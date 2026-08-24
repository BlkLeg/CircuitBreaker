import json
import os
import sys
from pathlib import Path
from typing import Annotated

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def _version_candidates() -> list[Path]:
    current = Path(__file__).resolve()
    candidates: list[Path] = []
    share_dir = os.environ.get("CB_SHARE_DIR")
    if share_dir:
        candidates.append(Path(share_dir) / "VERSION")
    executable_dir = Path(sys.executable).resolve().parent
    # The tarball/AppImage bundle layout: the binary sits next to its own share/.
    candidates.append(executable_dir / "share" / "VERSION")
    # The packaged (deb/rpm/apk) layout, which the bundle layout is not: nfpm
    # installs the binary to <prefix>/bin/circuit-breaker and the share tree to
    # <prefix>/share/circuit-breaker/, so the adjacent-share candidate above
    # resolves to /usr/local/bin/share/VERSION and never exists. Without this
    # entry an installed package had no readable VERSION at all and
    # `circuit-breaker --version` answered "unknown", which is what the
    # installed-artifact smoke gate caught.
    candidates.append(executable_dir.parent / "share" / "circuit-breaker" / "VERSION")
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "VERSION")
    if len(current.parents) > 5:
        candidates.append(current.parents[5] / "VERSION")
    return candidates


def resolve_app_version() -> str:
    """Resolve the app version for source, installed, and PyInstaller runs."""
    env_version = os.environ.get("APP_VERSION", "").strip()
    if env_version:
        return env_version

    for candidate in _version_candidates():
        try:
            version = candidate.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            continue
        if version:
            return version
    return "unknown"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Circuit Breaker"
    # APP_VERSION env var overrides at runtime (set via Docker build arg / compose).
    # Falls back to the repo-root VERSION file for local dev.
    app_version: str = resolve_app_version()
    debug: bool = False
    # Developer mode — enables verbose SQL logging, exposes
    # full stack traces in error responses.  NEVER enable in production.
    dev_mode: bool = False
    # Must be a postgresql:// URL. CB_DB_URL first, matching db/session.py's own
    # os.environ.get("CB_DB_URL", settings.database_url) precedence — without the
    # alias this field only ever saw DATABASE_URL, so it stayed empty everywhere
    # CB_DB_URL is the variable actually set (docker-compose.yml sets neither).
    # session.py reads the environment directly and so was unaffected; db_client's
    # _make_primary_engine has only this field, which is why the analytics engine
    # fell back onto create_engine("").
    database_url: str = Field("", validation_alias=AliasChoices("CB_DB_URL", "DATABASE_URL"))
    db_pool_url: str | None = None  # pgbouncer URL; falls back to database_url
    redis_url: str = Field(
        "redis://localhost:6379/0",
        validation_alias=AliasChoices("CB_REDIS_URL", "REDIS_URL"),
    )
    rate_limit_storage_url: str = Field(
        "",
        validation_alias=AliasChoices("CB_RATE_LIMIT_STORAGE_URL", "RATE_LIMIT_STORAGE_URL"),
    )
    # NoDecode: pydantic-settings JSON-decodes complex fields inside the env
    # source before any mode="before" validator runs, so the comma-separated
    # form install.sh writes to /etc/circuitbreaker/.env would raise
    # SettingsError at import time. Opt out and let the validator below decide.
    trusted_proxy_cidrs: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["127.0.0.1/32", "::1/128"],
        validation_alias=AliasChoices("CB_TRUSTED_PROXY_CIDRS", "TRUSTED_PROXY_CIDRS"),
    )
    egress_proxy_url: str = Field(
        "",
        validation_alias=AliasChoices("CB_EGRESS_PROXY_URL", "EGRESS_PROXY_URL"),
    )
    airgap: bool = False
    docker_host: str = ""
    api_prefix: str = "/api/v1"
    # Default same-origin only; set CORS_ORIGINS to a JSON array or a comma-separated
    # list for dev (e.g. ["http://localhost:5173"]). NoDecode for the same reason as
    # trusted_proxy_cidrs above.
    cors_origins: Annotated[list[str], NoDecode] = []

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: object) -> list[str]:
        if isinstance(v, list):
            return v
        if isinstance(v, str) and v.strip():
            try:
                parsed = json.loads(v)
                return list(parsed) if isinstance(parsed, list) else [v]
            except json.JSONDecodeError:
                return [o.strip() for o in v.split(",") if o.strip()]
        return []

    @field_validator("trusted_proxy_cidrs", mode="before")
    @classmethod
    def parse_trusted_proxy_cidrs(cls, v: object) -> list[str]:
        if isinstance(v, list):
            return [str(item).strip() for item in v if str(item).strip()]
        if isinstance(v, str) and v.strip():
            try:
                parsed = json.loads(v)
                if isinstance(parsed, list):
                    return [str(item).strip() for item in parsed if str(item).strip()]
            except json.JSONDecodeError:
                pass
            return [part.strip() for part in v.split(",") if part.strip()]
        return ["127.0.0.1/32", "::1/128"]

    # Relative to the backend working directory. Override with STATIC_DIR env var
    # in single-container Docker deployments (e.g. STATIC_DIR=/app/frontend/dist).
    static_dir: str = "../frontend/dist"
    # Base directory for all user uploads. Override with UPLOADS_DIR env var.
    # In Docker (single image) set UPLOADS_DIR=/data/uploads so files land on the volume.
    # In Docker Compose set UPLOADS_DIR=/app/data/uploads to match the compose volume.
    uploads_dir: str = "data/uploads"
    # Optional DuckDB file path for analytics queries.
    # Leave empty to run analytics on the primary PostgreSQL engine, which is
    # what db_client._make_analytics_engine falls back to.
    analytics_db_path: str = ""


settings = Settings()  # type: ignore[call-arg]
