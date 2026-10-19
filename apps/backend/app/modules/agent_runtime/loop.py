"""供应商无关的 Agent 主循环。

该模块刻意不依赖 LangChain 或 FastAPI。模型适配器负责产生一个回答对象，
回答对象可携带工具调用；loop 只负责轮次控制、工具执行、事件发布和取消。
"""

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.modules.agent_runtime.contracts import (
    AgentEvent,
    AgentEventType,
    ToolCall,
    ToolOutcome,
    merge_usage,
)
from app.modules.agent_runtime.hooks import AgentRuntimeHooks, resolve_messages
from app.modules.agent_runtime.errors import cancellation_error
from app.modules.agent_runtime.errors import error_from_exception
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(slots=True)
class ModelTurn:
    """一次模型调用的标准化结果。"""

    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class ModelInvoker(Protocol):
    async def __call__(
        self,
        messages: list[Any],
        *,
        emit: Callable[[AgentEvent], Awaitable[None]],
        allow_tools: bool = True,
    ) -> ModelTurn: ...


def _tool_event_entry(call: ToolCall, outcome: ToolOutcome) -> dict[str, Any]:
    """构造统一工具事件的基础条目。

    除协议字段外携带参数与工具分类：REST/WS 持久化工具步骤与工具快照
    需要 ``input_summary``/``tool_type`` 才能在灰度路径上与 legacy Graph
    保持一致；runtime 不负责序列化展示文本，只透出结构化参数供 Adapter
    按各自预算生成摘要。
    """

    entry: dict[str, Any] = {
        "tool_call_id": call.id,
        "tool": call.name,
        "outcome": outcome,
    }
    if call.arguments:
        entry["arguments"] = call.arguments
    if call.tool_type:
        entry["tool_type"] = call.tool_type
    return entry


def _tool_call_payload(call: ToolCall) -> dict[str, Any]:
    """TOOL_STARTED 事件中单个工具调用的协议字段。"""

    payload: dict[str, Any] = {
        "id": call.id,
        "name": call.name,
        "arguments": call.arguments,
    }
    if call.tool_type:
        payload["tool_type"] = call.tool_type
    return payload


_MAX_TURNS_WRAPUP_PROMPT = (
    "你已达到本次任务的最大执行轮数，请停止调用任何工具，"
    "仅基于已有信息直接给出最终回答；如果信息不足，请明确说明。"
)


class ToolInvoker(Protocol):
    async def __call__(self, call: ToolCall) -> ToolOutcome: ...


class AgentLoop:
    """可复用的轮次执行器。

    模型和工具均通过依赖注入提供。取消发生在模型调用前、工具调用前和每轮
    结束后，避免等待外部工具时继续推进后续轮次。
    """

    def __init__(
        self,
        *,
        model: ModelInvoker,
        tool_invoker: ToolInvoker | None = None,
        hooks: AgentRuntimeHooks | None = None,
    ) -> None:
        self.model = model
        self.tool_invoker = tool_invoker
        self.hooks = hooks or AgentRuntimeHooks()
        # 与 legacy Graph 的配置语义保持一致：0 或负数表示不设上限，
        # 避免请求在第一次模型调用前就被误判为已耗尽预算。
        if self.hooks.max_turns is not None and self.hooks.max_turns <= 0:
            self.hooks.max_turns = None

    async def run(
        self,
        messages: Sequence[Any],
        *,
        request_id: str | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> ModelTurn:
        context = list(messages)
        last_turn: ModelTurn | None = None
        tool_events: list[dict[str, Any]] = []
        # 思考文本按轮累积：工具轮与最终回答都可能包含 reasoning，legacy
        # GraphResult 会合并全部轮次，runtime 结果必须保持一致口径。
        accumulated_thinking: list[str] = []
        # usage 同样按轮累积：legacy 对所有模型调用逐轮相加，runtime 只有
        # 跨轮合并才能在多轮工具/收尾场景给出与 legacy 一致的 token 统计。
        accumulated_usage: dict[str, Any] | None = None
        turns = 0

        async def emit(event: AgentEvent) -> None:
            if event.request_id is None:
                event.request_id = request_id
            if self.hooks.on_event is not None:
                outcome = self.hooks.on_event(event)
                if hasattr(outcome, "__await__"):
                    await outcome

        async def raise_if_cancelled() -> None:
            """先发布权威取消事件，再中断本轮执行。

            取消不是供应商故障，也不能只依赖异常传播：协议 Adapter 可能已经
            在等待事件，必须先收到稳定的终态错误事件，才能把请求状态收敛到
            cancelled。随后仍抛出 ``CancelledError``，让调用方能够正确结束
            task、释放外部 Future，并保留 Python 的取消语义。
            """
            if cancel_event is not None and cancel_event.is_set():
                await emit(
                    AgentEvent(
                        type=AgentEventType.ERROR,
                        payload=cancellation_error().as_payload(),
                    )
                )
                raise asyncio.CancelledError

        while True:
            await raise_if_cancelled()
            if self.hooks.max_turns is not None and turns >= self.hooks.max_turns:
                # 达到上限后不再发起新的模型调用。带工具的“上限轮”在模型
                # 响应返回后（工具执行前）已被转换为失败结果并执行收尾，因此
                # 这里只兜底终止，防止 steering/follow-up 让轮次越过上限。
                break
            turns += 1

            context = await self._transform_context(context)
            pending = await resolve_messages(self.hooks.get_steering_messages)
            context.extend(pending)
            # 供应商真实错误（如上下文超限）允许一次性降级重试：由调用方通过
            # on_model_error 提供“更小上下文”，本次失败不算新增一轮，也不发布
            # 失败/错误事件；取消按既有语义原样传播，绝不伪装成可恢复错误。
            recovered = False
            while True:
                try:
                    turn = await self._await_with_cancel(
                        self.model(context, emit=emit),
                        cancel_event=cancel_event,
                        raise_if_cancelled=raise_if_cancelled,
                    )
                    break
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    if recovered or self.hooks.on_model_error is None:
                        raise
                    replacement = self.hooks.on_model_error(error, context)
                    if hasattr(replacement, "__await__"):
                        replacement = await replacement
                    if replacement is None:
                        raise
                    recovered = True
                    context = await self._transform_context(list(replacement))
                    continue
            last_turn = turn
            context.append(turn)
            turn_thinking = turn.metadata.get("thinking_text", "")
            if turn_thinking:
                accumulated_thinking.append(turn_thinking)
            accumulated_usage = merge_usage(
                accumulated_usage, turn.metadata.get("usage")
            )
            await emit(
                AgentEvent(
                    type=AgentEventType.COMPLETED
                    if not turn.tool_calls
                    else AgentEventType.TOOL_STARTED,
                    payload={
                        "content": turn.content,
                        "turn": turns,
                        "usage": accumulated_usage,
                        "thinking_text": "".join(accumulated_thinking),
                        # 在模型决定调用工具时一次性发布调用描述；工具执行
                        # 仍由后续 TOOL_COMPLETED 事件报告，协议层可据此先建
                        # loop step，再补齐结果，而不需要理解 LangChain 对象。
                        "tool_calls": [
                            _tool_call_payload(call) for call in turn.tool_calls
                        ],
                        "tool_events": tool_events,
                    },
                )
            )

            if not turn.tool_calls:
                should_stop = self.hooks.should_stop_after_turn
                if should_stop is None or await self._call_predicate(
                    should_stop, {"turn": turn, "messages": context}
                ):
                    break
                follow_ups = await resolve_messages(self.hooks.get_follow_up_messages)
                if not follow_ups:
                    break
                context.extend(follow_ups)
                continue

            if (
                self.hooks.max_turns is not None
                and turns >= self.hooks.max_turns
            ):
                # 与 legacy Graph / Pi 对齐：达到上限的那次模型响应若请求新
                # 工具，该轮工具不再执行。Pi 对输出上限截断的响应会把全部
                # 工具调用转为失败结果（failToolCallsFromTruncatedMessage），
                # 这里以同一方式回填 failed(max_turns_reached)：保证 assistant
                # tool call 与失败结果成对、消息序列合法，收尾模型也能看到
                # “因达到上限未执行”的原因，而不是被蒙在鼓里继续重试。
                for call in turn.tool_calls:
                    outcome = ToolOutcome(
                        status="failed",
                        error={
                            "code": "max_turns_reached",
                            "message": "已达到最大执行轮数，该轮工具不再执行",
                        },
                        call_id=call.id,
                    )
                    context.append(outcome)
                    tool_events.append(_tool_event_entry(call, outcome))
                    await emit(
                        AgentEvent(
                            type=AgentEventType.TOOL_COMPLETED,
                            payload={
                                "tool_call_id": call.id,
                                "tool_name": call.name,
                                "tool_type": call.tool_type,
                                "arguments": call.arguments,
                                "status": outcome.status,
                                "result": outcome.result,
                                "error": outcome.error,
                                "outcome": outcome,
                            },
                        )
                    )
                # 达到上限后只允许一次收尾模型调用：注入内部系统提示并显式
                # 关闭工具，模型只能基于已有信息给出最终回答；若仍返回工具
                # 调用则转为稳定失败结果，绝不再次进入工具循环（防无限循环）。
                wrapup_messages = [_MAX_TURNS_WRAPUP_PROMPT, *context]
                model_kwargs = {"emit": emit}
                try:
                    signature = inspect.signature(self.model)
                    accepts_tools = "allow_tools" in signature.parameters or any(
                        parameter.kind is inspect.Parameter.VAR_KEYWORD
                        for parameter in signature.parameters.values()
                    )
                except (TypeError, ValueError):
                    # 无法反射的供应商 callable 采用旧签名兼容路径；收尾分支
                    # 仍通过下方结果屏障禁止真实工具执行。
                    accepts_tools = False
                if accepts_tools:
                    model_kwargs["allow_tools"] = False
                wrapup = await self._await_with_cancel(
                    self.model(wrapup_messages, **model_kwargs),
                    cancel_event=cancel_event,
                    raise_if_cancelled=raise_if_cancelled,
                )
                if wrapup.tool_calls:
                    for call in wrapup.tool_calls:
                        outcome = ToolOutcome(
                            status="failed",
                            error={
                                "code": "max_turns_reached",
                                "message": "已达到最大执行轮数，收尾阶段禁止执行工具",
                            },
                            call_id=call.id,
                        )
                        tool_events.append(_tool_event_entry(call, outcome))
                        await emit(
                            AgentEvent(
                                type=AgentEventType.TOOL_COMPLETED,
                                payload={
                                    "tool_call_id": call.id,
                                    "tool_name": call.name,
                                    "status": outcome.status,
                                    "result": outcome.result,
                                    "error": outcome.error,
                                    "outcome": outcome,
                                },
                            )
                        )
                wrapup_thinking = wrapup.metadata.get("thinking_text", "")
                if wrapup_thinking:
                    accumulated_thinking.append(wrapup_thinking)
                accumulated_usage = merge_usage(
                    accumulated_usage, wrapup.metadata.get("usage")
                )
                # 无论收尾模型是否再次返回工具调用，最终结果都必须明确标记
                # 预算终态，供 REST/SSE/WS 结果 Adapter 识别。
                wrapup.metadata["budget_exceeded"] = True
                last_turn = wrapup
                await emit(
                    AgentEvent(
                        type=AgentEventType.COMPLETED,
                        payload={
                            "content": wrapup.content,
                            "turn": turns,
                            "usage": accumulated_usage,
                            "thinking_text": "".join(accumulated_thinking),
                            "tool_calls": [],
                            "tool_events": tool_events,
                            "budget_exceeded": True,
                        },
                    )
                )
                break

            if self.tool_invoker is None:
                raise RuntimeError("tool calls require a tool_invoker")
            for call in turn.tool_calls:
                await raise_if_cancelled()
                try:
                    outcome = await self._await_with_cancel(
                        self.tool_invoker(call),
                        cancel_event=cancel_event,
                        raise_if_cancelled=raise_if_cancelled,
                    )
                except asyncio.CancelledError:
                    # 取消由统一的 cancel_event 逻辑发布 error；不能把取消
                    # 伪装成工具失败，否则协议层会同时看到两种终态。
                    raise
                except Exception as error:
                    # 工具抛异常与工具主动返回 failed 必须拥有同样的工具级
                    # 结果事件，便于 loop step、审计和前端统一消费。普通工具
                    # 失败只影响当前调用，不应连带跳过同一 assistant 消息中
                    # 的其他独立工具；模型会在下一轮同时看到成功和失败结果。
                    # 协议层只会把失败归一成“工具执行失败”，堆栈必须在这里留痕。
                    logger.warning(
                        "Tool invocation raised tool=%s call_id=%s error=%s",
                        call.name,
                        call.id,
                        error,
                        exc_info=True,
                    )
                    outcome = ToolOutcome(
                        status="failed",
                        error=error_from_exception(error).as_payload(),
                        call_id=call.id,
                    )
                if outcome.call_id is None:
                    outcome.call_id = call.id
                context.append(outcome)
                tool_events.append(_tool_event_entry(call, outcome))
                waiting = str(outcome.status) in {
                    "confirmation_required",
                    "waiting_user",
                    "waiting_question",
                }
                pending_context = list(context) if waiting else None
                if pending_context is not None:
                    # 等待态的消息快照只是一组**活引用**（含本轮 assistant
                    # tool_calls 与刚产生的 ToolOutcome），不在这里序列化：
                    # 存储格式属于 adapter，落哪张表属于调用方。ToolOutcome
                    # 的 model_dump 是显式字段列表，因此它不会被带进线协议事件。
                    outcome.pending_context = pending_context
                await emit(
                    AgentEvent(
                        type=AgentEventType.TOOL_COMPLETED,
                        payload={
                            "tool_call_id": call.id,
                            "tool_name": call.name,
                            "tool_type": call.tool_type,
                            "arguments": call.arguments,
                            "status": outcome.status,
                            "result": outcome.result,
                            "error": outcome.error,
                            "outcome": outcome,
                        },
                    )
                )
                if waiting:
                    # 外部确认/用户回答尚未完成时，不能继续请求模型；否则同一
                    # 个工具调用可能被重复发起。上层可使用 metadata 里的结果
                    # 创建 continuation，在用户输入完成后恢复执行。
                    last_turn.metadata["pending_tool_outcome"] = outcome
                    # 等待态同样是一次请求的稳定结果：工具事件与思考文本必须
                    # 随结果返回，否则 REST/WS 收尾看不到已执行的工具步骤，
                    # 也无法在 continuation 前正确落库等待状态。
                    last_turn.metadata.setdefault("tool_events", tool_events)
                    last_turn.metadata["thinking_text"] = "".join(
                        accumulated_thinking
                    )
                    # 等待态同样是跨轮执行后的稳定结果：usage 必须携带此前
                    # 所有模型轮次的累计值，供 REST/WS continuation 合并。
                    last_turn.metadata["usage"] = accumulated_usage
                    # 续跑要用的「等待那一刻的完整上下文」；流式通路另经
                    # TOOL_COMPLETED 事件把同一份快照交给 conversation 适配层。
                    last_turn.metadata["pending_context"] = pending_context
                    return last_turn

        if last_turn is None:
            raise RuntimeError("agent loop completed without a model turn")
        # 将工具执行记录挂在最终轮次上，供上层持久化器生成 loop step；AgentLoop
        # 本身不接触数据库，避免把运行时和存储事务耦合在一起。
        last_turn.metadata.setdefault("tool_events", tool_events)
        # 直接赋值而不是 setdefault：最终轮的 metadata 只含本轮思考，legacy
        # GraphResult 会合并全部轮次，这里必须保留跨轮累计的完整文本。
        last_turn.metadata["thinking_text"] = "".join(accumulated_thinking)
        # 与 thinking 同理，最终轮 usage 覆盖为跨轮累计值，避免多轮工具
        # 场景只上报最后一轮的 token 消耗。
        last_turn.metadata["usage"] = accumulated_usage
        return last_turn

    async def continue_run(
        self,
        messages: Sequence[Any],
        outcome: ToolOutcome,
        *,
        request_id: str | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> ModelTurn:
        """在外部确认/用户回答完成后恢复同一 Agent loop。

        continuation 只负责把已完成的工具结果接回上下文，工具本身不会再次
        执行；调用方应传入原请求的消息快照，确保模型看到完整的工具调用链。
        """

        # 某些协议 Adapter 会先把工具结果写入恢复快照，再调用 continuation。
        # 这里按对象身份避免同一个结果被追加两次；不能按 call_id 粗暴去重，
        # 因为同一工具可能经过重试产生不同结果。
        resumed_messages = list(messages)
        if not resumed_messages or resumed_messages[-1] is not outcome:
            resumed_messages.append(outcome)
        return await self.run(
            resumed_messages,
            request_id=request_id,
            cancel_event=cancel_event,
        )

    async def _transform_context(self, messages: list[Any]) -> list[Any]:
        from app.modules.agent_runtime.hooks import transform_messages

        return await transform_messages(self.hooks.transform_context, messages)

    @staticmethod
    async def _await_with_cancel(
        awaitable: Awaitable[Any],
        *,
        cancel_event: asyncio.Event | None,
        raise_if_cancelled: Callable[[], Awaitable[None]],
    ) -> Any:
        """等待模型/工具结果，同时响应请求级取消信号。

        仅在调用前检查取消无法覆盖网络请求、宿主工具或数据库操作的长等待。
        这里用两个 task 竞争：收到取消后主动取消底层调用，再由统一的
        ``raise_if_cancelled`` 发布唯一标准取消事件并抛出 ``CancelledError``。
        没有取消事件时保留最轻量的直接 await 路径。
        """

        operation = asyncio.ensure_future(awaitable)
        if cancel_event is None:
            return await operation

        cancellation = asyncio.create_task(cancel_event.wait())
        try:
            done, _ = await asyncio.wait(
                {operation, cancellation},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if cancellation in done and cancel_event.is_set():
                operation.cancel()
                await asyncio.gather(operation, return_exceptions=True)
                await raise_if_cancelled()
            return await operation
        finally:
            if not cancellation.done():
                cancellation.cancel()
            await asyncio.gather(cancellation, return_exceptions=True)

    @staticmethod
    async def _call_predicate(predicate, value: dict[str, Any]) -> bool:
        result = predicate(value)
        if hasattr(result, "__await__"):
            result = await result
        return bool(result)
