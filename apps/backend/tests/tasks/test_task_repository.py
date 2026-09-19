"""任务仓储单元测试（sqlite 内存库）。

覆盖：可见性过滤、抢占到期任务、串行判定与看门狗超时清理。
说明：``FOR UPDATE SKIP LOCKED`` 在 sqlite 上会被忽略，真正的多副本
抢占语义需要在 PostgreSQL 上验证（见 verify.md 的人工验证项）。
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.agent.models import Agent
from app.modules.platform.models import Platform
from app.modules.tasks.models import TaskRun
from app.modules.tasks.repositories import TaskRepository, TaskRunRepository
from app.modules.user.models import User
from app.shared.base_model import BaseModel
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
    """建一个平台、一个智能体、两个用户，返回 (platform, agent, admin, member)。"""

    platform = Platform(name="Acme", code="acme", is_active=True)
    session.add(platform)
    await session.flush()
    agent = Agent(platform_id=platform.id, name="Bot", slug="bot")
    admin = User(
        name="Admin", email="admin@acme.dev", account="admin", password="x"
    )
    member = User(
        name="Member", email="member@acme.dev", account="member", password="x"
    )
    session.add_all([agent, admin, member])
    await session.flush()
    return platform, agent, admin, member


def _task_kwargs(platform_id: int, agent_id: int, **overrides):
    data = {
        "platform_id": platform_id,
        "agent_id": agent_id,
        "name": "task",
        "prompt": "do it",
        "trigger_type": "cron",
        "cron_expression": "* * * * *",
        "timezone": "UTC",
        "status": "active",
        "next_run_at": datetime.now(UTC),
        "created_by_type": "user",
        "run_as_type": "user",
        "auto_approve": True,
        "strict_approval": False,
        "timeout_seconds": 600,
    }
    data.update(overrides)
    return data


def test_list_tasks_filters_by_owner_for_normal_user() -> None:
    """普通用户只能看到自己名下的任务，平台管理员能看到全部（含平台级）。"""

    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            platform, agent, admin, member = await _seed(session)
            repo = TaskRepository(session)
            await repo.create(**_task_kwargs(
                platform.id, agent.id, name="platform-task", owner_user_id=None
            ))
            await repo.create(**_task_kwargs(
                platform.id, agent.id, name="admin-task", owner_user_id=admin.id
            ))
            await repo.create(**_task_kwargs(
                platform.id, agent.id, name="member-task", owner_user_id=member.id
            ))

            params = PaginationParams(page=1, page_size=20)
            # 普通用户视角：只看自己的
            member_page = await repo.list_tasks(
                platform.id, params, owner_user_id=member.id
            )
            assert [t.name for t in member_page.items] == ["member-task"]
            assert member_page.total == 1

            # 管理员视角：全平台
            admin_page = await repo.list_tasks(platform.id, params)
            assert sorted(t.name for t in admin_page.items) == [
                "admin-task",
                "member-task",
                "platform-task",
            ]
            assert admin_page.total == 3
        await engine.dispose()

    asyncio.run(run())


def test_claim_due_tasks_only_returns_active_and_due() -> None:
    """只有 active 且已到期的任务会被抢占。"""

    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            platform, agent, _admin, _member = await _seed(session)
            repo = TaskRepository(session)
            past = datetime.now(UTC) - timedelta(minutes=5)
            future = datetime.now(UTC) + timedelta(minutes=30)
            await repo.create(**_task_kwargs(
                platform.id, agent.id, name="due", next_run_at=past
            ))
            await repo.create(**_task_kwargs(
                platform.id, agent.id, name="not-due", next_run_at=future
            ))
            await repo.create(**_task_kwargs(
                platform.id, agent.id, name="paused", next_run_at=past, status="paused"
            ))

            claimed = await repo.claim_due_tasks()
            assert [t.name for t in claimed] == ["due"]
            # 抢占时写入 last_run_at，供「错过不补跑」推进时参考
            await session.commit()
            assert claimed[0].last_run_at is not None
        await engine.dispose()

    asyncio.run(run())


def test_serial_detection_via_running_record() -> None:
    """存在 running 记录即判定为「上一次未结束」，用于产生 skipped 记录。"""

    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            platform, agent, _admin, _member = await _seed(session)
            task = await TaskRepository(session).create(
                **_task_kwargs(platform.id, agent.id, name="serial")
            )
            run_repo = TaskRunRepository(session)
            assert await run_repo.get_running(task.id) is None

            await run_repo.create_run(
                task_id=task.id,
                status="running",
                trigger_kind="scheduled",
                started_at=datetime.now(UTC),
            )
            await session.commit()

            assert await run_repo.get_running(task.id) is not None
            # 重叠触发应写成 skipped(overlapped)，而不是第二条 running
            await run_repo.create_run(
                task_id=task.id,
                status="skipped",
                trigger_kind="scheduled",
                skip_reason="overlapped",
            )
            await session.commit()
            runs = await TaskRepository(session).list_runs(
                task.id, PaginationParams(page=1, page_size=20)
            )
            statuses = sorted(r.status for r in runs.items)
            assert statuses == ["running", "skipped"]
        await engine.dispose()

    asyncio.run(run())


def test_watchdog_marks_overdue_running_as_failed() -> None:
    """超过 timeout_seconds 仍 running 的记录被看门狗标记 failed。

    数据库层面「一个任务最多一条 running」，所以「超时」与「未超时」
    两条记录分别挂在两个任务上，才能同时存在。
    """

    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            platform, agent, _admin, _member = await _seed(session)
            repo = TaskRepository(session)
            stale_task = await repo.create(
                **_task_kwargs(platform.id, agent.id, name="wd-stale", timeout_seconds=60)
            )
            fresh_task = await repo.create(
                **_task_kwargs(platform.id, agent.id, name="wd-fresh", timeout_seconds=60)
            )
            run_repo = TaskRunRepository(session)
            stale = await run_repo.create_run(
                task_id=stale_task.id,
                status="running",
                trigger_kind="scheduled",
                started_at=datetime.now(UTC) - timedelta(seconds=600),
            )
            fresh = await run_repo.create_run(
                task_id=fresh_task.id,
                status="running",
                trigger_kind="scheduled",
                started_at=datetime.now(UTC),
            )
            await session.commit()

            expired = await run_repo.expire_stale_running(default_timeout_seconds=600)
            await session.commit()
            assert expired == 1
            assert stale.status == "failed"
            assert stale.error_message is not None
            assert "超时" in stale.error_message
            assert fresh.status == "running"
        await engine.dispose()

    asyncio.run(run())


def test_database_blocks_second_running_record_per_task() -> None:
    """数据库级兜底：同一任务不允许出现第二条 running 记录。

    这是「同一任务串行」的最后一道防线，即使应用层判定被绕过，
    重叠触发也无法落成两条并行运行。
    """

    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            platform, agent, _admin, _member = await _seed(session)
            task = await TaskRepository(session).create(
                **_task_kwargs(platform.id, agent.id, name="db-guard")
            )
            run_repo = TaskRunRepository(session)
            await run_repo.create_run(
                task_id=task.id,
                status="running",
                trigger_kind="scheduled",
                started_at=datetime.now(UTC),
            )
            await session.commit()
            # 提前取出一份普通值：回滚会让 ORM 实例过期，之后再访问属性
            # 会触发懒加载 IO，在异步会话里报 MissingGreenlet。
            task_id = task.id

            from sqlalchemy.exc import IntegrityError

            try:
                await run_repo.create_run(
                    task_id=task_id,
                    status="running",
                    trigger_kind="manual",
                    started_at=datetime.now(UTC),
                )
                await session.commit()
                raised = False
            except IntegrityError:
                await session.rollback()
                raised = True
            assert raised, "数据库必须拒绝同一任务的第二条 running 记录"

            # skipped 记录不受该索引限制
            await run_repo.create_run(
                task_id=task_id,
                status="skipped",
                trigger_kind="scheduled",
                skip_reason="overlapped",
            )
            await session.commit()
        await engine.dispose()

    asyncio.run(run())


def test_list_runs_is_scoped_by_task() -> None:
    """执行记录列表按任务隔离，不会串到别的任务。"""

    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            platform, agent, _admin, _member = await _seed(session)
            repo = TaskRepository(session)
            task_a = await repo.create(**_task_kwargs(platform.id, agent.id, name="a"))
            task_b = await repo.create(**_task_kwargs(platform.id, agent.id, name="b"))
            run_repo = TaskRunRepository(session)
            await run_repo.create_run(
                task_id=task_a.id, status="completed", trigger_kind="scheduled"
            )
            await run_repo.create_run(
                task_id=task_b.id, status="completed", trigger_kind="scheduled"
            )
            await session.commit()

            page = await repo.list_runs(task_a.id, PaginationParams(page=1, page_size=20))
            assert page.total == 1
            assert all(r.task_id == task_a.id for r in page.items)
        await engine.dispose()

    asyncio.run(run())


def test_finish_run_writes_result_fields() -> None:
    """执行结果回写包含状态、结束时刻与自动批准计数。"""

    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            platform, agent, _admin, _member = await _seed(session)
            task = await TaskRepository(session).create(
                **_task_kwargs(platform.id, agent.id, name="finish")
            )
            run_repo = TaskRunRepository(session)
            record = await run_repo.create_run(
                task_id=task.id,
                status="running",
                trigger_kind="manual",
                started_at=datetime.now(UTC),
            )
            await session.commit()

            await run_repo.finish_run(
                record,
                status="completed",
                auto_approved_count=2,
            )
            await session.commit()
            refreshed = await session.get(TaskRun, record.id)
            assert refreshed.status == "completed"
            assert refreshed.finished_at is not None
            assert refreshed.auto_approved_count == 2
        await engine.dispose()

    asyncio.run(run())
