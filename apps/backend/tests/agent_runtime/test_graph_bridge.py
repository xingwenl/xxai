import asyncio
from types import SimpleNamespace

from app.modules.agent_runtime.graph_bridge import LegacyGraphRuntimeBridge


def test_graph_bridge_adds_unified_result_without_removing_legacy_result():
    async def source():
        yield {
            "type": "completed",
            "result": SimpleNamespace(content="完成", usage={"total_tokens": 1}),
        }

    async def collect():
        return [event async for event in LegacyGraphRuntimeBridge().stream(source())]

    event = asyncio.run(collect())[0]

    assert event.payload["result"].content == "完成"
    assert event.payload["agent_result"].content == "完成"
    assert event.payload["agent_result"].usage == {"total_tokens": 1}
