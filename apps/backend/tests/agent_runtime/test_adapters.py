import asyncio

from app.modules.agent_runtime.contracts import ToolCall
from types import SimpleNamespace

from app.modules.agent_runtime.adapters import (
    invoke_legacy_tool,
    tool_call_from_legacy,
)


def test_tool_call_from_legacy_normalizes_call_shape():
    call = tool_call_from_legacy({"id": 42, "args": {"q": "python"}}, name="search")

    assert call.id == "42"
    assert call.name == "search"
    assert call.arguments == {"q": "python"}


def test_invoke_legacy_tool_normalizes_object_and_dict_results():
    async def callback(*, tool, call):
        return {"status": "failed", "error": {"code": "bad"}}

    result = asyncio.run(
        invoke_legacy_tool(
            callback,
            object(),
            tool_call_from_legacy({"id": "1", "args": {}}, name="test"),
        )
    )

    assert result.status == "failed"
    assert result.error == {"code": "bad"}


def test_invoke_legacy_tool_preserves_confirmation_and_audit_fields():
    async def callback(*, tool, call):
        return {
            "status": "confirmation_required",
            "audit_id": 11,
            "confirmation_id": 12,
        }

    result = asyncio.run(
        invoke_legacy_tool(
            callback, object(), ToolCall(id="1", name="approve")
        )
    )

    assert result.audit_id == 11
    assert result.confirmation_id == 12


def test_agent_result_from_legacy_preserves_graph_result_fields():
    from app.modules.agent_runtime.adapters import agent_result_from_legacy

    result = agent_result_from_legacy(
        SimpleNamespace(
            content="回答",
            citations=[{"title": "来源"}],
            tool_events=[{"tool": "search"}],
            usage={"total_tokens": 3},
            pending_confirmation_id=8,
        )
    )

    assert result.content == "回答"
    assert result.citations == [{"title": "来源"}]
    assert result.tool_events == [{"tool": "search"}]
    assert result.usage == {"total_tokens": 3}
    assert result.pending_confirmation_id == 8
