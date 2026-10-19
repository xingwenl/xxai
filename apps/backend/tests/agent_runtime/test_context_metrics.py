"""AgentLoop 与上下文计量 seam 的接线测试。

上下文控制器只返回 ``(事件类型, payload)``，真正把它发出去的是 loop：这样压缩
结果与占用上报才会和其他事件走同一条持久化/协议编码路径。本文件守住三件事：
每轮模型调用前后各取一次、事件顺序在回答之前、legacy 适配器不吞掉新事件。
"""

import asyncio

from app.modules.agent_runtime.contracts import (
    AgentEvent,
    AgentEventType,
    ToolCall,
    ToolOutcome,
)
from app.modules.agent_runtime.event_adapters import event_from_legacy, event_to_legacy
from app.modules.agent_runtime.events import run_events_from_stream_item
from app.modules.agent_runtime.hooks import AgentRuntimeHooks
from app.modules.agent_runtime.loop import AgentLoop, ModelTurn


class _FakeMetricsSink:
    """记录 loop 何时、带着什么 usage 来取事件。"""

    def __init__(self, *, pre_events=None, usage_payload=None):
        self.calls: list[tuple[int, dict | None]] = []
        self._pre_events = list(pre_events or [])
        self._usage_payload = usage_payload or {
            "usedTokens": 700,
            "windowTokens": 1_000,
            "percent": 70.0,
            "source": "provider",
            "lastCompactedAt": None,
        }

    def drain_events(self, messages, usage=None):
        self.calls.append((len(messages), usage))
        if usage is None:
            return list(self._pre_events)
        return [("context_usage", dict(self._usage_payload))]


def test_loop_reports_usage_after_each_model_turn():
    sink = _FakeMetricsSink()
    events = []

    async def model(messages, *, emit):
        return ModelTurn(
            content="答",
            metadata={"usage": {"prompt_tokens": 700, "completion_tokens": 12}},
        )

    async def on_event(event):
        events.append((str(event.type), event.payload))

    result = asyncio.run(
        AgentLoop(
            model=model,
            tool_invoker=None,
            hooks=AgentRuntimeHooks(on_event=on_event, context_metrics=sink),
        ).run([], request_id="r-context")
    )

    # 模型调用前取一次（只取压缩事件），调用后带本轮真值取一次。
    assert [usage for _size, usage in sink.calls] == [
        None,
        {"prompt_tokens": 700, "completion_tokens": 12},
    ]
    usage_events = [payload for name, payload in events if name == "context_usage"]
    assert usage_events == [
        {
            "usedTokens": 700,
            "windowTokens": 1_000,
            "percent": 70.0,
            "source": "provider",
            "lastCompactedAt": None,
        }
    ]
    assert result.content == "答"


def test_loop_emits_compaction_event_before_the_answer():
    """压缩发生在模型调用之前，事件必须也在回答事件之前到达客户端。"""

    sink = _FakeMetricsSink(
        pre_events=[
            (
                "context_compacted",
                {
                    "ok": True,
                    "reason": "compacted",
                    "trigger": "auto",
                    "tokensBefore": 900,
                    "tokensAfter": 120,
                    "windowTokens": 1_000,
                    "percent": 12.0,
                    "summaryChars": 42,
                },
            )
        ]
    )
    order: list[str] = []

    async def model(messages, *, emit):
        return ModelTurn(
            content="答", metadata={"usage": {"prompt_tokens": 120}}
        )

    async def on_event(event):
        order.append(str(event.type))

    asyncio.run(
        AgentLoop(
            model=model,
            tool_invoker=None,
            hooks=AgentRuntimeHooks(on_event=on_event, context_metrics=sink),
        ).run([], request_id="r-compact")
    )

    assert order.index("context_compacted") < order.index("context_usage")
    assert "completed" in order


def test_compaction_event_reaches_tool_rounds_too():
    """工具轮里发生的压缩同样要发事件（fork 后第二轮上下文可能已超阈值）。"""

    calls = 0
    sink = _FakeMetricsSink(
        pre_events=[("context_compacted", {"ok": True, "reason": "compacted"})]
    )
    seen: list[str] = []

    async def model(messages, *, emit):
        nonlocal calls
        calls += 1
        if calls == 1:
            return ModelTurn(
                tool_calls=[ToolCall("c1", "lookup", {})],
                metadata={"usage": {"prompt_tokens": 10}},
            )
        return ModelTurn(content="完成", metadata={"usage": {"prompt_tokens": 10}})

    async def invoke(call):
        return ToolOutcome(status="completed", result="值")

    async def on_event(event):
        seen.append(str(event.type))

    asyncio.run(
        AgentLoop(
            model=model,
            tool_invoker=invoke,
            hooks=AgentRuntimeHooks(on_event=on_event, context_metrics=sink),
        ).run([], request_id="r-tool")
    )

    assert seen.count("context_compacted") == 2
    assert seen.count("context_usage") == 2


def test_context_events_survive_legacy_adapter_and_wire_mapping():
    """新事件必须能穿过 legacy 适配器与 SSE/WS 映射，否则客户端什么也收不到。"""

    event = AgentEvent(
        type=AgentEventType.CONTEXT_USAGE,
        payload={"usedTokens": 12, "windowTokens": None, "percent": None},
        conversation_id=1,
        request_id="r-1",
    )
    legacy = event_to_legacy(event)

    assert legacy["type"] == "context_usage"
    assert legacy["payload"]["usedTokens"] == 12

    items = run_events_from_stream_item(legacy, request_id="r-1")
    assert [item.wire_type for item in items] == ["context_usage"]
    assert items[0].payload == {"usedTokens": 12, "windowTokens": None, "percent": None}


def test_event_from_legacy_recognizes_context_events():
    event = event_from_legacy(
        {"type": "context_compacted", "payload": {"ok": False, "reason": "summary_failed"}},
        request_id="r-2",
    )

    assert event is not None
    assert event.type == AgentEventType.CONTEXT_COMPACTED
    assert event.payload["reason"] == "summary_failed"
