"""旧 Graph 执行器接入 Agent runtime 的过渡桥接层。"""

from collections.abc import AsyncIterable, AsyncIterator
from typing import Any

from app.modules.agent_runtime.contracts import AgentEvent
from app.modules.agent_runtime.legacy_adapter import LegacyGraphEventAdapter
from app.modules.agent_runtime.adapters import agent_result_from_legacy


class LegacyGraphRuntimeBridge:
    """隐藏 legacy Graph 调用细节，只向 Gateway 暴露 AgentEvent 流。"""

    def __init__(self, event_adapter: LegacyGraphEventAdapter | None = None) -> None:
        self._event_adapter = event_adapter or LegacyGraphEventAdapter()

    async def stream(
        self,
        source: AsyncIterable[dict[str, Any]],
        *,
        request_id: str | None = None,
        conversation_id: int | None = None,
    ) -> AsyncIterator[AgentEvent]:
        """透传旧 Graph 事件，异常和取消原样传播给 Gateway。"""

        async for event in self._event_adapter.stream(
            source,
            request_id=request_id,
            conversation_id=conversation_id,
        ):
            if event.type == "completed" and "result" in event.payload:
                # 旧 Gateway 仍读取 result；统一结果另存于 agent_result，逐步
                # 迁移的调用方可先使用新字段，避免一次性改动收尾事务逻辑。
                event.payload.setdefault(
                    "agent_result", agent_result_from_legacy(event.payload["result"])
                )
            yield event
