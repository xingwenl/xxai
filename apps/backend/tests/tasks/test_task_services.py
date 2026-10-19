"""任务业务规则测试（sqlite 内存库）。

覆盖：最小间隔拒绝、数量上限、暂停/恢复语义、可见性与管理权限、
一次性任务跑完即止、手动运行的串行约束。
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.agent.models import Agent, AgentVersion
from app.modules.platform.models import Platform
from app.modules.tasks import services
from app.modules.tasks.models import Task
from app.modules.tasks.schemas import TaskCreate, TaskUpdate
from app.modules.user.models import User
from app.shared.base_model import BaseModel
from app.shared.exceptions import BadRequestException, ConflictException, NotFoundException
from app.shared.pagination import PaginationParams


async def _make_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as connection:
        await connection.run_sync(BaseModel.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _seed(session):
    """建平台 + 已发布智能体 + 两个用户。"""

    platform = Platform(name="Acme", code="acme", is_active=True)
    session.add(platform)
    await session.flush()
    agent = Agent(platform_id=platform.id, name="Bot", slug="bot")
    admin = User(name="Admin", email="a@acme.dev", account="admin", password="x")
    member = User(name="Member", email="m@acme.dev", account="member", password="x")
    session.add_all([agent, admin, member])
    await session.flush()
    version = AgentVersion(
        agent_id=agent.id,
        version=1,
        system_prompt="你是定时任务助手",
        temperature=0.2,
        created_at=datetime.now(UTC),
        published_at=datetime.now(UTC),
    )
    session.add(version)
    await session.flush()
    agent.default_version_id = version.id
    await session.commit()
    return platform, agent, admin, member


def _payload(agent_id: int, **overrides) -> TaskCreate:
    data = {
        "name": "task",
        "prompt": "do it",
        "agent_id": agent_id,
        "trigger_type": "cron",
        "cron_expression": "0 9 * * *",
        "timezone": "Asia/Shanghai",
    }
    data.update(overrides)
    return TaskCreate(**data)


def test_create_task_rejects_too_frequent_cron() -> None:
    """低于最小间隔下限（这里用秒级六段式与非法表达式）必须被拒绝。"""

    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            platform, agent, admin, _member = await _seed(session)
            with pytest.raises(BadRequestException):
                await services.create_task(
                    session,
                    platform_id=platform.id,
                    payload=_payload(agent.id, cron_expression="*/10 * * * * *"),
                    owner_user_id=admin.id,
                )
            with pytest.raises(BadRequestException):
                await services.create_task(
                    session,
                    platform_id=platform.id,
                    payload=_payload(agent.id, cron_expression="bad cron"),
                    owner_user_id=admin.id,
                )
        await engine.dispose()

    asyncio.run(run())


def test_create_task_accepts_one_minute_interval() -> None:
    """每分钟触发处于下限，必须被接受。"""

    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            platform, agent, admin, _member = await _seed(session)
            task = await services.create_task(
                session,
                platform_id=platform.id,
                payload=_payload(agent.id, cron_expression="* * * * *"),
                owner_user_id=admin.id,
            )
            assert task.id is not None
            assert task.status == "active"
            assert task.next_run_at is not None
            assert task.run_as_user_id == admin.id
        await engine.dispose()

    asyncio.run(run())


def test_create_task_rejects_agent_from_other_platform() -> None:
    """只能选用本平台已发布的智能体，否则任务到点必然失败。"""

    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            platform, agent, admin, _member = await _seed(session)
            other = Platform(name="Other", code="other", is_active=True)
            session.add(other)
            await session.flush()
            with pytest.raises(BadRequestException):
                await services.create_task(
                    session,
                    platform_id=other.id,
                    payload=_payload(agent.id),
                    owner_user_id=admin.id,
                )
            # 未发布的智能体同样不可用
            unpublished = Agent(platform_id=platform.id, name="Draft", slug="draft")
            session.add(unpublished)
            await session.flush()
            with pytest.raises(BadRequestException):
                await services.create_task(
                    session,
                    platform_id=platform.id,
                    payload=_payload(unpublished.id),
                    owner_user_id=admin.id,
                )
        await engine.dispose()

    asyncio.run(run())


def test_create_task_enforces_platform_limit(monkeypatch) -> None:
    """达到单平台任务数上限后再创建返回冲突。"""

    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            platform, agent, admin, _member = await _seed(session)
            from app.modules.tasks import services as svc

            class _FakeSettings:
                task_max_per_platform = 1

            monkeypatch.setattr(svc, "get_settings", lambda: _FakeSettings())
            await svc.create_task(
                session,
                platform_id=platform.id,
                payload=_payload(agent.id, name="first"),
                owner_user_id=admin.id,
            )
            with pytest.raises(ConflictException):
                await svc.create_task(
                    session,
                    platform_id=platform.id,
                    payload=_payload(agent.id, name="second"),
                    owner_user_id=admin.id,
                )
        await engine.dispose()

    asyncio.run(run())


def test_pause_and_resume_recompute_next_run_at() -> None:
    """暂停清空 next_run_at；恢复后重算，且不补跑历史触发点。"""

    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            platform, agent, admin, _member = await _seed(session)
            task = await services.create_task(
                session,
                platform_id=platform.id,
                payload=_payload(agent.id),
                owner_user_id=admin.id,
            )
            assert task.next_run_at is not None

            paused = await services.update_task(
                session, task, TaskUpdate(status="paused")
            )
            assert paused.status == "paused"
            assert paused.next_run_at is None

            resumed = await services.update_task(
                session, task, TaskUpdate(status="active")
            )
            assert resumed.status == "active"
            assert resumed.next_run_at is not None
            # 恢复后的触发点必须晚于当前时刻（不补跑）
            anchor = resumed.next_run_at
            if anchor.tzinfo is None:
                anchor = anchor.replace(tzinfo=UTC)
            assert anchor > datetime.now(UTC) - timedelta(seconds=5)
        await engine.dispose()

    asyncio.run(run())


def test_once_task_is_exhausted_after_run() -> None:
    """一次性任务跑完后 next_run_at 变为 None，不会重复触发。"""

    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            platform, agent, admin, _member = await _seed(session)
            future = datetime.now(UTC) + timedelta(hours=1)
            task = await services.create_task(
                session,
                platform_id=platform.id,
                payload=_payload(
                    agent.id, trigger_type="once", run_at=future, cron_expression=None
                ),
                owner_user_id=admin.id,
            )
            assert task.next_run_at is not None

            # 模拟调度推进：把触发点当作已到，重算应返回 None
            task.next_run_at = datetime.now(UTC) - timedelta(seconds=1)
            await session.commit()
            advanced = await services.update_task(
                session, task, TaskUpdate(status="active")
            )
            assert advanced.next_run_at is None
        await engine.dispose()

    asyncio.run(run())


def test_once_task_requires_future_run_at() -> None:
    """一次性任务的时刻必须在未来，过去时刻被拒绝。"""

    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            platform, agent, admin, _member = await _seed(session)
            with pytest.raises(BadRequestException):
                await services.create_task(
                    session,
                    platform_id=platform.id,
                    payload=_payload(
                        agent.id,
                        trigger_type="once",
                        run_at=datetime.now(UTC) - timedelta(hours=1),
                        cron_expression=None,
                    ),
                    owner_user_id=admin.id,
                )
        await engine.dispose()

    asyncio.run(run())


def test_assert_can_manage_permissions() -> None:
    """平台级任务只有管理员能管；个人任务只有本人能管。"""

    platform_task = Task(id=1, owner_user_id=None)
    member_task = Task(id=2, owner_user_id=7)

    # 本人可管自己的任务
    services.assert_can_manage(member_task, user_id=7, is_platform_admin=False)
    # 管理员可管任意任务
    services.assert_can_manage(member_task, user_id=99, is_platform_admin=True)
    services.assert_can_manage(platform_task, user_id=99, is_platform_admin=True)

    # 他人不能管别人的个人任务，也不能管平台级任务
    with pytest.raises(NotFoundException):
        services.assert_can_manage(member_task, user_id=8, is_platform_admin=False)
    with pytest.raises(NotFoundException):
        services.assert_can_manage(platform_task, user_id=8, is_platform_admin=False)


def test_manual_run_is_serialized() -> None:
    """手动运行同样受串行约束：已有 running 时记为 skipped(overlapped)。"""

    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            platform, agent, admin, _member = await _seed(session)
            task = await services.create_task(
                session,
                platform_id=platform.id,
                payload=_payload(agent.id),
                owner_user_id=admin.id,
            )
            first, started_first = await services.enqueue_manual_run(session, task)
            assert started_first is True
            assert first.status == "running"
            assert first.trigger_kind == "manual"

            second, started_second = await services.enqueue_manual_run(session, task)
            assert started_second is False
            assert second.status == "skipped"
            assert second.skip_reason == "overlapped"

            # 结束后可以再次手动运行
            from app.modules.tasks.repositories import TaskRunRepository

            await TaskRunRepository(session).finish_run(first, status="completed")
            await session.commit()
            third, started_third = await services.enqueue_manual_run(session, task)
            assert started_third is True
            assert third.status == "running"
        await engine.dispose()

    asyncio.run(run())


def test_list_tasks_visibility() -> None:
    """列表可见性：管理员全平台，普通用户只看自己。"""

    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            platform, agent, admin, member = await _seed(session)
            await services.create_task(
                session,
                platform_id=platform.id,
                payload=_payload(agent.id, name="admin-task"),
                owner_user_id=admin.id,
            )
            await services.create_task(
                session,
                platform_id=platform.id,
                payload=_payload(agent.id, name="member-task"),
                owner_user_id=member.id,
            )
            params = PaginationParams(page=1, page_size=20)

            admin_page = await services.list_tasks(
                session, platform_id=platform.id, params=params, owner_user_id=None
            )
            assert admin_page.total == 2

            member_page = await services.list_tasks(
                session,
                platform_id=platform.id,
                params=params,
                owner_user_id=member.id,
            )
            assert member_page.total == 1
            assert member_page.items[0].name == "member-task"
        await engine.dispose()

    asyncio.run(run())


def test_get_task_or_404_is_platform_scoped() -> None:
    """跨平台读取任务应当 404，而不是泄露存在性。"""

    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            platform, agent, admin, _member = await _seed(session)
            task = await services.create_task(
                session,
                platform_id=platform.id,
                payload=_payload(agent.id),
                owner_user_id=admin.id,
            )
            other = Platform(name="Other2", code="other2", is_active=True)
            session.add(other)
            await session.flush()

            with pytest.raises(NotFoundException):
                await services.get_task_or_404(
                    session, task_id=task.id, platform_id=other.id
                )
            found = await services.get_task_or_404(
                session, task_id=task.id, platform_id=platform.id
            )
            assert found.id == task.id
        await engine.dispose()

    asyncio.run(run())


def test_get_run_detail_returns_steps() -> None:
    """执行详情按 agent_loop_run_id 组装出步骤清单。"""

    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            platform, agent, admin, _member = await _seed(session)
            task = await services.create_task(
                session,
                platform_id=platform.id,
                payload=_payload(agent.id),
                owner_user_id=admin.id,
            )
            # 造一个带步骤的 loop，并挂到 task_run 上
            from app.modules.conversation.models import (
                AgentLoopRun,
                AgentLoopStep,
                Conversation,
            )
            from app.modules.tasks.models import TaskRun

            conversation = Conversation(
                platform_id=platform.id,
                agent_id=agent.id,
                user_id=admin.id,
                title="任务执行",
            )
            session.add(conversation)
            await session.flush()
            loop = AgentLoopRun(
                conversation_id=conversation.id,
                request_id="svc-detail",
                status="completed",
                summary="一轮完成",
            )
            session.add(loop)
            await session.flush()
            session.add(
                AgentLoopStep(
                    loop_run_id=loop.id,
                    sequence=1,
                    step_type="builtin_tool",
                    title="调用工具：create_task",
                    status="succeeded",
                    tool_name="create_task",
                    output_summary='工具执行完成：{"kind":"create_task"}',
                )
            )
            task_run = TaskRun(
                task_id=task.id,
                status="completed",
                trigger_kind="scheduled",
                conversation_id=conversation.id,
                agent_loop_run_id=loop.id,
            )
            session.add(task_run)
            await session.commit()

            detail = await services.get_run_detail(
                session, task=task, run_id=task_run.id
            )
            assert detail.loop_id == str(loop.id)
            assert detail.loop_status == "completed"
            assert len(detail.steps) == 1
            step = detail.steps[0]
            assert step.tool_name == "create_task"
            assert step.sequence == 1
            assert step.step_type == "builtin_tool"
        await engine.dispose()

    asyncio.run(run())


def test_get_run_detail_empty_when_never_executed() -> None:
    """从未执行的运行（无 loop/会话）返回空步骤，而不是报错。

    这是排查「执行超时」的关键区分：没有步骤说明它从未真正开始，
    而不是执行到一半失败。
    """

    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            platform, agent, admin, _member = await _seed(session)
            task = await services.create_task(
                session,
                platform_id=platform.id,
                payload=_payload(agent.id),
                owner_user_id=admin.id,
            )
            from app.modules.tasks.repositories import TaskRunRepository

            task_run = await TaskRunRepository(session).create_run(
                task_id=task.id,
                status="failed",
                trigger_kind="manual",
            )
            await session.commit()

            detail = await services.get_run_detail(
                session, task=task, run_id=task_run.id
            )
            assert detail.steps == []
            assert detail.loop_id is None
            # 未使用委派时字段为 None（前端据此静默不渲染）
            assert detail.delegatedRuns is None
        await engine.dispose()

    asyncio.run(run())


def test_get_run_detail_exposes_delegated_runs() -> None:
    """委派子运行在任务详情里可读：步骤带子运行 ID，详情带子运行摘要。

    任务详情不经会话页，委派结果只能靠这份投影看见；字段名与 conversation
    侧契约一致（camelCase），前端两处渲染共用同一形状。
    """

    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            platform, agent, admin, _member = await _seed(session)
            task = await services.create_task(
                session,
                platform_id=platform.id,
                payload=_payload(agent.id),
                owner_user_id=admin.id,
            )
            from app.modules.conversation.models import (
                AgentLoopRun,
                AgentLoopStep,
                Conversation,
            )
            from app.modules.tasks.models import TaskRun

            parent_conversation = Conversation(
                platform_id=platform.id,
                agent_id=agent.id,
                user_id=admin.id,
                title="父会话",
            )
            session.add(parent_conversation)
            await session.flush()
            parent_loop = AgentLoopRun(
                conversation_id=parent_conversation.id,
                request_id="svc-delegated",
                status="completed",
            )
            session.add(parent_loop)
            await session.flush()

            child_conversation = Conversation(
                platform_id=platform.id,
                agent_id=agent.id,
                user_id=admin.id,
                title="子会话",
            )
            session.add(child_conversation)
            await session.flush()
            child_loop = AgentLoopRun(
                conversation_id=child_conversation.id,
                request_id="svc-delegated-child",
                status="completed",
                summary="子运行完成",
                parent_loop_run_id=parent_loop.id,
            )
            session.add(child_loop)
            await session.flush()

            session.add(
                AgentLoopStep(
                    loop_run_id=parent_loop.id,
                    sequence=1,
                    step_type="builtin_tool",
                    title="调用工具：delegate_tasks",
                    status="succeeded",
                    tool_name="delegate_tasks",
                    step_metadata={"delegatedRunIds": [str(child_loop.id)]},
                )
            )
            task_run = TaskRun(
                task_id=task.id,
                status="completed",
                trigger_kind="scheduled",
                conversation_id=parent_conversation.id,
                agent_loop_run_id=parent_loop.id,
            )
            session.add(task_run)
            await session.commit()

            detail = await services.get_run_detail(
                session, task=task, run_id=task_run.id
            )
            assert detail.steps[0].delegatedRunIds == [str(child_loop.id)]
            assert detail.delegatedRuns is not None
            child = detail.delegatedRuns[0]
            assert child.id == str(child_loop.id)
            assert child.agentSlug == agent.slug
            assert child.status == "completed"
            assert child.summary == "子运行完成"
            assert child.conversationId == str(child_conversation.id)
            # 序列化后的键名是前端契约（camelCase），不能退化成 snake_case
            assert set(child.model_dump()) == {
                "id",
                "agentSlug",
                "agentName",
                "status",
                "summary",
                "conversationId",
            }
        await engine.dispose()

    asyncio.run(run())


def test_get_run_detail_rejects_other_task_run() -> None:
    """跨任务的 run_id 不能读到别人的执行过程。"""

    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            platform, agent, admin, _member = await _seed(session)
            task_a = await services.create_task(
                session,
                platform_id=platform.id,
                payload=_payload(agent.id, name="a"),
                owner_user_id=admin.id,
            )
            from app.modules.tasks.repositories import TaskRunRepository

            run_b = await TaskRunRepository(session).create_run(
                task_id=(await services.create_task(
                    session,
                    platform_id=platform.id,
                    payload=_payload(agent.id, name="b"),
                    owner_user_id=admin.id,
                )).id,
                status="completed",
                trigger_kind="scheduled",
            )
            await session.commit()

            with pytest.raises(NotFoundException):
                await services.get_run_detail(
                    session, task=task_a, run_id=run_b.id
                )
        await engine.dispose()

    asyncio.run(run())
