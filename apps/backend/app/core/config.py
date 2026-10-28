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


DEFAULT_CORS_ORIGINS = (
    "http://127.0.0.1:5500",
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    "http://localhost:5174",
)


def _get_cors_origins() -> list[str]:
    """读取允许跨域访问的来源列表。

    通过 ``CORS_ORIGINS``（逗号分隔）配置；未配置时沿用内置的本地开发来源，
    保证既有部署的跨域行为不变。条目按 origin 规范去掉尾部斜杠。
    """
    raw = os.getenv("CORS_ORIGINS", "")
    origins = [item.strip().rstrip("/") for item in raw.split(",")]
    return [item for item in origins if item] or list(DEFAULT_CORS_ORIGINS)


def _resolve_log_file_path() -> str:
    """解析日志落盘路径。

    容器工作目录与本地开发目录不一定一致，``LOG_FILE_PATH`` 若为相对路径，统一按
    ``BASE_DIR``（``apps/backend``）解析，避免日志落到不可预期的位置；Docker 部署时
    由 Compose 按服务分别指定绝对路径，防止多个服务写同一个文件。
    """
    raw = os.getenv("LOG_FILE_PATH")
    if not raw or not raw.strip():
        return str(BASE_DIR / "logs" / "app.log")
    candidate = Path(raw.strip()).expanduser()
    if candidate.is_absolute():
        return str(candidate)
    return str(BASE_DIR / candidate)


def _parse_optional_int(name: str) -> int | None:
    value = os.getenv(name)
    if value is None or not value.strip():
        return None
    try:
        return int(value)
    except ValueError:
        return None


@dataclass(frozen=True)
class Settings:
    app_name: str
    app_version: str
    app_env: str
    app_host: str
    app_port: int
    app_debug: bool
    cors_origins: list[str]
    api_v1_prefix: str
    log_level: str
    log_file_path: str
    log_file_backup_count: int
    database_url: str
    database_echo: bool
    # 只读查库（db_schema / db_query）使用独立的 reader 角色连接，空串表示未配置，
    # 此时工具返回 db_reader_not_configured，不影响应用启动。
    database_reader_url: str
    db_query_statement_timeout_ms: int
    db_query_max_rows: int
    db_query_max_result_bytes: int
    db_query_max_cell_chars: int
    db_query_pool_size: int
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
    openai_api_key: str | None
    openai_base_url: str | None
    openai_image_model: str
    provider_capability_cache_ttl_seconds: int
    provider_capability_query_timeout_seconds: float
    read_image_model: str | None
    read_image_base_url: str | None
    read_image_api_key: str | None
    read_image_timeout_seconds: float
    image_generation_timeout_seconds: float
    image_max_bytes: int
    image_max_count: int
    model_request_timeout_seconds: float
    model_max_retries: int
    agent_file_storage_path: str
    agent_max_upload_bytes: int
    agent_fetch_timeout_seconds: int
    agent_max_iterations: int
    embedding_batch_size: int
    attachment_embedding_provider: str | None
    attachment_embedding_model: str | None
    attachment_embedding_base_url: str | None
    attachment_embedding_api_key: str | None
    attachment_embedding_dimension: int | None
    # 附件向量检索的最小余弦相似度。低于该阈值的切块视为“没匹配上”，
    # 不再返回给模型（pgvector 检索本身没有阈值，不设限会把整库最相似
    # 的 k 条全部返回，即使用户问的内容文档里根本没有）。
    attachment_retrieval_min_score: float
    agent_master_key: str
    builtin_http_get_timeout_seconds: float
    builtin_http_get_text_max_bytes: int
    builtin_http_get_text_max_chars: int
    builtin_http_get_file_max_bytes: int
    # MCP 出站安全开关：默认只允许公网可达的 HTTP(S) endpoint（防 SSRF）。
    # 显式开启后额外放行回环与私网地址，便于本地或内网自建 MCP 服务接入；
    # 链路本地地址（含云元数据 169.254.169.254）始终拒绝。
    mcp_allow_private_endpoints: bool
    skill_runner_url: str
    skill_runner_shared_secret: str
    skill_runner_timeout_seconds: int
    skill_runner_max_output_bytes: int
    # 按 GitHub 源添加技能：由 API 进程主动出网拉取公开仓库的技能目录，
    # 再交给既有的技能包导入链路。目标主机恒为 api.github.com。
    skill_source_import_enabled: bool
    skill_source_http_timeout_seconds: float
    # 单次来源导入允许的文件数与总体积上限：超限即拒绝，避免一次导入把
    # 请求耗时与内存拖垮（技能目录通常只有 1~5 个文件）。
    skill_source_max_files: int
    skill_source_max_total_bytes: int
    # 可选 GitHub Token：只提升 REST 限流额度（匿名 60 次/小时 → 5000 次/小时），
    # 不改变网络带宽。
    github_token: str | None
    knowledge_context_max_chars: int
    conversation_history_window_seconds: int
    tool_snapshot_max_chars: int
    tool_snapshot_total_chars: int
    tool_snapshot_max_entries: int
    tool_snapshot_retention_seconds: int | None
    context_input_ratio: float
    context_estimate_chars_per_token: float
    context_exceeded_retry_enabled: bool
    # 上下文压缩：阈值用绝对余量（Pi 的默认值），而不是比例，避免把
    # 「回答要留多少空间」和「历史能占多少」绑死在同一个比例上。
    context_compaction_enabled: bool
    context_compaction_reserve_tokens: int
    context_compaction_keep_recent_tokens: int
    context_compaction_summary_max_tokens: int
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
    wechat_bot_enabled: bool
    wechat_bot_system_prompt: str
    wechat_bot_max_reply_chars: int
    wechat_bot_state_dir: str
    wechat_bot_api_base_url: str
    wechat_bot_max_instances: int
    store_ops_base_url: str
    store_ops_redis_ttl_seconds: int
    store_ops_http_timeout_seconds: float
    # 任务调度（常驻调度进程）相关配置：tick 间隔、单次执行默认超时、
    # 单个平台的任务数上限，以及调度进程自身的启用开关。
    task_scheduler_enabled: bool
    task_scheduler_tick_seconds: int
    task_default_timeout_seconds: int
    task_max_per_platform: int
    # 单个平台的工作流数量上限：工作流会按计划反复执行并落运行记录，
    # 不做上限时一个平台可以无限堆积定义，把调度队列拖垮。
    workflow_max_per_platform: int
    # 运行期委派（delegate_tasks）：模型自主发起的并发子 Agent 运行所需的显式闸。
    # 单次调用可派的子任务数、同时跑几个、每个子运行的模型轮次上限与整体超时，
    # 以及单个子任务回给父模型的输出字节上限。
    # 子运行必须有自己的轮次上限：父运行的一轮里一次派生就会把子运行的整轮预算
    # 花掉，而子运行的 token 不会并回父运行的 usage，沿用 agent_max_iterations
    # 会让一次委派的成本量级失控。
    delegation_max_tasks: int
    delegation_max_concurrency: int
    delegation_max_iterations: int
    delegation_timeout_seconds: int
    delegation_output_max_bytes: int
    # 注入委派工具描述的可派智能体清单条数上限：清单太长会挤占模型上下文。
    delegation_max_agents_in_prompt: int


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
        cors_origins=_get_cors_origins(),
        api_v1_prefix=os.getenv("API_V1_PREFIX", "/api/v1"),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        log_file_path=_resolve_log_file_path(),
        # 按天保留最近 N 天的日志文件（每个服务各自一个目录，互不影响）
        log_file_backup_count=int(os.getenv("LOG_FILE_BACKUP_COUNT", "14")),
        database_url=_build_database_url(),
        database_echo=_get_bool("DATABASE_ECHO", default=False),
        database_reader_url=os.getenv("DATABASE_READER_URL", ""),
        db_query_statement_timeout_ms=int(os.getenv("DB_QUERY_STATEMENT_TIMEOUT_MS", "5000")),
        db_query_max_rows=int(os.getenv("DB_QUERY_MAX_ROWS", "200")),
        db_query_max_result_bytes=int(os.getenv("DB_QUERY_MAX_RESULT_BYTES", "65536")),
        db_query_max_cell_chars=int(os.getenv("DB_QUERY_MAX_CELL_CHARS", "8192")),
        db_query_pool_size=int(os.getenv("DB_QUERY_POOL_SIZE", "2")),
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
        model_default_name=os.getenv("MODEL_DEFAULT_NAME", "deepseek-v4-flash"),
        model_default_base_url=os.getenv("MODEL_DEFAULT_BASE_URL") or None,
        openai_api_key=os.getenv("OPENAI_API_KEY") or None,
        openai_base_url=os.getenv("OPENAI_BASE_URL") or None,
        openai_image_model=os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1"),
        provider_capability_cache_ttl_seconds=int(
            os.getenv("PROVIDER_CAPABILITY_CACHE_TTL_SECONDS", "600")
        ),
        provider_capability_query_timeout_seconds=float(
            os.getenv("PROVIDER_CAPABILITY_QUERY_TIMEOUT_SECONDS", "5")
        ),
        read_image_model=os.getenv("READ_IMAGE_MODEL") or None,
        read_image_base_url=os.getenv("READ_IMAGE_BASE_URL") or None,
        read_image_api_key=os.getenv("READ_IMAGE_API_KEY") or None,
        read_image_timeout_seconds=float(
            os.getenv("READ_IMAGE_TIMEOUT_SECONDS", "120")
        ),
        image_generation_timeout_seconds=float(
            os.getenv("IMAGE_GENERATION_TIMEOUT_SECONDS", "120")
        ),
        image_max_bytes=int(os.getenv("IMAGE_MAX_BYTES", str(25 * 1024 * 1024))),
        image_max_count=max(1, int(os.getenv("IMAGE_MAX_COUNT", "4"))),
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
        agent_max_iterations=int(os.getenv("AGENT_MAX_ITERATIONS", "20")),
        embedding_batch_size=int(os.getenv("EMBEDDING_BATCH_SIZE", "10")),
        attachment_embedding_provider=os.getenv("ATTACHMENT_EMBEDDING_PROVIDER"),
        attachment_embedding_model=os.getenv("ATTACHMENT_EMBEDDING_MODEL"),
        attachment_embedding_base_url=os.getenv("ATTACHMENT_EMBEDDING_BASE_URL"),
        attachment_embedding_api_key=os.getenv("ATTACHMENT_EMBEDDING_API_KEY"),
        attachment_embedding_dimension=_parse_optional_int(
            "ATTACHMENT_EMBEDDING_DIMENSION"
        ),
        # 经验值：text-embedding-v3 下相关问句 top1 约 0.55~0.68，
        # 无关问句 top1 约 0.38~0.45，0.5 能稳住这条分界线；换模型时
        # 可用环境变量重新标定，避免把阈值写死在代码里。
        attachment_retrieval_min_score=min(
            1.0,
            max(
                0.0,
                float(os.getenv("ATTACHMENT_RETRIEVAL_MIN_SCORE", "0.5")),
            ),
        ),
        agent_master_key=os.getenv(
            "AGENT_MASTER_KEY", "dev-agent-master-key-change-me"
        ),
        builtin_http_get_timeout_seconds=float(
            os.getenv("BUILTIN_HTTP_GET_TIMEOUT_SECONDS", "30")
        ),
        builtin_http_get_text_max_bytes=int(
            os.getenv("BUILTIN_HTTP_GET_TEXT_MAX_BYTES", str(1024 * 1024))
        ),
        builtin_http_get_text_max_chars=int(
            os.getenv("BUILTIN_HTTP_GET_TEXT_MAX_CHARS", "100000")
        ),
        builtin_http_get_file_max_bytes=int(
            os.getenv("BUILTIN_HTTP_GET_FILE_MAX_BYTES", str(25 * 1024 * 1024))
        ),
        mcp_allow_private_endpoints=_get_bool(
            "MCP_ALLOW_PRIVATE_ENDPOINTS", default=False
        ),
        # 本地 Python API 运行在宿主机时使用开发 runner 端口；Compose API
        # 会通过环境变量显式覆盖为内部 DNS 地址，生产环境也必须显式配置。
        skill_runner_url=os.getenv(
            "SKILL_RUNNER_URL",
            (
                "http://127.0.0.1:8090"
                if app_env == "development"
                else "http://skill-runner:8090"
            ),
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
        skill_source_import_enabled=_get_bool(
            "SKILL_SOURCE_IMPORT_ENABLED", default=True
        ),
        # 单次 GitHub 请求 20 秒：实测本机到 api.github.com 的列树请求约 8 秒。
        skill_source_http_timeout_seconds=float(
            os.getenv("SKILL_SOURCE_HTTP_TIMEOUT_SECONDS", "20")
        ),
        skill_source_max_files=min(
            300, max(1, int(os.getenv("SKILL_SOURCE_MAX_FILES", "120")))
        ),
        skill_source_max_total_bytes=min(
            25 * 1024 * 1024,
            max(
                1024,
                int(os.getenv("SKILL_SOURCE_MAX_TOTAL_BYTES", str(10 * 1024 * 1024))),
            ),
        ),
        github_token=(os.getenv("GITHUB_TOKEN") or "").strip() or None,
        knowledge_context_max_chars=int(
            os.getenv("KNOWLEDGE_CONTEXT_MAX_CHARS", "24000")
        ),
        conversation_history_window_seconds=max(
            0, int(os.getenv("CONVERSATION_HISTORY_WINDOW_SECONDS", "3600"))
        ),
        tool_snapshot_max_chars=int(os.getenv("TOOL_SNAPSHOT_MAX_CHARS", "8000")),
        tool_snapshot_total_chars=int(
            os.getenv("TOOL_SNAPSHOT_TOTAL_CHARS", "20000")
        ),
        tool_snapshot_max_entries=max(
            1, int(os.getenv("TOOL_SNAPSHOT_MAX_ENTRIES", "20"))
        ),
        tool_snapshot_retention_seconds=_parse_optional_int(
            "TOOL_SNAPSHOT_RETENTION_SECONDS"
        ),
        context_input_ratio=max(
            0.1, min(1.0, float(os.getenv("CONTEXT_INPUT_RATIO", "0.75")))
        ),
        context_estimate_chars_per_token=float(
            os.getenv("CONTEXT_ESTIMATE_CHARS_PER_TOKEN", "1.2")
        ),
        context_exceeded_retry_enabled=_get_bool(
            "CONTEXT_EXCEEDED_RETRY_ENABLED", default=True
        ),
        context_compaction_enabled=_get_bool(
            "CONTEXT_COMPACTION_ENABLED", default=True
        ),
        # 守卫下限：reserve 小于 1k 时阈值会贴着窗口，压缩几乎每轮触发；
        # keep 为 0 会让压缩后一条历史都不保留，等于把对话记忆清零。
        context_compaction_reserve_tokens=max(
            1024, int(os.getenv("CONTEXT_COMPACTION_RESERVE_TOKENS", "16384"))
        ),
        context_compaction_keep_recent_tokens=max(
            0, int(os.getenv("CONTEXT_COMPACTION_KEEP_RECENT_TOKENS", "20000"))
        ),
        context_compaction_summary_max_tokens=max(
            0, int(os.getenv("CONTEXT_COMPACTION_SUMMARY_MAX_TOKENS", "0"))
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
        quota_model_tokens_limit=int(os.getenv("QUOTA_MODEL_TOKENS_LIMIT", "10000000")),
        sdk_minimum_version=os.getenv("SDK_MINIMUM_VERSION", "0.1.0"),
        wechat_bot_enabled=_get_bool("WECHAT_BOT_ENABLED", default=False),
        wechat_bot_system_prompt=os.getenv(
            "WECHAT_BOT_SYSTEM_PROMPT",
            "你是「ai-base」的微信 AI 助手。用简洁、准确的中文回答用户问题，"
            "不要输出 Markdown 格式符号，尽量直接给出答案。",
        ),
        wechat_bot_max_reply_chars=max(
            200, int(os.getenv("WECHAT_BOT_MAX_REPLY_CHARS", "4000"))
        ),
        wechat_bot_state_dir=os.getenv(
            "WECHAT_BOT_STATE_DIR",
            str(BASE_DIR / "data" / "wechat_bot"),
        ),
        wechat_bot_api_base_url=os.getenv("WECHAT_BOT_API_BASE_URL", "http://api:8000"),
        wechat_bot_max_instances=max(
            1, int(os.getenv("WECHAT_BOT_MAX_INSTANCES", "20"))
        ),
        # 店铺运营平台（hua8）接入：服务器业务工具 store_ops_query 的接口地址与
        # 店铺 token 在 Redis 中的有效期（默认 43200 秒，跟随店铺系统登录时效）。
        store_ops_base_url=os.getenv(
            "STORE_OPS_BASE_URL", "http://hua8.bbtree.xyz"
        ),
        store_ops_redis_ttl_seconds=int(
            os.getenv("STORE_OPS_REDIS_TTL_SECONDS", "43200")
        ),
        store_ops_http_timeout_seconds=float(
            os.getenv("STORE_OPS_HTTP_TIMEOUT_SECONDS", "10")
        ),
        # 任务调度：tick 默认 30 秒，配合任务侧「最小间隔 1 分钟」的下限，
        # 触发延迟在秒级到十秒级；超时默认 600 秒，与工具确认的等待上限同量级。
        task_scheduler_enabled=_get_bool("TASK_SCHEDULER_ENABLED", default=True),
        task_scheduler_tick_seconds=max(
            5, int(os.getenv("TASK_SCHEDULER_TICK_SECONDS", "30"))
        ),
        task_default_timeout_seconds=max(
            30, int(os.getenv("TASK_DEFAULT_TIMEOUT_SECONDS", "600"))
        ),
        task_max_per_platform=max(
            1, int(os.getenv("TASK_MAX_PER_PLATFORM", "100"))
        ),
        # 工作流默认上限比任务低：一条工作流一次运行会拆成多步、产生多条步骤记录。
        workflow_max_per_platform=max(
            1, int(os.getenv("WORKFLOW_MAX_PER_PLATFORM", "50"))
        ),
        # 运行期委派：默认单次最多 8 个子任务、同时最多 4 个（对齐 Pi subagent
        # 示例的 MAX_PARALLEL_TASKS / MAX_CONCURRENCY）。上界被工具契约（
        # input_schema 的 maxItems）与并发池实现规模夹住，配置只能把它们调小。
        delegation_max_tasks=min(8, max(1, int(os.getenv("DELEGATION_MAX_TASKS", "8")))),
        delegation_max_concurrency=min(
            8, max(1, int(os.getenv("DELEGATION_MAX_CONCURRENCY", "4")))
        ),
        # 子运行默认 8 轮（父 Agent 默认 20 轮）、整体 300 秒；单个子任务回给父模型
        # 的输出上限 50KB（对齐 Pi 的 PER_TASK_OUTPUT_CAP）。
        delegation_max_iterations=max(
            1, int(os.getenv("DELEGATION_MAX_ITERATIONS", "8"))
        ),
        delegation_timeout_seconds=max(
            30, int(os.getenv("DELEGATION_TIMEOUT_SECONDS", "300"))
        ),
        delegation_output_max_bytes=max(
            1024, int(os.getenv("DELEGATION_OUTPUT_MAX_BYTES", "51200"))
        ),
        delegation_max_agents_in_prompt=max(
            1, int(os.getenv("DELEGATION_MAX_AGENTS_IN_PROMPT", "50"))
        ),
    )
