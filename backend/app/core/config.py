from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_name: str = "Circuit Breaker"
    app_version: str = "0.1.0"
    debug: bool = False
    database_url: str = "sqlite:///./data/app.db"
    api_prefix: str = "/api/v1"
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:5173"]
    static_dir: str = "/app/frontend/dist"


settings = Settings()
