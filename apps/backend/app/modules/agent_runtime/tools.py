"""Agent runtime 的工具执行器 seam。"""

from collections.abc import Awaitable, Callable
from typing import Protocol

from app.modules.agent_runtime.contracts import ToolCall, ToolOutcome
from app.modules.agent_runtime.adapters import tool_outcome_from_legacy


class ToolExecutor(Protocol):
    """单一工具来源的执行器接口。"""

    def supports(self, tool: object) -> bool:
        """返回该执行器是否负责给定工具。"""

    async def execute(self, tool: object, call: ToolCall) -> ToolOutcome:
        """执行工具并返回统一结果。"""


class ToolDispatcher:
    """按注册顺序选择工具执行器。

    执行器是内部 Adapter；新增工具来源只需注册新的执行器，不需要修改 Agent
    loop。未找到执行器时返回失败结果，避免把来源判断泄漏给调用方。
    """

    def __init__(self, executors: list[ToolExecutor] | None = None) -> None:
        self._executors = list(executors or [])

    def register(self, executor: ToolExecutor) -> None:
        self._executors.append(executor)

    async def execute(self, tool: object, call: ToolCall) -> ToolOutcome:
        for executor in self._executors:
            if executor.supports(tool):
                return tool_outcome_from_legacy(await executor.execute(tool, call))
        return ToolOutcome(
            status="failed",
            error={
                "code": "tool_executor_not_found",
                "message": f"No executor registered for tool: {call.name}",
            },
        )


class ToolCatalog:
    """请求级工具索引，统一工具名称解析并拒绝重复名称。"""

    def __init__(self, tools: list[object] | None = None) -> None:
        self._by_name: dict[str, object] = {}
        for tool in tools or []:
            name = getattr(tool, "name", None)
            if not isinstance(name, str) or not name:
                continue
            if name in self._by_name:
                raise ValueError(f"duplicate runtime tool name: {name}")
            self._by_name[name] = tool

    def get(self, name: str) -> object | None:
        return self._by_name.get(name)

    def names(self) -> tuple[str, ...]:
        return tuple(self._by_name)


class CallbackToolExecutor:
    """把一个已有回调包装成单一工具执行器。"""

    def __init__(self, callback, *, predicate=None) -> None:
        self._callback = callback
        self._predicate = predicate or (lambda _tool: True)

    def supports(self, tool: object) -> bool:
        return bool(self._predicate(tool))

    async def execute(self, tool: object, call: ToolCall) -> ToolOutcome:
        return await invoke_with_legacy_callback(
            self._callback,
            tool=tool,
            call=call,
        )


async def invoke_with_legacy_callback(
    callback: Callable[..., Awaitable[object]],
    *,
    tool: object,
    call: ToolCall,
) -> ToolOutcome:
    """把现有 kwargs 风格回调转换为新契约，供渐进迁移使用。"""

    raw = await callback(
        tool=tool,
        call={"id": call.id, "args": call.arguments},
    )
    return tool_outcome_from_legacy(raw)
