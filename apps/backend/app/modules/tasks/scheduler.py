"""任务调度常驻进程入口。

运行方式：``python -m app.modules.tasks.scheduler``

形态与 ``wechat_bot/worker.py`` 同构：不启动 FastAPI，只做
``setup_logging`` + 常驻 asyncio 循环。每个 tick 做四件事：

1. **看门狗**：把超时仍 running 的执行记录标记为失败。这是唯一的兜底
   清理入口——进程被杀、容器重启都会留下永久 running，而会话侧没有
   任何超时清理。
2. **抢占到期任务**：``FOR UPDATE SKIP LOCKED``，抢占与推进 ``next_run_at``
   在同一事务内提交。多副本同时跑也只有一个副本能拿到同一个触发点。
3. **启动执行**：为每条抢占到的任务写入执行记录并提交，再用独立 Task
   去跑 Agent。调度循环本身不等模型跑完，避免一个慢任务拖住整轮 tick。
4. **驱动工作流 tick**：工作流没有独立的常驻进程，它的看门狗与定时触发
   都由本循环代为驱动（见 ``app.modules.workflows.scheduler``），两类运行
   共享同一个并发上限。

并发语义：
- 抢占时若该任务已有 running 记录，写一条 ``skipped(overlapped)``，不发新运行；
- 错过触发点不补跑：``next_run_at`` 永远从「当前时间之后」重算。
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
from datetime import UTC, datetime

from app.core.config import get_settings
from app.core.database import get_session_factory
from app.core.logging import get_logger, setup_logging
from app.modules.tasks import runner
from app.modules.tasks.repositories import TaskRepository, TaskRunRepository
from app.modules.tasks.triggers import compute_next_run_at
from app.modules.workflows import runner as workflow_runner
from app.modules.workflows import scheduler as workflow_scheduler

logger = get_logger(__name__)

# 并发执行的运行上限：防止一次性抢到太多任务后同时打满模型网关。
MAX_CONCURRENT_RUNS = 5


async def _watchdog(session_factory, *, default_timeout_seconds: int) -> int:
    """清理超时的 running 记录，返回处理条数。"""

    async with session_factory() as session:
        expired = await TaskRunRepository(session).expire_stale_running(
            default_timeout_seconds=default_timeout_seconds
        )
        await session.commit()
    if expired:
        logger.warning("Task watchdog marked %s stale run(s) as failed", expired)
    return expired


async def _claim_and_dispatch(session_factory, *, limit: int = 50) -> list[int]:
    """认领本轮要执行的 run，返回 run id 列表。

    做两件事，都必须在各自事务内完成：

    1. **抢占到期任务**：抢占、写执行记录、推进 ``next_run_at`` 必须在
       **同一个事务**内提交，否则进程崩溃会重复触发、多副本之间也会重复。
    2. **认领已排队的 run**：包括「立即运行一次」由接口写入的记录，
       以及上一次进程被杀时遗留的待执行记录。

    第 2 步是必需的：调度器如果只执行自己在本 tick 里创建的记录，
    接口写入的 run 就永远无人认领，只会卡在 running 直到被看门狗判超时。
    """

    now = datetime.now(UTC)
    async with session_factory() as session:
        task_repo = TaskRepository(session)
        run_repo = TaskRunRepository(session)
        # 显式排除「由工作流触发」的任务：工作流触发点由
        # app.modules.workflows.scheduler 单独认领（workflow_linked=True），
        # 两条路径因此切成互不相交的集合，同一批到期任务不会被两个 tick
        # 同时处理、也不会各自跑一遍。
        claimed = await task_repo.claim_due_tasks(limit=limit, workflow_linked=False)
        for task in claimed:
            planned_at = task.next_run_at
            running = await run_repo.get_running(task.id)
            if running is not None:
                # 同一任务串行：上一次还没结束，这次触发记为跳过。
                await run_repo.create_run(
                    task_id=task.id,
                    status="skipped",
                    trigger_kind="scheduled",
                    planned_at=planned_at,
                    skip_reason="overlapped",
                )
                logger.info(
                    "Task trigger skipped (overlapped) task_id=%s planned_at=%s",
                    task.id,
                    planned_at,
                )
            else:
                # 只入队、不写 started_at；下面的 claim_queued_runs 统一认领，
                # 这样「到点触发」与「手动触发」走同一条执行路径。
                await run_repo.create_run(
                    task_id=task.id,
                    status="running",
                    trigger_kind="scheduled",
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

    # 第二步：认领所有已排队的 run（含手动触发与重启遗留）。
    # 与抢占分开事务：抢占的锁窗口要尽量短，认领失败也不该回滚触发推进。
    async with session_factory() as session:
        pending = await TaskRunRepository(session).claim_queued_runs(limit=limit)
        await session.commit()
    return pending


async def _supervise() -> None:
    """常驻调度循环。"""

    settings = get_settings()
    session_factory = get_session_factory()
    tick_seconds = settings.task_scheduler_tick_seconds
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_RUNS)
    in_flight: set[asyncio.Task] = set()

    logger.info(
        "任务调度器启动（tick=%ss default_timeout=%ss max_concurrent=%s）",
        tick_seconds,
        settings.task_default_timeout_seconds,
        MAX_CONCURRENT_RUNS,
    )

    async def _run_one(run_id: int) -> None:
        async with semaphore:
            try:
                await runner.run_task_run(session_factory, task_run_id=run_id)
            except Exception:  # noqa: BLE001 - 单条运行失败不能拖垮调度循环
                logger.exception("Task run crashed task_run_id=%s", run_id)

    async def _run_workflow_one(run_id: int) -> None:
        # 与任务运行共享同一个 semaphore：两类运行合计不超过
        # MAX_CONCURRENT_RUNS，这是有意的——工作流每一步都要打模型网关，
        # 两类运行各自无上限地并发会把网关打满。
        async with semaphore:
            try:
                await workflow_runner.run_workflow_run(
                    session_factory, workflow_run_id=run_id
                )
            except Exception:  # noqa: BLE001 - 单条运行失败不能拖垮调度循环
                logger.exception("Workflow run crashed workflow_run_id=%s", run_id)

    try:
        while True:
            try:
                await _watchdog(
                    session_factory,
                    default_timeout_seconds=settings.task_default_timeout_seconds,
                )
                # 只认领「马上就能开始跑」的数量：认领会写入 started_at，
                # 而看门狗按 started_at 计算超时。如果一次认领远多于并发上限，
                # 排队的记录会被当成"已在执行"并在真正开跑前被误判超时。
                available = max(1, MAX_CONCURRENT_RUNS - len(in_flight))
                pending = await _claim_and_dispatch(session_factory, limit=available)
                for run_id in pending:
                    task = asyncio.create_task(_run_one(run_id))
                    in_flight.add(task)
                    task.add_done_callback(in_flight.discard)

                # 工作流 tick：工作流没有独立的常驻进程，它的每一轮都由这里
                # 代为驱动，因此全局只有一个调度进程、一套启停生命周期。
                # 放在普通任务派发之后，是为了让工作流侧的异常（多一次 DB
                # 往返、多一个模块的代码）不影响已定稿的任务链路。
                await workflow_scheduler._watchdog(
                    session_factory,
                    default_timeout_seconds=settings.task_default_timeout_seconds,
                )
                # 工作流看门狗内部已记 warning，这里不重复记。
                # limit 取「扣掉在途运行后的剩余额度」：claim_queued_runs 会写
                # started_at，而看门狗按 started_at 算超时，一次认领超过并发
                # 上限会让排队中的记录在真正开跑前被误判超时（理由同上文）。
                pending_workflow_runs = (
                    await workflow_scheduler._claim_and_dispatch_workflows(
                        session_factory,
                        limit=max(1, MAX_CONCURRENT_RUNS - len(in_flight)),
                    )
                )
                for run_id in pending_workflow_runs:
                    task = asyncio.create_task(_run_workflow_one(run_id))
                    in_flight.add(task)
                    task.add_done_callback(in_flight.discard)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - 数据库抖动等不应终止调度进程
                logger.exception("Task scheduler tick failed; will retry next tick")

            await asyncio.sleep(tick_seconds)
    except asyncio.CancelledError:
        logger.info("任务调度器停止，等待在途运行结束…")
        for task in list(in_flight):
            task.cancel()
        with contextlib.suppress(Exception):
            await asyncio.gather(*in_flight, return_exceptions=True)
        raise


def main() -> None:
    settings = get_settings()
    setup_logging(
        settings.log_level,
        log_file_path=settings.log_file_path,
        log_file_backup_count=settings.log_file_backup_count,
    )
    if not settings.task_scheduler_enabled:
        logger.info("TASK_SCHEDULER_ENABLED=false，任务调度器退出")
        return

    try:
        asyncio.run(_supervise())
    except KeyboardInterrupt:
        logger.info("任务调度器退出")


if __name__ == "__main__":
    sys.exit(main())
