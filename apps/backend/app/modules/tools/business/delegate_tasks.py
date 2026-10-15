"""内置业务工具：让 Agent 在运行期把一个任务扇出给多个子 Agent 并发执行。

边界（与 request `2026-10-15-delegated-subagent-runtime` 的 spec 一致）：

- **动态扇出**：子任务数量与子 Agent 都由模型在运行期决定，声明式工作流表达不了
  「任务边界要看到数据才知道」的形态；
- **深度恒 1**：子运行的工具清单里没有本工具（``allow_delegation=False``），这条闸
  落在代码里，不靠「用户别这么配」；
- **工具范围收缩**：子运行不带 MCP/宿主工具（``platform_tools_only=True``），因为
  无人值守路径没有渠道把确认弹给人，只有「静默批准」和「不可用」两个选项；
- **上下文隔离**：每个子运行走 ``execute_unattended_chat``——各自新建会话、只拿到
  自包含的 task 文本，父的历史不流转；
- **每个子运行一个独立 Session**：绝不复用 ``ctx.session``。流式运行时它是网关正在
  flush/commit 的 AsyncSession，被并发子运行复用会撞 asyncpg 的并发操作错误。
"""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import update

from app.core.config import get_settings
from app.core.database import get_session_factory
from app.modules.tools.business.framework import (
    BusinessToolContext,
    BusinessToolError,
    business_tool,
)

DELEGATE_TASKS_TOOL_NAME = "delegate_tasks"

# 输出截断标记：与工作流可见输出用同一句话，读侧看到它就知道被截过。
TRUNCATION_MARKER = "\n…（输出已按上限截断）"

MAX_TASKS_IN_SCHEMA = 8


def build_agent_catalog_description(base: str, catalog: list[tuple[str, str]]) -> str:
    """把「本平台可派智能体清单」拼进委派工具的描述。

    静态 ``@business_tool`` 的 description 在导入期就固定，无法随平台变化，因此
    运行时上下文组装时替换一份。清单为空时保持原描述不变——不向模型承诺一个
    实际上不存在的清单。
    """
    if not catalog:
        return base
    lines = [f"- {slug}（{name}）" if name else f"- {slug}" for slug, name in catalog]
    return (
        f"{base}\n\n当前平台可派的智能体（agent 字段只能填这里的 slug）：\n"
        + "\n".join(lines)
    )


def _truncate_output(text: str, max_bytes: int) -> str:
    """按字节上限截断子运行输出。"""

    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode("utf-8", errors="ignore") + TRUNCATION_MARKER


def _validate_arguments(
    arguments: dict[str, Any], *, max_tasks: int
) -> list[dict[str, str]]:
    """参数级校验：任何一项不合法就整体拒绝，不创建任何子运行。"""

    raw_tasks = arguments.get("tasks")
    if not isinstance(raw_tasks, list) or not raw_tasks:
        raise BusinessToolError(
            "invalid_tasks", "tasks 必须是非空数组，每项形如 {agent, task}"
        )
    if len(raw_tasks) > max_tasks:
        raise BusinessToolError(
            "too_many_tasks",
            f"一次最多委派 {max_tasks} 个子任务，收到 {len(raw_tasks)} 个",
        )
    tasks: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_tasks):
        if not isinstance(item, dict):
            raise BusinessToolError("invalid_tasks", f"第 {index + 1} 项必须是对象")
        agent = item.get("agent")
        task = item.get("task")
        if not isinstance(agent, str) or not agent.strip():
            raise BusinessToolError("invalid_tasks", f"第 {index + 1} 项缺少 agent")
        if not isinstance(task, str) or not task.strip():
            raise BusinessToolError("invalid_tasks", f"第 {index + 1} 项缺少 task")
        slug = agent.strip()
        if slug in seen:
            raise BusinessToolError(
                "duplicate_agent", f"agent '{slug}' 在一次调用里出现了多次"
            )
        seen.add(slug)
        tasks.append({"agent": slug, "task": task.strip()})
    return tasks


async def _resolve_agents(session, platform_id: int, tasks: list[dict[str, str]]):
    """把 slug 解析成本平台「已发布且已启用」的 Agent；任一不存在即整体拒绝。"""

    from app.modules.agent.repositories import AgentRepository

    repo = AgentRepository(session)
    resolved: list[tuple[dict[str, str], Any]] = []
    for item in tasks:
        agent = await repo.get_published_active_agent_by_slug(
            platform_id, item["agent"]
        )
        if agent is None:
            raise BusinessToolError(
                "agent_not_available",
                f"agent '{item['agent']}' 不是本平台可派的智能体",
            )
        resolved.append((item, agent))
    return resolved


async def _fail_running_children(parent_loop_run_id: int, reason: str) -> None:
    """把该父运行下仍处 running 的子运行落为终态。

    只在本次调用异常/取消时调用：子运行自己跑完会正常收尾，能走到这里的都是
    「父已经走了、子还在跑」的孤儿。这里单独开一个 Session，避免使用已被取消
    的那一套连接。
    """

    from app.modules.conversation.models import AgentLoopRun

    try:
        async with get_session_factory()() as session:
            await session.execute(
                update(AgentLoopRun)
                .where(
                    AgentLoopRun.parent_loop_run_id == parent_loop_run_id,
                    AgentLoopRun.status == "running",
                )
                .values(status="failed", summary=reason)
            )
            await session.commit()
    except Exception:  # noqa: BLE001 - 收尾尽力而为，不能掩盖原始异常
        pass


@business_tool(
    name=DELEGATE_TASKS_TOOL_NAME,
    description=(
        "把当前任务拆成若干**互相独立**的子任务，交给同平台的其他智能体并发执行，"
        "然后拿回它们各自的结果。"
        "适用场景：你要处理的条目数量或范围**此刻才知道**（例如用户给了一段列表、"
        "要逐个核查一批对象），而每个条目都可以独立完成；不适合必须按顺序推进、"
        "或后一步依赖前一步结论的任务。"
        "每个子任务是一个全新会话：子智能体**看不到**你和用户的对话，因此 task "
        "必须写成自包含的完整指令（把需要的背景、对象、判断标准和输出格式都写进去）。"
        "子任务之间不共享上下文，也读不到彼此的中间结果。"
        "子任务里不能使用需要人工确认的工具（外部 MCP、页面宿主工具），"
        "也不能再向下委派。"
        "用法：tasks 是子任务数组，每项 {agent, task}；agent 填本平台可派智能体的 slug，"
        "任务相同的 agent 不要重复。"
        "结果使用：返回 {tasks:[{agent,status,output|error}],succeeded,failed}，"
        "你可以据此对失败项重试或换人；单个子任务失败不会影响其他子任务。"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "tasks": {
                "type": "array",
                "minItems": 1,
                "maxItems": MAX_TASKS_IN_SCHEMA,
                "description": "要并发派出的子任务，每项一个 {agent, task}",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "agent": {
                            "type": "string",
                            "description": "子智能体的 slug（见工具描述里的可派清单）",
                        },
                        "task": {
                            "type": "string",
                            "description": (
                                "交给该子智能体的完整指令；子智能体看不到当前对话，"
                                "必须自包含"
                            ),
                        },
                    },
                    "required": ["agent", "task"],
                },
            }
        },
        "required": ["tasks"],
        "additionalProperties": False,
    },
)
async def delegate_tasks(
    arguments: dict[str, Any], ctx: BusinessToolContext
) -> dict[str, Any]:
    """并发派生若干子运行，返回每个子任务的结果。

    返回给模型的只有 ``{agent, status, output|error}`` 数组；派生子运行的 ID 放在
    保留键 ``_metadata`` 里，由 ``builtin_tool/services.py`` 摘出来进落库链路
    （模型看不到它）。
    """

    settings = get_settings()
    if ctx.loop_run_id is None:
        # 没有父运行就没有「挂在谁下面」可言。工作流的**工具步骤**是典型场景：
        # 它不产生 agent_loop_runs 行，因此不能作为委派父运行。
        raise BusinessToolError(
            "delegation_requires_parent_run",
            "当前调用不属于任何一次 Agent 运行，无法派生委派子运行",
        )
    if ctx.session is None:
        raise BusinessToolError("delegation_unavailable", "缺少数据库会话")

    # 执行身份二选一，与 execute_unattended_chat 的校验口径一致。
    if ctx.platform_end_user_id is not None:
        run_as_type, user_id, end_user_id = (
            "end_user",
            None,
            ctx.platform_end_user_id,
        )
    elif ctx.user_id is not None:
        run_as_type, user_id, end_user_id = "user", ctx.user_id, None
    else:
        raise BusinessToolError(
            "delegation_requires_execution_identity",
            "当前会话没有可用的执行身份，无法派生委派子运行",
        )

    tasks = _validate_arguments(arguments, max_tasks=settings.delegation_max_tasks)
    resolved = await _resolve_agents(ctx.session, ctx.platform_id, tasks)

    from app.modules.conversation.services import execute_unattended_chat

    semaphore = asyncio.Semaphore(settings.delegation_max_concurrency)
    timeout_seconds = settings.delegation_timeout_seconds
    output_limit = settings.delegation_output_max_bytes

    async def run_one(item: dict[str, str], child_agent) -> dict[str, Any]:
        """跑一个子运行；返回结果条目与（可能的）子运行 ID。"""

        async with semaphore:
            loop_run_id: int | None = None
            try:
                async with get_session_factory()() as child_session:
                    _conversation, _assistant, result = await asyncio.wait_for(
                        execute_unattended_chat(
                            child_session,
                            platform_id=ctx.platform_id,
                            agent_id=child_agent.id,
                            message=item["task"],
                            run_as_type=run_as_type,
                            user_id=user_id,
                            end_user_id=end_user_id,
                            # 深度恒 1 与工具范围收缩都在这一处断掉。
                            allow_delegation=False,
                            platform_tools_only=True,
                            parent_loop_run_id=ctx.loop_run_id,
                            max_iterations=settings.delegation_max_iterations,
                        ),
                        timeout=timeout_seconds,
                    )
            except TimeoutError:
                return (
                    {
                        "agent": item["agent"],
                        "status": "failed",
                        "error": {"code": "delegation_timeout"},
                    },
                    None,
                )
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001 - 单个子运行失败不中止其余
                return (
                    {
                        "agent": item["agent"],
                        "status": "failed",
                        "error": {
                            "code": "delegation_failed",
                            "message": str(error).strip() or type(error).__name__,
                        },
                    },
                    None,
                )
            loop_run_id = getattr(result, "loop_id", None)
            content = getattr(result, "content", None) or ""
            return (
                {
                    "agent": item["agent"],
                    "status": "completed",
                    "output": _truncate_output(str(content), output_limit),
                },
                loop_run_id,
            )

    try:
        settled = await asyncio.gather(
            *(run_one(item, agent) for item, agent in resolved)
        )
    except BaseException:
        # 父被取消或并发池本身出错：把还在跑的子运行落为终态，避免留下
        # 「父已结束、子永远 running」的孤儿。shield 是为了让这段收尾在
        # 取消传播中也能跑完。
        await asyncio.shield(
            _fail_running_children(ctx.loop_run_id, "父运行已结束，子运行被中断")
        )
        raise

    entries: list[dict[str, Any]] = []
    delegated_run_ids: list[str] = []
    for entry, loop_run_id in settled:
        entries.append(entry)
        if loop_run_id is not None:
            delegated_run_ids.append(str(loop_run_id))

    succeeded = sum(1 for entry in entries if entry["status"] == "completed")
    response: dict[str, Any] = {
        "tasks": entries,
        "succeeded": succeeded,
        "failed": len(entries) - succeeded,
    }
    if delegated_run_ids:
        # 保留键：只进落库链路（工具步骤 metadata），回填给模型的文本里没有它。
        response["_metadata"] = {"delegatedRunIds": delegated_run_ids}
    return response
