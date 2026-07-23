from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parents[2]
ENV_FILE = BASE_DIR / ".env"

load_dotenv(ENV_FILE, override=False)


def _get_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_name: str
    app_version: str
    app_env: str
    app_host: str
    app_port: int
    app_debug: bool
    api_v1_prefix: str
    log_level: str
    database_url: str
    database_echo: bool
    docs_url: str | None
    openapi_url: str | None
    jwt_secret_key: str
    jwt_algorithm: str
    access_token_expire_minutes: int


def _build_database_url() -> str:
    direct_url = os.getenv("DATABASE_URL")
    if direct_url:
        return direct_url

    db_user = os.getenv("DB_USER", "postgres")
    db_password = os.getenv("DB_PASSWORD", "postgres")
    db_host = os.getenv("DB_HOST", "127.0.0.1")
    db_port = os.getenv("DB_PORT", "5432")
    db_name = os.getenv("DB_NAME", "ai_base")
    return f"postgresql+asyncpg://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"


@lru_cache
def get_settings() -> Settings:
    app_env = os.getenv("APP_ENV", "development")
    docs_enabled = _get_bool("DOCS_ENABLED", default=app_env != "production")

    return Settings(
        app_name=os.getenv("APP_NAME", "AI Base Backend"),
        app_version=os.getenv("APP_VERSION", "0.1.0"),
        app_env=app_env,
        app_host=os.getenv("APP_HOST", "0.0.0.0"),
        app_port=int(os.getenv("APP_PORT", "8000")),
        app_debug=_get_bool("APP_DEBUG", default=False),
        api_v1_prefix=os.getenv("API_V1_PREFIX", "/api/v1"),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        database_url=_build_database_url(),
        database_echo=_get_bool("DATABASE_ECHO", default=False),
        docs_url="/docs" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
        jwt_secret_key=os.getenv("JWT_SECRET_KEY", "dev-secret-change-me"),
        jwt_algorithm=os.getenv("JWT_ALGORITHM", "HS256"),
        access_token_expire_minutes=int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30")),
    )
