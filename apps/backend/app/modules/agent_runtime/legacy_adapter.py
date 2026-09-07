"""旧 Graph 流到 Agent runtime 事件的兼容适配器。

现有 conversation 图执行器仍负责模型流、工具轮次和数据库收尾，暂时不能
直接替换。这个适配器只承担协议转换：把旧的字典事件转换为类型化事件，给
后续迁移提供稳定 seam，同时避免 gateway 继续散落转换细节。
"""

from collections.abc import AsyncIterable, AsyncIterator
from typing import Any

from app.modules.agent_runtime.contracts import AgentEvent
from app.modules.agent_runtime.event_adapters import event_from_legacy


class LegacyGraphEventAdapter:
    """将旧 Graph 事件流转换成 ``AgentEvent`` 流。

    适配器不修改事件内容、不吞异常，也不负责持久化；调用方仍然拥有旧图
    执行器的生命周期和事务边界。这样迁移失败时可以直接切回原调用方式。
    """

    async def stream(
        self,
        source: AsyncIterable[dict[str, Any]],
        *,
        request_id: str | None = None,
        conversation_id: int | None = None,
    ) -> AsyncIterator[AgentEvent]:
        """逐项转换旧事件，并补齐请求级关联字段。"""

        async for item in source:
            yield self.convert(
                item, request_id=request_id, conversation_id=conversation_id
            )

    @staticmethod
    def convert(
        item: dict[str, Any],
        *,
        request_id: str | None = None,
        conversation_id: int | None = None,
    ) -> AgentEvent:
        """转换单个事件，供已有 ``async for`` 主循环渐进接入。"""

        return event_from_legacy(
            item,
            request_id=request_id,
            conversation_id=conversation_id,
        )
