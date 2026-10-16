"""开发环境种子：把本地环境恢复成「可登录、可对话、带样例对象」的状态。

设计要点：

- **声明式 + 幂等**：每条种子对象都先按业务键（account / code / slug / name）查一次，
  存在就复用、不存在才创建。重复执行不会产生第二份数据。
- **复用服务层**：对象一律走 `app.modules.<模块>.services` 的既有入口，保证种出来的
  状态与管理台点出来的一模一样。只有「按业务键查一次」这类只读判断才直接用 ORM
  `select`，与 `seed_demo_host_tools.py` 保持同一形态。
- **拒绝在生产执行**：`APP_ENV=production` 时直接退出，避免把开发账号写进线上库。
- **密码不入库仓**：管理员密码取自 `SEED_ADMIN_PASSWORD`，未设置时用下面的开发
  默认值（该默认值同时写在 `docs/runbooks/dev-environment.md`）。

用法见 `docs/runbooks/dev-environment.md`：

    bash apps/backend/scripts/reset_dev_db.sh
    # 只灌种子（库结构已就绪）。必须用 `python -m`：直接跑 `python scripts/seed_dev_env.py`
    # 时 sys.path[0] 是 /app/scripts，`import app` 会 ModuleNotFoundError。
    docker compose run --rm --no-deps \\
      -v "$PWD/apps/backend/scripts:/app/scripts:ro" \\
      api python -m scripts.seed_dev_env
"""

from __future__ import annotations

import asyncio
import io
import os
import zipfile
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import get_session_factory
from app.core.security import hash_password, verify_password
from app.modules.agent.models import Agent, AgentVersion
from app.modules.agent.repositories import AgentRepository
from app.modules.agent.schemas import AgentCreate, AgentVersionCreate
from app.modules.agent.services import (
    create_agent,
    create_agent_version,
    publish_agent_version,
)
from app.modules.builtin_tool.repositories import BuiltinToolRepository
from app.modules.embed.models import PlatformEmbedClient
from app.modules.embed.repositories import EmbedRepository
from app.modules.mcp.repositories import McpRepository
from app.modules.mcp.schemas import McpServerCreate
from app.modules.mcp.services import create_mcp_server
from app.modules.platform.repositories import PlatformRepository
from app.modules.platform.schemas import PlatformCreate
from app.modules.platform.services import create_platform
from app.modules.role.repositories import RoleRepository
from app.modules.skill.models import Skill
from app.modules.skill.repositories import SkillRepository
from app.modules.skill.schemas import AgentSkillBind
from app.modules.skill.services import bind_skill, import_skill_package
from app.modules.user.models import User
from app.modules.user.repositories import UserRepository
from app.modules.user.schemas import UserCreate
from app.modules.user.services import create_user
from app.modules.workflows.models import Workflow
from app.modules.workflows.schemas import WorkflowCreate, WorkflowStepInput
from app.modules.workflows.services import create_workflow

# 开发环境默认管理员密码。只在本文件与 runbook 里出现；真实密码请用
# SEED_ADMIN_PASSWORD 覆盖，不要改这里的字面量。
DEFAULT_ADMIN_PASSWORD = "admin123456"

SEED_DATA_DIR = Path(__file__).resolve().parent / "seed_data"
SKILL_SOURCE_DIR = SEED_DATA_DIR / "skills"

PLATFORM_CODE = "dev-platform"
PLATFORM_NAME = "开发平台"

ADMIN_ACCOUNT = "admin"
ADMIN_NAME = "开发管理员"
ADMIN_EMAIL = "admin@example.com"

AGENT_SLUG = "dev-assistant"
AGENT_NAME = "开发助手"
AGENT_DESCRIPTION = "开发环境默认助手：用于验证登录、会话、工具与技能链路。"
AGENT_SYSTEM_PROMPT = (
    "你是「开发助手」，服务于本仓库的本地开发与联调。"
    "回答用中文，简洁、直接。需要用户提供关键决策时调用 ask_user，"
    "不要自行假设。涉及平台信息（版本、配额、模型）时调用 get_runtime_info 查证，"
    "不要凭记忆回答。"
)

# 技能包名称保持 ASCII：`import_skill_package` 的包 slug 由名称 slugify 得到，
# 中文名称会退化成 "skill"，让「按 slug 判存在」失去区分度。
SKILL_PACKAGE_NAME = "dev-sample-skill"

MCP_SERVER_SLUG = "dev-sample-mcp"
MCP_SERVER_NAME = "开发样例 MCP"
# 仅用于占位的配置示例，不指向真实服务；管理台「同步工具」会连不通，属预期。
MCP_SERVER_ENDPOINT = "https://example.com/mcp"

WORKFLOW_NAME = "开发助手单步流程"

# 开发环境默认打开的 Agent 内置工具。`ask_user` 由网关直连处理，
# `get_runtime_info` 只读，`http_get` 用来验证带出网的工具调用链路。
ENABLED_BUILTIN_TOOLS = ("ask_user", "get_runtime_info", "http_get")


def _admin_password() -> str:
    return os.getenv("SEED_ADMIN_PASSWORD") or DEFAULT_ADMIN_PASSWORD


async def _ensure_admin(session) -> User:
    """建或复用管理员账号。

    平台管理员在本仓库就等于「`platform_admins` 里有一行」（见
    `app/modules/tasks/router.py` 的注释），所以只要有一个 `sys_users` 用户
    加一个平台即可，不需要任何角色。
    """
    repo = UserRepository(session)
    password = _admin_password()
    user = await repo.get_by_account(ADMIN_ACCOUNT)
    if user is None:
        await create_user(
            repo,
            RoleRepository(session),
            UserCreate(
                name=ADMIN_NAME,
                email=ADMIN_EMAIL,
                account=ADMIN_ACCOUNT,
                password=password,
            ),
        )
        user = await repo.get_by_account(ADMIN_ACCOUNT)
        if user is None:  # pragma: no cover - 创建成功却查不到属数据库异常
            raise RuntimeError("管理员账号创建后查询失败")
        return user

    # 声明式：这个账号的密码以 SEED_ADMIN_PASSWORD 为准，改了变量重跑即生效。
    # `UserRepository` 没有「改密码」入口（管理台也不允许改别人的密码），
    # 因此这里直接写哈希列。
    if not verify_password(password, user.password):
        print("· 管理员密码与 SEED_ADMIN_PASSWORD 不一致，已按变量值重置")
        user.password = hash_password(password)
        await session.commit()
    return user


async def _ensure_platform(session, admin: User):
    repo = PlatformRepository(session)
    platform = await repo.get_by_code(PLATFORM_CODE)
    if platform is not None:
        return platform
    await create_platform(
        repo,
        PlatformCreate(name=PLATFORM_NAME, code=PLATFORM_CODE),
        user_id=admin.id,
    )
    platform = await repo.get_by_code(PLATFORM_CODE)
    if platform is None:  # pragma: no cover
        raise RuntimeError("平台创建后查询失败")
    return platform


async def _ensure_agent(session, platform_id: int):
    """建或复用 Agent，并保证它有一个已发布版本。

    「可对话」的硬条件是 `default_version_id` 非空且对应版本 `published_at`
    非空，因此必须走 `publish_agent_version`，不能只插一行 `agent_versions`。
    """
    repo = AgentRepository(session)
    agent = await repo.get_by_slug(platform_id, AGENT_SLUG)
    if agent is None:
        agent = await create_agent(
            repo,
            AgentCreate(
                name=AGENT_NAME,
                slug=AGENT_SLUG,
                description=AGENT_DESCRIPTION,
            ),
            platform_id=platform_id,
        )

    versions = await repo.list_versions(agent.id)
    if agent.default_version_id is not None:
        return agent
    if versions:
        version = versions[-1]
    else:
        settings = get_settings()
        version = await create_agent_version(
            repo,
            agent.id,
            AgentVersionCreate(
                system_prompt=AGENT_SYSTEM_PROMPT,
                # 模型名沿用平台默认；base_url 与 api_key 留空表示继承运行栈的
                # OPENAI_BASE_URL / OPENAI_API_KEY 环境变量，种子不持有密钥。
                model_name=settings.model_default_name,
                model_base_url=settings.model_default_base_url,
            ),
            platform_id=platform_id,
        )
    await publish_agent_version(
        repo, agent.id, version.id, platform_id=platform_id
    )
    agent = await session.get(Agent, agent.id)
    if agent is None:  # pragma: no cover
        raise RuntimeError("Agent 发布后查询失败")
    return agent


async def _seed_builtin_tools(session, platform_id: int, agent_id: int) -> list[str]:
    repo = BuiltinToolRepository(session)
    enabled: list[str] = []
    for name in ENABLED_BUILTIN_TOOLS:
        binding = await repo.set_binding(
            platform_id, agent_id, name, is_enabled=True
        )
        if binding is not None:
            enabled.append(name)
    return enabled


async def _zip_skill_source(source_dir: Path) -> bytes:
    """把仓库内的技能包源目录打包成 zip 字节。

    `import_skill_package` 只接受 zip，而 `skill/source_resolver.py` 只认
    github.com，所以仓库内的源文件必须在这里现场打包——但落库与落盘仍然走
    与管理员后台上传完全相同的那条链路。
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source_dir.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(source_dir).as_posix())
    return buffer.getvalue()


async def _ensure_skill(session, platform_id: int, agent_id: int):
    """导入并绑定仓库内置的示例技能包。"""
    repo = SkillRepository(session)
    package = await repo.get_package_by_slug(platform_id, SKILL_PACKAGE_NAME)
    if package is None:
        content = await _zip_skill_source(SKILL_SOURCE_DIR / SKILL_PACKAGE_NAME)
        package = await import_skill_package(
            repo,
            platform_id,
            filename=f"{SKILL_PACKAGE_NAME}.zip",
            content=content,
            package_name=SKILL_PACKAGE_NAME,
        )
    skill = await session.scalar(
        select(Skill)
        .where(Skill.package_id == package.id)
        .order_by(Skill.id)
    )
    if skill is None:  # pragma: no cover - 解析器保证至少一个技能
        raise RuntimeError("技能包内没有解析出技能")
    await bind_skill(
        repo, platform_id, agent_id, AgentSkillBind(skill_id=skill.id)
    )
    return package, skill


async def _ensure_mcp_server(session, platform_id: int, agent_id: int):
    """建一个 MCP 服务配置行并绑定给 Agent。

    只写配置：`mcp_tools` 需要 `sync_mcp_tools` 连真实端点才能生成，
    占位地址连不通属预期，管理台里能看到「已配置、工具未同步」的状态。
    """
    repo = McpRepository(session)
    server = await repo.get_server_by_slug(platform_id, MCP_SERVER_SLUG)
    if server is None:
        server = await create_mcp_server(
            repo,
            platform_id,
            McpServerCreate(
                name=MCP_SERVER_NAME,
                slug=MCP_SERVER_SLUG,
                endpoint_url=MCP_SERVER_ENDPOINT,
            ),
        )
    await repo.bind_server(platform_id, agent_id, server.id)
    return server


async def _ensure_workflow(session, platform_id: int, agent_id: int, admin_id: int):
    """建一条只含单个 agent 步骤的工作流。

    不造 `kind="tool"` 步骤：保存期会强校验「该工具已在这个 Agent 的可用清单里」
    （`workflows/services.py` 的 `_ensure_tool_step_available`），而工具清单本身
    已经由 `_seed_builtin_tools` 覆盖，属于另一条验收路径。
    """
    existing = await session.scalar(
        select(Workflow).where(
            Workflow.platform_id == platform_id, Workflow.name == WORKFLOW_NAME
        )
    )
    if existing is not None:
        return existing
    return await create_workflow(
        session,
        platform_id=platform_id,
        payload=WorkflowCreate(
            name=WORKFLOW_NAME,
            agent_id=agent_id,
            description="开发环境单步编排：只用一个 agent 步骤，用于验证工作流链路。",
            steps=[
                WorkflowStepInput(
                    step_id="draft",
                    name="生成回复",
                    kind="agent",
                    agent_id=agent_id,
                    # 显式空依赖 = 起点步骤；省略则被解释为「依赖前一个步骤」。
                    depends_on=[],
                    prompt="{{input}}",
                )
            ],
        ),
        owner_user_id=admin_id,
        created_by_type="user",
        created_by_user_id=admin_id,
    )


async def _ensure_embed_client(session, platform_id: int, agent_id: int):
    """按 .env 里已有的 client_id 重建 embed client。

    `client_id` 在模型上是普通列（`app/modules/embed/models.py`），所以种子可以
    写死成 `EMBED_CLIENT_ID` 的值——这样清库之后根 `.env` 不用改就能继续用；
    而 `create_embed_client` 服务会随机生成 id，不适合种子。
    """
    settings = get_settings()
    if not settings.embed_client_id or not settings.embed_client_secret:
        print("· 未配置 EMBED_CLIENT_ID / EMBED_CLIENT_SECRET，跳过 embed client")
        return None

    repo = EmbedRepository(session)
    client = await session.scalar(
        select(PlatformEmbedClient).where(
            PlatformEmbedClient.client_id == settings.embed_client_id
        )
    )
    if client is None:
        client = await repo.create_client(
            platform_id=platform_id,
            client_id=settings.embed_client_id,
            name="开发环境嵌入客户端",
            secret_hash=hash_password(settings.embed_client_secret),
            allowed_origins=[settings.embed_origin] if settings.embed_origin else [],
            token_ttl_seconds=600,
        )
        await session.commit()
        await session.refresh(client)
    if not await repo.is_agent_allowed(client.id, agent_id):
        await repo.bind_agent(client.id, agent_id)
    return client


async def seed() -> None:
    settings = get_settings()
    if settings.app_env == "production":
        raise RuntimeError("拒绝在 production 环境执行开发种子脚本")

    async with get_session_factory()() as session:
        admin = await _ensure_admin(session)
        platform = await _ensure_platform(session, admin)
        agent = await _ensure_agent(session, platform.id)
        builtin_tools = await _seed_builtin_tools(session, platform.id, agent.id)
        package, skill = await _ensure_skill(session, platform.id, agent.id)
        server = await _ensure_mcp_server(session, platform.id, agent.id)
        workflow = await _ensure_workflow(
            session, platform.id, agent.id, admin.id
        )
        client = await _ensure_embed_client(session, platform.id, agent.id)
        files = len(package.files) if package.files is not None else 0

    print("开发环境种子完成：")
    print(f"  · 平台：{PLATFORM_NAME}（id={platform.id}，code={PLATFORM_CODE}）")
    print(f"  · 管理员：{ADMIN_ACCOUNT} / 见 SEED_ADMIN_PASSWORD 或开发默认密码")
    print(f"  · Agent：{AGENT_NAME}（id={agent.id}，slug={AGENT_SLUG}）")
    print(f"  · 内置工具：{', '.join(builtin_tools) or '（无）'}")
    print(f"  · 技能包：{package.name}（slug={package.slug}，{files} 个文件）")
    print(f"    绑定技能：{skill.name}（slug={skill.slug}）")
    print(f"  · MCP 配置：{server.name}（slug={server.slug}，未同步工具）")
    print(f"  · 工作流：{workflow.name}（id={workflow.id}，status={workflow.status}）")
    if client is None:
        print("  · Embed Client：（跳过）")
    else:
        print(f"  · Embed Client：{client.client_id}")
    if settings.embed_agent_id != agent.id:
        print(
            f"  ! 注意：.env 的 EMBED_AGENT_ID={settings.embed_agent_id} 与种子 "
            f"Agent id={agent.id} 不一致，请改 .env"
        )


if __name__ == "__main__":
    asyncio.run(seed())
