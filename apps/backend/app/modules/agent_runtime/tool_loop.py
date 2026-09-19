"""与协议和模型消息格式无关的工具轮次执行器。"""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from types import SimpleNamespace
from typing import Any

from app.modules.agent_runtime.contracts import ToolCall, ToolOutcome, ToolRoundState
from app.modules.agent_runtime.errors import error_from_exception
from app.modules.agent_runtime.tool_events import build_tool_completed_event, build_tool_event
from app.modules.agent_runtime.tools import ToolCatalog
from app.core.logging import get_logger

logger = get_logger(__name__)


def _budget_exceeded(outcome: ToolOutcome) -> bool:
    """识别旧页面工具返回的预算错误，不依赖具体工具对象。"""

    if str(outcome.status) in {"budget_exceeded", "quota_exceeded"}:
        return True
    result = outcome.result
    return isinstance(result, dict) and (
        result.get("code") == "host_tool_budget_exceeded"
        or result.get("message") == "page_tool_budget_exceeded"
    )


def _unknown_tool_stub(name: str) -> SimpleNamespace:
    """为未注册工具构造最小事件载体，避免协议层收到空事件。"""

    return SimpleNamespace(name=name, kind=None, skill_name=None, skill_version=None)


def _unknown_tool_outcome(call: ToolCall) -> ToolOutcome:
    """未知工具与 runtime 主路径保持一致：失败结果化而非静默跳过。"""

    # 模型调用了执行器目录里不存在的工具（工具未注册或名称不符）时，前端只能
    # 看到“执行失败”，因此这里必须把工具名和目录成员写进日志。
    logger.warning(
        "Tool not registered for execution tool=%s call_id=%s",
        call.name,
        call.id,
    )
    return ToolOutcome(
        status="failed",
        error={
            "code": "tool_not_found",
            "message": f"工具 {call.name} 未注册，无法执行，请更换工具或直接回答",
        },
        call_id=call.id,
    )


class ToolRoundExecutor:
    """执行一轮工具调用，并通过回调交给上层处理上下文和等待态。"""

    def __init__(self, tools: Sequence[object]) -> None:
        self._catalog = ToolCatalog(list(tools))

    async def run(
        self,
        calls: Sequence[ToolCall],
        *,
        invoke: Callable[[object, ToolCall], Awaitable[ToolOutcome]],
        on_event: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        append_result: Callable[[object, ToolCall, ToolOutcome], Awaitable[None]]
        | None = None,
    ) -> ToolRoundState:
        """执行调用列表，遇到用户等待态立即返回，不继续请求后续工具。"""

        state = ToolRoundState()
        for call in calls:
            tool = self._catalog.get(call.name)
            outcome = None
            if tool is None:
                # 未知工具不能静默跳过：必须发布失败事件并把结果回填模型，
                # 否则模型请求会被吞掉，最终可能返回空回答。语义与
                # AgentLoop 主路径（make_legacy_tool_invoker）保持一致。
                tool = _unknown_tool_stub(call.name)
                outcome = _unknown_tool_outcome(call)
            state.executed_tool = True
            started = build_tool_event(
                tool,
                {"id": call.id, "args": call.arguments},
                waiting_status=(
                    "waiting_question" if call.name == "ask_user" else None
                ),
            )
            if on_event is not None:
                await on_event({"type": "tool_started", **started})
            if outcome is None:
                outcome = await self._invoke_or_fail(invoke, tool, call)
            if append_result is not None:
                await append_result(tool, call, outcome)
            if on_event is not None:
                await on_event(
                    {
                        "type": "tool_completed",
                        **build_tool_completed_event(started, outcome),
                    }
                )
            if str(outcome.status) in {
                "confirmation_required",
                "waiting_user",
                "waiting_question",
            }:
                state.confirmation_result = outcome
                return state
            if _budget_exceeded(outcome):
                state.budget_exceeded = True
                return state
        return state

    async def stream(
        self,
        calls: Sequence[ToolCall],
        *,
        invoke: Callable[[object, ToolCall], Awaitable[ToolOutcome]],
        append_result: Callable[[object, ToolCall, ToolOutcome], Awaitable[None]]
        | None = None,
        state_sink: Callable[[ToolRoundState], Awaitable[None]] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """惰性输出工具事件，调用方关闭生成器时不会启动后续工具。

        该入口刻意不创建后台 task：生成器在 yield started 后暂停，只有调用方
        继续请求下一个事件时才会进入 invoke，保持旧 Graph 的取消和 backpressure
        语义。
        """

        state = ToolRoundState()
        for call in calls:
            tool = self._catalog.get(call.name)
            outcome = None
            if tool is None:
                tool = _unknown_tool_stub(call.name)
                outcome = _unknown_tool_outcome(call)
            state.executed_tool = True
            started = build_tool_event(
                tool,
                {"id": call.id, "args": call.arguments},
                waiting_status=(
                    "waiting_question" if call.name == "ask_user" else None
                ),
            )
            yield {"type": "tool_started", **started}
            if outcome is None:
                outcome = await self._invoke_or_fail(invoke, tool, call)
            if append_result is not None:
                await append_result(tool, call, outcome)
            yield {
                "type": "tool_completed",
                **build_tool_completed_event(started, outcome),
            }
            if str(outcome.status) in {
                "confirmation_required",
                "waiting_user",
                "waiting_question",
            }:
                state.confirmation_result = outcome
                break
            if _budget_exceeded(outcome):
                state.budget_exceeded = True
                break
        if state_sink is not None:
            await state_sink(state)

    @staticmethod
    async def _invoke_or_fail(
        invoke: Callable[[object, ToolCall], Awaitable[ToolOutcome]],
        tool: object,
        call: ToolCall,
    ) -> ToolOutcome:
        """执行单个工具并把普通异常归一化为失败结果。

        取消（``CancelledError``）必须原样传播，不能伪装成普通工具失败；
        其余异常与 AgentLoop 主循环保持同一安全分类和工具级事件语义。
        """

        try:
            return await invoke(tool, call)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            payload = error_from_exception(error).as_payload()
            # 工具异常会被归一化成 failed 步骤，异常堆栈只在这里可见。
            logger.warning(
                "Tool invocation raised tool=%s call_id=%s code=%s message=%s",
                getattr(tool, "name", None),
                call.id,
                payload.get("code"),
                payload.get("message"),
                exc_info=True,
            )
            return ToolOutcome(
                status="failed",
                error=payload,
                call_id=call.id,
            )
