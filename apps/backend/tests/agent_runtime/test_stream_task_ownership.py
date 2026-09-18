"""验证流式 runtime 暴露模型 Task，调用方能在关闭 Session 前 join。

背景：消费方提前放弃事件流（流内 error 事件、结果为空、取消或断连）时，
生成器的 finally 不保证执行，模型 Task 会孤儿化并继续写库；请求任务必须
持有 Task 引用，才能在关闭请求级数据库 Session 前完成收尾，否则会出现
SQLAlchemy 的 `close()` 与 `commit()` 相撞。
"""

import asyncio

from langchain_core.messages import AIMessageChunk

from app.modules.agent_runtime.composition import build_langchain_runtime
from app.modules.agent_runtime.contracts import AgentEvent
from app.modules.agent_runtime.loop import ModelTurn
from app.modules.agent_runtime.runtime import AgentRuntime, cancel_and_join_tasks


def test_stream_reports_model_task_so_caller_can_join_before_closing_session():
    async def scenario():
        started = asyncio.Event()
        release = asyncio.Event()

        async def model(messages, *, emit):
            await emit(AgentEvent("message_delta", {"content": "hi"}))
            started.set()
            await release.wait()
            return ModelTurn(content="hi")

        spawned: set[asyncio.Task] = set()
        runtime = AgentRuntime(model=model, on_task_started=spawned.add)

        stream = runtime.stream([])
        async for event in stream:
            if event.type == "message_delta":
                # 模拟消费方提前结束，不再继续消费事件流。
                break
        await started.wait()

        assert len(spawned) == 1
        task = next(iter(spawned))
        # 这正是必须在关闭 Session 前显式 join 的原因：消费方退出后任务仍在跑。
        assert not task.done()

        await cancel_and_join_tasks(spawned)
        assert task.done()
        await stream.aclose()

    asyncio.run(scenario())


def test_cancel_and_join_tasks_waits_for_task_cleanup():
    async def scenario():
        cleaned = asyncio.Event()

        async def worker():
            try:
                await asyncio.sleep(60)
            finally:
                await asyncio.sleep(0)
                cleaned.set()

        task = asyncio.create_task(worker())
        await asyncio.sleep(0)

        await cancel_and_join_tasks({task})

        assert task.done()
        assert cleaned.is_set(), "join 必须等到任务清理逻辑执行完成"

    asyncio.run(scenario())


def test_cancel_and_join_tasks_ignores_finished_tasks():
    async def scenario():
        async def worker():
            return "done"

        task = asyncio.create_task(worker())
        await asyncio.sleep(0)

        await cancel_and_join_tasks({task})

        assert task.result() == "done"

    asyncio.run(scenario())


def test_build_langchain_runtime_forwards_task_hook_to_stream():
    """入口层（WS/SSE）走的组合根也必须能把模型 Task 交给调用方。"""

    async def scenario():
        release = asyncio.Event()

        class Model:
            async def astream(self, messages):
                yield AIMessageChunk(content="hi")
                await release.wait()

        spawned: set[asyncio.Task] = set()
        runtime = build_langchain_runtime(
            Model(),
            tools=[],
            callback=None,
            streaming=True,
            on_task_started=spawned.add,
        )

        stream = runtime.stream([])
        async for _event in stream:
            break

        assert len(spawned) == 1
        task = next(iter(spawned))
        assert not task.done()

        await cancel_and_join_tasks(spawned)
        assert task.done()
        release.set()
        await stream.aclose()

    asyncio.run(scenario())
