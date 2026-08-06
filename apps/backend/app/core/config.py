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
    log_file_path: str
    log_file_backup_count: int
    database_url: str
    database_echo: bool
    docs_url: str | None
    openapi_url: str | None
    jwt_secret_key: str
    jwt_algorithm: str
    access_token_expire_minutes: int
    embed_jwt_secret_key: str
    embed_jwt_algorithm: str
    embed_token_issuer: str
    embed_token_audience: str
    embed_client_id: str
    embed_client_secret: str
    embed_agent_id: int
    embed_origin: str
    model_default_name: str
    model_default_base_url: str | None
    model_request_timeout_seconds: float
    model_max_retries: int
    agent_file_storage_path: str
    agent_max_upload_bytes: int
    agent_fetch_timeout_seconds: int
    agent_master_key: str
    skill_runner_url: str
    skill_runner_shared_secret: str
    skill_runner_timeout_seconds: int
    skill_runner_max_output_bytes: int
    celery_broker_url: str
    celery_result_backend: str
    metrics_enabled: bool
    quota_enabled: bool
    quota_window_seconds: int
    quota_token_issue_limit: int
    quota_connection_limit: int
    quota_message_limit: int
    quota_model_tokens_limit: int
    sdk_minimum_version: str


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
        log_file_path=os.getenv("LOG_FILE_PATH", str(BASE_DIR / "logs" / "app.log")),
        log_file_backup_count=int(os.getenv("LOG_FILE_BACKUP_COUNT", "5")),
        database_url=_build_database_url(),
        database_echo=_get_bool("DATABASE_ECHO", default=False),
        docs_url="/docs" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
        jwt_secret_key=os.getenv("JWT_SECRET_KEY", "dev-secret-change-me"),
        jwt_algorithm=os.getenv("JWT_ALGORITHM", "HS256"),
        access_token_expire_minutes=int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30")),
        embed_jwt_secret_key=os.getenv(
            "EMBED_JWT_SECRET_KEY", "dev-embed-secret-change-me-32-bytes-long"
        ),
        embed_jwt_algorithm=os.getenv("EMBED_JWT_ALGORITHM", "HS256"),
        embed_token_issuer=os.getenv("EMBED_TOKEN_ISSUER", "ai-base"),
        embed_token_audience=os.getenv("EMBED_TOKEN_AUDIENCE", "agent-embed"),
        embed_client_id=os.getenv("EMBED_CLIENT_ID", ""),
        embed_client_secret=os.getenv("EMBED_CLIENT_SECRET", ""),
        embed_agent_id=int(os.getenv("EMBED_AGENT_ID", "0")),
        embed_origin=os.getenv("EMBED_ORIGIN", ""),
        model_default_name=os.getenv("MODEL_DEFAULT_NAME", "gpt-4o-mini"),
        model_default_base_url=os.getenv("MODEL_DEFAULT_BASE_URL") or None,
        model_request_timeout_seconds=float(
            os.getenv("MODEL_REQUEST_TIMEOUT_SECONDS", "60")
        ),
        model_max_retries=int(os.getenv("MODEL_MAX_RETRIES", "0")),
        agent_file_storage_path=os.getenv(
            "AGENT_FILE_STORAGE_PATH", str(BASE_DIR / "storage")
        ),
        agent_max_upload_bytes=int(
            os.getenv("AGENT_MAX_UPLOAD_BYTES", str(25 * 1024 * 1024))
        ),
        agent_fetch_timeout_seconds=int(os.getenv("AGENT_FETCH_TIMEOUT_SECONDS", "15")),
        agent_master_key=os.getenv(
            "AGENT_MASTER_KEY", "dev-agent-master-key-change-me"
        ),
        # 本地 Python API 运行在宿主机时使用开发 runner 端口；Compose API
        # 会通过环境变量显式覆盖为内部 DNS 地址，生产环境也必须显式配置。
        skill_runner_url=os.getenv(
            "SKILL_RUNNER_URL",
            "http://127.0.0.1:8090"
            if app_env == "development"
            else "http://skill-runner:8090",
        ),
        skill_runner_shared_secret=os.getenv(
            "SKILL_RUNNER_SHARED_SECRET", "dev-skill-runner-secret-change-me"
        ),
        skill_runner_timeout_seconds=int(
            os.getenv("SKILL_RUNNER_TIMEOUT_SECONDS", "30")
        ),
        skill_runner_max_output_bytes=int(
            os.getenv("SKILL_RUNNER_MAX_OUTPUT_BYTES", str(64 * 1024))
        ),
        celery_broker_url=os.getenv("CELERY_BROKER_URL", "redis://127.0.0.1:6379/0"),
        celery_result_backend=os.getenv(
            "CELERY_RESULT_BACKEND", "redis://127.0.0.1:6379/0"
        ),
        metrics_enabled=_get_bool("METRICS_ENABLED", default=True),
        quota_enabled=_get_bool("QUOTA_ENABLED", default=app_env == "production"),
        quota_window_seconds=int(os.getenv("QUOTA_WINDOW_SECONDS", "60")),
        quota_token_issue_limit=int(os.getenv("QUOTA_TOKEN_ISSUE_LIMIT", "60")),
        quota_connection_limit=int(os.getenv("QUOTA_CONNECTION_LIMIT", "10")),
        quota_message_limit=int(os.getenv("QUOTA_MESSAGE_LIMIT", "60")),
        quota_model_tokens_limit=int(os.getenv("QUOTA_MODEL_TOKENS_LIMIT", "100000")),
        sdk_minimum_version=os.getenv("SDK_MINIMUM_VERSION", "0.1.0"),
    )
