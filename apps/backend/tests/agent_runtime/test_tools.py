import asyncio

from app.modules.agent_runtime.contracts import ToolCall
from app.modules.agent_runtime.tools import CallbackToolExecutor, ToolDispatcher


class SearchExecutor:
    def supports(self, tool):
        return getattr(tool, "kind", None) == "search"

    async def execute(self, tool, call):
        from app.modules.agent_runtime.contracts import ToolOutcome

        return ToolOutcome(status="completed", result={"query": call.arguments["q"]})


def test_dispatcher_selects_registered_executor():
    dispatcher = ToolDispatcher([SearchExecutor()])
    tool = type("Tool", (), {"kind": "search"})()

    result = asyncio.run(
        dispatcher.execute(
            tool, ToolCall(id="1", name="search", arguments={"q": "python"})
        )
    )

    assert result.status == "completed"
    assert result.result == {"query": "python"}


def test_dispatcher_returns_stable_error_for_unknown_tool():
    result = asyncio.run(
        ToolDispatcher().execute(object(), ToolCall(id="1", name="unknown"))
    )

    assert result.status == "failed"
    assert result.error["code"] == "tool_executor_not_found"


def test_callback_executor_adapts_existing_callback():
    async def callback(*, tool, call):
        return type("Outcome", (), {"status": "completed", "result": call["args"]})()

    tool = type("Tool", (), {"name": "search"})()
    result = asyncio.run(
        CallbackToolExecutor(callback).execute(
            tool,
            ToolCall(id="1", name="search", arguments={"q": "x"}),
        )
    )

    assert result.status == "completed"
    assert result.result == {"q": "x"}


def test_callback_executor_preserves_dict_error_and_resume_fields():
    async def callback(*, tool, call):
        return {
            "status": "failed",
            "error": {"code": "upstream_failed"},
            "resume_token": "resume-1",
            "call_id": call["id"],
        }

    tool = type("Tool", (), {"name": "search"})()
    result = asyncio.run(
        CallbackToolExecutor(callback).execute(
            tool,
            ToolCall(id="call-1", name="search"),
        )
    )

    assert result.status == "failed"
    assert result.error == {"code": "upstream_failed"}
    assert result.resume_token == "resume-1"
    assert result.call_id == "call-1"
