"""Agent 请求级运行上下文。"""

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(slots=True)
class AgentRuntimeContext:
    """一次 Agent 请求共享的只读配置与可变执行状态。

    数据库对象和协议对象通过 ``resources``/``metadata`` 注入，runtime 不依赖
    FastAPI 或具体 ORM 类型；后续可替换为更严格的资源接口而不改变调用入口。
    """

    agent: Any
    version: Any
    messages: list[Any] = field(default_factory=list)
    tools: list[Any] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    channel: Literal["rest", "embed"] = "rest"
    conversation_id: int | None = None
    request_id: str | None = None
    resources: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def copy_for_turn(self) -> "AgentRuntimeContext":
        """创建请求上下文的浅拷贝，避免 continuation 修改调用方容器。"""

        return AgentRuntimeContext(
            agent=self.agent,
            version=self.version,
            messages=list(self.messages),
            tools=list(self.tools),
            citations=list(self.citations),
            channel=self.channel,
            conversation_id=self.conversation_id,
            request_id=self.request_id,
            resources=dict(self.resources),
            metadata=dict(self.metadata),
        )
