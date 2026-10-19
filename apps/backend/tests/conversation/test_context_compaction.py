"""上下文计量与压缩的纯函数/控制器测试（不依赖数据库）。

覆盖 spec 验收标准里三条最容易被改坏的约束：
1. 压缩切点永不落在 tool 行（否则保留区以孤立工具结果开头，供应商会拒绝）；
2. 注入的压缩摘要 SystemMessage 不会被硬截断护栏删掉（删掉＝模型彻底失忆）；
3. 阈值必须早于护栏预算触发，否则现有 0.75×window 的硬截断会先把历史删掉。
"""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from app.modules.conversation.compaction import (
    COMPACTION_SUMMARY_SYSTEM_PROMPT,
    CompactionOutcome,
    ContextCompactionController,
    build_model_history,
    serialize_history_for_summary,
)
from app.modules.conversation.runtime import (
    COMPACTION_SUMMARY_TITLE,
    apply_runtime_context_guardrail,
    build_compaction_summary_message,
    build_history_view,
    estimate_context_tokens,
    plan_compaction_cut,
    resolve_compaction_threshold,
)


def _row(
    row_id: int,
    role: str,
    content: str,
    *,
    tool_call_id: str | None = None,
) -> SimpleNamespace:
    """伪造一条持久化消息行；只需满足 runtime 读取的字段。"""

    return SimpleNamespace(
        id=row_id,
        role=role,
        content=content,
        status="completed",
        tool_call_id=tool_call_id,
        content_blocks=None,
        message_metadata=None,
        created_at=datetime.now(UTC),
    )


def test_compaction_threshold_fires_before_guardrail_budget():
    """阈值取 min(window-reserve, ratio*window)：必须不晚于护栏硬截断预算。"""

    window = 1_000_000
    threshold = resolve_compaction_threshold(window)

    assert threshold == min(window - 16_384, int(window * 0.75))
    # 护栏预算（字符）换算成 token 后不得比压缩阈值更早触发。
    guardrail_budget_chars = int(window * 0.75 * 1.2)
    guardrail_budget_tokens = guardrail_budget_chars / 1.2
    assert threshold <= guardrail_budget_tokens


def test_compaction_threshold_zero_for_unknown_window():
    assert resolve_compaction_threshold(None) == 0
    assert resolve_compaction_threshold(0) == 0


def test_plan_compaction_cut_never_lands_on_tool_row():
    """切点向前回退到非 tool 行：工具调用与其结果绝不能被拆开。"""

    history = [
        _row(1, "user", "u" * 400),
        _row(2, "assistant", "a" * 400),
        _row(3, "user", "u" * 400),
        _row(4, "assistant", "a" * 400),
        _row(5, "tool", "t" * 400, tool_call_id="call_1"),
        _row(6, "assistant", "a" * 400),
        _row(7, "user", "u" * 400),
        _row(8, "assistant", "a" * 400),
    ]
    # keep_recent 取 1000 token，切点会落在第 4 行（tool）附近。
    cut = plan_compaction_cut(history, keep_recent_tokens=1000)

    assert cut is not None
    assert 0 < cut < len(history)
    assert history[cut].role != "tool"


def test_plan_compaction_cut_returns_none_when_history_too_small():
    history = [_row(1, "user", "短"), _row(2, "assistant", "短")]
    assert plan_compaction_cut(history, keep_recent_tokens=20_000) is None


def test_serialize_history_truncates_long_tool_results():
    rows = [
        _row(1, "user", "帮我读一下这个接口"),
        _row(2, "assistant", "好"),
        _row(3, "tool", "x" * 5_000, tool_call_id="call_1"),
    ]
    text = serialize_history_for_summary(rows)

    assert "[User]: 帮我读一下这个接口" in text
    assert "[Assistant]: 好" in text
    assert "[Tool result]: " in text
    assert "characters truncated]" in text
    assert "x" * 3_000 not in text


def test_summary_message_is_injected_first_and_compacted_rows_dropped():
    history = [
        _row(1, "user", "旧问题"),
        _row(2, "assistant", "旧回答"),
        _row(3, "user", "新问题"),
        _row(4, "assistant", "新回答"),
    ]
    compaction = SimpleNamespace(summary="早前讨论了旧问题", first_kept_message_id=3)

    messages, bindings = build_history_view(history, compaction=compaction)

    assert isinstance(messages[0], SystemMessage)
    assert COMPACTION_SUMMARY_TITLE in messages[0].content
    assert "早前讨论了旧问题" in messages[0].content
    assert [row_id for row_id, _ in bindings] == [3, 4]
    assert all(not isinstance(message, HumanMessage) or "旧问题" not in message.content
               for message in messages)


def test_guardrail_keeps_injected_summary_as_last_resort():
    """历史全被删也要保留摘要：它是被压缩历史的唯一载体。"""

    messages = [
        SystemMessage(content="系统提示"),
        SystemMessage(
            content=build_compaction_summary_message(
                SimpleNamespace(summary="关键结论一" * 200)
            ).content
        ),
        HumanMessage(content="旧" * 400),
        HumanMessage(content="中" * 400),
        HumanMessage(content="新" * 400),
    ]
    trimmed = apply_runtime_context_guardrail(messages, window_tokens=1_000)

    summary_messages = [
        message
        for message in trimmed
        if isinstance(message, SystemMessage)
        and str(message.content).startswith(COMPACTION_SUMMARY_TITLE)
    ]
    assert len(summary_messages) == 1
    assert trimmed[-1].content == "新" * 400


def test_compaction_outcome_projects_wire_and_rest_shapes():
    outcome = CompactionOutcome(
        compacted=True,
        reason="compacted",
        trigger="manual",
        tokens_before=100,
        tokens_after=20,
        window_tokens=1_000,
        used_tokens=20,
        percent=2.0,
        summary_chars=7,
    )

    payload = outcome.as_payload()
    assert payload["ok"] is True
    assert payload["tokensBefore"] == 100
    assert payload["tokensAfter"] == 20
    assert payload["windowTokens"] == 1_000
    assert payload["summaryChars"] == 7

    rest = outcome.as_rest()
    assert set(rest) == {
        "compacted",
        "reason",
        "trigger",
        "tokens_before",
        "tokens_after",
        "window_tokens",
        "used_tokens",
        "percent",
    }
    assert "tokensBefore" not in rest


def test_estimate_context_tokens_adds_baseline_and_trailing_chars():
    messages = [HumanMessage(content="a" * 120)]

    assert estimate_context_tokens(messages) == 100
    assert estimate_context_tokens(messages, baseline_usage=50) == 150


def test_controller_rebuilds_summary_and_keeps_request_suffix():
    """压缩后重建：摘要 + 保留历史 + 当前请求消息，顺序稳定。"""

    rows = [_row(1, "user", "旧"), _row(2, "assistant", "旧答"), _row(3, "user", "新")]
    history = build_model_history(rows)
    controller = ContextCompactionController(
        repo=None,
        conversation_id=1,
        model=None,
        history=history,
        window_tokens=1_000_000,
    )
    controller.compaction = SimpleNamespace(first_kept_message_id=3, summary=None)
    controller.summary_message = SystemMessage(
        content=f"{COMPACTION_SUMMARY_TITLE}\n\n旧摘要"
    )
    controller._history_ids.add(id(controller.summary_message))

    # 模拟 loop 的上下文：系统提示 + 历史视图 + 本次用户消息。
    current = HumanMessage(content="本次问题")
    rebuilt = asyncio.run(
        controller.transform([SystemMessage(content="系统提示"), *history.messages, current])
    )

    assert isinstance(rebuilt[0], SystemMessage)
    assert rebuilt[0].content == "系统提示"
    assert rebuilt[1].content.startswith(COMPACTION_SUMMARY_TITLE)
    assert rebuilt[-1] is current
    # first_kept_message_id=3 之前的行不再逐条回放（只剩第 3 行与当前消息）。
    human_texts = [
        message.content for message in rebuilt if isinstance(message, HumanMessage)
    ]
    assert human_texts == ["新", "本次问题"]


def test_controller_drain_events_reports_provider_truth_then_estimate():
    history = build_model_history([_row(1, "user", "你好")])
    controller = ContextCompactionController(
        repo=None,
        conversation_id=1,
        model=None,
        history=history,
        window_tokens=1_000,
    )
    messages = [SystemMessage(content="系统提示"), HumanMessage(content="你好"), AIMessage(content="答")]

    # 模型调用前：只吐压缩事件（这里没有），不产生占用上报。
    assert controller.drain_events(messages) == []

    events = controller.drain_events(
        messages, {"prompt_tokens": 700, "completion_tokens": 10, "total_tokens": 710}
    )
    assert [name for name, _ in events] == ["context_usage"]
    payload = events[0][1]
    assert payload["source"] == "provider"
    assert payload["usedTokens"] == 700
    assert payload["windowTokens"] == 1_000
    assert payload["percent"] == 70.0
    assert payload["lastCompactedAt"] is None

    # 供应商没给 prompt_tokens 时退回本地估算口径。
    events = controller.drain_events(messages, {"completion_tokens": 1})
    assert events[0][1]["source"] == "estimated"
    assert events[0][1]["usedTokens"] >= 1


def test_controller_reports_absolute_tokens_when_window_unknown():
    history = build_model_history([_row(1, "user", "你好")])
    controller = ContextCompactionController(
        repo=None,
        conversation_id=1,
        model=None,
        history=history,
        window_tokens=None,
    )
    messages = [SystemMessage(content="系统提示"), HumanMessage(content="你好")]
    events = controller.drain_events(messages, {"prompt_tokens": 42})

    assert events[0][1]["windowTokens"] is None
    assert events[0][1]["percent"] is None
    assert events[0][1]["usedTokens"] == 42


def test_summary_prompt_forbids_continuing_conversation():
    """提示词必须明确「不要继续对话」：否则摘要模型会输出对用户问题的回答。"""

    assert "不要继续对话" in COMPACTION_SUMMARY_SYSTEM_PROMPT
    assert "只输出" in COMPACTION_SUMMARY_SYSTEM_PROMPT
