"""Agent runtime 持久化接口。

运行循环只发布生命周期事件，不直接写数据库。conversation/gateway 可以分别
提供持久化 Adapter，但二者必须遵守同一套状态收敛约束。
"""

from dataclasses import dataclass, field
from typing import Protocol

from app.modules.agent_runtime.contracts import AgentEvent


class AgentRunPersistence(Protocol):
    """Agent 运行生命周期的持久化 Adapter。"""

    async def record(self, event: AgentEvent) -> None:
        """记录一个运行事件；实现方负责幂等和事务边界。"""


class NullAgentRunPersistence:
    """默认空实现，供不需要持久化的调用方和单元测试使用。"""

    async def record(self, event: AgentEvent) -> None:
        return None


@dataclass(slots=True)
class BufferedAgentRunPersistence:
    """请求级事件缓冲器。

    它不负责提交数据库，只负责按 request 顺序保存 runtime 事件并去重。正式
    Adapter 可以在请求结束时消费 ``events``，也可以在关键状态发生时增量落库。
    ``request_id`` 是幂等键，避免重放或重复回调造成重复状态变更。
    """

    request_id: str
    events: list[AgentEvent] = field(default_factory=list)
    sequences: list[int] = field(default_factory=list)
    _next_sequence: int = field(default=1, init=False)
    _seen: set[tuple[str, str | None]] = field(default_factory=set, init=False)

    async def record(self, event: AgentEvent) -> None:
        event.request_id = event.request_id or self.request_id
        event_id = event.payload.get("event_id")
        # 只有上游明确提供幂等键时才去重。message_delta 等流式事件通常
        # 没有 event_id；按类型去重会错误丢掉同一回答的后续增量。
        if event_id is not None:
            key = (str(event.type), str(event_id))
            if key in self._seen:
                return
            self._seen.add(key)
        # AgentEvent 保持协议无关；顺序单独保存，避免污染公开事件 payload。
        self.sequences.append(self._next_sequence)
        self._next_sequence += 1
        self.events.append(event)

    def snapshot(self) -> tuple[AgentEvent, ...]:
        """返回不可变快照，避免消费方遍历期间被后续事件修改。"""

        return tuple(self.events)
