"""create_task 内置业务工具测试。

重点锁定 spec 里的约束：归属为会话用户、创建者为该 Agent、执行身份为
会话用户、受最小间隔与数量上限约束、且只创建不修改。
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.agent.models import Agent, AgentVersion
from app.modules.embed.models import PlatformEndUser
from app.modules.platform.models import Platform
from app.modules.tasks.models import Task
from app.modules.tools.business.create_task import create_task_business
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
    await session.flush()
    version = AgentVersion(
        agent_id=agent.id,
        version=1,
        system_prompt="助手",
        created_at=datetime.now(UTC),
        published_at=datetime.now(UTC),
    )
    session.add(version)
    await session.flush()
    agent.default_version_id = version.id
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


def test_tool_is_registered() -> None:
    """工具已注册，且描述里说明了无人值守与最小间隔约束。"""

    tool = BUSINESS_TOOL_REGISTRY.get("create_task")
    assert tool is not None
    assert "无人值守" in tool.description
    assert "1 分钟" in tool.description
    schema = tool.input_schema
    assert set(schema["required"]) == {"name", "prompt", "trigger_type"}
    assert schema["additionalProperties"] is False


def test_create_task_attributes_to_conversation_user_and_agent() -> None:
    """归属为会话用户，创建者为该 Agent，执行身份为会话用户。"""

    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            platform, agent, user = await _seed(session)
            result = await create_task_business(
                {
                    "name": "每日巡检",
                    "prompt": "检查服务状态并汇报",
                    "trigger_type": "cron",
                    "cron_expression": "0 9 * * *",
                    "timezone": "Asia/Shanghai",
                },
                _ctx(session, platform, agent, user),
            )
            task_id = result["task"]["id"]
            stored = await session.get(Task, task_id)
            assert stored.owner_user_id == user.id
            assert stored.created_by_type == "agent"
            assert stored.created_by_agent_id == agent.id
            assert stored.run_as_type == "user"
            assert stored.run_as_user_id == user.id
            assert stored.status == "active"
            assert stored.next_run_at is not None
            assert result["task"]["name"] == "每日巡检"
        await engine.dispose()

    asyncio.run(run())


def test_create_task_rejects_too_frequent_cron() -> None:
    """低于最小间隔的表达式被拒绝，并给出稳定错误码。"""

    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            platform, agent, user = await _seed(session)
            with pytest.raises(BusinessToolError) as exc:
                await create_task_business(
                    {
                        "name": "太频繁",
                        "prompt": "x",
                        "trigger_type": "cron",
                        "cron_expression": "*/10 * * * * *",
                    },
                    _ctx(session, platform, agent, user),
                )
            assert exc.value.code in {
                "task_interval_too_short",
                "invalid_cron_expression",
            }
        await engine.dispose()

    asyncio.run(run())


def test_create_task_once_requires_future_run_at() -> None:
    """一次性任务的时刻必须在未来。"""

    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            platform, agent, user = await _seed(session)
            with pytest.raises(BusinessToolError):
                await create_task_business(
                    {
                        "name": "过去时刻",
                        "prompt": "x",
                        "trigger_type": "once",
                        "run_at": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
                    },
                    _ctx(session, platform, agent, user),
                )
            # 合法的一次性任务可以创建
            future = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
            ok = await create_task_business(
                {
                    "name": "未来时刻",
                    "prompt": "x",
                    "trigger_type": "once",
                    "run_at": future,
                },
                _ctx(session, platform, agent, user),
            )
            assert ok["task"]["run_at"] is not None
        await engine.dispose()

    asyncio.run(run())


def test_create_task_rejects_invalid_iso_run_at() -> None:
    """run_at 不是合法 ISO 时间时给出明确错误码。"""

    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            platform, agent, user = await _seed(session)
            with pytest.raises(BusinessToolError) as exc:
                await create_task_business(
                    {
                        "name": "坏时间",
                        "prompt": "x",
                        "trigger_type": "once",
                        "run_at": "明天上午",
                    },
                    _ctx(session, platform, agent, user),
                )
            assert exc.value.code == "invalid_run_at"
        await engine.dispose()

    asyncio.run(run())


def test_create_task_requires_some_identity() -> None:
    """两种身份都没有时不创建任务，且错误信息可操作（不只给错误码）。"""

    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            platform, agent, _user = await _seed(session)
            ctx = BusinessToolContext(
                platform_id=platform.id,
                agent_id=agent.id,
                conversation_id=1,
                user_id=None,
                platform_end_user_id=None,
                session=session,
            )
            with pytest.raises(BusinessToolError) as exc:
                await create_task_business(
                    {"name": "n", "prompt": "p", "trigger_type": "cron",
                     "cron_expression": "0 9 * * *"},
                    ctx,
                )
            assert exc.value.code == "task_requires_user_identity"
            # 模型需要能读懂「为什么失败、缺什么」，而不是只有错误码。
            assert exc.value.message
            assert "身份" in exc.value.message
        await engine.dispose()

    asyncio.run(run())


def test_create_task_for_end_user_in_embed_session() -> None:
    """Embed 链路：只有终端用户身份时也能创建任务。

    这是本次 fix 的核心场景——原实现只认后台 user_id，
    导致 Embed 会话里创建任务必然失败。
    """

    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            platform, agent, _user = await _seed(session)
            end_user = PlatformEndUser(
                platform_id=platform.id, external_user_id="eu_1"
            )
            session.add(end_user)
            await session.commit()

            ctx = BusinessToolContext(
                platform_id=platform.id,
                agent_id=agent.id,
                conversation_id=1,
                user_id=None,
                platform_end_user_id=end_user.id,
                session=session,
            )
            result = await create_task_business(
                {
                    "name": "每天提醒",
                    "prompt": "整理今日待办",
                    "trigger_type": "cron",
                    "cron_expression": "0 9 * * *",
                },
                ctx,
            )
            stored = await session.get(Task, result["task"]["id"])
            # 终端用户任务没有后台归属，靠 run_as_end_user_id 标识
            assert stored.owner_user_id is None
            assert stored.run_as_type == "end_user"
            assert stored.run_as_end_user_id == end_user.id
            assert stored.run_as_user_id is None
            assert stored.created_by_type == "agent"
            assert stored.created_by_agent_id == agent.id
            assert stored.status == "active"
            assert stored.next_run_at is not None
        await engine.dispose()

    asyncio.run(run())


def test_create_task_backend_session_prefers_user_identity() -> None:
    """同时有两种身份时优先用后台用户，保持既有行为不变。"""

    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            platform, agent, user = await _seed(session)
            end_user = PlatformEndUser(
                platform_id=platform.id, external_user_id="eu_2"
            )
            session.add(end_user)
            await session.commit()

            ctx = BusinessToolContext(
                platform_id=platform.id,
                agent_id=agent.id,
                conversation_id=1,
                user_id=user.id,
                platform_end_user_id=end_user.id,
                session=session,
            )
            result = await create_task_business(
                {"name": "后台任务", "prompt": "p", "trigger_type": "cron",
                 "cron_expression": "0 9 * * *"},
                ctx,
            )
            stored = await session.get(Task, result["task"]["id"])
            assert stored.run_as_type == "user"
            assert stored.run_as_user_id == user.id
            assert stored.owner_user_id == user.id
            assert stored.run_as_end_user_id is None
        await engine.dispose()

    asyncio.run(run())


def test_tool_description_mentions_end_user() -> None:
    """工具描述不再暗示「仅后台用户」，避免模型据此拒绝终端用户请求。"""

    tool = BUSINESS_TOOL_REGISTRY.get("create_task")
    assert tool is not None
    assert "终端用户" in tool.description


def test_create_task_enforces_platform_limit(monkeypatch) -> None:
    """达到单平台任务上限后拒绝创建。"""

    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            platform, agent, user = await _seed(session)
            from app.modules.tasks import services as svc

            class _FakeSettings:
                task_max_per_platform = 1

            monkeypatch.setattr(svc, "get_settings", lambda: _FakeSettings())
            ctx = _ctx(session, platform, agent, user)
            await create_task_business(
                {"name": "first", "prompt": "p", "trigger_type": "cron",
                 "cron_expression": "0 9 * * *"},
                ctx,
            )
            with pytest.raises(BusinessToolError) as exc:
                await create_task_business(
                    {"name": "second", "prompt": "p", "trigger_type": "cron",
                     "cron_expression": "0 9 * * *"},
                    ctx,
                )
            assert exc.value.code == "task_limit_reached"
        await engine.dispose()

    asyncio.run(run())


def test_tool_does_not_touch_other_tasks() -> None:
    """工具只创建新任务，不会修改或删除已有任务。"""

    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            platform, agent, user = await _seed(session)
            existing = Task(
                platform_id=platform.id,
                agent_id=agent.id,
                owner_user_id=user.id,
                name="已存在",
                prompt="p",
                trigger_type="cron",
                cron_expression="0 9 * * *",
                timezone="UTC",
                status="paused",
                created_by_type="user",
                run_as_type="user",
                run_as_user_id=user.id,
                auto_approve=True,
                strict_approval=False,
                timeout_seconds=600,
            )
            session.add(existing)
            await session.commit()
            existing_id = existing.id

            await create_task_business(
                {"name": "新任务", "prompt": "p", "trigger_type": "cron",
                 "cron_expression": "0 10 * * *"},
                _ctx(session, platform, agent, user),
            )
            untouched = await session.get(Task, existing_id)
            assert untouched.name == "已存在"
            assert untouched.status == "paused"
        await engine.dispose()

    asyncio.run(run())
