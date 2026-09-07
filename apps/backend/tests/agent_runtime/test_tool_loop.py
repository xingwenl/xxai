import asyncio

from app.modules.agent_runtime.contracts import ToolCall, ToolOutcome
from app.modules.agent_runtime.tool_loop import ToolRoundExecutor
from types import SimpleNamespace


def test_tool_round_executor_uses_callbacks_and_stops_on_waiting_state():
    events = []
    calls = []

    async def invoke(tool, call):
        calls.append(call.id)
        return ToolOutcome(status="confirmation_required", confirmation_id=3)

    async def on_event(event):
        events.append(event["type"])

    async def append_result(tool, call, outcome):
        assert tool.name == "approve"
        assert call.id == "c1"

    async def run():
        return await ToolRoundExecutor(
            [SimpleNamespace(name="approve")]
        ).run(
            [ToolCall("c1", "approve"), ToolCall("c2", "approve")],
            invoke=invoke,
            on_event=on_event,
            append_result=append_result,
        )

    state = asyncio.run(run())

    assert calls == ["c1"]
    assert events == ["tool_started", "tool_completed"]
    assert state.confirmation_result.confirmation_id == 3


def test_tool_round_executor_stream_is_lazy_and_does_not_invoke_after_close():
    invoked = []

    async def invoke(tool, call):
        invoked.append(call.id)
        return ToolOutcome(status="completed", result="ok")

    async def run():
        stream = ToolRoundExecutor(
            [SimpleNamespace(name="lookup")]
        ).stream(
            [ToolCall("c1", "lookup"), ToolCall("c2", "lookup")],
            invoke=invoke,
        )
        assert (await anext(stream))["type"] == "tool_started"
        assert invoked == []
        await stream.aclose()

    asyncio.run(run())


def test_unknown_tool_becomes_failed_outcome_and_batch_continues():
    """未知工具不允许静默跳过：失败结果回填模型，同批次后续工具仍执行。"""

    invoked = []
    events = []
    appended = []

    async def invoke(tool, call):
        invoked.append(call.id)
        return ToolOutcome(status="completed", result="ok")

    async def on_event(event):
        events.append(event)

    async def append_result(tool, call, outcome):
        appended.append((call.id, str(outcome.status), outcome.error))

    async def run():
        return await ToolRoundExecutor(
            [SimpleNamespace(name="lookup")]
        ).run(
            [
                ToolCall("c1", "ghost_tool"),
                ToolCall("c2", "lookup"),
            ],
            invoke=invoke,
            on_event=on_event,
            append_result=append_result,
        )

    state = asyncio.run(run())

    assert invoked == ["c2"]
    assert state.executed_tool is True
    assert events[0]["type"] == "tool_started"
    assert events[0]["tool"] == "ghost_tool"
    assert events[1]["type"] == "tool_completed"
    assert events[1]["status"] == "failed"
    assert events[1]["error"]["code"] == "tool_not_found"
    assert appended[0][0] == "c1"
    assert appended[0][1] == "failed"
    assert appended[1] == ("c2", "completed", None)


def test_tool_exception_is_normalized_and_next_tool_still_runs():
    """工具异常转为失败结果，同一轮后续工具继续执行，不升级为请求错误。"""

    invoked = []
    events = []

    async def invoke(tool, call):
        invoked.append(call.id)
        if call.id == "boom":
            raise RuntimeError("tool exploded")
        return ToolOutcome(status="completed", result="ok")

    async def on_event(event):
        events.append(event)

    async def run():
        return await ToolRoundExecutor(
            [SimpleNamespace(name="lookup")]
        ).run(
            [
                ToolCall("boom", "lookup"),
                ToolCall("next", "lookup"),
            ],
            invoke=invoke,
            on_event=on_event,
        )

    state = asyncio.run(run())

    assert invoked == ["boom", "next"]
    assert state.executed_tool is True
    assert [event["type"] for event in events] == [
        "tool_started",
        "tool_completed",
        "tool_started",
        "tool_completed",
    ]
    assert events[1]["status"] == "failed"
    assert events[1]["error"]["details"]["exceptionType"] == "RuntimeError"
    assert events[3]["status"] == "completed"


def test_tool_cancellation_propagates_and_is_not_disguised_as_failure():
    """取消必须原样传播，不能转成失败工具结果。"""

    invoked = []

    async def invoke(tool, call):
        invoked.append(call.id)
        raise asyncio.CancelledError

    async def run():
        return await ToolRoundExecutor(
            [SimpleNamespace(name="lookup")]
        ).run(
            [ToolCall("c1", "lookup"), ToolCall("c2", "lookup")],
            invoke=invoke,
        )

    try:
        asyncio.run(run())
    except asyncio.CancelledError:
        pass
    else:
        raise AssertionError("CancelledError must propagate")
    assert invoked == ["c1"]


def test_stream_unknown_tool_emits_failed_completed_event():
    """legacy 流式路径的未知工具同样产生失败工具事件。"""

    events = []

    async def invoke(tool, call):
        raise AssertionError("unknown tool must not be invoked")

    async def collect():
        stream = ToolRoundExecutor(
            [SimpleNamespace(name="lookup")]
        ).stream(
            [ToolCall("c1", "ghost_tool"), ToolCall("c2", "lookup")],
            invoke=invoke,
        )
        async for event in stream:
            events.append(event)

    asyncio.run(collect())

    assert events[0]["type"] == "tool_started"
    assert events[0]["tool"] == "ghost_tool"
    assert events[1]["type"] == "tool_completed"
    assert events[1]["status"] == "failed"
    assert events[1]["error"]["code"] == "tool_not_found"
