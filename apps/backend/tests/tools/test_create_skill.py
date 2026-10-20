"""create_skill 内置业务工具测试。

锁定三件事：技能落在当前平台、创建后自动绑定当前 Agent（否则 load_skill
看不到）、slug 冲突时给稳定错误码而不是覆盖或抛栈。
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.agent.models import Agent
from app.modules.platform.models import Platform
from app.modules.skill.models import AgentSkill, Skill
from app.modules.tools.business.create_skill import create_skill_business
from app.modules.tools.business.framework import (
    BUSINESS_TOOL_REGISTRY,
    BusinessToolContext,
    BusinessToolError,
)
from app.modules.user.models import User
from app.shared.base_model import BaseModel


async def _make_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as connection:
        await connection.run_sync(BaseModel.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _seed(session):
    platform = Platform(name="Acme", code="acme", is_active=True)
    session.add(platform)
    await session.flush()
    agent = Agent(platform_id=platform.id, name="Bot", slug="bot")
    user = User(name="U", email="u@acme.dev", account="u", password="x")
    session.add_all([agent, user])
    await session.commit()
    return platform, agent, user


def _ctx(session, platform, agent, user) -> BusinessToolContext:
    return BusinessToolContext(
        platform_id=platform.id,
        agent_id=agent.id,
        conversation_id=1,
        user_id=user.id,
        session=session,
    )


def test_tool_is_registered_with_write_side_effect() -> None:
    """工具已注册、声明写副作用，且描述说明会绑定到当前 Agent。"""

    tool = BUSINESS_TOOL_REGISTRY.get("create_skill")
    assert tool is not None
    assert tool.side_effect == "write"
    assert "load_skill" in tool.description
    assert "绑定" in tool.description
    schema = tool.input_schema
    assert set(schema["required"]) == {"name", "instruction_template"}
    assert schema["additionalProperties"] is False


def test_creates_platform_skill_and_binds_current_agent() -> None:
    """技能写入当前平台，并自动绑定到当前 Agent。"""

    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            platform, agent, user = await _seed(session)
            result = await create_skill_business(
                {
                    "name": "每周日报",
                    "slug": "weekly-report",
                    "description": "生成固定格式的每周工作日报",
                    "instruction_template": "## 步骤\n1. 汇总本周进展\n2. 按模板输出",
                },
                _ctx(session, platform, agent, user),
            )
            skill_id = result["skill"]["id"]
            stored = await session.get(Skill, skill_id)
            assert stored.platform_id == platform.id
            assert stored.package_id is None
            assert stored.slug == "weekly-report"
            assert stored.name == "每周日报"
            assert stored.description == "生成固定格式的每周工作日报"
            assert stored.instruction_template.startswith("## 步骤")
            assert stored.is_active is True

            binding = await session.scalar(
                select(AgentSkill).where(AgentSkill.skill_id == skill_id)
            )
            assert binding is not None
            assert binding.agent_id == agent.id
            assert binding.is_enabled is True
            assert binding.sort_order == 0
            assert result["binding"]["agent_id"] == agent.id
            assert "下一轮" in result["message"]
        await engine.dispose()

    asyncio.run(run())


def test_derives_unique_slug_when_name_is_chinese() -> None:
    """纯中文名退化为 skill 时自动加序号，且绑定顺序追加到末尾。"""

    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            platform, agent, user = await _seed(session)
            payload = {"name": "周报助手", "instruction_template": "按周报模板输出"}
            first = await create_skill_business(
                dict(payload), _ctx(session, platform, agent, user)
            )
            second = await create_skill_business(
                dict(payload), _ctx(session, platform, agent, user)
            )

            assert first["skill"]["slug"] == "skill"
            assert second["skill"]["slug"] == "skill-2"
            assert first["binding"]["sort_order"] == 0
            assert second["binding"]["sort_order"] == 1

            bindings = list(
                (
                    await session.execute(
                        select(AgentSkill).order_by(AgentSkill.sort_order)
                    )
                ).scalars()
            )
            assert [item.skill_id for item in bindings] == [
                first["skill"]["id"],
                second["skill"]["id"],
            ]
        await engine.dispose()

    asyncio.run(run())


def test_explicit_slug_conflict_is_a_stable_error() -> None:
    """显式 slug 已存在时报稳定错误码，且不创建第二条技能。"""

    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            platform, agent, user = await _seed(session)
            session.add(
                Skill(
                    platform_id=platform.id,
                    name="已有技能",
                    slug="daily-report",
                    instruction_template="x",
                )
            )
            await session.commit()

            with pytest.raises(BusinessToolError) as exc:
                await create_skill_business(
                    {
                        "name": "重复技能",
                        "slug": "daily-report",
                        "instruction_template": "y",
                    },
                    _ctx(session, platform, agent, user),
                )
            assert exc.value.code == "skill_slug_exists"

            skills = list((await session.execute(select(Skill))).scalars())
            assert len(skills) == 1
        await engine.dispose()

    asyncio.run(run())


def test_missing_instruction_is_rejected() -> None:
    """缺少指令正文时不落库，返回参数错误。"""

    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            platform, agent, user = await _seed(session)
            with pytest.raises(BusinessToolError) as exc:
                await create_skill_business(
                    {"name": "空技能"}, _ctx(session, platform, agent, user)
                )
            assert exc.value.code == "invalid_arguments"
            assert (await session.execute(select(Skill))).first() is None
        await engine.dispose()

    asyncio.run(run())


def test_bind_failure_keeps_skill_and_returns_stable_error() -> None:
    """Agent 不属于当前平台时绑定失败：技能已落库，错误码提示手工绑定。"""

    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            platform, agent, user = await _seed(session)
            other_platform = Platform(name="Other", code="other", is_active=True)
            session.add(other_platform)
            await session.flush()
            other_agent = Agent(
                platform_id=other_platform.id, name="OtherBot", slug="other-bot"
            )
            session.add(other_agent)
            await session.commit()

            with pytest.raises(BusinessToolError) as exc:
                await create_skill_business(
                    {"name": "跨平台", "instruction_template": "x"},
                    _ctx(session, platform, other_agent, user),
                )
            assert exc.value.code == "skill_bind_failed"

            skill = await session.scalar(select(Skill))
            assert skill is not None
            binding = await session.scalar(select(AgentSkill))
            assert binding is None
        await engine.dispose()

    asyncio.run(run())
