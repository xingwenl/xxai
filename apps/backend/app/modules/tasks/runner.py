"""单次任务运行的编排：建会话 → 跑一轮 Agent → 回写执行结果。

职责边界：调度器只负责「什么时候跑」，这里负责「怎么跑完一次并留下痕迹」。
与 HTTP 聊天路径的区别是有超时上限与结果回写——无人值守运行必须自己
兜住失败，否则执行记录会永远停在 running。

并发模型（与仓库既有约束一致）：
- 执行使用独立 Session，不与调度 tick 共用；
- 模型循环跑在 ``AgentRuntime`` 内部启动的独立 Task 中，会话关闭前
  必须确定性 join（由 ``execute_chat`` 链路内部保证）；
- 单次运行整体套 ``asyncio.wait_for``，超时后取消并记为失败。
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.core.logging import get_logger
from app.modules.conversation.services import execute_unattended_chat
from app.modules.tasks.models import Task, TaskRun
from app.modules.tasks.repositories import TaskRunRepository
from app.modules.tasks.unattended import UnattendedPolicy, build_confirmation_decider

logger = get_logger(__name__)


async def run_task_run(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    task_run_id: int,
) -> str:
    """执行一条任务运行记录，返回最终状态。

    全程用一个新的 Session，避免与调度 tick 的事务互相影响；无论成功、
    失败还是超时，都会把结果写回执行记录。
    """

    settings = get_settings()
    async with session_factory() as session:
        run = await session.get(TaskRun, task_run_id)
        if run is None:
            logger.warning("Task run not found task_run_id=%s", task_run_id)
            return "missing"
        if run.status != "running":
            # 已被看门狗标记失败，或被人为终止：不重复执行。
            logger.info(
                "Task run skipped because status=%s task_run_id=%s",
                run.status,
                task_run_id,
            )
            return run.status
        task = await session.get(Task, run.task_id)
        if task is None:
            await TaskRunRepository(session).finish_run(
                run, status="failed", error_message="任务已被删除"
            )
            await session.commit()
            return "failed"
        if task.status == "paused":
            # 暂停发生在排队与执行之间：记为跳过，不发起模型调用。
            await TaskRunRepository(session).finish_run(
                run,
                status="skipped",
                error_message=None,
            )
            run.skip_reason = "task_paused"
            run.finished_at = datetime.now(UTC)
            await session.commit()
            return "skipped"

        # 取出执行所需的普通字段，避免后续在长任务里持有 ORM 对象。
        task_id = task.id
        platform_id = task.platform_id
        agent_id = task.agent_id
        prompt = task.prompt
        model_id = task.model_id
        timeout_seconds = task.timeout_seconds or settings.task_default_timeout_seconds
        run_as_type = task.run_as_type
        # 后台用户身份允许回落到归属（历史数据没有写 run_as_user_id）；
        # 终端用户身份只认 run_as_end_user_id。
        run_as_user_id = (
            (task.run_as_user_id or task.owner_user_id)
            if run_as_type == "user"
            else None
        )
        run_as_end_user_id = (
            task.run_as_end_user_id if run_as_type == "end_user" else None
        )
        policy = UnattendedPolicy(
            auto_approve=task.auto_approve,
            strict_approval=task.strict_approval,
        )

    if run_as_user_id is None and run_as_end_user_id is None:
        # 必须有一个 principal：会话与工具审计都要求「恰有一个」身份，
        # 否则这一轮无人值守运行既建不了会话、也记不了账。
        async with session_factory() as session:
            run = await session.get(TaskRun, task_run_id)
            if run is not None:
                await TaskRunRepository(session).finish_run(
                    run,
                    status="failed",
                    error_message=(
                        "任务没有可用的执行身份：既没有后台用户（run_as_user_id），"
                        "也没有终端用户（run_as_end_user_id）"
                    ),
                )
                await session.commit()
        return "failed"

    logger.info(
        "Task run started task_id=%s task_run_id=%s platform_id=%s agent_id=%s run_as_type=%s run_as_user_id=%s run_as_end_user_id=%s timeout=%s",
        task_id,
        task_run_id,
        platform_id,
        agent_id,
        run_as_type,
        run_as_user_id,
        run_as_end_user_id,
        timeout_seconds,
    )

    try:
        conversation_id, loop_id = await asyncio.wait_for(
            _execute_once(
                session_factory,
                platform_id=platform_id,
                agent_id=agent_id,
                run_as_type=run_as_type,
                user_id=run_as_user_id,
                end_user_id=run_as_end_user_id,
                prompt=prompt,
                model_id=model_id,
                policy=policy,
            ),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError:
        await _finish(
            session_factory,
            task_run_id=task_run_id,
            status="failed",
            error_message=f"执行超时：超过 {timeout_seconds} 秒仍未完成",
            auto_approved_count=policy.approved_count,
        )
        logger.warning(
            "Task run timed out task_run_id=%s timeout=%s", task_run_id, timeout_seconds
        )
        return "failed"
    except Exception as exc:  # noqa: BLE001 - 无人值守必须兜住所有异常并留痕
        await _finish(
            session_factory,
            task_run_id=task_run_id,
            status="failed",
            error_message=f"执行失败：{type(exc).__name__}: {exc}",
            auto_approved_count=policy.approved_count,
        )
        logger.exception(
            "Task run failed task_run_id=%s task_id=%s", task_run_id, task_id
        )
        return "failed"

    await _finish(
        session_factory,
        task_run_id=task_run_id,
        status="completed",
        conversation_id=conversation_id,
        agent_loop_run_id=loop_id,
        auto_approved_count=policy.approved_count,
    )
    logger.info(
        "Task run completed task_run_id=%s conversation_id=%s loop_id=%s auto_approved=%s",
        task_run_id,
        conversation_id,
        loop_id,
        policy.approved_count,
    )
    return "completed"


async def _execute_once(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    platform_id: int,
    agent_id: int,
    run_as_type: str,
    user_id: int | None,
    end_user_id: int | None,
    prompt: str,
    model_id: int | None,
    policy: UnattendedPolicy,
) -> tuple[int | None, int | None]:
    """跑完一轮对话，返回 (conversation_id, agent_loop_run_id)。

    这里对应 REST 的非流式路径：内层模型 Task 的生命周期由
    ``execute_chat`` 内部的运行时自行收敛（流式路径才需要调用方登记
    并 join 模型 Task），因此本函数不额外管理 Task 集合。
    """

    # 会话与工具执行分属两个 Session：模型循环跑在独立 Task 中，
    # 与消费方共用一个 AsyncSession 会触发并发状态错误。
    async with (
        session_factory() as session,
        session_factory() as tool_session,
    ):
        conversation, assistant, result = await execute_unattended_chat(
            session,
            platform_id=platform_id,
            agent_id=agent_id,
            run_as_type=run_as_type,
            user_id=user_id,
            end_user_id=end_user_id,
            message=prompt,
            model_id=model_id,
            confirmation_decider=build_confirmation_decider(policy),
            tool_session=tool_session,
            # 任务触发的运行不走「会话内编排接管」：接管是给终端用户对话准备的，
            # 而任务本身就是一条已经编排好的无人值守流程，两者叠加会让触发源
            # 说不清楚（还要给被接管的每一步再配一套审批口径）。
            allow_orchestration=False,
        )
        await session.commit()
        _ = assistant
        return conversation.id, getattr(result, "loop_id", None)


async def _finish(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    task_run_id: int,
    status: str,
    error_message: str | None = None,
    conversation_id: int | None = None,
    agent_loop_run_id: int | None = None,
    auto_approved_count: int = 0,
) -> None:
    """把执行结果写回执行记录。"""

    async with session_factory() as session:
        run = await session.get(TaskRun, task_run_id)
        if run is None:
            return
        repo = TaskRunRepository(session)
        # 超时被取消时可能已经写了会话，尽量保留已有痕迹。
        await repo.finish_run(
            run,
            status=status,
            error_message=error_message,
            conversation_id=conversation_id,
            agent_loop_run_id=agent_loop_run_id,
            auto_approved_count=auto_approved_count,
        )
        await session.commit()
