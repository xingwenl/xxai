import asyncio

from app.modules.agent_runtime.contracts import (
    AgentEvent,
    AgentResult,
    ToolCall,
    ToolOutcome,
)
from app.modules.agent_runtime.runtime import AgentRuntime
from app.modules.agent_runtime.persistence import BufferedAgentRunPersistence
from app.modules.agent_runtime.loop import ModelTurn
from app.modules.agent_runtime.hooks import AgentRuntimeHooks


def test_runtime_stream_exposes_events_without_leaking_loop_details():
    async def model(messages, *, emit):
        await emit(AgentEvent("message_delta", {"content": "hi"}))
        return ModelTurn(content="hi")

    async def collect():
        return [event async for event in AgentRuntime(model=model).stream([])]

    events = asyncio.run(collect())

    assert [event.type for event in events] == ["message_delta", "completed"]
    assert events[-1].payload["content"] == "hi"


def test_runtime_result_and_completed_event_carry_thinking_text():
    async def model(messages, *, emit):
        return ModelTurn(
            content="已完成",
            metadata={"thinking_text": "先分析再作答"},
        )

    result = asyncio.run(AgentRuntime(model=model).run([]))

    async def collect():
        return [event async for event in AgentRuntime(model=model).stream([])]

    events = asyncio.run(collect())

    assert result.thinking_text == "先分析再作答"
    assert events[-1].payload["thinking_text"] == "先分析再作答"


def test_runtime_run_returns_stable_result():
    async def model(messages, *, emit):
        return ModelTurn(content="done", metadata={"usage": {"total": 1}})

    result = asyncio.run(AgentRuntime(model=model).run([]))

    assert result.content == "done"
    assert result.usage == {"total": 1}


def test_runtime_run_records_events_and_keeps_original_hook():
    observed = []

    async def model(messages, *, emit):
        return ModelTurn(content="done")

    async def hook(event):
        observed.append(event.type)

    persistence = BufferedAgentRunPersistence("r1")
    from app.modules.agent_runtime.hooks import AgentRuntimeHooks

    result = asyncio.run(
        AgentRuntime(
            model=model,
            hooks=AgentRuntimeHooks(on_event=hook),
            persistence=persistence,
        ).run([], request_id="r1")
    )

    assert result.content == "done"
    assert observed
    assert len(persistence.events) == len(observed)


def test_runtime_stream_records_events_before_protocol_consumption():
    async def model(messages, *, emit):
        return ModelTurn(content="done")

    persistence = BufferedAgentRunPersistence("r1")

    async def collect():
        return [
            event
            async for event in AgentRuntime(
                model=model, persistence=persistence
            ).stream([], request_id="r1")
        ]

    events = asyncio.run(collect())

    assert len(persistence.events) == len(events)
    assert all(event.request_id == "r1" for event in persistence.events)


def test_runtime_publishes_safe_error_event_before_reraising():
    async def model(messages, *, emit):
        raise TimeoutError("upstream timeout")

    persistence = BufferedAgentRunPersistence("r1")

    async def run():
        await AgentRuntime(model=model, persistence=persistence).run([], request_id="r1")

    try:
        asyncio.run(run())
    except TimeoutError:
        pass
    else:
        raise AssertionError("expected model error")
    assert persistence.events[-1].type == "error"
    assert persistence.events[-1].payload["code"] == "agent_upstream_unavailable"


def test_runtime_stream_publishes_one_error_when_tool_fails():
    model_calls = 0

    async def model(messages, *, emit):
        nonlocal model_calls
        model_calls += 1
        if model_calls == 1:
            return ModelTurn(tool_calls=[ToolCall("call-1", "broken")])
        return ModelTurn(content="工具失败已交由模型处理")

    async def invoke(call):
        raise RuntimeError("tool exploded")

    persistence = BufferedAgentRunPersistence("tool-error-1")

    async def collect():
        return [
            event
            async for event in AgentRuntime(
                model=model,
                tool_invoker=invoke,
                persistence=persistence,
            ).stream([], request_id="tool-error-1")
        ]

    events = asyncio.run(collect())

    errors = [event for event in persistence.events if event.type == "error"]
    failed_tools = [
        event
        for event in events
        if event.type == "tool_completed" and event.payload["status"] == "failed"
    ]
    assert errors == []
    assert len(failed_tools) == 1
    assert events[-1].type == "completed"


def test_runtime_stream_invokes_hook_for_fallback_model_error():
    observed = []

    async def model(messages, *, emit):
        raise TimeoutError("upstream timeout")

    async def hook(event):
        observed.append(event)

    persistence = BufferedAgentRunPersistence("stream-error-1")

    async def collect():
        return [
            event
            async for event in AgentRuntime(
                model=model,
                hooks=AgentRuntimeHooks(on_event=hook),
                persistence=persistence,
            ).stream([], request_id="stream-error-1")
        ]

    events = asyncio.run(collect())

    # 与 legacy stream_graph 的契约一致：模型级错误以终止 error 事件结束事件
    # 流，而不是把普通异常抛给协议层；协议层据此落库 failed 并发送 SSE/WS
    # error，避免灰度流在首事件前失败时 loop 永久停在 running。
    assert [event.type for event in events] == ["error"]
    assert events[-1].payload["code"] == "agent_upstream_unavailable"
    assert [event.type for event in observed] == ["error"]
    assert observed[0].payload["code"] == "agent_upstream_unavailable"
    assert persistence.events[-1].type == "error"


def test_runtime_stream_cancellation_still_propagates():
    """取消语义不能随模型错误收尾一起被吞掉。"""

    cancelled = asyncio.Event()
    cancelled.set()
    persistence = BufferedAgentRunPersistence("cancel-stream-1")

    async def model(messages, *, emit):
        raise AssertionError("cancelled request must not call the model")

    async def collect():
        async for _ in AgentRuntime(
            model=model,
            persistence=persistence,
        ).stream(
            [],
            request_id="cancel-stream-1",
            cancel_event=cancelled,
        ):
            pass

    try:
        asyncio.run(collect())
    except asyncio.CancelledError:
        pass
    else:
        raise AssertionError("expected cancellation")


def test_runtime_does_not_duplicate_loop_cancellation_event():
    cancelled = asyncio.Event()
    cancelled.set()
    persistence = BufferedAgentRunPersistence("cancel-1")

    async def model(messages, *, emit):
        raise AssertionError("cancelled request must not call the model")

    async def run():
        await AgentRuntime(model=model, persistence=persistence).run(
            [], request_id="cancel-1", cancel_event=cancelled
        )

    try:
        asyncio.run(run())
    except asyncio.CancelledError:
        pass
    else:
        raise AssertionError("expected cancellation")

    assert len(persistence.events) == 1
    assert persistence.events[0].payload["code"] == "agent_request_cancelled"


def test_runtime_stream_invokes_event_hook_for_every_event():
    observed = []

    async def model(messages, *, emit):
        await emit(AgentEvent("message_delta", {"content": "streamed"}))
        return ModelTurn(content="streamed")

    async def hook(event):
        observed.append(event.type)

    async def scenario():
        runtime = AgentRuntime(
            model=model,
            hooks=AgentRuntimeHooks(on_event=hook),
        )
        return [event.type async for event in runtime.stream([])]

    event_types = asyncio.run(scenario())

    assert [str(event_type) for event_type in event_types] == [
        "message_delta",
        "completed",
    ]
    assert [str(event_type) for event_type in observed] == [
        "message_delta",
        "completed",
    ]


def test_runtime_continuation_is_available_through_public_facade():
    async def model(messages, *, emit):
        return ModelTurn(content="继续完成")

    result = asyncio.run(
        AgentRuntime(model=model).continue_run(
            [], ToolOutcome(status="completed", result="已确认"), request_id="r1"
        )
    )

    assert result.content == "继续完成"


def test_runtime_continuation_does_not_duplicate_snapshot_outcome():
    outcome = ToolOutcome(status="completed", result="已确认")
    seen = []

    async def model(messages, *, emit):
        seen.append(list(messages))
        return ModelTurn(content="继续完成")

    asyncio.run(
        AgentRuntime(model=model).continue_run(
            [outcome], outcome, request_id="r1"
        )
    )

    assert seen == [[outcome]]


def test_runtime_result_preserves_pending_confirmation_id():
    async def model(messages, *, emit):
        return ModelTurn(
            tool_calls=[ToolCall("confirm-1", "delete_order")]
        )

    async def invoke(call):
        return ToolOutcome(
            status="confirmation_required",
            confirmation_id=42,
            call_id=call.id,
        )

    result = asyncio.run(
        AgentRuntime(model=model, tool_invoker=invoke).run([])
    )

    assert result.pending_confirmation_id == 42
    assert len(result.tool_events) == 1
    assert result.tool_events[0]["tool_call_id"] == "confirm-1"


def test_runtime_continuation_merges_prior_usage_and_tool_events():
    prior = AgentResult(
        content="等待确认",
        usage={"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
        tool_events=[{"tool": "delete_order"}],
        pending_confirmation_id=42,
    )
    outcome = ToolOutcome(
        status="completed", result={"approved": True}, call_id="confirm-1"
    )

    async def model(messages, *, emit):
        return ModelTurn(
            content="已完成",
            metadata={
                "usage": {
                    "prompt_tokens": 5,
                    "completion_tokens": 3,
                    "total_tokens": 8,
                },
                "tool_events": [{"tool": "delete_order", "status": "completed"}],
            },
        )

    result = asyncio.run(
        AgentRuntime(model=model).continue_run(
            [outcome],
            outcome,
            request_id="r1",
            prior_result=prior,
        )
    )

    assert result.usage == {
        "prompt_tokens": 15,
        "completion_tokens": 5,
        "total_tokens": 20,
    }
    assert result.tool_events == [
        {"tool": "delete_order"},
        {"tool": "delete_order", "status": "completed"},
    ]
    assert result.pending_confirmation_id is None


def test_runtime_can_be_composed_from_langchain_model():
    class Model:
        async def ainvoke(self, messages):
            from langchain_core.messages import AIMessage

            return AIMessage(content="组合完成")

    result = asyncio.run(
        AgentRuntime.from_langchain(Model()).run([])
    )

    assert result.content == "组合完成"
