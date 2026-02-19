from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_name: str = "Circuit Breaker"
    app_version: str = "0.1.0"
    debug: bool = False
    database_url: str = "sqlite:///./data/app.db"
    api_prefix: str = "/api/v1"
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:5173"]
    # Relative to the backend working directory. Override with STATIC_DIR env var
    # in single-container Docker deployments (e.g. STATIC_DIR=/app/frontend/dist).
    static_dir: str = "../frontend/dist"


settings = Settings()
