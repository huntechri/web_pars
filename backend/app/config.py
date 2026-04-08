from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/petrovich"
    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 12
    admin_username: str = "admin"
    admin_password: str = "admin"
    frontend_origin: str = "http://localhost:3000"

    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parents[1] / ".env"),
        env_prefix="APP_",
    )


settings = Settings()

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
