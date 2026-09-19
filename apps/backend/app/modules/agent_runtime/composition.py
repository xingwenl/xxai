"""AgentRuntime 的组合根辅助函数。

这里仅处理运行时依赖的组装，不执行工具、不访问数据库。入口层仍负责提供
权限过滤后的工具和旧版回调，避免 runtime 组合模块越过 REST/WS 的安全边界。
"""

from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from app.modules.agent_runtime.adapters import tool_outcome_from_legacy
from app.modules.agent_runtime.hooks import AgentRuntimeHooks
from app.core.logging import get_logger

logger = get_logger(__name__)


def build_runtime_tools(
    *,
    builtin_tools: Iterable[Any] = (),
    mcp_tools: Iterable[Any] = (),
    skill_script_tools: Iterable[Any] = (),
    skill_instruction_tool: Any | None = None,
    exclude_names: set[str] | frozenset[str] = frozenset(),
) -> list[Any]:
    """按固定顺序组装工具，并在组合边界过滤入口不可用的工具。"""

    tools = [*builtin_tools, *mcp_tools, *skill_script_tools]
    if skill_instruction_tool is not None:
        tools.append(skill_instruction_tool)
    return [tool for tool in tools if getattr(tool, "name", None) not in exclude_names]


def make_legacy_tool_invoker(
    tools: Iterable[Any],
    callback: Callable[..., Awaitable[Any]],
):
    """将旧 kwargs 回调封装为 AgentRuntime 的标准工具调用器。"""

    tool_by_name = {tool.name: tool for tool in tools if getattr(tool, "name", None)}

    async def invoke(call):
        tool = tool_by_name.get(call.name)
        if tool is None:
            # 只把工具名写进日志：模型调用了不在绑定/执行集合里的工具时，
            # 前端看到的只有“执行失败”。
            logger.warning(
                "Tool not found in invoker catalog tool=%s call_id=%s available=%s",
                call.name,
                call.id,
                sorted(tool_by_name),
            )
            return tool_outcome_from_legacy(
                {"status": "failed", "error": {"code": "tool_not_found"}}
            )
        raw = await callback(
            tool=tool,
            call={
                **call.metadata,
                "id": call.id,
                "name": call.name,
                "args": call.arguments,
            },
        )
        return tool_outcome_from_legacy(raw)

    return invoke


def build_langchain_runtime(
    model: Any,
    tools: Iterable[Any],
    callback: Callable[..., Awaitable[Any]],
    *,
    streaming: bool,
    context_transform: Callable[[list[Any]], Any] | None = None,
    max_turns: int | None = None,
    on_model_error=None,
    on_task_started=None,
):
    """统一创建 LangChain runtime，避免入口层重复配置 streaming 语义。"""

    from app.modules.agent_runtime.runtime import AgentRuntime

    tool_list = list(tools)
    return AgentRuntime.from_langchain(
        model,
        tools=tool_list,
        tool_invoker=make_legacy_tool_invoker(tool_list, callback),
        hooks=AgentRuntimeHooks(
            transform_context=context_transform,
            max_turns=max_turns,
            on_model_error=on_model_error,
        ),
        on_task_started=on_task_started,
        streaming=streaming,
    )
