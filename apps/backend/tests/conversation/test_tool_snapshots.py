"""工具结果快照跨轮记忆的单元测试：构造、去重、注入、护栏与超限兜底。"""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.modules.conversation.runtime import (
    SNAPSHOT_METADATA_KEY,
    apply_context_guardrail,
    attach_tool_snapshots,
    build_agent_error_payload,
    build_history_messages,
    build_snapshot_injection_message,
    build_tool_snapshots,
    collect_tool_snapshots,
    is_context_length_exceeded,
    resolve_context_window_tokens,
    run_graph,
    _SNAPSHOT_LIMIT_NOTE,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _succeeded_event(tool: str = "order_query", result=None, params=None) -> dict:
    return {
        "tool": tool,
        "input_summary": params or '{"scope":"2026-09"}',
        "outcome": SimpleNamespace(status="succeeded", result=result),
    }


def _message_row(
    role: str,
    content: str,
    *,
    metadata=None,
    created_at=None,
) -> SimpleNamespace:
    return SimpleNamespace(
        role=role,
        content=content,
        tool_call_id=None,
        message_metadata=metadata,
        content_blocks=None,
        created_at=created_at,
    )


def _orders_result(total: int, kept: int) -> dict:
    return {
        "kind": "store_ops_order_list",
        "total": total,
        "page": 1,
        "page_size": kept,
        "orders": [
            {"id": index, "amount": index * 100, "status": "paid"}
            for index in range(kept)
        ],
    }


def test_snapshot_collects_only_succeeded_events():
    now = _now()
    snapshots = build_tool_snapshots(
        [
            _succeeded_event(result=_orders_result(3, 3)),
            {
                "tool": "payout",
                "input_summary": "{}",
                "outcome": SimpleNamespace(status="confirmation_required"),
            },
            {
                "tool": "ask_user",
                "input_summary": "{}",
                "outcome": SimpleNamespace(status="waiting_question"),
            },
            {
                "tool": "failed_tool",
                "input_summary": "{}",
                "outcome": SimpleNamespace(status="failed"),
            },
        ],
        now=now,
        max_entries=10,
        total_chars=20000,
    )
    assert [entry["tool"] for entry in snapshots] == ["order_query"]
    entry = snapshots[0]
    assert entry["queried_at"] == now.isoformat()
    assert entry["params"] == '{"scope":"2026-09"}'
    assert "共 3 条" in entry["summary"]
    assert "order_query" not in entry["summary"]


def test_snapshot_accepts_platform_completed_status():
    """宿主/MCP 工具成功态为 completed（order_query 走此链路），必须落快照。"""
    event = {
        "tool": "order_query",
        "input_summary": '{"scope":"2026-09"}',
        "outcome": SimpleNamespace(status="completed", result=_orders_result(2, 2)),
    }
    snapshots = build_tool_snapshots([event], now=_now())
    assert [entry["tool"] for entry in snapshots] == ["order_query"]
    assert "共 2 条" in snapshots[0]["summary"]
    assert '{"id":0' in snapshots[0]["summary"]


def test_snapshot_skips_completed_status_with_error_payload():
    """completed 状态但载荷带 error/拒绝语义时不落快照。"""
    events = [
        {
            "tool": "order_query",
            "input_summary": "{}",
            "outcome": SimpleNamespace(
                status="completed", result={"error": {"code": "upstream"}}
            ),
        },
        {
            "tool": "payout",
            "input_summary": "{}",
            "outcome": SimpleNamespace(
                status="completed", result={"status": "rejected", "message": "拒绝"}
            ),
        },
    ]
    assert build_tool_snapshots(events, now=_now()) == []


def test_snapshot_large_list_keeps_count_and_partial_items():
    result = _orders_result(total=50, kept=50)
    snapshots = build_tool_snapshots(
        [_succeeded_event(result=result)],
        now=_now(),
        max_chars=320,
        total_chars=20000,
    )
    summary = snapshots[0]["summary"]
    assert "共 50 条" in summary
    assert "仅保留前" in summary
    assert "其余未保留" in summary
    assert len(summary) <= 320


def test_snapshot_caps_entries_and_total_chars_drops_oldest():
    entries = [
        _succeeded_event(tool=f"tool_{index}", result={"count": index})
        for index in range(5)
    ]
    snapshots = build_tool_snapshots(
        entries, now=_now(), max_entries=3, total_chars=20000
    )
    assert [entry["tool"] for entry in snapshots] == [
        "tool_2",
        "tool_3",
        "tool_4",
    ]


def test_attach_snapshot_metadata_keeps_other_keys():
    metadata = attach_tool_snapshots(
        {"source": "sse"}, [{"tool": "order_query", "summary": "x"}]
    )
    assert metadata["source"] == "sse"
    assert metadata[SNAPSHOT_METADATA_KEY][0]["tool"] == "order_query"
    assert attach_tool_snapshots({}, []) == {}


def test_history_injects_snapshot_system_message_before_current():
    now = _now()
    history = [
        _message_row("user", "我的订单"),
        _message_row(
            "assistant",
            "已为您查询订单",
            metadata=attach_tool_snapshots(
                {},
                build_tool_snapshots(
                    [_succeeded_event(result=_orders_result(2, 2))],
                    now=now - timedelta(minutes=1),
                ),
            ),
            created_at=now - timedelta(minutes=1),
        ),
    ]
    converted = build_history_messages(history)
    assert [type(item).__name__ for item in converted] == [
        "HumanMessage",
        "AIMessage",
        "SystemMessage",
    ]
    snapshot_message = converted[-1]
    assert isinstance(snapshot_message, SystemMessage)
    assert "数据快照" in snapshot_message.content
    assert "order_query" in snapshot_message.content
    assert "变更动作" in snapshot_message.content
    # 注入为纯文本 SystemMessage，不伪造 tool 配对。
    assert "tool_calls" not in snapshot_message.content


def test_history_without_snapshots_injects_nothing():
    converted = build_history_messages(
        [
            _message_row("user", "你好"),
            _message_row("assistant", "你好呀"),
        ]
    )
    assert [type(item).__name__ for item in converted] == [
        "HumanMessage",
        "AIMessage",
    ]


def test_collect_snapshots_dedupes_same_params_keeping_newest():
    now = _now()
    old = {
        "tool": "order_query",
        "params": '{"scope":"2026-09"}',
        "queried_at": (now - timedelta(minutes=10)).isoformat(),
        "summary": "旧结果",
    }
    fresh = {
        "tool": "order_query",
        "params": '{"scope":"2026-09"}',
        "queried_at": now.isoformat(),
        "summary": "新结果",
    }
    other = {
        "tool": "order_query",
        "params": '{"scope":"2026-08"}',
        "queried_at": (now - timedelta(minutes=5)).isoformat(),
        "summary": "另一条件",
    }
    history = [
        _message_row("assistant", "a", metadata={SNAPSHOT_METADATA_KEY: [old, other]}),
        _message_row("assistant", "b", metadata={SNAPSHOT_METADATA_KEY: [fresh]}),
    ]
    collected = collect_tool_snapshots(history, now=now, retention_seconds=3600)
    summaries = [entry["summary"] for entry in collected]
    assert summaries == ["另一条件", "新结果"]
    assert "旧结果" not in summaries


def test_collect_snapshots_filters_by_retention_window():
    now = _now()
    stale = {
        "tool": "order_query",
        "params": "p1",
        "queried_at": (now - timedelta(seconds=100)).isoformat(),
        "summary": "过期结果",
    }
    history = [_message_row("assistant", "a", metadata={SNAPSHOT_METADATA_KEY: [stale]})]
    assert collect_tool_snapshots(history, now=now, retention_seconds=10) == []
    assert len(collect_tool_snapshots(history, now=now, retention_seconds=200)) == 1


def test_second_turn_replay_includes_snapshot_without_fake_tool_pairing():
    now = _now()
    captured = []

    class CaptureModel:
        async def ainvoke(self, messages):
            captured.append(messages)
            return AIMessage(content="最大金额的订单是 9800 元")

    history = [
        _message_row("user", "查一下我的订单"),
        _message_row(
            "assistant",
            "已查询，共 2 笔订单",
            metadata=attach_tool_snapshots(
                {},
                build_tool_snapshots(
                    [_succeeded_event(result=_orders_result(2, 2))],
                    now=now - timedelta(seconds=30),
                ),
            ),
            created_at=now - timedelta(seconds=30),
        ),
    ]
    asyncio.run(
        run_graph(
            CaptureModel(),
            system_prompt="系统提示",
            history=history,
            user_message="刚才订单里金额最大的是哪笔？",
        )
    )
    first_call = captured[0]
    types = [type(item).__name__ for item in first_call]
    assert "ToolMessage" not in types
    assert first_call[-2].content.startswith("以下为此前工具查询到的数据快照")
    assert first_call[-1].content == "刚才订单里金额最大的是哪笔？"
    # 系统提示与历史正文仍按原顺序保留。
    assert types[0] == "SystemMessage"


def test_context_guardrail_keeps_system_and_current_trimming_history_first():
    now = _now()
    history = [
        _message_row(
            "assistant",
            "查询结果正文内容很长" * 30,
            metadata=attach_tool_snapshots(
                {},
                build_tool_snapshots(
                    [_succeeded_event(result=_orders_result(10, 10))],
                    now=now,
                ),
            ),
        ),
        _message_row("user", "中间历史消息" * 30),
    ]
    snapshot_message = build_snapshot_injection_message(history)
    assert snapshot_message is not None
    messages = [
        SystemMessage(content="系统提示" * 100),
        HumanMessage(content="旧历史 1" * 50),
        AIMessage(content="旧历史 2" * 50),
        snapshot_message,
        HumanMessage(content="当前问题"),
    ]
    trimmed = apply_context_guardrail(
        messages,
        window_tokens=160,
        input_ratio=1.0,
        chars_per_token=1.0,
    )
    assert type(trimmed[0]).__name__ == "SystemMessage"
    assert type(trimmed[-1]).__name__ == "HumanMessage"
    assert trimmed[-1].content == "当前问题"
    # 预算极小：旧历史与快照均被裁掉，仅剩系统提示 + 当前消息。
    assert len(trimmed) == 2


def test_context_guardrail_marks_dropped_snapshot_with_note():
    now = _now()
    history = [
        _message_row(
            "assistant",
            "正文",
            metadata=attach_tool_snapshots(
                {},
                build_tool_snapshots(
                    [_succeeded_event(result=_orders_result(10, 10))],
                    now=now,
                ),
            ),
        ),
    ]
    snapshot_message = build_snapshot_injection_message(history)
    messages = [
        SystemMessage(content="系统提示" * 20),
        snapshot_message,
        HumanMessage(content="当前问题"),
    ]
    trimmed = apply_context_guardrail(
        messages,
        window_tokens=150,
        input_ratio=1.0,
        chars_per_token=1.0,
    )
    assert type(trimmed[1]).__name__ == "SystemMessage"
    assert _SNAPSHOT_LIMIT_NOTE in trimmed[1].content


def test_run_graph_degrades_once_on_context_limit_error():
    captured = []
    system_prompt = "系统提示词"
    user_message = "请继续"

    class DegradeModel:
        async def ainvoke(self, messages):
            captured.append(messages)
            if len(captured) == 1:
                raise Exception(
                    "Error code: 400 - This model's maximum context length is "
                    "128000 tokens. However, you requested 150000 tokens. "
                    "Please reduce the length of the messages."
                )
            return AIMessage(content="降级重试成功")

    result = asyncio.run(
        run_graph(
            DegradeModel(),
            system_prompt=system_prompt,
            user_message=user_message,
        )
    )
    assert result.content == "降级重试成功"
    assert len(captured) == 2
    degraded_call = captured[1]
    assert len(degraded_call) == 2
    assert type(degraded_call[0]).__name__ == "SystemMessage"
    assert type(degraded_call[1]).__name__ == "HumanMessage"
    assert degraded_call[1].content.startswith(user_message)
    assert "超过模型上下文上限" in degraded_call[1].content


def test_context_limit_error_payload_is_friendly():
    payload = build_agent_error_payload(
        Exception(
            "This model's maximum context length is 128000 tokens. "
            "However, you requested 150000 tokens."
        )
    )
    assert payload["code"] == "context_length_exceeded"
    assert payload["retryable"] is False
    assert "缩小查询范围" in payload["message"]


def test_is_context_length_exceeded_detects_code_and_text():
    class CodedError(Exception):
        code = "context_length_exceeded"

    assert is_context_length_exceeded(CodedError("bad request"))
    assert is_context_length_exceeded(
        Exception("maximum context length is 128000 tokens")
    )
    assert not is_context_length_exceeded(Exception("connection reset by peer"))


def test_resolve_context_window_priority_and_model_map():
    version = SimpleNamespace(context_window_tokens=None, model_name="deepseek-v4-flash")
    assert resolve_context_window_tokens(version) == 1_000_000
    explicit = SimpleNamespace(
        context_window_tokens=128_000, model_name="deepseek-v4-flash"
    )
    assert resolve_context_window_tokens(explicit) == 128_000
    suffix = SimpleNamespace(context_window_tokens=None, model_name="openrouter/deepseek-chat")
    assert resolve_context_window_tokens(suffix) == 128_000
    unknown = SimpleNamespace(context_window_tokens=None, model_name="gpt-some-new")
    assert resolve_context_window_tokens(unknown) is None
    assert resolve_context_window_tokens(SimpleNamespace(context_window_tokens=None, model_name="")) is None
