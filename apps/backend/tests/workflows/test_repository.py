"""工作流仓储层的用例（spec 验收第 1、8 条）。

用真实的 sqlite 内存库（开启外键）跑 DDL，因为这里要锁的语义——
「同一工作流只允许一条 running」的部分唯一索引、看门狗按 ``started_at or created_at``
判定超时——都只有走真实数据库才测得出来。
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.modules.workflows import validators
from app.modules.workflows.models import Workflow, WorkflowRun, WorkflowStepRun
from app.modules.workflows.repositories import (
    WorkflowRepository,
    WorkflowRunRepository,
    WorkflowStepRunRepository,
)
from app.shared.pagination import PaginationParams
from helpers import agent_step, make_session, seed


async def _make_workflow(session, meta, **overrides) -> Workflow:
    """建一条工作流定义（默认属于 ``meta.member``，两步 agent）。"""

    data = {
        "platform_id": meta.platform.id,
        "name": "测试工作流",
        "agent_id": meta.agent.id,
        "owner_user_id": meta.member.id,
        "definition": validators.compile_definition([agent_step("first")]),
        "timeout_seconds": 600,
    }
    data.update(overrides)
    workflow = Workflow(**data)
    session.add(workflow)
    await session.flush()
    return workflow


async def _create_run(session, workflow_id: int, **overrides) -> WorkflowRun:
    """建一条运行记录（默认 running + 未认领，即「排队中」）。"""

    data = {
        "workflow_id": workflow_id,
        "status": "running",
        "trigger_kind": "manual",
        "definition_version_id": 1,
        "definition_snapshot": {"nodes": [], "edges": []},
    }
    data.update(overrides)
    return await WorkflowRunRepository(session).create_run(**data)


def test_partial_unique_index_allows_one_running_but_many_skipped() -> None:
    """锁（验收 1）：同一工作流最多一条 running；skipped 不受唯一索引约束。

    这条用例专门锁「两种方言都写 where」这个坑：若只给 ``postgresql_where``，
    sqlite 上 ``unique=True`` 会退化成「workflow_id 全表唯一」，第二条 skipped
    记录也会被拒绝——而调度器在每次重叠触发时都要写一条 skipped 记录。
    """

    async def run() -> None:
        engine, session_factory = await make_session()
        try:
            async with session_factory() as session:
                meta = await seed(session)
                workflow = await _make_workflow(session, meta)
                workflow_id = workflow.id
                repo = WorkflowRunRepository(session)
                await repo.create_run(
                    workflow_id=workflow_id,
                    status="running",
                    trigger_kind="manual",
                    definition_version_id=1,
                    definition_snapshot={},
                )
                await session.commit()

                # 第二条 running：由部分唯一索引兜底拒绝。
                with pytest.raises(IntegrityError):
                    await repo.create_run(
                        workflow_id=workflow_id,
                        status="running",
                        trigger_kind="manual",
                        definition_version_id=1,
                        definition_snapshot={},
                    )
                await session.rollback()

                # 第二条 skipped：必须成功（回滚后只能靠提前取出的 workflow_id）。
                first_skipped = await _create_run(
                    session, workflow_id, status="skipped", skip_reason="overlapped"
                )
                second_skipped = await _create_run(
                    session, workflow_id, status="skipped", skip_reason="overlapped"
                )
                await session.commit()
                assert first_skipped.id is not None
                assert second_skipped.id != first_skipped.id

                total = await session.execute(
                    select(func.count())
                    .select_from(WorkflowRun)
                    .where(WorkflowRun.workflow_id == workflow_id)
                )
                assert total.scalar_one() == 3
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_claim_queued_runs_only_takes_unstarted_running_records() -> None:
    """锁：只认领 ``status='running' AND started_at IS NULL``，认领即写 started_at。

    调度器不能只跑自己本 tick 创建的记录：手动运行与进程重启遗留的排队记录
    都要靠这里认领，否则永远没人执行、只会被看门狗判成超时。
    """

    async def run() -> None:
        engine, session_factory = await make_session()
        try:
            async with session_factory() as session:
                meta = await seed(session)
                # 每条待观察的运行都挂在**自己的**工作流下：部分唯一索引要求
                # 「一个工作流最多一条 running」，同一工作流里放不下多个 running 样本。
                queued = await _make_workflow(session, meta, name="排队待认领")
                started = await _make_workflow(session, meta, name="已被认领")
                completed = await _make_workflow(session, meta, name="已完成")
                skipped = await _make_workflow(session, meta, name="已跳过")

                queued_run = await _create_run(session, queued.id)
                already_started = await _create_run(
                    session, started.id, started_at=datetime.now(UTC)
                )
                completed_run = await _create_run(session, completed.id, status="completed")
                skipped_run = await _create_run(
                    session, skipped.id, status="skipped", skip_reason="overlapped"
                )
                await session.commit()

                repo = WorkflowRunRepository(session)
                claimed = await repo.claim_queued_runs()
                assert claimed == [queued_run.id]
                await session.commit()

                # 已认领（started_at 非空）的记录不会被第二次取走。
                assert await repo.claim_queued_runs() == []

                refreshed = await session.get(WorkflowRun, queued_run.id)
                assert refreshed.started_at is not None
                # 非 running 状态与已认领记录的 started_at 都不该被改写。
                assert (await session.get(WorkflowRun, skipped_run.id)).started_at is None
                assert (await session.get(WorkflowRun, completed_run.id)).started_at is None
                assert (
                    await session.get(WorkflowRun, already_started.id)
                ).started_at is not None
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_claim_queued_runs_respects_limit_and_oldest_first() -> None:
    """锁：认领按 id 升序且受 ``limit`` 限制（多副本调度不会一次全抢走）。"""

    async def run() -> None:
        engine, session_factory = await make_session()
        try:
            async with session_factory() as session:
                meta = await seed(session)
                # 同样一条工作流只能有一条 running，因此每个样本挂一个工作流。
                runs = []
                for index in range(3):
                    workflow = await _make_workflow(session, meta, name=f"排队{index}")
                    runs.append(await _create_run(session, workflow.id))
                await session.commit()

                claimed = await WorkflowRunRepository(session).claim_queued_runs(limit=2)
                assert claimed == [runs[0].id, runs[1].id]
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_expire_stale_running_uses_each_workflow_timeout() -> None:
    """锁（验收 8）：超时 running 被标 failed、error_message 含「超时」、
    ``watchdog_checked_at`` 被刷新；未超时的保持 running。

    超时按**每个工作流自己的** ``timeout_seconds`` 算，锚点是
    ``started_at or created_at``（``started_at`` 为空时用创建时间兜底）。
    """

    async def run() -> None:
        engine, session_factory = await make_session()
        try:
            async with session_factory() as session:
                meta = await seed(session)
                # 一条工作流只能有一条 running，所以两个超时样本各自挂一条工作流。
                short_a = await _make_workflow(
                    session, meta, name="短超时-按started_at", timeout_seconds=600
                )
                short_b = await _make_workflow(
                    session, meta, name="短超时-按created_at", timeout_seconds=600
                )
                long_running = await _make_workflow(
                    session, meta, name="长超时", timeout_seconds=100000
                )
                old = datetime.now(UTC) - timedelta(seconds=1000)

                stale_by_started = await _create_run(session, short_a.id, started_at=old)
                stale_by_created = await _create_run(session, short_b.id)
                # 锚点回落到 created_at：排队太久没被认领，同样要收敛。
                stale_by_created.created_at = old
                fresh = await _create_run(
                    session, long_running.id, started_at=datetime.now(UTC)
                )
                await session.commit()

                expired = await WorkflowRunRepository(session).expire_stale_running(
                    default_timeout_seconds=600
                )
                assert expired == 2
                await session.commit()

                stale = await session.get(WorkflowRun, stale_by_started.id)
                assert stale.status == "failed"
                assert "超时" in stale.error_message
                assert "超过 600 秒" in stale.error_message
                assert stale.finished_at is not None
                assert stale.watchdog_checked_at is not None

                fallback = await session.get(WorkflowRun, stale_by_created.id)
                assert fallback.status == "failed"
                assert "超时" in fallback.error_message

                survivor = await session.get(WorkflowRun, fresh.id)
                assert survivor.status == "running"
                assert survivor.error_message is None
                assert survivor.finished_at is None
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_fail_running_steps_fails_only_running_steps() -> None:
    """锁：把一个 run 下仍是 running 的步骤标 failed 并写 ``finished_at``，
    已 succeeded 的步骤不被改动，返回条数等于被改写的条数。"""

    async def run() -> None:
        engine, session_factory = await make_session()
        try:
            async with session_factory() as session:
                meta = await seed(session)
                workflow = await _make_workflow(session, meta)
                workflow_run = await _create_run(session, workflow.id)
                await session.commit()

                steps = WorkflowStepRunRepository(session)
                still_running = await steps.create_step_run(
                    run_id=workflow_run.id, step_id="slow", seq=0, node_type="agent"
                )
                succeeded = await steps.create_step_run(
                    run_id=workflow_run.id,
                    step_id="done",
                    seq=1,
                    node_type="agent",
                    status="succeeded",
                )
                failed = await steps.create_step_run(
                    run_id=workflow_run.id,
                    step_id="already_failed",
                    seq=2,
                    node_type="agent",
                    status="failed",
                )
                await session.commit()

                count = await steps.fail_running_steps(
                    workflow_run.id, error_message="执行超时：超过 600 秒仍未完成"
                )
                assert count == 1
                await session.commit()

                refreshed = await session.get(WorkflowStepRun, still_running.id)
                assert refreshed.status == "failed"
                assert refreshed.finished_at is not None
                assert refreshed.error_message == "执行超时：超过 600 秒仍未完成"

                untouched_success = await session.get(WorkflowStepRun, succeeded.id)
                assert untouched_success.status == "succeeded"
                assert untouched_success.error_message is None
                assert untouched_success.finished_at is None

                untouched_failure = await session.get(WorkflowStepRun, failed.id)
                assert untouched_failure.error_message is None
                assert untouched_failure.finished_at is None
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_list_for_run_orders_by_seq() -> None:
    """锁：步骤明细按 ``seq`` 升序返回（详情页与「哪一步用了兜底值」都依赖顺序）。"""

    async def run() -> None:
        engine, session_factory = await make_session()
        try:
            async with session_factory() as session:
                meta = await seed(session)
                workflow = await _make_workflow(session, meta)
                workflow_run = await _create_run(session, workflow.id)
                steps = WorkflowStepRunRepository(session)
                for seq, step_id in ((2, "third"), (0, "first"), (1, "second")):
                    await steps.create_step_run(
                        run_id=workflow_run.id, step_id=step_id, seq=seq, node_type="agent"
                    )
                await session.commit()

                ordered = await steps.list_for_run(workflow_run.id)
                assert [step.step_id for step in ordered] == ["first", "second", "third"]
                assert [step.seq for step in ordered] == [0, 1, 2]
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_list_workflows_visibility_rules_and_platform_scoping() -> None:
    """锁（照 ``tests/tasks/test_task_repository.py`` 的可见性用例）：
    ``owner_user_id=<member>`` 只看自己的；``owner_user_id=None`` 是管理员视角看全部；
    ``get_scoped`` 跨平台取不到。"""

    async def run() -> None:
        engine, session_factory = await make_session()
        try:
            async with session_factory() as session:
                meta = await seed(session)
                mine = await _make_workflow(session, meta, name="我的")
                others = await _make_workflow(
                    session, meta, name="别人的", owner_user_id=meta.admin.id
                )
                platform_level = await _make_workflow(
                    session, meta, name="平台级", owner_user_id=None
                )
                await session.commit()

                repo = WorkflowRepository(session)
                params = PaginationParams(page=1, page_size=20)

                member_page = await repo.list_workflows(
                    meta.platform.id, params, owner_user_id=meta.member.id
                )
                assert [item.id for item in member_page.items] == [mine.id]
                assert (member_page.total, member_page.page_no) == (1, 1)

                admin_page = await repo.list_workflows(
                    meta.platform.id, params, owner_user_id=None
                )
                assert [item.id for item in admin_page.items] == [
                    platform_level.id,
                    others.id,
                    mine.id,
                ]
                assert admin_page.total == 3

                # 另一个平台（next_suffix 避开 Platform.code 唯一冲突）。
                other_meta = await seed(session)
                await session.commit()
                assert await repo.get_scoped(mine.id, other_meta.platform.id) is None
                found = await repo.get_scoped(mine.id, meta.platform.id)
                assert found is not None and found.id == mine.id
                assert await repo.count_for_platform(meta.platform.id) == 3
                assert await repo.count_for_platform(other_meta.platform.id) == 0
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_list_workflows_status_filter_applies_on_top_of_visibility() -> None:
    """锁：``status`` 过滤与归属过滤是叠加条件，不是二选一。"""

    async def run() -> None:
        engine, session_factory = await make_session()
        try:
            async with session_factory() as session:
                meta = await seed(session)
                active = await _make_workflow(session, meta, name="启用")
                paused = await _make_workflow(session, meta, name="暂停", status="paused")
                await session.commit()

                repo = WorkflowRepository(session)
                params = PaginationParams(page=1, page_size=20)
                page = await repo.list_workflows(
                    meta.platform.id,
                    params,
                    owner_user_id=meta.member.id,
                    status="paused",
                )
                assert [item.id for item in page.items] == [paused.id]
                assert page.total == 1

                everything = await repo.list_workflows(
                    meta.platform.id, params, owner_user_id=meta.member.id
                )
                assert [item.id for item in everything.items] == [paused.id, active.id]
        finally:
            await engine.dispose()

    asyncio.run(run())
