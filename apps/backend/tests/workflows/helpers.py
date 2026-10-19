"""工作流编排测试的共用夹具。

只放「每个用例都要用、且与断言无关」的东西：

- ``make_session``：sqlite 内存库（开启外键约束）——与 ``tests/tasks`` 同一写法，
  这样部分唯一索引、级联删除等依赖真实 DDL 的行为才测得出来；
- ``seed``：平台 + 已发布 Agent + 两个用户（其一是平台管理员），
  已发布 Agent 是 ``services.create_workflow`` 的前置条件
  （``AgentRepository.get_published_agent`` 要求 default_version 已发布）；
- ``agent_step`` / ``tool_step`` / ``condition_step`` / ``predicate``：构造步骤与
  谓词 dict，避免每个用例重复拼字段。

``seed`` 用 ``session.info["seed_seq"]`` 递增后缀，避免同一用例里建第二个平台时
``Platform.code`` 唯一约束冲突（照抄 ``tests/tasks/test_scheduler.py``）。
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.agent.models import Agent, AgentVersion
from app.modules.platform.models import Platform, PlatformAdmin
from app.modules.user.models import User
from app.shared.base_model import BaseModel


async def make_session():
    """建一个 sqlite 内存库，返回 (engine, session_factory)。"""

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as connection:
        await connection.run_sync(BaseModel.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def next_suffix(session) -> int:
    """取一个会话内单调递增的后缀，用来给平台 code 去重。"""

    session.info["seed_seq"] = session.info.get("seed_seq", 0) + 1
    return session.info["seed_seq"]


async def seed(session, *, published: bool = True):
    """建平台 / Agent / 用户，返回带 platform、agent、admin、member、version 的命名空间。

    ``admin`` 与 ``member`` 都会写入 ``platform_admins``：本仓库没有独立的平台
    角色概念，能在该表里查到就算「平台成员」。真正的归属过滤发生在服务层
    ``assert_can_manage`` 与仓储的 ``owner_user_id`` 参数上。
    """

    suffix = next_suffix(session)
    platform = Platform(name=f"Acme{suffix}", code=f"acme{suffix}", is_active=True)
    session.add(platform)
    await session.flush()

    agent = Agent(platform_id=platform.id, name="Bot", slug=f"bot{suffix}")
    session.add(agent)
    await session.flush()

    version = None
    if published:
        version = AgentVersion(
            agent_id=agent.id,
            version=1,
            system_prompt="你是测试助手",
            # agent_versions.created_at 覆盖了 TimeModel 的列，没有 server_default，
            # 必须显式给值，否则 sqlite 上直接 NOT NULL 失败。
            created_at=datetime.now(UTC),
            published_at=datetime.now(UTC),
        )
        session.add(version)
        await session.flush()
        agent.default_version_id = version.id
        await session.flush()

    admin = User(
        name=f"Admin{suffix}",
        email=f"admin{suffix}@acme.dev",
        account=f"admin{suffix}",
        password="x",
    )
    member = User(
        name=f"Member{suffix}",
        email=f"member{suffix}@acme.dev",
        account=f"member{suffix}",
        password="x",
    )
    session.add_all([admin, member])
    await session.flush()
    session.add_all(
        [
            PlatformAdmin(platform_id=platform.id, user_id=admin.id),
            PlatformAdmin(platform_id=platform.id, user_id=member.id),
        ]
    )
    await session.flush()

    meta = SimpleNamespace(
        platform=platform,
        agent=agent,
        version=version,
        admin=admin,
        member=member,
    )
    return meta


async def add_published_agent(session, *, platform_id: int, slug: str):
    """在指定平台下再建一个已发布 Agent（用于跨平台越权用例）。"""

    agent = Agent(platform_id=platform_id, name=f"Bot-{slug}", slug=slug)
    session.add(agent)
    await session.flush()
    version = AgentVersion(
        agent_id=agent.id,
        version=1,
        system_prompt="你是另一个平台的助手",
        created_at=datetime.now(UTC),
        published_at=datetime.now(UTC),
    )
    session.add(version)
    await session.flush()
    agent.default_version_id = version.id
    await session.flush()
    return agent


def agent_step(step_id: str, *, prompt: str | None = None, **overrides) -> dict:
    """构造一个合法 agent 步骤 dict（``WorkflowStepInput.model_dump()`` 的形状）。"""

    step = {
        "step_id": step_id,
        "name": f"步骤 {step_id}",
        "kind": "agent",
        "depends_on": None,
        "position": None,
        "agent_id": None,
        "prompt": prompt if prompt is not None else f"执行 {step_id}",
        "tool_name": None,
        "tool_arguments": {},
        "input_bindings": {},
        "on_error": "abort",
        "max_retries": 0,
        "default_output": None,
        "timeout_seconds": None,
    }
    step.update(overrides)
    return step


def tool_step(step_id: str, tool_name: str, **overrides) -> dict:
    """构造一个合法 tool 步骤 dict。"""

    step = {
        "step_id": step_id,
        "name": f"步骤 {step_id}",
        "kind": "tool",
        "depends_on": None,
        "position": None,
        "agent_id": None,
        "prompt": None,
        "tool_name": tool_name,
        "tool_arguments": {},
        "input_bindings": {},
        "on_error": "abort",
        "max_retries": 0,
        "default_output": None,
        "timeout_seconds": None,
    }
    step.update(overrides)
    return step


def output_ref(step_id: str) -> str:
    """谓词左操作数 / 提示词里引用的 ``{{step_id.output}}`` 字面量。"""

    return "{{" + step_id + ".output}}"


def predicate(
    op: str,
    *,
    left: str | None = None,
    right: str | None = None,
    children: list[dict] | None = None,
) -> dict:
    """构造一个谓词 dict（``ConditionPredicate.model_dump()`` 的形状）。"""

    return {"op": op, "left": left, "right": right, "children": children}


def condition_step(
    step_id: str,
    *,
    branches: list[dict] | None = None,
    **overrides,
) -> dict:
    """构造一个合法 condition 步骤 dict。

    条件步骤没有执行体：``prompt`` / ``tool_name`` / ``agent_id`` /
    ``input_bindings`` 一律为空，判定结果直接来自 ``branches`` 里第一个成立的
    谓词。缺省只给一个无条件分支——它必须对**任何**上游都合法，因此不能内置
    「读某个步骤输出」的谓词；要真正判定的用例请自己传 ``branches``。
    """

    step = {
        "step_id": step_id,
        "name": f"条件 {step_id}",
        "kind": "condition",
        "depends_on": None,
        "position": None,
        "agent_id": None,
        "prompt": None,
        "tool_name": None,
        "tool_arguments": {},
        "input_bindings": {},
        "on_error": "abort",
        "max_retries": 0,
        "default_output": None,
        "timeout_seconds": None,
        "branches": (
            branches if branches is not None else [{"name": "only", "when": None}]
        ),
    }
    step.update(overrides)
    return step
