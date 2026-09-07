import asyncio
from types import SimpleNamespace

from app.modules.agent_runtime.composition import (
    build_runtime_tools,
    make_legacy_tool_invoker,
)
from app.modules.agent_runtime.contracts import ToolCall


def test_build_runtime_tools_keeps_order_and_filters_names():
    builtin = SimpleNamespace(name="builtin")
    mcp = SimpleNamespace(name="mcp")
    skill = SimpleNamespace(name="skill")
    hidden = SimpleNamespace(name="ask_user")

    assert build_runtime_tools(
        builtin_tools=[builtin, hidden],
        mcp_tools=[mcp],
        skill_script_tools=[skill],
        exclude_names={"ask_user"},
    ) == [builtin, mcp, skill]


def test_make_legacy_tool_invoker_preserves_typed_call_fields():
    tool = SimpleNamespace(name="calculate_total")
    received = {}

    async def callback(**kwargs):
        received.update(kwargs)
        return {"status": "completed", "result": 6}

    async def run():
        invoke = make_legacy_tool_invoker([tool], callback)
        return await invoke(
            ToolCall(
                id="call-1",
                name="calculate_total",
                arguments={"left": 3, "right": 3},
                metadata={"server_id": 7},
            )
        )

    outcome = asyncio.run(run())
    assert outcome.result == 6
    assert received["call"]["server_id"] == 7
    assert received["call"]["args"] == {"left": 3, "right": 3}
