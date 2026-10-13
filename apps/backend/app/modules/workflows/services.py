"""工作流业务规则层。

承载四类规则，接口层与调度器共用：

1. **定义保存校验**：纯数据校验在 ``validators``，除此之外还要查库确认
   步骤引用的 Agent 属于本平台、工具步骤声明的工具真的可用；
2. **可见性与管理权限**：与 ``tasks`` 同一口径，非管理员只认 owner，
   且一律用 404 而不是 403；
3. **定义版本与运行快照**：每次保存定义令 ``version`` 加一，每次运行把
   当次定义整份快照写进运行记录，让历史运行永远解释得了自己；
4. **触发入队**：手动与定时触发都只写「已排队」记录，真实执行由调度器认领。

校验放在服务层而不是路由层，是因为定时触发不经过 HTTP：调度器必须和接口层
走过同一套规则，否则「接口存不进去的定义」可以绕过接口直接写库。

执行本身不在这里：真实跑流程的入口是 ``runner.run_workflow_run``。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.agent.repositories import AgentRepository
from app.modules.builtin_tool.repositories import BuiltinToolRepository
from app.modules.conversation.runtime import load_runtime_context
from app.modules.conversation.services import build_runtime_tool_list
from app.modules.knowledge.repositories import KnowledgeRepository
from app.modules.mcp.repositories import McpRepository
from app.modules.skill.repositories import SkillRepository
from app.modules.tasks.unattended import NEVER_AUTO_APPROVE_SIDE_EFFECTS
from app.modules.workflows import validators
from app.modules.workflows.models import Workflow, WorkflowRun
from app.modules.workflows.repositories import (
    WorkflowRepository,
    WorkflowRunRepository,
    WorkflowStepRunRepository,
)
from app.modules.workflows.schemas import (
    WorkflowCreate,
    WorkflowRunDetail,
    WorkflowRunRead,
    WorkflowStepRunDetail,
    WorkflowUpdate,
)
from app.shared.exceptions import BadRequestException, ConflictException, NotFoundException
from app.shared.pagination import PageData, PaginationParams


async def _ensure_published_agent(
    session: AsyncSession, *, agent_id: int, platform_id: int
) -> None:
    """确认 Agent 属于该平台且已发布，否则拒绝。

    跨租户越权只能从这里进来：步骤可以用 ``agent_id`` 覆盖工作流级 Agent，
    若不逐个校验，A 平台的工作流就能驱动 B 平台的 Agent 执行。
    """
    agent = await AgentRepository(session).get_published_agent(agent_id, platform_id)
    if agent is None:
        raise BadRequestException("该平台下不存在已发布的 Agent")


async def _load_agent_tools(
    session: AsyncSession,
    *,
    platform_id: int,
    agent_id: int,
    cache: dict[int, list[Any]],
) -> list[Any]:
    """取某 Agent 的运行期工具清单，同一 Agent 只加载一次。

    清单要聚合知识库 / 技能 / MCP / 内置工具，逐步骤重复加载没有意义，
    因此按 agent_id 缓存。
    """
    cached = cache.get(agent_id)
    if cached is not None:
        return cached
    context = await load_runtime_context(
        AgentRepository(session),
        KnowledgeRepository(session),
        SkillRepository(session),
        McpRepository(session),
        BuiltinToolRepository(session),
        agent_id=agent_id,
        platform_id=platform_id,
    )
    tools = build_runtime_tool_list(context)
    cache[agent_id] = tools
    return tools


async def _ensure_tool_step_available(
    session: AsyncSession,
    *,
    platform_id: int,
    agent_id: int,
    tool_name: str,
    cache: dict[int, list[Any]],
) -> None:
    """校验工具步骤：工具必须可用，且不能是永不自动批准的那类。

    「保存时就查工具」的理由：``financial`` 这类副作用的工具在无人值守下
    永远不会被批准，写进工作流等于每次运行都在这一步必定失败。如果留到运行
    时才拒绝，前面步骤的副作用早已真实发生，回滚不了。所以保存时就拦住。
    """
    tools = await _load_agent_tools(
        session, platform_id=platform_id, agent_id=agent_id, cache=cache
    )
    tool = next((c for c in tools if getattr(c, "name", None) == tool_name), None)
    if tool is None:
        raise BadRequestException(f"工具 {tool_name} 不在 Agent {agent_id} 的可用工具清单中")
    side_effect = getattr(tool, "side_effect", None)
    if side_effect in NEVER_AUTO_APPROVE_SIDE_EFFECTS:
        raise BadRequestException(
            f"工具 {tool_name} 的副作用类型为 {side_effect}，无人值守下不会被自动批准，"
            "因此不能写入工作流"
        )


async def _validate_step_references(
    session: AsyncSession,
    *,
    platform_id: int,
    default_agent_id: int,
    steps: list[dict[str, Any]],
) -> None:
    """校验步骤里需要查库的引用：Agent 与工具。"""
    await _ensure_published_agent(session, agent_id=default_agent_id, platform_id=platform_id)
    tool_cache: dict[int, list[Any]] = {}
    for step in steps:
        step_agent_id = step.get("agent_id")
        if step_agent_id is not None:
            await _ensure_published_agent(
                session, agent_id=int(step_agent_id), platform_id=platform_id
            )
        if step.get("kind") != "tool":
            continue
        effective_agent_id = (
            int(step_agent_id) if step_agent_id is not None else int(default_agent_id)
        )
        await _ensure_tool_step_available(
            session,
            platform_id=platform_id,
            agent_id=effective_agent_id,
            tool_name=str(step.get("tool_name") or ""),
            cache=tool_cache,
        )


async def create_workflow(
    session: AsyncSession,
    *,
    platform_id: int,
    payload: WorkflowCreate,
    owner_user_id: int,
    created_by_type: str = "user",
    created_by_user_id: int | None = None,
    created_by_agent_id: int | None = None,
) -> Workflow:
    """创建工作流：先校验，后写库。"""
    settings = get_settings()
    repo = WorkflowRepository(session)
    total = await repo.count_for_platform(platform_id)
    if total >= settings.workflow_max_per_platform:
        raise ConflictException(f"平台工作流数量已达上限（{settings.workflow_max_per_platform}）")

    steps = [step.model_dump() for step in payload.steps]
    # 顺序固定：先纯数据校验（便宜、无 IO），再查库校验，最后才落库。
    validators.validate_steps(steps, max_steps=payload.max_steps)
    await _validate_step_references(
        session,
        platform_id=platform_id,
        default_agent_id=payload.agent_id,
        steps=steps,
    )

    return await repo.create(
        platform_id=platform_id,
        name=payload.name,
        description=payload.description,
        agent_id=payload.agent_id,
        owner_user_id=owner_user_id,
        created_by_type=created_by_type,
        created_by_user_id=created_by_user_id,
        created_by_agent_id=created_by_agent_id,
        status="active",
        version=1,
        max_steps=payload.max_steps,
        definition=validators.compile_definition(steps),
        timeout_seconds=payload.timeout_seconds,
        auto_approve=payload.auto_approve,
        strict_approval=payload.strict_approval,
    )


async def update_workflow(
    session: AsyncSession, *, workflow: Workflow, payload: WorkflowUpdate
) -> Workflow:
    """更新工作流；只有显式传入的字段才生效。"""
    touched = payload.model_fields_set
    repo = WorkflowRepository(session)

    next_agent_id = workflow.agent_id
    if "agent_id" in touched and payload.agent_id is not None:
        await _ensure_published_agent(
            session, agent_id=payload.agent_id, platform_id=workflow.platform_id
        )
        next_agent_id = payload.agent_id

    if "steps" in touched and payload.steps is not None:
        steps = [step.model_dump() for step in payload.steps]
        # 更新接口不允许改 max_steps，因此沿用定义上的现值。
        validators.validate_steps(steps, max_steps=workflow.max_steps)
        await _validate_step_references(
            session,
            platform_id=workflow.platform_id,
            default_agent_id=next_agent_id,
            steps=steps,
        )
        workflow.definition = validators.compile_definition(steps)
        # 每次保存定义都令版本加一：运行记录靠 definition_version_id 标记当时
        # 执行的是哪一版，不递增就无法解释「这条运行跑的是哪份定义」。
        # 只改名字 / 状态 / 开关这类元数据时定义没变，版本不动。
        workflow.version += 1

    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        if field in {"steps", "agent_id"}:
            continue
        setattr(workflow, field, value)
    # agent_id 显式传 null 视为不变（该列非空，直接置空没有业务含义）。
    if "agent_id" in changes and changes["agent_id"] is not None:
        workflow.agent_id = next_agent_id

    return await repo.update(workflow)


async def get_workflow_or_404(
    session: AsyncSession, *, workflow_id: int, platform_id: int
) -> Workflow:
    """按平台范围取工作流，查不到即 404。

    必须带 platform_id：否则平台 A 的工作流 id 可以在平台 B 的路径下被读到。
    """
    workflow = await WorkflowRepository(session).get_scoped(workflow_id, platform_id)
    if workflow is None:
        raise NotFoundException("workflow not found")
    return workflow


def assert_can_manage(workflow: Workflow, *, user_id: int, is_platform_admin: bool) -> None:
    """校验管理权限：管理员放行，其余只认 owner。

    越权时抛 404 而不是 403：403 等于承认「这条定义存在」，会泄露他人工作流的
    存在性，404 则把「不存在」和「无权查看」合并成同一个回答。
    """
    if is_platform_admin:
        return
    if workflow.owner_user_id != user_id:
        raise NotFoundException("workflow not found")


async def list_workflows(
    session: AsyncSession,
    *,
    platform_id: int,
    params: PaginationParams,
    owner_user_id: int,
    status: str | None = None,
) -> PageData[Workflow]:
    """列出工作流：普通成员只看自己创建的，管理员看平台全部。

    管理员传入的 owner_user_id 为 None，表示不加 owner 过滤。
    """
    return await WorkflowRepository(session).list_workflows(
        platform_id, params, owner_user_id=owner_user_id, status=status
    )


async def delete_workflow(session: AsyncSession, *, workflow: Workflow) -> None:
    """删除工作流定义，其历史运行记录按库级外键级联处理。"""
    await WorkflowRepository(session).delete(workflow)


async def enqueue_manual_run(
    session: AsyncSession, workflow: Workflow, *, user_id: int, is_platform_admin: bool
) -> tuple[WorkflowRun, bool]:
    """手动触发一次运行：写排队记录，返回 (记录, 是否真的入队)。

    手动触发一律用当前登录用户的身份执行，不区分管理员与普通成员（Q9 的决定）；
    ``is_platform_admin`` 保留在入参里，是为了让接口层对「可见性 + 权限 + 触发」
    保持同一组判断入参，将来若策略分化也无需改调用点。

    已有 running 记录时不排队，而是写一条 skipped 记录：工作流是互斥执行的，
    静默丢弃会让「我点了按钮」这件事在运行历史里查无实据。
    """
    repo = WorkflowRunRepository(session)
    definition = workflow.definition or {}
    nodes = definition.get("nodes") or []
    total_steps = len(nodes)

    running = await repo.get_running(workflow.id)
    if running is not None:
        skipped = await repo.create_run(
            workflow_id=workflow.id,
            status="skipped",
            trigger_kind="manual",
            definition_version_id=workflow.version,
            definition_snapshot=definition,
            total_steps=total_steps,
            run_as_type="user",
            run_as_user_id=user_id,
            planned_at=datetime.now(UTC),
            skip_reason="overlapped",
        )
        await session.commit()
        return skipped, False

    # 不写 started_at：status='running' 且 started_at IS NULL 才是「已排队」，
    # 调度器认领时才补 started_at。这里若提前写入，调度器会以为它已在执行、
    # 永远不认领，记录就一直卡在 running，最后被看门狗判超时。
    run = await repo.create_run(
        workflow_id=workflow.id,
        status="running",
        trigger_kind="manual",
        definition_version_id=workflow.version,
        # 快照必须是当次定义，之后改定义也不能让这条运行「跟着变」。
        definition_snapshot=definition,
        total_steps=total_steps,
        run_as_type="user",
        run_as_user_id=user_id,
        planned_at=datetime.now(UTC),
        started_at=None,
    )
    await session.commit()
    return run, True


async def list_workflow_runs(
    session: AsyncSession,
    *,
    workflow_id: int,
    params: PaginationParams,
    status: str | None = None,
) -> PageData[WorkflowRun]:
    """列出某个工作流的运行记录，可按状态过滤。"""
    return await WorkflowRunRepository(session).list_runs(
        workflow_id, params, status=status
    )


async def get_run_detail(
    session: AsyncSession, *, workflow: Workflow, run_id: int
) -> WorkflowRunDetail:
    """取一次运行的完整明细：运行信息 + 当时的定义快照 + 各步骤记录。"""
    run = await session.get(WorkflowRun, run_id)
    # 同时校验归属：run 存在但不属于该工作流时，同样按「不存在」处理，
    # 避免用别的工作流的 run_id 读到不相关的运行明细。
    if run is None or run.workflow_id != workflow.id:
        raise NotFoundException("workflow run not found")
    steps = await WorkflowStepRunRepository(session).list_for_run(run.id)
    return WorkflowRunDetail(
        run=WorkflowRunRead.model_validate(run),
        definition_snapshot=run.definition_snapshot or {},
        steps=[WorkflowStepRunDetail.model_validate(step) for step in steps],
    )
