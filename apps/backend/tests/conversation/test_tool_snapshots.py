"""工具结果快照跨轮记忆的单元测试：构造、去重、注入、护栏与超限兜底。"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from langchain_core.messages import HumanMessage, SystemMessage
from app.modules.conversation.runtime import (
    SNAPSHOT_METADATA_KEY,
    _SNAPSHOT_LIMIT_NOTE,
    _SNAPSHOT_SECTION_TITLE,
    apply_runtime_context_guardrail,
    attach_tool_snapshots,
    build_agent_error_payload,
    build_history_messages,
    build_tool_snapshots,
    collect_tool_snapshots,
    is_context_length_exceeded,
    resolve_context_window_tokens,
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

def test_history_builds_tool_pairing_in_original_order():
    history = [
        SimpleNamespace(
            role="user", content="我叫小明", tool_call_id=None,
            message_metadata=None, content_blocks=None, created_at=None,
        ),
        SimpleNamespace(
            role="assistant", content="你好，小明", tool_call_id=None,
            message_metadata=None, content_blocks=None, created_at=None,
        ),
        SimpleNamespace(
            role="tool", content="工具结果", tool_call_id="call-1",
            message_metadata=None, content_blocks=None, created_at=None,
        ),
    ]
    converted = build_history_messages(history)
    assert [type(item).__name__ for item in converted] == [
        "HumanMessage",
        "AIMessage",
        "ToolMessage",
    ]
    assert converted[2].content == "工具结果"
    assert converted[2].tool_call_id == "call-1"


def test_history_restores_attachment_content():
    history = [
        SimpleNamespace(
            role="user", content="分析附件",
            content_blocks=[
                {"type": "file", "asset_id": "doc-1"},
                {"type": "image", "asset_id": "img-1"},
            ],
            tool_call_id=None, message_metadata=None, created_at=None,
        ),
    ]
    converted = build_history_messages(
        history,
        attachment_parts={
            "doc-1": [{"type": "text", "text": "附件 doc-1 内容如下：\n金额 100"}],
            "img-1": [
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/jpeg;base64,YQ=="},
                }
            ],
        },
    )
    user_message = converted[0]
    assert user_message.content[0]["text"] == "分析附件"
    assert [part["type"] for part in user_message.content[1:]] == [
        "text",
        "image_url",
    ]
    assert user_message.content[1]["text"].startswith("附件 doc-1")

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

def test_context_guardrail_keeps_system_and_current_trimming_history_first():
    snapshot = SystemMessage(
        content=f"{_SNAPSHOT_SECTION_TITLE}\n" + "订单金额" * 20
    )
    current = HumanMessage(content="当前问题")
    messages = [
        SystemMessage(content="系统提示"),
        HumanMessage(content="旧历史消息" * 60),
        snapshot,
        current,
    ]
    budget = (
        len(messages[0].content)
        + len(snapshot.content)
        + len(current.content)
    )
    trimmed = apply_runtime_context_guardrail(
        messages,
        window_tokens=budget,
        input_ratio=1.0,
        chars_per_token=1.0,
    )
    # 系统提示、快照与当前问题保留；旧历史整条先被裁掉。
    assert type(trimmed[0]).__name__ == "SystemMessage"
    assert type(trimmed[-1]).__name__ == "HumanMessage"
    assert trimmed[-1].content == "当前问题"
    assert [item.content for item in trimmed] == [
        "系统提示",
        snapshot.content,
        "当前问题",
    ]

def test_context_guardrail_marks_dropped_snapshot_with_note():
    snapshot = SystemMessage(
        content=f"{_SNAPSHOT_SECTION_TITLE}\n" + "订单金额" * 20
    )
    current = HumanMessage(content="当前问题")
    messages = [
        SystemMessage(content="系统提示"),
        HumanMessage(content="旧历史消息" * 60),
        snapshot,
        current,
    ]
    # 预算比「系统 + 快照 + 当前」还小：历史裁完后仍超限，快照退化为提示语。
    tiny_budget = len(messages[0].content) + len(current.content) + 1
    trimmed = apply_runtime_context_guardrail(
        messages,
        window_tokens=tiny_budget,
        input_ratio=1.0,
        chars_per_token=1.0,
    )
    assert type(trimmed[0]).__name__ == "SystemMessage"
    assert type(trimmed[-1]).__name__ == "HumanMessage"
    assert trimmed[-1].content == "当前问题"
    notes = [
        item.content
        for item in trimmed
        if isinstance(item, SystemMessage) and item.content == _SNAPSHOT_LIMIT_NOTE
    ]
    assert notes, "快照超预算时应改写为 _SNAPSHOT_LIMIT_NOTE 保留占位"

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
    # 模型名由调用方传入（注册表解析结果），版本行只提供显式列值。
    version = SimpleNamespace(context_window_tokens=None)
    assert (
        resolve_context_window_tokens(version, model_name="deepseek-v4-flash")
        == 1_000_000
    )
    explicit = SimpleNamespace(context_window_tokens=128_000)
    assert (
        resolve_context_window_tokens(explicit, model_name="deepseek-v4-flash")
        == 128_000
    )
    assert (
        resolve_context_window_tokens(
            SimpleNamespace(context_window_tokens=None),
            model_name="openrouter/deepseek-chat",
        )
        == 128_000
    )
    assert (
        resolve_context_window_tokens(
            SimpleNamespace(context_window_tokens=None), model_name="gpt-some-new"
        )
        is None
    )
    assert resolve_context_window_tokens(SimpleNamespace(context_window_tokens=None)) is None
