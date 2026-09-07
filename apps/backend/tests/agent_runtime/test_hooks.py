import asyncio

from app.modules.agent_runtime.hooks import (
    AgentRuntimeHooks,
    resolve_messages,
    transform_messages,
)


def test_hooks_normalize_sync_and_async_context_operations():
    async def messages():
        return ["follow-up"]

    async def transform(values):
        return [*values, "system-note"]

    result = asyncio.run(
        _resolve_and_transform(messages, transform, ["user-message"])
    )

    assert result == (["follow-up"], ["user-message", "system-note"])
    assert AgentRuntimeHooks(max_turns=3).max_turns == 3


async def _resolve_and_transform(messages, transform, values):
    return await resolve_messages(messages), await transform_messages(transform, values)
