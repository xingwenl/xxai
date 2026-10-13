"""工作流调度 tick 函数。

与 ``app/modules/tasks/scheduler.py`` 同构，但**不是**一个独立的常驻入口：
工作流的 tick 由任务调度器的 ``_supervise`` 在每一轮里调用（见
``app/modules/tasks/scheduler.py``），这样只保留一个调度进程与一套生命周期，
避免两个常驻循环各跑各的看门狗与抢占。

本模块只导出三个东西：

1. ``MAX_CONCURRENT_RUNS``：并发执行上限（与任务调度器共享同一个信号量）；
2. ``_watchdog``：把超时仍 running 的工作流运行标记为失败；
3. ``_claim_and_dispatch_workflows``：抢占到期的工作流触发点，并按串联/暂停/
   超期三种情况决定写新运行还是写一条跳过记录，最后认领所有已排队的运行。

定时触发复用任务模块已定案的抢占语义：``FOR UPDATE SKIP LOCKED`` 保证多副本
下同一个触发点只被一个副本拿到；``next_run_at`` 与抢占在同一事务内推进，
因此**错过触发点不补跑**。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.core.logging import get_logger
from app.modules.tasks.repositories import TaskRepository
from app.modules.tasks.triggers import compute_next_run_at
from app.modules.workflows.models import Workflow
from app.modules.workflows.repositories import WorkflowRunRepository

logger = get_logger(__name__)

# 并发执行的运行上限：防止一次性抢到太多运行后同时打满模型网关。
# 任务与工作流两类运行共享这一个上限（见 tasks/scheduler.py 的信号量）。
MAX_CONCURRENT_RUNS = 5

# 触发点过期多久就不再补跑：进程停机很久后重启，一批早该跑的触发点会同时
# 到期，全部补跑等于一次自伤式的雪崩，因此超过宽限的直接记 deadline_missed
# 跳过（**不补跑**，与任务模块「错过触发点不补跑」的口径一致）。
MISSED_TRIGGER_GRACE_SECONDS = 300


async def _watchdog(session_factory, *, default_timeout_seconds: int) -> int:
    """清理超时的 running 工作流运行，返回处理条数。"""

    async with session_factory() as session:
        expired = await WorkflowRunRepository(session).expire_stale_running(
            default_timeout_seconds=default_timeout_seconds
        )
        await session.commit()
    if expired:
        logger.warning("Workflow watchdog marked %s stale run(s) as failed", expired)
    return expired


async def _claim_and_dispatch_workflows(
    session_factory, *, limit: int = 50
) -> list[int]:
    """认领本轮要执行的工作流运行，返回 run id 列表。

    与任务的 ``_claim_and_dispatch`` 一样分两个独立事务：

    1. **抢占到期触发点**：只抢 ``workflow_id`` 非空的任务（``workflow_linked=True``），
       写运行记录、推进 ``next_run_at`` 必须在**同一个事务**内提交，否则进程
       崩溃会重复触发、多副本之间也会重复。
    2. **认领已排队的运行**：含本 tick 刚写入的记录、手动运行接口写入的记录，
       以及上一次进程被杀时遗留的待执行记录。
    """

    now = datetime.now(UTC)
    async with session_factory() as session:
        task_repo = TaskRepository(session)
        run_repo = WorkflowRunRepository(session)
        claimed = await task_repo.claim_due_tasks(limit=limit, workflow_linked=True)
        for task in claimed:
            # planned_at 取「推进之前」的值，与任务模块同一取法：它标识这次运行
            # 对应的是哪一个触发点。sqlite 不保留时区信息，读出来可能是 naive，
            # 与 aware 的 now 相减会直接抛 TypeError，所以先按 UTC 补齐时区。
            planned_at = task.next_run_at
            if planned_at is not None and planned_at.tzinfo is None:
                planned_at = planned_at.replace(tzinfo=UTC)
            workflow = await session.get(Workflow, task.workflow_id)
            if workflow is None:
                # 防御性分支：正常路径下工作流被删时 tasks 上的外键会 CASCADE
                # 把触发任务一起删掉，理论上到不了这里。真出现了也没有工作流
                # 可挂，只能记警告跳过；仍需照常推进触发点，否则这条任务每个
                # tick 都会被重新抢占、刷出无尽的告警。
                logger.warning(
                    "Workflow trigger skipped (workflow_missing) task_id=%s workflow_id=%s",
                    task.id,
                    task.workflow_id,
                )
                task.next_run_at = compute_next_run_at(
                    trigger_type=task.trigger_type,
                    timezone_name=task.timezone,
                    now=now,
                    cron_expression=task.cron_expression,
                    run_at=task.run_at,
                )
                continue

            # 运行记录按定义快照冻结当次执行的内容，定义之后被改动也不影响它。
            total_steps = len((workflow.definition or {}).get("nodes") or [])
            definition_version_id = workflow.version
            definition_snapshot = workflow.definition

            if workflow.status != "active":
                # 工作流已暂停：触发点不执行，但要留一条 skipped 记录，
                # 否则「为什么这几次没跑」在界面上无迹可查。
                await run_repo.create_run(
                    workflow_id=workflow.id,
                    status="skipped",
                    trigger_kind="scheduled",
                    definition_version_id=definition_version_id,
                    definition_snapshot=definition_snapshot,
                    total_steps=total_steps,
                    skip_reason="workflow_paused",
                    planned_at=planned_at,
                )
                logger.info(
                    "Workflow trigger skipped (workflow_paused) workflow_id=%s",
                    workflow.id,
                )
            elif planned_at is not None and (
                now - planned_at > timedelta(seconds=MISSED_TRIGGER_GRACE_SECONDS)
            ):
                # 超过宽限的触发点不补跑：停机很久后重启时，若补跑所有过期
                # 触发点会集中撞上模型网关，宁可记 deadline_missed 跳过。
                await run_repo.create_run(
                    workflow_id=workflow.id,
                    status="skipped",
                    trigger_kind="scheduled",
                    definition_version_id=definition_version_id,
                    definition_snapshot=definition_snapshot,
                    total_steps=total_steps,
                    skip_reason="deadline_missed",
                    planned_at=planned_at,
                )
                logger.info(
                    "Workflow trigger skipped (deadline_missed) workflow_id=%s planned_at=%s",
                    workflow.id,
                    planned_at,
                )
            else:
                running = await run_repo.get_running(workflow.id)
                if running is not None:
                    # 同一工作流串行：上一次还没结束，这次触发记为跳过。
                    await run_repo.create_run(
                        workflow_id=workflow.id,
                        status="skipped",
                        trigger_kind="scheduled",
                        definition_version_id=definition_version_id,
                        definition_snapshot=definition_snapshot,
                        total_steps=total_steps,
                        skip_reason="overlapped",
                        planned_at=planned_at,
                    )
                    logger.info(
                        "Workflow trigger skipped (overlapped) workflow_id=%s planned_at=%s",
                        workflow.id,
                        planned_at,
                    )
                else:
                    # 执行身份由触发源决定（Q9 的决定）：普通任务用 run_as_user_id
                    # （为空时回落到归属人），终端用户任务用 run_as_end_user_id。
                    # 身份不在工作流定义里存死，同一份定义才能被不同身份复用。
                    # started_at=None 表示「已排队」：status=running 且 started_at
                    # 为空，由下面的 claim_queued_runs 统一认领，这样定时触发与
                    # 手动运行走同一条执行路径。
                    await run_repo.create_run(
                        workflow_id=workflow.id,
                        status="running",
                        trigger_kind="scheduled",
                        definition_version_id=definition_version_id,
                        definition_snapshot=definition_snapshot,
                        total_steps=total_steps,
                        run_as_type=task.run_as_type,
                        run_as_user_id=(
                            (task.run_as_user_id or task.owner_user_id)
                            if task.run_as_type == "user"
                            else None
                        ),
                        run_as_end_user_id=(
                            task.run_as_end_user_id
                            if task.run_as_type == "end_user"
                            else None
                        ),
                        planned_at=planned_at,
                        started_at=None,
                    )

            # 推进下一次触发：cron 从当前时间往后取（错过不补跑）；
            # 一次性任务跑完即止（next_run_at 置空）。
            task.next_run_at = compute_next_run_at(
                trigger_type=task.trigger_type,
                timezone_name=task.timezone,
                now=now,
                cron_expression=task.cron_expression,
                run_at=task.run_at,
            )
        await session.commit()

    # 第二步：认领所有已排队的运行（含手动触发与重启遗留）。
    # 与抢占分开事务：抢占的锁窗口要尽量短，认领失败也不该回滚触发推进。
    async with session_factory() as session:
        pending = await WorkflowRunRepository(session).claim_queued_runs(limit=limit)
        await session.commit()
    return pending


__all__ = [
    "MAX_CONCURRENT_RUNS",
    "MISSED_TRIGGER_GRACE_SECONDS",
    "_claim_and_dispatch_workflows",
    "_watchdog",
]
