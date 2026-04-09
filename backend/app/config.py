import os
from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/petrovich"
    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 12
    admin_username: str = "admin"
    admin_password: str = "admin"
    frontend_origin: str = "http://localhost:3000"
    parser_cookies: str | dict[str, str] = Field(default_factory=dict)
    parser_headers: str | dict[str, str] = Field(default_factory=dict)
    parser_max_category_workers: int = 3
    parser_retry_base_delay_seconds: float = 0.35
    parser_rate_limit_wait_cap_seconds: int = 15
    parser_request_timeout_seconds: int = 20
    storage_bucket: str | None = None
    storage_endpoint_url: str | None = None
    storage_access_key_id: str | None = None
    storage_secret_access_key: str | None = None
    storage_region: str = "auto"
    storage_presign_expire_seconds: int = 3600

    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parents[1] / ".env"),
        env_prefix="APP_",
    )


settings = Settings()

_DEFAULT_LOCAL_DATABASE_URL = "postgresql+psycopg2://postgres:postgres@localhost:5432/petrovich"
if os.getenv("RENDER") and settings.database_url == _DEFAULT_LOCAL_DATABASE_URL:
    raise RuntimeError(
        "APP_DATABASE_URL is not set in Render environment. "
        "Current value points to localhost, so API cannot reach PostgreSQL. "
        "Set APP_DATABASE_URL to your Render Postgres connection string."
    )

if settings.database_url.startswith("postgres://"):
    settings.database_url = settings.database_url.replace("postgres://", "postgresql+psycopg2://", 1)

if (
    "localhost" not in settings.database_url
    and "127.0.0.1" not in settings.database_url
    and "sslmode=" not in settings.database_url
):
    sep = "&" if "?" in settings.database_url else "?"
    settings.database_url = f"{settings.database_url}{sep}sslmode=require"

PROJECT_ROOT = Path(__file__).resolve().parents[2]
