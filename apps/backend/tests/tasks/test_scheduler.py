"""调度器核心逻辑测试（sqlite 内存库）。

不启动常驻循环，只测每个 tick 里最关键的三个语义：
抢占到期任务、重叠触发记为 skipped、推进 next_run_at 时「错过不补跑」。
真正的多副本 ``FOR UPDATE SKIP LOCKED`` 语义需要在 PostgreSQL 上验证。
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.agent.models import Agent
from app.modules.platform.models import Platform
from app.modules.tasks import scheduler
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


async def _seed(session, **overrides):
    # 平台 code 有唯一约束，同一个用例里多次建种子数据时需要互不相同。
    suffix = str(session.info.setdefault("seed_seq", 0))
    session.info["seed_seq"] = session.info["seed_seq"] + 1
    platform = Platform(name=f"Acme{suffix}", code=f"acme{suffix}", is_active=True)
    session.add(platform)
    await session.flush()
    agent = Agent(platform_id=platform.id, name=f"Bot{suffix}", slug=f"bot{suffix}")
    user = User(
        name="Admin",
        email=f"a{suffix}@acme.dev",
        account=f"admin{suffix}",
        password="x",
    )
    session.add_all([agent, user])
    await session.flush()
    data = {
        "platform_id": platform.id,
        "agent_id": agent.id,
        "owner_user_id": user.id,
        "name": "task",
        "prompt": "do it",
        "trigger_type": "cron",
        "cron_expression": "*/5 * * * *",
        "timezone": "UTC",
        "status": "active",
        "next_run_at": datetime.now(UTC) - timedelta(minutes=1),
        "created_by_type": "user",
        "run_as_type": "user",
        "run_as_user_id": user.id,
        "auto_approve": True,
        "strict_approval": False,
        "timeout_seconds": 600,
    }
    data.update(overrides)
    task = await TaskRepository(session).create(**data)
    return platform, agent, user, task


def test_claim_dispatches_due_task_and_advances_next_run(monkeypatch) -> None:
    """到点任务被抢占：写 running 记录，并把 next_run_at 推进到未来。"""

    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            _platform, _agent, _user, task = await _seed(session)
            task_id = task.id

        pending = await scheduler._claim_and_dispatch(session_factory)
        assert len(pending) == 1

        async with session_factory() as session:
            record = await session.get(TaskRun, pending[0])
            assert record.status == "running"
            assert record.trigger_kind == "scheduled"
            assert record.started_at is not None

            refreshed = await session.get(type(task), task_id)
            # 错过不补跑：推进后的触发点必须晚于当前时刻
            anchor = refreshed.next_run_at
            if anchor.tzinfo is None:
                anchor = anchor.replace(tzinfo=UTC)
            assert anchor > datetime.now(UTC)
            assert refreshed.last_run_at is not None
        await engine.dispose()

    asyncio.run(run())


def test_manual_run_is_claimed_and_dispatched() -> None:
    """「立即运行一次」写入的 run 必须被调度器认领并派发。

    这是回归测试：修复前调度器只派发自己在本 tick 创建的记录，
    接口写入的 manual run 永远无人认领，只会卡在 running 直到被
    看门狗判为「执行超时」——任务实际从未执行过。
    """

    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            _platform, _agent, _user, task = await _seed(
                session,
                # 未到点：本次派发只能来自「认领已排队 run」，不能来自抢占
                next_run_at=datetime.now(UTC) + timedelta(days=1),
            )
            from app.modules.tasks import services

            manual_run, started = await services.enqueue_manual_run(session, task)
            assert started is True
            assert manual_run.trigger_kind == "manual"
            # 入队时不得写 started_at：否则调度器会以为它已在执行而不认领
            assert manual_run.started_at is None
            manual_run_id = manual_run.id

        pending = await scheduler._claim_and_dispatch(session_factory)
        assert manual_run_id in pending, "手动触发的 run 必须被派发执行"

        async with session_factory() as session:
            record = await session.get(TaskRun, manual_run_id)
            assert record.status == "running"
            # 认领后才写 started_at，作为「真正开始执行」的标记
            assert record.started_at is not None
        await engine.dispose()

    asyncio.run(run())


def test_queued_run_from_restart_is_claimed() -> None:
    """进程重启后遗留的待执行 run（started_at 为空）会被重新认领。"""

    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            _platform, _agent, _user, task = await _seed(
                session, next_run_at=datetime.now(UTC) + timedelta(days=1)
            )
            # 模拟上一次进程被杀：留下一条已排队但未开始的记录
            session.add(
                TaskRun(
                    task_id=task.id,
                    status="running",
                    trigger_kind="scheduled",
                    planned_at=datetime.now(UTC),
                    started_at=None,
                )
            )
            await session.commit()

        pending = await scheduler._claim_and_dispatch(session_factory)
        assert len(pending) == 1
        await engine.dispose()

    asyncio.run(run())


def test_already_started_run_is_not_reclaimed() -> None:
    """已在执行的 run（started_at 有值）不会被重复认领，避免并发跑两次。"""

    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            _platform, _agent, _user, task = await _seed(
                session, next_run_at=datetime.now(UTC) + timedelta(days=1)
            )
            session.add(
                TaskRun(
                    task_id=task.id,
                    status="running",
                    trigger_kind="scheduled",
                    planned_at=datetime.now(UTC),
                    started_at=datetime.now(UTC),
                )
            )
            await session.commit()

        pending = await scheduler._claim_and_dispatch(session_factory)
        assert pending == [], "已在执行的 run 不应被重复认领"
        await engine.dispose()

    asyncio.run(run())


def test_overlapped_trigger_is_skipped(monkeypatch) -> None:
    """上一次仍在运行时，本次触发记为 skipped(overlapped)，不发新运行。"""

    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            _platform, _agent, _user, task = await _seed(session)
            task_id = task.id
            # 先制造一条 running，模拟「上一次还没结束」
            session.add(
                TaskRun(
                    task_id=task_id,
                    status="running",
                    trigger_kind="scheduled",
                    started_at=datetime.now(UTC),
                )
            )
            await session.commit()

        pending = await scheduler._claim_and_dispatch(session_factory)
        # 不产生新的待执行运行
        assert pending == []

        async with session_factory() as session:
            from sqlalchemy import select

            records = (
                await session.execute(
                    select(TaskRun).where(TaskRun.task_id == task_id)
                )
            ).scalars().all()
            statuses = sorted(r.status for r in records)
            assert statuses == ["running", "skipped"]
            skipped = next(r for r in records if r.status == "skipped")
            assert skipped.skip_reason == "overlapped"
            # 依然要推进触发时间，否则会每个 tick 都重复判断
            refreshed = await session.get(type(task), task_id)
            assert refreshed.next_run_at is not None
        await engine.dispose()

    asyncio.run(run())


def test_paused_and_future_tasks_are_not_claimed(monkeypatch) -> None:
    """暂停任务与未到点任务都不会被抢占。"""

    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            await _seed(
                session,
                name="paused",
                status="paused",
                next_run_at=datetime.now(UTC) - timedelta(minutes=1),
            )
            await _seed(
                session,
                name="future",
                next_run_at=datetime.now(UTC) + timedelta(hours=1),
            )

        pending = await scheduler._claim_and_dispatch(session_factory)
        assert pending == []
        await engine.dispose()

    asyncio.run(run())


def test_once_task_is_not_rescheduled_after_dispatch(monkeypatch) -> None:
    """一次性任务触发后 next_run_at 置空，不会再次被抢占。"""

    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            _platform, _agent, _user, task = await _seed(
                session,
                trigger_type="once",
                cron_expression=None,
                run_at=datetime.now(UTC) - timedelta(seconds=5),
                next_run_at=datetime.now(UTC) - timedelta(seconds=5),
            )
            task_id = task.id

        pending = await scheduler._claim_and_dispatch(session_factory)
        assert len(pending) == 1

        async with session_factory() as session:
            refreshed = await session.get(type(task), task_id)
            assert refreshed.next_run_at is None
        # 第二次 tick 不会再抢到它
        assert await scheduler._claim_and_dispatch(session_factory) == []
        await engine.dispose()

    asyncio.run(run())


def test_watchdog_runs_inside_tick(monkeypatch) -> None:
    """看门狗把超时 running 记录标记失败。"""

    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            _platform, _agent, _user, task = await _seed(
                session, timeout_seconds=30
            )
            session.add(
                TaskRun(
                    task_id=task.id,
                    status="running",
                    trigger_kind="scheduled",
                    started_at=datetime.now(UTC) - timedelta(hours=2),
                )
            )
            await session.commit()
            run_id = (
                await session.execute(
                    TaskRun.__table__.select().where(TaskRun.task_id == task.id)
                )
            ).first().id

        expired = await scheduler._watchdog(
            session_factory, default_timeout_seconds=600
        )
        assert expired == 1

        async with session_factory() as session:
            record = await session.get(TaskRun, run_id)
            assert record.status == "failed"
            assert "超时" in record.error_message
        await engine.dispose()

    asyncio.run(run())


def test_claim_and_advance_are_atomic(monkeypatch) -> None:
    """抢占与推进在同一事务提交：两次连续 tick 不会对同一触发点重复派发。"""

    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            _platform, _agent, _user, task = await _seed(session)
            task_id = task.id

        first = await scheduler._claim_and_dispatch(session_factory)
        assert len(first) == 1
        # 第二个 tick：触发点已被推进到未来，不应再次派发
        second = await scheduler._claim_and_dispatch(session_factory)
        assert second == []

        async with session_factory() as session:
            from sqlalchemy import select

            total = len(
                (
                    await session.execute(
                        select(TaskRun).where(TaskRun.task_id == task_id)
                    )
                ).scalars().all()
            )
            assert total == 1
        await engine.dispose()

    asyncio.run(run())
