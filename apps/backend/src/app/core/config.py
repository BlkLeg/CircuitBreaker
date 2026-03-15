import json
import os
import sys
from pathlib import Path

from pydantic import field_validator
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

    # ── Deployment topology ──────────────────────────────────────────────────
    deploy_mode: str = "docker"  # CB_DEPLOY_MODE: "docker" | "native"
    data_dir: Path = Path("/data")  # CB_DATA_DIR — root for all persistent data
    app_root: Path = Path("/opt/circuitbreaker")  # CB_APP_ROOT
    log_dir: Path | None = None  # CB_LOG_DIR — defaults to data_dir

    @field_validator("data_dir", mode="before")
    @classmethod
    def coerce_data_dir(cls, v: object) -> Path:
        return Path(v) if isinstance(v, str) else v

    @field_validator("app_root", mode="before")
    @classmethod
    def coerce_app_root(cls, v: object) -> Path:
        return Path(v) if isinstance(v, str) else v

    @field_validator("log_dir", mode="before")
    @classmethod
    def coerce_log_dir(cls, v: object) -> Path | None:
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        return Path(v) if isinstance(v, str) else v

    @property
    def postgres_data_dir(self) -> Path:
        return self.data_dir / "pgdata"

    @property
    def effective_uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def tls_dir(self) -> Path:
        return self.data_dir / "tls"

    @property
    def vault_key_path(self) -> Path:
        return self.data_dir / ".vault_key"

    @property
    def effective_log_dir(self) -> Path:
        return self.log_dir or self.data_dir

    @property
    def redis_password_file(self) -> Path:
        return self.data_dir / ".redis_pass"

    @property
    def data_env_path(self) -> Path:
        return self.data_dir / ".env"

    @property
    def tmp_dir(self) -> Path:
        return self.data_dir / "tmp"

    @property
    def backups_dir(self) -> Path:
        return self.data_dir / "backups"

    @field_validator("database_url", mode="before")
    @classmethod
    def resolve_database_url(cls, v: str) -> str:
        from urllib.parse import quote_plus

        url = os.environ.get("CB_DB_URL", "").strip() or (v or "").strip()
        if url:
            return url
        # Auto-construct embedded PostgreSQL URL from CB_DB_PASSWORD
        db_password = os.environ.get("CB_DB_PASSWORD", "").strip()
        if db_password:
            return f"postgresql://breaker:{quote_plus(db_password)}@127.0.0.1:5432/circuitbreaker"
        return ""

    redis_url: str = "redis://localhost:6379/0"
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

    # Relative to the backend working directory. Override with STATIC_DIR env var
    # in single-container Docker deployments (e.g. STATIC_DIR=/app/frontend/dist).
    static_dir: str = "../frontend/dist"
    # Base directory for all user uploads. Override with UPLOADS_DIR env var.
    # In Docker (single image) set UPLOADS_DIR={CB_DATA_DIR}/uploads so files land on the volume.
    # In Docker Compose set UPLOADS_DIR={CB_DATA_DIR}/uploads to match the compose volume.
    uploads_dir: str = "data/uploads"
    # Optional DuckDB file path for analytics queries.
    # Leave empty to use SQLite for all queries (default for most deployments).
    analytics_db_path: str = ""


settings = Settings()
