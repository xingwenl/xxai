"""任务执行编排测试。

这里不碰真实模型：把 ``execute_unattended_chat`` 换成替身，验证编排本身
的语义——每轮新建会话、超时记为失败、异常兜底留痕、暂停任务跳过、
以及自动批准次数与运行记录的回写。
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.agent.models import Agent
from app.modules.embed.models import PlatformEndUser
from app.modules.platform.models import Platform
from app.modules.tasks import runner
from app.modules.tasks.models import TaskRun
from app.modules.tasks.repositories import TaskRepository
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


async def _seed(session, **task_overrides):
    platform = Platform(name="Acme", code="acme", is_active=True)
    session.add(platform)
    await session.flush()
    agent = Agent(platform_id=platform.id, name="Bot", slug="bot")
    user = User(name="Admin", email="a@acme.dev", account="admin", password="x")
    session.add_all([agent, user])
    await session.flush()

    data = {
        "platform_id": platform.id,
        "agent_id": agent.id,
        "owner_user_id": user.id,
        "name": "task",
        "prompt": "do it",
        "trigger_type": "cron",
        "cron_expression": "0 9 * * *",
        "timezone": "UTC",
        "status": "active",
        "next_run_at": datetime.now(UTC),
        "created_by_type": "user",
        "run_as_type": "user",
        "run_as_user_id": user.id,
        "auto_approve": True,
        "strict_approval": False,
        "timeout_seconds": 600,
    }
    data.update(task_overrides)
    task = await TaskRepository(session).create(**data)
    return platform, agent, user, task


def _patch_execution(monkeypatch, fake):
    monkeypatch.setattr(runner, "execute_unattended_chat", fake)


def test_runner_completes_and_writes_conversation(monkeypatch) -> None:
    """成功执行：写回 completed、会话 id、loop id 与自动批准次数。"""

    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            _platform, _agent, _user, task = await _seed(session)
            session.add(
                TaskRun(task_id=task.id, status="running", trigger_kind="scheduled")
            )
            await session.commit()
            run_id = (
                await session.execute(
                    select(TaskRun.id).where(TaskRun.task_id == task.id)
                )
            ).scalar_one()

        captured: dict = {}

        async def fake_execute(session, **kwargs):
            captured.update(kwargs)
            # 真实写入会话与 loop 记录：task_runs 对二者有外键约束，
            # 编排层回写的 id 必须真实存在。
            from app.modules.conversation.models import AgentLoopRun, Conversation

            conversation = Conversation(
                platform_id=kwargs["platform_id"],
                agent_id=kwargs["agent_id"],
                user_id=kwargs["user_id"],
                title="任务执行",
            )
            session.add(conversation)
            await session.flush()
            loop = AgentLoopRun(
                conversation_id=conversation.id,
                request_id="test-request",
                status="completed",
            )
            session.add(loop)
            await session.flush()
            return (
                conversation,
                SimpleNamespace(id=1),
                SimpleNamespace(loop_id=loop.id),
            )

        _patch_execution(monkeypatch, fake_execute)
        status = await runner.run_task_run(session_factory, task_run_id=run_id)
        assert status == "completed"

        async with session_factory() as session:
            record = await session.get(TaskRun, run_id)
            assert record.status == "completed"
            assert record.conversation_id is not None
            assert record.agent_loop_run_id is not None
            assert record.finished_at is not None
        # 执行身份与平台由任务配置传入，而不是来自 HTTP 上下文
        assert captured["user_id"] is not None
        assert captured["platform_id"] is not None
        # 无人值守必须注入审批裁决器，否则工具确认会无处处理
        assert captured["confirmation_decider"] is not None
        await engine.dispose()

    asyncio.run(run())


def test_runner_marks_timeout_as_failed(monkeypatch) -> None:
    """超过 timeout_seconds 必须记为失败并写明超时。

    用任务自己的 timeout_seconds=1 触发真实超时（而不是打桩 wait_for），
    这样验证的是编排层真实的超时分支。
    """

    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            _platform, _agent, _user, task = await _seed(session, timeout_seconds=1)
            session.add(
                TaskRun(task_id=task.id, status="running", trigger_kind="scheduled")
            )
            await session.commit()
            run_id = (
                await session.execute(
                    select(TaskRun.id).where(TaskRun.task_id == task.id)
                )
            ).scalar_one()

        async def slow_execute(session, **kwargs):
            await asyncio.sleep(30)
            raise AssertionError("应当被超时取消，不应跑到这里")

        _patch_execution(monkeypatch, slow_execute)
        status = await runner.run_task_run(session_factory, task_run_id=run_id)
        assert status == "failed"

        async with session_factory() as session:
            record = await session.get(TaskRun, run_id)
            assert record.status == "failed"
            assert record.error_message is not None
            assert "超时" in record.error_message
        await engine.dispose()

    asyncio.run(run())


def test_runner_marks_exception_as_failed_with_reason(monkeypatch) -> None:
    """执行抛异常时兜底记为失败，并保留异常类型与信息。"""

    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            _platform, _agent, _user, task = await _seed(session)
            session.add(
                TaskRun(task_id=task.id, status="running", trigger_kind="scheduled")
            )
            await session.commit()
            run_id = (
                await session.execute(
                    select(TaskRun.id).where(TaskRun.task_id == task.id)
                )
            ).scalar_one()

        async def boom(session, **kwargs):
            raise RuntimeError("模型服务不可用")

        _patch_execution(monkeypatch, boom)
        status = await runner.run_task_run(session_factory, task_run_id=run_id)
        assert status == "failed"

        async with session_factory() as session:
            record = await session.get(TaskRun, run_id)
            assert record.status == "failed"
            assert "模型服务不可用" in record.error_message
        await engine.dispose()

    asyncio.run(run())


def test_runner_skips_when_task_paused_between_queue_and_run(monkeypatch) -> None:
    """排队期间任务被暂停：记为跳过，且不发起模型调用。"""

    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            _platform, _agent, _user, task = await _seed(session, status="paused")
            session.add(
                TaskRun(task_id=task.id, status="running", trigger_kind="scheduled")
            )
            await session.commit()
            run_id = (
                await session.execute(
                    select(TaskRun.id).where(TaskRun.task_id == task.id)
                )
            ).scalar_one()

        called = False

        async def should_not_run(session, **kwargs):
            nonlocal called
            called = True
            raise AssertionError("暂停的任务不应发起模型调用")

        _patch_execution(monkeypatch, should_not_run)
        status = await runner.run_task_run(session_factory, task_run_id=run_id)
        assert status == "skipped"
        assert called is False

        async with session_factory() as session:
            record = await session.get(TaskRun, run_id)
            assert record.status == "skipped"
            assert record.skip_reason == "task_paused"
        await engine.dispose()

    asyncio.run(run())


def test_runner_executes_end_user_task_with_end_user_identity(monkeypatch) -> None:
    """终端用户任务以 end_user 身份执行，且不会误用后台用户身份。

    这是 Embed 链路创建的任务能真正跑起来的关键：runner 必须按
    run_as_type 分派，而不是永远走 user 分支。
    """

    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            platform, agent, _user, _task = await _seed(session)
            end_user = PlatformEndUser(
                platform_id=platform.id, external_user_id="eu_runner"
            )
            session.add(end_user)
            await session.flush()

            task = await TaskRepository(session).create(
                platform_id=platform.id,
                agent_id=agent.id,
                owner_user_id=None,
                name="end-user-task",
                prompt="do it",
                trigger_type="cron",
                cron_expression="0 9 * * *",
                timezone="UTC",
                status="active",
                next_run_at=datetime.now(UTC),
                created_by_type="agent",
                run_as_type="end_user",
                run_as_user_id=None,
                run_as_end_user_id=end_user.id,
                auto_approve=True,
                strict_approval=False,
                timeout_seconds=600,
            )
            session.add(
                TaskRun(task_id=task.id, status="running", trigger_kind="scheduled")
            )
            await session.commit()
            run_id = (
                await session.execute(
                    select(TaskRun.id).where(TaskRun.task_id == task.id)
                )
            ).scalar_one()
            end_user_id = end_user.id

        captured: dict = {}

        async def fake_execute(session, **kwargs):
            captured.update(kwargs)
            from app.modules.conversation.models import AgentLoopRun, Conversation

            conversation = Conversation(
                platform_id=kwargs["platform_id"],
                agent_id=kwargs["agent_id"],
                # 终端用户会话：principal 是 platform_end_user_id
                platform_end_user_id=kwargs["end_user_id"],
                title="任务执行",
            )
            session.add(conversation)
            await session.flush()
            loop = AgentLoopRun(
                conversation_id=conversation.id,
                request_id="test-end-user",
                status="completed",
            )
            session.add(loop)
            await session.flush()
            return (
                conversation,
                SimpleNamespace(id=1),
                SimpleNamespace(loop_id=loop.id),
            )

        _patch_execution(monkeypatch, fake_execute)
        status = await runner.run_task_run(session_factory, task_run_id=run_id)
        assert status == "completed"
        # 关键断言：按 end_user 分派，后台用户身份为空
        assert captured["run_as_type"] == "end_user"
        assert captured["end_user_id"] == end_user_id
        assert captured["user_id"] is None

        async with session_factory() as session:
            record = await session.get(TaskRun, run_id)
            assert record.status == "completed"
            assert record.conversation_id is not None
        await engine.dispose()

    asyncio.run(run())


def test_runner_fails_without_run_as_identity(monkeypatch) -> None:
    """没有可用执行身份时必须立刻失败，而不是发起一次无身份的运行。"""

    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            _platform, _agent, _user, task = await _seed(
                session,
                owner_user_id=None,
                run_as_user_id=None,
                run_as_type="user",
            )
            session.add(
                TaskRun(task_id=task.id, status="running", trigger_kind="scheduled")
            )
            await session.commit()
            run_id = (
                await session.execute(
                    select(TaskRun.id).where(TaskRun.task_id == task.id)
                )
            ).scalar_one()

        async def should_not_run(session, **kwargs):
            raise AssertionError("无执行身份不应发起模型调用")

        _patch_execution(monkeypatch, should_not_run)
        status = await runner.run_task_run(session_factory, task_run_id=run_id)
        assert status == "failed"

        async with session_factory() as session:
            record = await session.get(TaskRun, run_id)
            assert record.status == "failed"
            assert "执行身份" in record.error_message
        await engine.dispose()

    asyncio.run(run())


def test_runner_does_not_reexecute_finished_run(monkeypatch) -> None:
    """已是终态的记录不会被再次执行（看门狗标记失败后不应复活）。"""

    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            _platform, _agent, _user, task = await _seed(session)
            session.add(
                TaskRun(
                    task_id=task.id,
                    status="failed",
                    trigger_kind="scheduled",
                    error_message="已被看门狗标记",
                )
            )
            await session.commit()
            run_id = (
                await session.execute(
                    select(TaskRun.id).where(TaskRun.task_id == task.id)
                )
            ).scalar_one()

        async def should_not_run(session, **kwargs):
            raise AssertionError("终态记录不应被重新执行")

        _patch_execution(monkeypatch, should_not_run)
        status = await runner.run_task_run(session_factory, task_run_id=run_id)
        assert status == "failed"
        await engine.dispose()

    asyncio.run(run())
