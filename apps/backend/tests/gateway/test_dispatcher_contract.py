import asyncio

from app.modules.agent_runtime.contracts import ToolCall
from app.modules.gateway.dispatcher import RuntimeToolDispatcher


def test_dispatcher_accepts_typed_tool_call_and_keeps_missing_context_error():
    dispatcher = object.__new__(RuntimeToolDispatcher)
    dispatcher.mcp_tools_by_key = {}
    dispatcher.mcp_call_sequence = 0

    async def invoke():
        return await dispatcher.invoke(
            call=ToolCall(id="c1", name="missing", arguments={"q": "x"}),
        )

    try:
        asyncio.run(invoke())
    except ValueError as error:
        assert str(error) == "runtime tool context is missing"
    else:
        raise AssertionError("missing typed tool context should be rejected")
