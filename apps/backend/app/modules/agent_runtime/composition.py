"""AgentRuntime 的组合根辅助函数。

这里仅处理运行时依赖的组装，不执行工具、不访问数据库。入口层仍负责提供
权限过滤后的工具和旧版回调，避免 runtime 组合模块越过 REST/WS 的安全边界。
"""

from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from app.modules.agent_runtime.adapters import tool_outcome_from_legacy
from app.modules.agent_runtime.hooks import AgentRuntimeHooks
from app.modules.agent_runtime.tool_groups import (
    LOAD_TOOL_GROUP_NAME,
    RETRY_HINT,
    ToolGroupState,
    build_tool_group_state,
    tool_group,
)
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
    *,
    group_state: ToolGroupState | None = None,
):
    """将旧 kwargs 回调封装为 AgentRuntime 的标准工具调用器。

    ``group_state`` 非空时承担两件事：拦截 ``load_tool_group``（框架级工具，
    没有业务 handler），以及为「调用了尚未加载的工具」提供自动兜底——加载
    全部工具组并回填可重试的提示。兜底是这套机制能成立的前提：模型看不见的
    工具必须能通过一次失败调用重新变为可见。
    """

    tool_by_name = {tool.name: tool for tool in tools if getattr(tool, "name", None)}

    async def invoke(call):
        if group_state is not None and call.name == LOAD_TOOL_GROUP_NAME:
            raw = group_state.handle_loader_call(call.arguments)
            logger.info(
                "Tool group load call=%s group=%s status=%s bound_groups=%s",
                call.id,
                call.arguments.get("group"),
                raw.get("status"),
                sorted(group_state.active),
            )
            return tool_outcome_from_legacy(raw)
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
        if group_state is not None and tool_group(tool) not in group_state.active:
            # 模型猜到了一个尚未加载的工具名：先把全量组打开再让它重试，而不是
            # 直接执行——否则「工具是否可见」与「工具是否可执行」会变成两套口径。
            added = group_state.activate_all()
            logger.info(
                "Tool group auto-activate tool=%s call_id=%s added=%s",
                call.name,
                call.id,
                added,
            )
            return tool_outcome_from_legacy(
                {
                    "status": "failed",
                    "error": {
                        "code": "tool_not_loaded",
                        "message": (
                            f"工具 {call.name} 属于尚未加载的工具组，已自动加载全部工具组"
                            f"（新增 {len(added)} 个工具）。"
                            + RETRY_HINT.format(loader=LOAD_TOOL_GROUP_NAME)
                        ),
                    },
                }
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
    context_metrics: Any | None = None,
    max_turns: int | None = None,
    on_model_error=None,
    on_task_started=None,
    tool_group_state: ToolGroupState | None = None,
    enable_tool_groups: bool = False,
):
    """统一创建 LangChain runtime，避免入口层重复配置 streaming 语义。

    ``context_metrics`` 是上下文计量出口（见 ``AgentRuntimeHooks``）：loop 在
    变换后与每次模型调用后向它取事件，因此压缩结果与占用上报能进入事件流。

    ``enable_tool_groups`` 打开按组按需加载（默认关闭，保持旧行为）。调用方必须
    同时把 ``ToolGroupState.catalog_text()`` 注入系统提示词，否则模型看不到
    未加载的工具组、也就没有任何渠道加载它们——两者是一个整体，只能一起开。
    """

    from app.modules.agent_runtime.runtime import AgentRuntime

    tool_list = list(tools)
    group_state = tool_group_state
    if group_state is None and enable_tool_groups:
        group_state = build_tool_group_state(tool_list)
    return AgentRuntime.from_langchain(
        model,
        tools=tool_list,
        tool_invoker=make_legacy_tool_invoker(
            tool_list, callback, group_state=group_state
        ),
        hooks=AgentRuntimeHooks(
            transform_context=context_transform,
            max_turns=max_turns,
            on_model_error=on_model_error,
            context_metrics=context_metrics,
        ),
        on_task_started=on_task_started,
        streaming=streaming,
        tool_group_state=group_state,
    )
