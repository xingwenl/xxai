"""Agent runtime 的稳定对外门面。

协议层只应依赖本模块的 ``run``/``stream``，而不应直接拼装 AgentLoop 的
内部参数。模型、工具和生命周期钩子仍由组合根注入。
"""

import asyncio
from collections.abc import AsyncIterator, Callable, Iterable, Sequence
from typing import Any

from app.modules.agent_runtime.contracts import (
    AgentEvent,
    AgentResult,
    ToolOutcome,
    merge_usage,
)
from app.modules.agent_runtime.hooks import AgentRuntimeHooks
from app.modules.agent_runtime.loop import AgentLoop, ModelInvoker, ToolInvoker
from app.modules.agent_runtime.persistence import (
    AgentRunPersistence,
    NullAgentRunPersistence,
)
from app.modules.agent_runtime.errors import error_from_exception


async def cancel_and_join_tasks(tasks: Iterable[asyncio.Task]) -> None:
    """取消并等待一批任务真正收尾。

    调用方（请求任务）持有请求级数据库 Session，必须在关闭 Session 前调用
    本函数；否则内层模型任务仍可能在 `commit()` 中被 `close()` 撞上，抛出
    SQLAlchemy 的 `IllegalStateChangeError`。
    """

    pending = [task for task in tasks if not task.done()]
    for task in pending:
        task.cancel()
    if pending:
        # gather 会等到任务真正结束（包含它自己的清理逻辑），不是只发出取消。
        await asyncio.gather(*pending, return_exceptions=True)


class AgentRuntime:
    """一次请求范围内的 Agent 执行门面。"""

    def __init__(
        self,
        *,
        model: ModelInvoker,
        tool_invoker: ToolInvoker | None = None,
        hooks: AgentRuntimeHooks | None = None,
        persistence: AgentRunPersistence | None = None,
        persistence_factory: Callable[[str | None], AgentRunPersistence]
        | None = None,
        on_task_started: Callable[[asyncio.Task], None] | None = None,
    ) -> None:
        self._loop = AgentLoop(
            model=model,
            tool_invoker=tool_invoker,
            hooks=hooks,
        )
        self._persistence = persistence or NullAgentRunPersistence()
        self._persistence_factory = persistence_factory
        self._on_task_started = on_task_started

    @classmethod
    def from_langchain(
        cls,
        model: Any,
        *,
        tools: list[Any] | None = None,
        tool_invoker: ToolInvoker | None = None,
        hooks: AgentRuntimeHooks | None = None,
        persistence: AgentRunPersistence | None = None,
        persistence_factory: Callable[[str | None], AgentRunPersistence]
        | None = None,
        on_task_started: Callable[[asyncio.Task], None] | None = None,
        streaming: bool = False,
    ) -> "AgentRuntime":
        """用 LangChain 模型创建 runtime，集中收口供应商 Adapter 组合。"""

        from app.modules.agent_runtime.langchain_adapter import LangChainModelInvoker

        return cls(
            model=LangChainModelInvoker(model, tools, streaming=streaming),
            tool_invoker=tool_invoker,
            hooks=hooks,
            persistence=persistence,
            persistence_factory=persistence_factory,
            on_task_started=on_task_started,
        )

    async def run(
        self,
        messages: Sequence[Any],
        *,
        request_id: str | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> AgentResult:
        """执行一次非流式请求，并返回统一结果。"""

        terminal_error_recorded = False
        persistence = self._persistence_for_request(request_id)

        async def record(event: AgentEvent) -> None:
            nonlocal terminal_error_recorded
            if event.type == "error":
                terminal_error_recorded = True
            await persistence.record(event)
            previous = self._loop.hooks.on_event
            if previous is not None:
                result = previous(event)
                if hasattr(result, "__await__"):
                    await result

        loop = self._new_loop(record)
        try:
            turn = await loop.run(
                messages,
                request_id=request_id,
                cancel_event=cancel_event,
            )
        except BaseException as error:
            # AgentLoop 对 cancel_event 已先发布标准取消事件；避免异常传播时
            # 再写一条重复终态，保证持久化和协议适配器看到单一权威结果。
            if not terminal_error_recorded:
                await record(
                    AgentEvent(
                        "error",
                        error_from_exception(error).as_payload(),
                        request_id=request_id,
                    )
                )
            raise
        return self._result_from_turn(turn)

    async def continue_run(
        self,
        messages: Sequence[Any],
        outcome: ToolOutcome,
        *,
        request_id: str | None = None,
        cancel_event: asyncio.Event | None = None,
        prior_result: AgentResult | None = None,
    ) -> AgentResult:
        """通过 runtime 门面恢复一次等待外部输入的 Agent 请求。

        当前实现复用 ``run`` 的请求级事件与持久化链路；协议层无需知道
        ``AgentLoop`` 的 continuation 细节，后续可在此处接入持久化快照恢复。
        """

        resumed_messages = list(messages)
        if not resumed_messages or resumed_messages[-1] is not outcome:
            resumed_messages.append(outcome)
        result = await self.run(
            resumed_messages,
            request_id=request_id,
            cancel_event=cancel_event,
        )
        if prior_result is not None:
            result.usage = self._merge_usage(prior_result.usage, result.usage)
            result.tool_events = [
                *prior_result.tool_events,
                *result.tool_events,
            ]
        return result

    async def stream(
        self,
        messages: Sequence[Any],
        *,
        request_id: str | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> AsyncIterator[AgentEvent]:
        """以事件流形式执行请求。

        ``AgentLoop`` 的事件 sink 通过队列桥接到异步生成器；请求结束后以
        ``None`` 作为内部结束哨兵，不把队列实现细节暴露给协议 Adapter。
        """

        queue: asyncio.Queue[AgentEvent | None] = asyncio.Queue()

        terminal_error_recorded = False
        persistence = self._persistence_for_request(request_id)

        async def emit(event: AgentEvent) -> None:
            nonlocal terminal_error_recorded
            if event.type == "error":
                terminal_error_recorded = True
            await persistence.record(event)
            # 流式与非流式请求必须共享同一套观测钩子。否则指标、审计或
            # 调试订阅只在 REST 非流式路径生效，WebSocket/SSE 会出现
            # “客户端收到了事件，但运行时观测不到事件”的隐性分叉。
            previous = self._loop.hooks.on_event
            if previous is not None:
                result = previous(event)
                if hasattr(result, "__await__"):
                    await result
            await queue.put(event)

        # 每次流式请求使用独立 hooks/loop，不能临时修改 self._loop。WebSocket
        # 连接可能同时启动多个请求，修改共享回调会导致事件串到其他请求。
        loop = self._new_loop(emit)
        task = asyncio.create_task(
            loop.run(
                messages,
                request_id=request_id,
                cancel_event=cancel_event,
            )
        )
        # 消费方可能提前放弃本生成器（流内 error 事件、结果为空、取消或断连），
        # 此时生成器的 finally 不保证执行，内层模型 Task 会变成孤儿继续写库。
        # 把 Task 交给调用方登记，由请求任务在关闭数据库 Session 前显式 join。
        if self._on_task_started is not None:
            self._on_task_started(task)
        try:
            while True:
                if task.done() and queue.empty():
                    error = task.exception()
                    if error is None:
                        break
                    if isinstance(error, asyncio.CancelledError):
                        # 取消必须保持 Python 异常传播：协议层依赖 CancelledError
                        # 结束请求 task、清理 pending Future；取消错误事件已由
                        # AgentLoop 先行发布，不能把取消吞成普通错误收尾。
                        raise error
                    if terminal_error_recorded:
                        # 错误事件已经作为终态发布（通常是上一轮循环把模型级
                        # 错误放入队列后的第二次恢复）：事件流到此正常结束，
                        # 不再把同一异常重复抛给消费方。
                        break
                    # 模型在发布任何事件前失败（或流中途失败且未表达为错误
                    # 事件）时，先发布标准 error 事件再结束事件流。这与 legacy
                    # stream_graph“错误以事件终结”的契约一致，REST SSE/WS
                    # 协议层才能统一落库 failed 并向客户端发送终止 error；
                    # 否则灰度流会直接把异常抛给协议层，导致 loop 卡 running。
                    error_event = AgentEvent(
                        "error",
                        error_from_exception(error).as_payload(),
                        request_id=request_id,
                    )
                    await emit(error_event)
                    continue

                # 不能直接等待 queue.get()：模型可能在发布第一个事件前
                # 抛错，此时队列永远不会有数据，流式请求会被永久挂起。
                # 同时等待任务和队列，确保“无首事件即失败”也能及时收敛。
                event_task = asyncio.create_task(queue.get())
                done, _ = await asyncio.wait(
                    {task, event_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                # 任务和队列读取可能同时完成；队列里的事件仍必须先交给
                # 消费方，不能因为 task 已结束而把最后一批事件丢掉。
                if event_task in done:
                    event = event_task.result()
                elif task in done:
                    event_task.cancel()
                    await asyncio.gather(event_task, return_exceptions=True)
                    continue
                if event is None:
                    break
                yield event
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    def _new_loop(self, on_event) -> AgentLoop:
        """创建请求级 loop，避免并发请求共享可变 hooks。"""

        hooks = AgentRuntimeHooks(
            transform_context=self._loop.hooks.transform_context,
            should_stop_after_turn=self._loop.hooks.should_stop_after_turn,
            get_steering_messages=self._loop.hooks.get_steering_messages,
            get_follow_up_messages=self._loop.hooks.get_follow_up_messages,
            on_event=on_event,
            max_turns=self._loop.hooks.max_turns,
            on_model_error=self._loop.hooks.on_model_error,
            metadata=dict(self._loop.hooks.metadata),
        )
        return AgentLoop(
            model=self._loop.model,
            tool_invoker=self._loop.tool_invoker,
            hooks=hooks,
        )

    @staticmethod
    def _result_from_turn(turn) -> AgentResult:
        """把 loop 轮次的内部元数据收敛成稳定的 runtime 结果。

        等待确认是一次合法的中间终态，不能因为没有最终文本就丢掉
        ``confirmation_id``；协议层可以据此继续等待或恢复请求。
        """

        pending = turn.metadata.get("pending_tool_outcome")
        return AgentResult(
            content=turn.content,
            usage=turn.metadata.get("usage"),
            tool_events=turn.metadata.get("tool_events", []),
            thinking_text=str(turn.metadata.get("thinking_text", "") or ""),
            pending_confirmation_id=(
                pending.confirmation_id
                if pending is not None
                and str(pending.status) == "confirmation_required"
                else None
            ),
        )

    @staticmethod
    def _merge_usage(
        previous: dict[str, int] | None,
        current: dict[str, int] | None,
    ) -> dict[str, int] | None:
        """累加 continuation 的 token 用量；实现收敛到 contracts.merge_usage。"""

        return merge_usage(previous, current)

    def _persistence_for_request(
        self, request_id: str | None
    ) -> AgentRunPersistence:
        """为请求选择独立持久化器，避免长生命周期 runtime 串流。

        组合根通常会把一个 runtime 复用于多个 WebSocket/SSE 请求。显式提供
        ``persistence_factory`` 时，每个请求都会得到自己的事件缓冲器或数据库
        Adapter；未提供时保留旧的单实例语义，兼容已有调用方和测试替身。
        """

        if self._persistence_factory is not None:
            return self._persistence_factory(request_id)
        return self._persistence
