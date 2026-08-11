import json
import os
import sys
from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _version_candidates() -> list[Path]:
    current = Path(__file__).resolve()
    candidates: list[Path] = []
    share_dir = os.environ.get("CB_SHARE_DIR")
    if share_dir:
        candidates.append(Path(share_dir) / "VERSION")
    executable_share = Path(sys.executable).resolve().parent / "share" / "VERSION"
    candidates.append(executable_share)
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
    database_url: str = ""  # Must be a postgresql:// URL; set via CB_DB_URL env var
    db_pool_url: str | None = None  # pgbouncer URL; falls back to database_url
    redis_url: str = Field(
        "redis://localhost:6379/0",
        validation_alias=AliasChoices("CB_REDIS_URL", "REDIS_URL"),
    )
    rate_limit_storage_url: str = Field(
        "",
        validation_alias=AliasChoices("CB_RATE_LIMIT_STORAGE_URL", "RATE_LIMIT_STORAGE_URL"),
    )
    trusted_proxy_cidrs: list[str] = Field(
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
    # Default same-origin only; set CORS_ORIGINS JSON array for dev (e.g. ["http://localhost:5173"]).
    cors_origins: list[str] = []

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
    # Leave empty to use SQLite for all queries (default for most deployments).
    analytics_db_path: str = ""


settings = Settings()  # type: ignore[call-arg]
