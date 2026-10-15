"""任务业务规则层。

承载四类规则，接口层与调度层共用：
1. 任务的可见性与管理权限（平台级任务只有管理员能改，个人任务只有本人能改）；
2. 触发规则的校验与 ``next_run_at`` 计算（统一走 ``triggers``）；
3. 任务数量上限与状态流转（暂停 / 恢复）；
4. 执行记录的读取。

执行本身不在这里：真实发起 Agent 运行的是 ``runner``，调度由 ``scheduler`` 驱动。
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.agent.repositories import AgentRepository
from app.modules.tasks.models import Task, TaskRun
from app.modules.tasks.repositories import TaskRepository, TaskRunRepository
from app.modules.tasks.schemas import TaskCreate, TaskUpdate
from app.modules.tasks.triggers import (
    compute_next_run_at,
    ensure_min_interval,
    validate_cron_expression,
)
from app.shared.exceptions import BadRequestException, ConflictException, NotFoundException
from app.shared.pagination import PaginationParams


async def _validate_trigger(
    *,
    trigger_type: str,
    cron_expression: str | None,
    run_at: datetime | None,
    timezone: str,
) -> None:
    """校验触发规则；cron 额外校验表达式合法性与最小间隔。"""

    if trigger_type == "cron":
        if not cron_expression:
            raise BadRequestException("cron expression is required")
        validate_cron_expression(cron_expression)
        # 最小间隔下限在写入前就拒绝，避免高频任务把调度与模型调用写爆。
        ensure_min_interval(cron_expression, timezone_name=timezone)
    elif trigger_type == "once":
        if run_at is None:
            raise BadRequestException("run_at is required")
    else:
        raise BadRequestException(f"unknown trigger type: {trigger_type}")


async def _ensure_agent_available(
    session: AsyncSession, *, agent_id: int, platform_id: int
) -> None:
    """确认目标智能体属于该平台且已发布，否则任务到点必然失败。"""

    agent = await AgentRepository(session).get_published_agent(agent_id, platform_id)
    if agent is None:
        raise BadRequestException("published agent not found in this platform")


async def create_task(
    session: AsyncSession,
    *,
    platform_id: int,
    payload: TaskCreate,
    owner_user_id: int | None,
    created_by_type: str = "user",
    created_by_user_id: int | None = None,
    created_by_agent_id: int | None = None,
    run_as_user_id: int | None = None,
    run_as_end_user_id: int | None = None,
    run_as_type: str | None = None,
) -> Task:
    """创建任务。

    归属与执行身份是两件事：

    - ``owner_user_id``：后台归属，为空表示平台级任务或终端用户任务；
    - ``run_as_*``：执行身份。后台会话用 ``user``（``run_as_user_id``），
      Embed 会话用 ``end_user``（``run_as_end_user_id``）。

    ``run_as_type`` 不传时按已有 id 推断，保证「谁的任务就以谁的身份跑」。
    """

    settings = get_settings()
    repo = TaskRepository(session)
    total = await repo.count_for_platform(platform_id)
    if total >= settings.task_max_per_platform:
        raise ConflictException(
            f"platform task limit reached ({settings.task_max_per_platform})"
        )

    await _ensure_agent_available(
        session, agent_id=payload.agent_id, platform_id=platform_id
    )
    await _validate_trigger(
        trigger_type=payload.trigger_type,
        cron_expression=payload.cron_expression,
        run_at=payload.run_at,
        timezone=payload.timezone,
    )

    now = datetime.now(UTC)
    # 创建场景用 honor_run_at：未来的原定时刻原样保留，不被顺延。
    next_run_at = compute_next_run_at(
        trigger_type=payload.trigger_type,
        timezone_name=payload.timezone,
        now=now,
        cron_expression=payload.cron_expression,
        run_at=payload.run_at,
        honor_run_at=True,
    )
    if next_run_at is None:
        raise BadRequestException("run_at must be in the future")

    # 执行身份优先级：显式指定的类型 > 按已有 id 推断。
    # 终端用户任务（Embed 链路）没有后台归属，因此不能回落到 owner_user_id。
    if run_as_type is None:
        run_as_type = "end_user" if run_as_end_user_id is not None else "user"
    if run_as_type not in {"user", "end_user"}:
        # platform 仍是预留取值：现有数据模型没有平台主体 principal。
        raise BadRequestException(f"unsupported run_as_type: {run_as_type}")
    if run_as_type == "user":
        effective_run_as_user = run_as_user_id or owner_user_id
    else:
        effective_run_as_user = None
    task = await repo.create(
        platform_id=platform_id,
        agent_id=payload.agent_id,
        owner_user_id=owner_user_id,
        name=payload.name,
        prompt=payload.prompt,
        model_id=payload.model_id,
        trigger_type=payload.trigger_type,
        cron_expression=payload.cron_expression,
        run_at=payload.run_at,
        timezone=payload.timezone,
        status="active",
        next_run_at=next_run_at,
        created_by_type=created_by_type,
        created_by_user_id=created_by_user_id,
        created_by_agent_id=created_by_agent_id,
        run_as_type=run_as_type,
        run_as_user_id=effective_run_as_user,
        run_as_end_user_id=run_as_end_user_id if run_as_type == "end_user" else None,
        auto_approve=payload.auto_approve,
        strict_approval=payload.strict_approval,
        timeout_seconds=payload.timeout_seconds,
    )
    return task


async def update_task(
    session: AsyncSession,
    task: Task,
    payload: TaskUpdate,
) -> Task:
    """更新任务；触发规则变化时重算 ``next_run_at``。

    恢复（``paused -> active``）同样重算，且**不补跑**历史触发点——
    因为 ``next_run_at`` 始终从「当前时间之后」取。
    """

    repo = TaskRepository(session)
    changes = payload.model_dump(exclude_unset=True)

    trigger_type = changes.get("trigger_type", task.trigger_type)
    timezone = changes.get("timezone", task.timezone)
    cron_expression = changes.get("cron_expression", task.cron_expression)
    run_at = changes.get("run_at", task.run_at)

    trigger_touched = any(
        key in changes
        for key in ("trigger_type", "cron_expression", "run_at", "timezone")
    )

    if changes.get("agent_id") is not None:
        await _ensure_agent_available(
            session, agent_id=changes["agent_id"], platform_id=task.platform_id
        )

    if trigger_touched:
        await _validate_trigger(
            trigger_type=trigger_type,
            cron_expression=cron_expression,
            run_at=run_at,
            timezone=timezone,
        )

    status = changes.get("status", task.status)
    if status not in {"active", "paused"}:
        raise BadRequestException("invalid task status")

    # 先落普通字段，再单独处理 next_run_at，避免把 None 写进去覆盖掉。
    for field, value in changes.items():
        if field == "run_at":
            continue
        setattr(task, field, value)
    if "run_at" in changes:
        task.run_at = run_at

    should_recompute = trigger_touched or status == "active"
    if should_recompute:
        now = datetime.now(UTC)
        # 恢复或改规则后一律从「当前时间之后」取下一个触发点，
        # 因此停机/暂停期间错过的触发点不会被补跑。
        task.next_run_at = compute_next_run_at(
            trigger_type=task.trigger_type,
            timezone_name=task.timezone,
            now=now,
            cron_expression=task.cron_expression,
            run_at=task.run_at,
        )
    if status == "paused":
        # 暂停即停止触发，但保留 last_run_at 供详情页展示。
        task.next_run_at = None
    return await repo.update(task)


async def delete_task(session: AsyncSession, task: Task) -> None:
    """删除任务；执行记录随任务级联删除，会话默认保留。"""

    await TaskRepository(session).delete(task)


async def get_task_or_404(
    session: AsyncSession, *, task_id: int, platform_id: int
) -> Task:
    """按平台范围取任务，不存在即 404。"""

    task = await TaskRepository(session).get_scoped(task_id, platform_id)
    if task is None:
        raise NotFoundException("task not found")
    return task


def assert_can_manage(task: Task, *, user_id: int, is_platform_admin: bool) -> None:
    """管理权限：平台级任务只有管理员能管，个人任务只有本人能管。"""

    if is_platform_admin:
        return
    if task.owner_user_id != user_id:
        # 用 404 语义而不是 403，避免泄露「存在这条任务」。
        raise NotFoundException("task not found")


async def list_tasks(
    session: AsyncSession,
    *,
    platform_id: int,
    params: PaginationParams,
    owner_user_id: int | None,
    status: str | None = None,
):
    """任务列表；``owner_user_id=None`` 表示管理员视角（全平台）。"""

    return await TaskRepository(session).list_tasks(
        platform_id, params, owner_user_id=owner_user_id, status=status
    )


async def list_task_runs(
    session: AsyncSession,
    *,
    task_id: int,
    params: PaginationParams,
    status: str | None = None,
):
    """执行记录列表。"""

    return await TaskRepository(session).list_runs(task_id, params, status=status)


async def enqueue_manual_run(
    session: AsyncSession, task: Task
) -> tuple[TaskRun, bool]:
    """为「立即运行一次」写入一条**待执行**记录。

    返回 ``(run, started)``：``started=False`` 表示该任务正在运行，
    本次被记为 ``skipped(overlapped)``——手动运行同样受串行约束。

    关键：这里**不写 started_at**。按执行记录的口径，
    ``status='running'`` 且 ``started_at IS NULL`` 表示「已排队、等待执行」，
    ``started_at`` 有值才代表真正在执行。手动运行只是入队，由调度器在
    下一个 tick 认领并写 ``started_at``。若在这里就写 ``started_at``，
    调度器会认为它已在执行而不再认领，导致这条记录永远卡在 running、
    最终被看门狗判为超时失败。
    """

    repo = TaskRunRepository(session)
    now = datetime.now(UTC)
    running = await repo.get_running(task.id)
    if running is not None:
        run = await repo.create_run(
            task_id=task.id,
            status="skipped",
            trigger_kind="manual",
            planned_at=now,
            skip_reason="overlapped",
        )
        await session.commit()
        return run, False

    run = await repo.create_run(
        task_id=task.id,
        status="running",
        trigger_kind="manual",
        planned_at=now,
        # 不写 started_at：留给调度器认领时写入，见上面的说明。
        started_at=None,
    )
    await session.commit()
    return run, True


async def get_run_detail(session: AsyncSession, *, task: Task, run_id: int):
    """读取单次运行的执行过程（步骤清单）。

    步骤数据来自 ``agent_loop_steps``，通过 ``task_runs.agent_loop_run_id``
    关联。复用 conversation 模块既有的 ``build_loop_payload``，避免任务侧
    再实现一遍"把 loop 组装成可读结构"的逻辑——两份实现迟早会漂移。
    """

    from app.modules.conversation.repositories import ConversationRepository
    from app.modules.conversation.services import build_loop_payload
    from app.modules.tasks.schemas import (
        TaskRunDelegatedRun,
        TaskRunDetail,
        TaskRunRead,
        TaskRunStepRead,
    )

    run = await session.get(TaskRun, run_id)
    if run is None or run.task_id != task.id:
        raise NotFoundException("task run not found")

    loop_payload = None
    if run.agent_loop_run_id is not None and run.conversation_id is not None:
        loop_payload = await build_loop_payload(
            ConversationRepository(session), run.agent_loop_run_id, run.conversation_id
        )

    steps = [
        TaskRunStepRead(
            id=str(step.get("id")),
            sequence=int(step.get("sequence") or 0),
            step_type=str(step.get("stepType") or ""),
            title=step.get("title"),
            status=step.get("status"),
            output_summary=step.get("outputSummary"),
            thinking_text=step.get("thinkingText"),
            tool_name=step.get("toolName"),
            skill_name=step.get("skillName"),
            delegatedRunIds=step.get("delegatedRunIds"),
            error=step.get("error"),
        )
        for step in (loop_payload or {}).get("steps", [])
    ]
    # 子运行摘要直接沿用 conversation 侧的投影结果（未委派时该键不存在 → None）。
    delegated_runs = [
        TaskRunDelegatedRun.model_validate(item)
        for item in (loop_payload or {}).get("delegatedRuns") or []
    ]
    return TaskRunDetail(
        run=TaskRunRead.model_validate(run),
        loop_id=(loop_payload or {}).get("id"),
        loop_status=(loop_payload or {}).get("status"),
        loop_summary=(loop_payload or {}).get("summary"),
        delegatedRuns=delegated_runs or None,
        steps=steps,
    )
