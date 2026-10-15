import asyncio

from app.modules.agent_runtime.contracts import ToolCall, ToolOutcome
from app.modules.agent_runtime.hooks import AgentRuntimeHooks
from app.modules.agent_runtime.loop import AgentLoop, ModelTurn


def test_loop_reuses_one_core_for_tool_rounds_and_emits_events():
    calls = 0
    events = []

    async def model(messages, *, emit):
        nonlocal calls
        calls += 1
        if calls == 1:
            return ModelTurn(tool_calls=[ToolCall("c1", "search", {"q": "x"})])
        return ModelTurn(content="完成")

    async def invoke(call):
        return ToolOutcome(status="completed", result={"ok": True})

    async def on_event(event):
        events.append(event.type)

    result = asyncio.run(
        AgentLoop(
            model=model,
            tool_invoker=invoke,
            hooks=AgentRuntimeHooks(on_event=on_event),
        ).run([], request_id="r1")
    )

    assert result.content == "完成"
    assert calls == 2
    assert "tool_completed" in events
    assert result.metadata["tool_events"][0]["tool_call_id"] == "c1"


def test_loop_accumulates_thinking_across_tool_rounds():
    calls = 0

    async def model(messages, *, emit):
        nonlocal calls
        calls += 1
        if calls == 1:
            return ModelTurn(
                tool_calls=[ToolCall("c1", "lookup", {"city": "上海"})],
                metadata={"thinking_text": "先分析是否需要工具"},
            )
        return ModelTurn(
            content="已完成",
            metadata={"thinking_text": "最后基于结果总结"},
        )

    async def invoke(call):
        return ToolOutcome(status="completed", result="晴")

    result = asyncio.run(AgentLoop(model=model, tool_invoker=invoke).run([]))

    assert result.metadata["thinking_text"] == "先分析是否需要工具最后基于结果总结"


def test_loop_transforms_context_before_each_model_turn_and_keeps_tool_outcome():
    seen_contexts = []
    transform_calls = 0

    async def transform(messages):
        nonlocal transform_calls
        transform_calls += 1
        return [*messages, f"guard-{transform_calls}"]

    async def model(messages, *, emit):
        seen_contexts.append(list(messages))
        if len(seen_contexts) == 1:
            return ModelTurn(tool_calls=[ToolCall("c1", "lookup", {})])
        return ModelTurn(content="完成")

    async def invoke(call):
        return ToolOutcome(status="completed", result="value")

    result = asyncio.run(
        AgentLoop(
            model=model,
            tool_invoker=invoke,
            hooks=AgentRuntimeHooks(transform_context=transform),
        ).run(["初始消息"])
    )

    assert result.content == "完成"
    assert transform_calls == 2
    assert seen_contexts[0][-1] == "guard-1"
    assert seen_contexts[1][-1] == "guard-2"
    assert any(
        getattr(item, "result", None) == "value" for item in seen_contexts[1]
    )


def test_loop_tool_event_order_and_payload_are_correlation_safe():
    events = []
    model_calls = 0

    async def model(messages, *, emit):
        nonlocal model_calls
        model_calls += 1
        if model_calls == 1:
            return ModelTurn(
                tool_calls=[
                    ToolCall(
                        id="call-1",
                        name="calculate_total",
                        arguments={"left": 3, "right": 3},
                    )
                ]
            )
        return ModelTurn(content="done")

    async def invoke(call):
        return ToolOutcome(status="completed", result={"total": 6})

    async def on_event(event):
        events.append(event)

    result = asyncio.run(
        AgentLoop(
            model=model,
            tool_invoker=invoke,
            hooks=AgentRuntimeHooks(on_event=on_event),
        ).run([])
    )

    assert result.content == "done"
    assert [event.type for event in events] == [
        "tool_started",
        "tool_completed",
        "completed",
    ]
    assert events[0].payload["tool_calls"][0]["id"] == "call-1"
    assert events[0].payload["tool_calls"][0]["arguments"] == {
        "left": 3,
        "right": 3,
    }
    assert events[1].payload["tool_call_id"] == "call-1"
    assert events[1].payload["outcome"].result == {"total": 6}


def test_loop_honors_cancellation_before_model_call():
    async def model(messages, *, emit):
        raise AssertionError("model must not be called")

    cancelled = asyncio.Event()
    cancelled.set()

    try:
        asyncio.run(AgentLoop(model=model).run([], cancel_event=cancelled))
    except asyncio.CancelledError:
        pass
    else:
        raise AssertionError("expected cancellation")


def test_loop_publishes_one_stable_cancellation_event_before_stopping():
    cancelled = asyncio.Event()
    cancelled.set()
    events = []

    async def model(messages, *, emit):
        raise AssertionError("cancelled request must not call the model")

    async def on_event(event):
        events.append(event)

    from app.modules.agent_runtime.hooks import AgentRuntimeHooks

    try:
        asyncio.run(
            AgentLoop(
                model=model,
                hooks=AgentRuntimeHooks(on_event=on_event),
            ).run([], request_id="cancel-1", cancel_event=cancelled)
        )
    except asyncio.CancelledError:
        pass
    else:
        raise AssertionError("expected cancellation")

    assert len(events) == 1
    assert events[0].type == "error"
    assert events[0].request_id == "cancel-1"
    assert events[0].payload["code"] == "agent_request_cancelled"


def test_loop_cancels_a_pending_tool_when_cancel_event_is_set():
    cancelled = asyncio.Event()
    tool_started = asyncio.Event()

    async def model(messages, *, emit):
        return ModelTurn(tool_calls=[ToolCall("call-1", "slow")])

    async def invoke(call):
        tool_started.set()
        await asyncio.Future()

    async def scenario():
        events = []

        async def on_event(event):
            events.append(event)

        task = asyncio.create_task(
            AgentLoop(
                model=model,
                tool_invoker=invoke,
                hooks=AgentRuntimeHooks(on_event=on_event),
            ).run([], cancel_event=cancelled)
        )
        await tool_started.wait()
        cancelled.set()
        try:
            await task
        except asyncio.CancelledError:
            pass
        return events

    events = asyncio.run(scenario())
    assert [event.type for event in events].count("error") == 1
    assert events[-1].payload["code"] == "agent_request_cancelled"


def test_loop_converts_tool_exception_to_failure_and_continues_batch():
    events = []
    invoked = []
    contexts = []
    model_calls = 0

    async def model(messages, *, emit):
        nonlocal model_calls
        model_calls += 1
        contexts.append(list(messages))
        if model_calls == 1:
            return ModelTurn(
                tool_calls=[
                    ToolCall("call-1", "broken"),
                    ToolCall("call-2", "healthy"),
                ]
            )
        return ModelTurn(content="已根据工具结果完成")

    async def invoke(call):
        invoked.append(call.id)
        if call.id == "call-1":
            raise TimeoutError("tool timeout")
        return ToolOutcome(status="completed", result={"ok": True}, call_id=call.id)

    async def on_event(event):
        events.append(event)

    result = asyncio.run(
        AgentLoop(
            model=model,
            tool_invoker=invoke,
            hooks=AgentRuntimeHooks(on_event=on_event),
        ).run([])
    )

    completed = [event for event in events if event.type == "tool_completed"]
    assert result.content == "已根据工具结果完成"
    assert invoked == ["call-1", "call-2"]
    assert len(completed) == 2
    assert completed[0].payload["status"] == "failed"
    assert completed[0].payload["error"]["code"] == "agent_upstream_unavailable"
    assert completed[1].payload["status"] == "completed"
    assert contexts[1][-2].status == "failed"
    assert contexts[1][-1].status == "completed"


def test_loop_keeps_explicit_failed_outcome_as_model_input_without_short_circuit():
    invoked = []
    model_calls = 0

    async def model(messages, *, emit):
        nonlocal model_calls
        model_calls += 1
        if model_calls == 1:
            return ModelTurn(
                tool_calls=[
                    ToolCall("call-1", "first"),
                    ToolCall("call-2", "second"),
                ]
            )
        return ModelTurn(content="模型已处理失败结果")

    async def invoke(call):
        invoked.append(call.id)
        if call.id == "call-1":
            return ToolOutcome(
                status="failed",
                error={"code": "business_error", "message": "查询失败"},
                call_id=call.id,
            )
        return ToolOutcome(status="completed", result="ok", call_id=call.id)

    result = asyncio.run(AgentLoop(model=model, tool_invoker=invoke).run([]))

    assert result.content == "模型已处理失败结果"
    assert invoked == ["call-1", "call-2"]


def test_loop_stops_for_waiting_tool_outcome():
    calls = []

    async def model(messages, *, emit):
        calls.append("model")
        return ModelTurn(
            content="等待确认",
            tool_calls=[ToolCall(id="c1", name="approve")],
        )

    async def tool(call):
        return ToolOutcome(status="confirmation_required", confirmation_id=9)

    result = asyncio.run(
        AgentLoop(model=model, tool_invoker=tool).run([])
    )

    assert calls == ["model"]
    assert result.metadata["pending_tool_outcome"].confirmation_id == 9
    # 等待态也必须把已执行工具事件挂到结果 metadata，协议层才能落等待步骤。
    assert result.metadata["tool_events"][0]["tool_call_id"] == "c1"
    assert result.metadata["tool_events"][0]["outcome"].confirmation_id == 9


def test_loop_waiting_outcome_emits_completion_and_does_not_call_model_again():
    model_calls = 0
    tool_calls = 0
    events = []

    async def model(messages, *, emit):
        nonlocal model_calls
        model_calls += 1
        return ModelTurn(
            tool_calls=[ToolCall("confirm-1", "delete_order", {"id": "o-1"})]
        )

    async def invoke(call):
        nonlocal tool_calls
        tool_calls += 1
        return ToolOutcome(
            status="confirmation_required",
            confirmation_id=42,
            call_id=call.id,
        )

    async def on_event(event):
        events.append(event)

    result = asyncio.run(
        AgentLoop(
            model=model,
            tool_invoker=invoke,
            hooks=AgentRuntimeHooks(on_event=on_event),
        ).run([])
    )

    assert model_calls == 1
    assert tool_calls == 1
    assert result.metadata["pending_tool_outcome"].confirmation_id == 42
    assert [event.type for event in events] == [
        "tool_started",
        "tool_completed",
    ]
    assert events[-1].payload["outcome"].status == "confirmation_required"


def test_loop_continuation_reuses_completed_tool_result_without_reexecution():
    seen = []

    async def model(messages, *, emit):
        seen.append(messages[-1])
        return ModelTurn(content="已根据确认继续")

    outcome = ToolOutcome(
        status="completed", result={"approved": True}, call_id="c1"
    )
    result = asyncio.run(
        AgentLoop(model=model).continue_run(
            [], outcome, request_id="r1"
        )
    )

    assert result.content == "已根据确认继续"
    assert seen == [outcome]


def test_loop_continuation_does_not_duplicate_result_already_in_snapshot():
    outcome = ToolOutcome(
        status="completed", result={"approved": True}, call_id="c1"
    )
    seen = []

    async def model(messages, *, emit):
        seen.append(list(messages))
        return ModelTurn(content="已继续")

    asyncio.run(
        AgentLoop(model=model).continue_run(
            [outcome], outcome, request_id="r1"
        )
    )

    assert seen == [[outcome]]


def test_continuation_emits_completed_without_reexecuting_confirmed_tool():
    events = []
    tool_calls = 0
    outcome = ToolOutcome(
        status="completed",
        result={"approved": True},
        call_id="confirm-1",
    )

    async def model(messages, *, emit):
        assert messages[-1] is outcome
        return ModelTurn(content="已继续执行")

    async def invoke(call):
        nonlocal tool_calls
        tool_calls += 1
        raise AssertionError("continuation must not execute the tool again")

    async def on_event(event):
        events.append(event)

    result = asyncio.run(
        AgentLoop(
            model=model,
            tool_invoker=invoke,
            hooks=AgentRuntimeHooks(on_event=on_event),
        ).continue_run([], outcome, request_id="resume-1")
    )

    assert result.content == "已继续执行"
    assert tool_calls == 0
    assert [event.type for event in events] == ["completed"]
    assert events[0].request_id == "resume-1"


def test_max_turns_injects_wrapup_prompt_and_does_not_execute_wrapup_tools():
    model_calls = []
    executed = []

    async def model(messages, *, emit, **kwargs):
        model_calls.append((list(messages), kwargs))
        if len(model_calls) == 1:
            return ModelTurn(tool_calls=[ToolCall("c1", "lookup")])
        return ModelTurn(content="基于已有信息的最终回答")

    async def invoke(call):
        executed.append(call.id)
        return ToolOutcome(status="completed", result="found", call_id=call.id)

    result = asyncio.run(
        AgentLoop(
            model=model,
            tool_invoker=invoke,
            hooks=AgentRuntimeHooks(max_turns=1),
        ).run(["用户问题"])
    )

    # 与 legacy Graph / Pi 对齐：达到上限的那次模型响应若请求新工具，该轮
    # 工具不执行（max_turns=1 时首轮即达上限，c1 不执行），直接进入收尾。
    assert result.content == "基于已有信息的最终回答"
    assert result.metadata["budget_exceeded"] is True
    assert executed == []
    assert "最大执行轮数" in str(model_calls[1][0][0])
    assert model_calls[1][1]["allow_tools"] is False


def test_wrapup_tool_calls_become_stable_failed_outcomes_without_looping():
    model_calls = 0
    events = []

    async def model(messages, *, emit, **kwargs):
        nonlocal model_calls
        model_calls += 1
        if model_calls == 1:
            return ModelTurn(tool_calls=[ToolCall("c1", "lookup")])
        return ModelTurn(content="", tool_calls=[ToolCall("c2", "write")])

    async def invoke(call):
        raise AssertionError("wrapup tool must not execute")

    async def on_event(event):
        events.append(event)

    result = asyncio.run(
        AgentLoop(
            model=model,
            tool_invoker=invoke,
            hooks=AgentRuntimeHooks(max_turns=1, on_event=on_event),
        ).run([])
    )

    assert model_calls == 2
    assert result.metadata["budget_exceeded"] is True
    assert result.metadata["tool_events"][-1]["outcome"].status == "failed"
    assert [event.type for event in events][-1] == "completed"


def test_wrapup_model_type_error_is_not_retried_as_signature_fallback():
    calls = 0

    async def model(messages, *, emit, allow_tools=True):
        nonlocal calls
        calls += 1
        if calls == 1:
            return ModelTurn(tool_calls=[ToolCall("c1", "lookup")])
        raise TypeError("provider failure")

    async def invoke(call):
        return ToolOutcome(status="completed", result="ok", call_id=call.id)

    try:
        asyncio.run(
            AgentLoop(
                model=model,
                tool_invoker=invoke,
                hooks=AgentRuntimeHooks(max_turns=1),
            ).run([])
        )
    except TypeError as error:
        assert str(error) == "provider failure"
    else:
        raise AssertionError("provider TypeError should propagate")
    assert calls == 2


def test_non_positive_max_turns_preserves_unlimited_legacy_semantics():
    calls = 0

    async def model(messages, *, emit, allow_tools=True):
        nonlocal calls
        calls += 1
        if calls < 2:
            return ModelTurn(tool_calls=[ToolCall(f"c{calls}", "lookup")])
        return ModelTurn(content="完成")

    async def invoke(call):
        return ToolOutcome(status="completed", result="ok", call_id=call.id)

    result = asyncio.run(
        AgentLoop(
            model=model,
            tool_invoker=invoke,
            hooks=AgentRuntimeHooks(max_turns=0),
        ).run([])
    )

    assert calls == 2
    assert result.content == "完成"


def test_loop_accumulates_usage_across_tool_rounds():
    """多轮工具场景 usage 必须跨轮累计，与 legacy Graph 的逐轮相加一致。"""

    events = []
    model_calls = 0

    async def model(messages, *, emit):
        nonlocal model_calls
        model_calls += 1
        if model_calls == 1:
            return ModelTurn(
                content="",
                tool_calls=[ToolCall("call-1", "lookup")],
                metadata={
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 2,
                        "total_tokens": 12,
                    }
                },
            )
        return ModelTurn(
            content="回答完成",
            metadata={
                "usage": {
                    "prompt_tokens": 20,
                    "completion_tokens": 5,
                    "total_tokens": 25,
                }
            },
        )

    async def invoke(call):
        return ToolOutcome(status="completed", result={"ok": True}, call_id=call.id)

    async def on_event(event):
        events.append(event)

    result = asyncio.run(
        AgentLoop(
            model=model,
            tool_invoker=invoke,
            hooks=AgentRuntimeHooks(on_event=on_event),
        ).run([])
    )

    # 最终结果与 completed 事件都必须携带两轮合计值；工具轮事件至少携带
    # 到当前轮为止的累计值，供协议层按 legacy 口径落库 usage。
    assert result.metadata["usage"] == {
        "prompt_tokens": 30,
        "completion_tokens": 7,
        "total_tokens": 37,
    }
    started = next(event for event in events if event.type == "tool_started")
    completed = next(event for event in events if event.type == "completed")
    assert started.payload["usage"] == {
        "prompt_tokens": 10,
        "completion_tokens": 2,
        "total_tokens": 12,
    }
    assert completed.payload["usage"] == result.metadata["usage"]


def test_loop_recovers_once_from_model_error_with_degraded_context():
    """模型抛上下文超限时按 on_model_error 降级重试一次，不产生错误事件。"""
    calls = []
    events = []

    class ContextLimitError(RuntimeError):
        pass

    async def model(messages, *, emit):
        calls.append(list(messages))
        if len(calls) == 1:
            raise ContextLimitError("context_length_exceeded")
        return ModelTurn(content="基于降级上下文的回答")

    def on_model_error(error, messages):
        # 仅对上下文超限错误降级为“系统 + 当前用户”；返回 None 不重试。
        if not isinstance(error, ContextLimitError):
            return None
        return [messages[0], messages[-1]]

    async def on_event(event):
        events.append(event.type)

    result = asyncio.run(
        AgentLoop(
            model=model,
            hooks=AgentRuntimeHooks(
                on_event=on_event, on_model_error=on_model_error
            ),
        ).run(["system", "history", "user"])
    )

    assert result.content == "基于降级上下文的回答"
    assert len(calls) == 2
    # 第一次失败不发布错误/完成事件，只有成功那次有 completed。
    assert events == ["completed"]


def test_loop_does_not_retry_when_recoverer_returns_none():
    """on_model_error 返回 None（或不匹配）时不重试，错误原样向上传播。"""

    class OtherError(RuntimeError):
        pass

    async def model(messages, *, emit):
        raise OtherError("boom")

    async def on_model_error(error, messages):
        return None

    try:
        asyncio.run(
            AgentLoop(
                model=model,
                hooks=AgentRuntimeHooks(on_model_error=on_model_error),
            ).run(["m"])
        )
    except OtherError:
        pass
    else:
        raise AssertionError("expected OtherError to propagate")


def test_loop_runs_delegation_serially_and_keeps_sibling_tool_result():
    """委派工具走同一条串行工具通道：父 loop 不并发，失败也不拖累同批工具。

    并发池在 `delegate_tasks` 内部，不在 `AgentLoop` 里——这条断言是「父 loop
    语义零改动」的守门人：一旦有人在 loop 层加并发，这里立刻失败。
    """
    events = []
    contexts = []
    order = []
    in_flight = 0
    max_in_flight = 0
    model_calls = 0

    async def model(messages, *, emit):
        nonlocal model_calls
        model_calls += 1
        contexts.append(list(messages))
        if model_calls == 1:
            return ModelTurn(
                tool_calls=[
                    ToolCall("call-1", "delegate_tasks"),
                    ToolCall("call-2", "runtime_info"),
                ]
            )
        return ModelTurn(content="两个工具都回来了")

    async def invoke(call):
        nonlocal in_flight, max_in_flight
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        order.append(call.name)
        try:
            # 模拟子运行耗时不均：委派明显更慢，若 loop 并发执行则会重叠
            await asyncio.sleep(0.02 if call.name == "delegate_tasks" else 0)
        finally:
            in_flight -= 1
        if call.name == "delegate_tasks":
            return ToolOutcome(
                status="failed",
                call_id=call.id,
                error={"code": "delegation_timeout", "message": "子运行超时"},
            )
        return ToolOutcome(
            status="completed", call_id=call.id, result={"platform": "acme"}
        )

    async def on_event(event):
        events.append(event)

    result = asyncio.run(
        AgentLoop(
            model=model,
            tool_invoker=invoke,
            hooks=AgentRuntimeHooks(on_event=on_event),
        ).run([])
    )

    assert max_in_flight == 1
    assert order == ["delegate_tasks", "runtime_info"]
    assert result.content == "两个工具都回来了"
    completed = [event for event in events if event.type == "tool_completed"]
    assert [event.payload["status"] for event in completed] == ["failed", "completed"]
    # 委派的失败以一个稳定错误码交回父模型，而不是异常或整批中止
    assert completed[0].payload["error"]["code"] == "delegation_timeout"
    assert contexts[1][-2].status == "failed"
    assert contexts[1][-2].error["code"] == "delegation_timeout"
    assert contexts[1][-1].status == "completed"
