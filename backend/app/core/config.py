from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def _read_version_file() -> str:
    """Read the canonical VERSION file from the repo root.

    Resolution order:
      1. Walk up from this file's location to find VERSION at the repo root.
      2. Fall back to 'unknown' if the file is missing (e.g. editable installs
         where the working directory layout differs).
    """
    # __file__ is backend/app/core/config.py → repo root is 4 levels up
    candidate = Path(__file__).resolve().parent.parent.parent.parent / "VERSION"
    try:
        return candidate.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return "unknown"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", 
        env_file_encoding="utf-8",
        extra="ignore"
    )

    app_name: str = "Circuit Breaker"
    # APP_VERSION env var overrides at runtime (set via Docker build arg / compose).
    # Falls back to the repo-root VERSION file for local dev.
    app_version: str = _read_version_file()
    debug: bool = False
    database_url: str = "sqlite:///./data/app.db"
    api_prefix: str = "/api/v1"
    cors_origins: list[str] = ["*"]
    # Relative to the backend working directory. Override with STATIC_DIR env var
    # in single-container Docker deployments (e.g. STATIC_DIR=/app/frontend/dist).
    static_dir: str = "../frontend/dist"
    # Base directory for all user uploads. Override with UPLOADS_DIR env var.
    # In Docker (single image) set UPLOADS_DIR=/data/uploads so files land on the volume.
    # In Docker Compose set UPLOADS_DIR=/app/data/uploads to match the compose volume.
    uploads_dir: str = "data/uploads"

settings = Settings()
