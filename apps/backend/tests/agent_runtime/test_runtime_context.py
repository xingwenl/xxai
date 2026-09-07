"""AgentLoop 运行时混合上下文的上下文护栏回归。"""

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from app.modules.agent_runtime.contracts import ToolCall, ToolOutcome
from app.modules.agent_runtime.loop import ModelTurn
from app.modules.conversation.runtime import (
    apply_context_guardrail,
    apply_runtime_context_guardrail,
)


def _tool_call_ids(messages: list) -> set[str]:
    ids = set()
    for message in messages:
        for call in getattr(message, "tool_calls", []) or []:
            call_id = call.get("id") if isinstance(call, dict) else getattr(call, "id", None)
            if call_id:
                ids.add(call_id)
    return ids


def test_guardrail_does_not_orphan_tool_result_after_pruning():
    messages = [
        SystemMessage(content="系统提示"),
        HumanMessage(content="用户问题"),
        AIMessage(
            content="",
            tool_calls=[{"id": "c1", "name": "lookup", "args": {"q": "x"}}],
        ),
        ToolMessage(content="found", tool_call_id="c1"),
        HumanMessage(content="请继续"),
        AIMessage(content="最终回答"),
    ]

    pruned = apply_context_guardrail(
        messages,
        window_tokens=1,
        input_ratio=1.0,
        chars_per_token=1.0,
    )

    remaining_tool_calls = _tool_call_ids(pruned)
    for message in pruned:
        if isinstance(message, ToolMessage):
            assert message.tool_call_id in remaining_tool_calls, (
                "裁剪后工具结果与其 assistant 调用被拆散，会产生非法消息序列"
            )


def test_guardrail_keeps_runtime_tool_outcome_attached_to_assistant_call():
    messages = [
        SystemMessage(content="系统提示"),
        HumanMessage(content="用户问题"),
        HumanMessage(content="较早的历史问题"),
        AIMessage(content="较早的回答"),
        ModelTurn(
            content="",
            tool_calls=[ToolCall(id="c1", name="lookup", arguments={"q": "x"})],
        ),
        ToolOutcome(status="completed", result="found", call_id="c1"),
    ]

    pruned = apply_runtime_context_guardrail(
        messages,
        window_tokens=1,
        input_ratio=1.0,
        chars_per_token=1.0,
    )

    assistant_call_ids = {
        turn.tool_calls[0].id
        for turn in pruned
        if isinstance(turn, ModelTurn) and turn.tool_calls
    }
    for message in pruned:
        if isinstance(message, ToolOutcome):
            assert message.call_id in assistant_call_ids, (
                "裁剪后孤立工具结果仍会回填模型，破坏 assistant/tool 消息配对"
            )
    assert pruned[0].content == "系统提示"
    assert pruned[-1].call_id == "c1"
