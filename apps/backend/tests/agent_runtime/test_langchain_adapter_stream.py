import asyncio

from langchain_core.messages import AIMessageChunk

from app.modules.agent_runtime.contracts import AgentEventType
from app.modules.agent_runtime.langchain_adapter import LangChainModelInvoker


def test_langchain_model_invoker_streams_message_deltas():
    class Model:
        async def astream(self, messages):
            yield AIMessageChunk(content="你好")
            yield AIMessageChunk(content="世界")

    events = []

    async def emit(event):
        events.append(event)

    async def run():
        return await LangChainModelInvoker(Model(), streaming=True)([], emit=emit)

    turn = asyncio.run(run())

    assert turn.content == "你好世界"
    assert [event.type for event in events] == [
        AgentEventType.MESSAGE_DELTA,
        AgentEventType.MESSAGE_DELTA,
    ]
