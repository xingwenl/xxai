import asyncio

from app.modules.agent_runtime.model_stream import ModelStreamAdapter


def test_model_stream_adapter_preserves_chunk_order():
    async def source():
        for chunk in ("a", "b", "c"):
            yield chunk

    received = []

    async def on_chunk(chunk):
        received.append(chunk)

    async def collect():
        await ModelStreamAdapter.collect(source, on_chunk)

    asyncio.run(collect())

    assert received == ["a", "b", "c"]
