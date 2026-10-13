"""工作流调度 tick 的用例（spec 验收第 8 条）。

定时触发复用任务模块的抢占语义，但两条链路是**互不相交**的集合：
``app.modules.workflows.scheduler`` 只抢 ``workflow_id`` 非空的任务，
``app.modules.tasks.scheduler`` 只抢 ``workflow_id`` 为空的任务。用例 29
专门锁住这条反向保护——它是「同一个到期任务被两个 tick 各跑一遍」的唯一防线。
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.modules.tasks import scheduler as tasks_scheduler
from app.modules.tasks.models import Task, TaskRun
from app.modules.tasks.repositories import TaskRepository
from app.modules.workflows import scheduler, validators
from app.modules.workflows.models import Workflow, WorkflowRun
from app.modules.workflows.repositories import WorkflowRunRepository
from helpers import agent_step, make_session, seed

DUE = datetime.now(UTC) - timedelta(minutes=1)
LATE = datetime.now(UTC) - timedelta(minutes=10)


async def _make_workflow(session, meta, *, status="active", steps=None, **overrides):
    data = {
        "platform_id": meta.platform.id,
        "name": "定时工作流",
        "agent_id": meta.agent.id,
        "owner_user_id": meta.member.id,
        "status": status,
        "version": 1,
        "definition": validators.compile_definition(
            steps if steps is not None else [agent_step("first"), agent_step("second")]
        ),
        "max_steps": 50,
        "timeout_seconds": 600,
        "auto_approve": True,
        "strict_approval": False,
    }
    data.update(overrides)
    workflow = Workflow(**data)
    session.add(workflow)
    await session.flush()
    return workflow


async def _make_task(session, meta, *, workflow_id, next_run_at=DUE, **overrides):
    data = {
        "platform_id": meta.platform.id,
        "agent_id": meta.agent.id,
        "workflow_id": workflow_id,
        "owner_user_id": meta.member.id,
        "name": "触发任务",
        "prompt": "跑工作流",
        "trigger_type": "cron",
        "cron_expression": "*/5 * * * *",
        "timezone": "UTC",
        "status": "active",
        "next_run_at": next_run_at,
        "created_by_type": "user",
        "run_as_type": "user",
        "run_as_user_id": meta.member.id,
        "auto_approve": True,
        "strict_approval": False,
        "timeout_seconds": 600,
    }
    data.update(overrides)
    return await TaskRepository(session).create(**data)


async def _runs_for(session, workflow_id: int) -> list[WorkflowRun]:
    return list(
        (
            await session.execute(
                select(WorkflowRun)
                .where(WorkflowRun.workflow_id == workflow_id)
                .order_by(WorkflowRun.id)
            )
        )
        .scalars()
        .all()
    )


def test_trigger_creates_queued_run_and_ignores_unlinked_tasks(monkeypatch) -> None:
    """锁（验收 8）：到期且绑定工作流的任务被抢占后，建的是一条**已排队**的运行
    （``status='running'`` 且 ``started_at`` 为空）并带定义快照与 ``total_steps``，
    同时 ``next_run_at`` 被推进；没有绑定工作流的到期任务不被这条链路碰。

    ``started_at`` 为空是必须的：第二步 ``claim_queued_runs`` 会立刻把它认领掉，
    所以这里把认领换成 no-op 才观察得到「入队而非直接开始」这个中间态——
    如果实现改回「创建时写 started_at」，调度器就永远不会再认领它，
    这条记录只会卡在 running 直到被看门狗判超时。
    """

    async def run() -> None:
        engine, session_factory = await make_session()
        try:
            async with session_factory() as session:
                meta = await seed(session)
                workflow = await _make_workflow(session, meta)
                task = await _make_task(session, meta, workflow_id=workflow.id)
                # 未绑定工作流的到期任务：不属于本链路。
                plain = await _make_task(
                    session, meta, workflow_id=None, name="普通任务"
                )
                workflow_id = workflow.id
                task_id = task.id
                plain_id = plain.id
                await session.commit()

            class _NoClaimRepository(WorkflowRunRepository):
                async def claim_queued_runs(self, *, limit: int = 50):
                    return []

            monkeypatch.setattr(scheduler, "WorkflowRunRepository", _NoClaimRepository)
            pending = await scheduler._claim_and_dispatch_workflows(session_factory)
            assert pending == []

            async with session_factory() as session:
                runs = await _runs_for(session, workflow_id)
                assert len(runs) == 1
                created = runs[0]
                assert created.status == "running"
                assert created.started_at is None
                assert created.trigger_kind == "scheduled"
                assert created.planned_at is not None
                assert created.total_steps == 2
                assert created.definition_version_id == 1
                assert created.definition_snapshot["nodes"][0]["step_id"] == "first"
                assert len(created.definition_snapshot["nodes"]) == 2
                assert created.run_as_type == "user"
                assert created.run_as_user_id is not None

                # 触发点被推进到未来（不补跑过去的时间点）。
                refreshed = await session.get(Task, task_id)
                assert refreshed.next_run_at is not None
                assert refreshed.next_run_at.replace(tzinfo=UTC) > datetime.now(UTC)

                # 未绑定的任务原地不动：既没被推进，也没产生任何运行记录。
                untouched = await session.get(Task, plain_id)
                assert untouched.next_run_at.replace(tzinfo=UTC) == DUE
                assert (
                    (
                        await session.execute(
                            select(TaskRun).where(TaskRun.task_id == plain_id)
                        )
                    )
                    .scalars()
                    .all()
                    == []
                )
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_trigger_created_run_is_actually_claimed() -> None:
    """锁（验收 8）：触发写入的排队运行会被同一次 tick 的 ``claim_queued_runs``
    认领并写上 ``started_at``——「入队」与「开始」是同一条执行路径。"""

    async def run() -> None:
        engine, session_factory = await make_session()
        try:
            async with session_factory() as session:
                meta = await seed(session)
                workflow = await _make_workflow(session, meta)
                await _make_task(session, meta, workflow_id=workflow.id)
                workflow_id = workflow.id
                await session.commit()

            pending = await scheduler._claim_and_dispatch_workflows(session_factory)
            assert len(pending) == 1

            async with session_factory() as session:
                runs = await _runs_for(session, workflow_id)
                assert [run_row.id for run_row in runs] == pending
                assert runs[0].status == "running"
                assert runs[0].started_at is not None
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_trigger_records_overlapped_when_workflow_already_running() -> None:
    """锁（验收 8）：同一工作流已有 running 运行时，新触发写 skipped+overlapped。"""

    async def run() -> None:
        engine, session_factory = await make_session()
        try:
            async with session_factory() as session:
                meta = await seed(session)
                workflow = await _make_workflow(session, meta)
                await _make_task(session, meta, workflow_id=workflow.id)
                await session.commit()

                # 在跑的运行：started_at 已写，避免被 claim_queued_runs 重复认领。
                running = await WorkflowRunRepository(session).create_run(
                    workflow_id=workflow.id,
                    status="running",
                    trigger_kind="manual",
                    definition_version_id=workflow.version,
                    definition_snapshot=workflow.definition,
                    total_steps=2,
                    started_at=datetime.now(UTC),
                )
                running_id = running.id
                workflow_id = workflow.id
                await session.commit()

            await scheduler._claim_and_dispatch_workflows(session_factory)

            async with session_factory() as session:
                runs = await _runs_for(session, workflow_id)
                assert [row.id for row in runs] == [running_id, running_id + 1]
                # 先前的运行不被改写。
                assert runs[0].status == "running"
                # 这一次触发只留痕，不产生第二条可执行记录。
                assert runs[1].status == "skipped"
                assert runs[1].skip_reason == "overlapped"
                assert runs[1].trigger_kind == "scheduled"
                assert runs[1].started_at is None
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_trigger_records_workflow_paused_before_deadline_check() -> None:
    """锁（验收 8）：工作流非 active 时记 skipped+workflow_paused；
    且该判定**先于**超期判定——暂停本身就是要跳过的理由，不该被写成 deadline_missed。"""

    async def run() -> None:
        engine, session_factory = await make_session()
        try:
            async with session_factory() as session:
                meta = await seed(session)
                workflow = await _make_workflow(session, meta, status="paused")
                # 故意给一个早已过期的触发点：状态判定仍应优先命中。
                task = await _make_task(session, meta, workflow_id=workflow.id, next_run_at=LATE)
                workflow_id = workflow.id
                task_id = task.id
                await session.commit()

            pending = await scheduler._claim_and_dispatch_workflows(session_factory)
            assert pending == []

            async with session_factory() as session:
                runs = await _runs_for(session, workflow_id)
                assert len(runs) == 1
                assert runs[0].status == "skipped"
                assert runs[0].skip_reason == "workflow_paused"
                assert runs[0].started_at is None

                # 触发点照样推进，否则这条任务每个 tick 都会被重新抢占。
                refreshed = await session.get(Task, task_id)
                assert refreshed.next_run_at.replace(tzinfo=UTC) > datetime.now(UTC)
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_trigger_records_deadline_missed_beyond_grace() -> None:
    """锁（验收 8）：触发点早于 ``MISSED_TRIGGER_GRACE_SECONDS`` 时记
    skipped+deadline_missed，不做补跑。"""

    async def run() -> None:
        engine, session_factory = await make_session()
        try:
            async with session_factory() as session:
                meta = await seed(session)
                workflow = await _make_workflow(session, meta)
                task = await _make_task(
                    session, meta, workflow_id=workflow.id, next_run_at=LATE
                )
                workflow_id = workflow.id
                task_id = task.id
                await session.commit()

            assert scheduler.MISSED_TRIGGER_GRACE_SECONDS == 300
            pending = await scheduler._claim_and_dispatch_workflows(session_factory)
            assert pending == []

            async with session_factory() as session:
                runs = await _runs_for(session, workflow_id)
                assert len(runs) == 1
                assert runs[0].status == "skipped"
                assert runs[0].skip_reason == "deadline_missed"
                assert runs[0].started_at is None
                # 计划的触发点被如实记录，便于排障。
                assert runs[0].planned_at is not None

                refreshed = await session.get(Task, task_id)
                assert refreshed.next_run_at.replace(tzinfo=UTC) > datetime.now(UTC)
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_task_tick_excludes_workflow_linked_tasks() -> None:
    """锁（用例 29 的反向保护）：``tasks.scheduler._claim_and_dispatch`` 只认领
    ``workflow_id IS NULL`` 的任务，绑了工作流的到期任务留给工作流调度器。

    两个 tick 若都认领同一个任务，它会被跑两遍（一遍自己的 prompt、一遍工作流），
    这条用例是防这件事的唯一一道闸。
    """

    async def run() -> None:
        engine, session_factory = await make_session()
        try:
            async with session_factory() as session:
                meta = await seed(session)
                workflow = await _make_workflow(session, meta)
                linked = await _make_task(
                    session, meta, workflow_id=workflow.id, name="工作流触发任务"
                )
                plain = await _make_task(session, meta, workflow_id=None, name="普通任务")
                linked_id = linked.id
                plain_id = plain.id
                await session.commit()

            pending = await tasks_scheduler._claim_and_dispatch(session_factory)
            assert len(pending) == 1

            async with session_factory() as session:
                runs = list(
                    (await session.execute(select(TaskRun))).scalars().all()
                )
                assert [run_row.task_id for run_row in runs] == [plain_id]
                assert [run_row.id for run_row in runs] == pending

                # 工作流触发任务完全没被任务调度器碰过。
                untouched = await session.get(Task, linked_id)
                assert untouched.next_run_at.replace(tzinfo=UTC) == DUE
        finally:
            await engine.dispose()

    asyncio.run(run())
