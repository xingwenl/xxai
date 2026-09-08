"""Agent loop 的显式扩展点。

参考 Pi 的设计，这些钩子属于 runtime 配置，而不是协议层或工具 Adapter 的
隐式副作用。这样上下文压缩、继续执行和停止策略可以独立测试。
"""

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.modules.agent_runtime.contracts import AgentEvent

ContextTransformer = Callable[[list[Any]], Awaitable[list[Any]] | list[Any]]
TurnPredicate = Callable[[dict[str, Any]], Awaitable[bool] | bool]
MessageProvider = Callable[[], Awaitable[Sequence[Any]] | Sequence[Any]]
# 模型调用失败后的上下文恢复策略：给定抛出的异常与本次尝试的消息列表，
# 返回用于降级重试一次的新消息（如“仅保留系统提示 + 当前用户消息”），
# 返回 None 表示不重试、让错误原样向上传播。恢复只执行一次，避免死循环。
ModelErrorRecoverer = Callable[
    [BaseException, list[Any]], Awaitable[list[Any] | None] | list[Any] | None
]


@dataclass(slots=True)
class AgentRuntimeHooks:
    """一次 Agent 请求可选的生命周期钩子。"""

    transform_context: ContextTransformer | None = None
    should_stop_after_turn: TurnPredicate | None = None
    get_steering_messages: MessageProvider | None = None
    get_follow_up_messages: MessageProvider | None = None
    on_event: Callable[[AgentEvent], Awaitable[None] | None] | None = None
    max_turns: int | None = None
    on_model_error: ModelErrorRecoverer | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


async def resolve_messages(provider: MessageProvider | None) -> list[Any]:
    """读取可选消息提供器并归一化为列表。"""

    if provider is None:
        return []
    messages = provider()
    if hasattr(messages, "__await__"):
        messages = await messages
    return list(messages)


async def transform_messages(
    transformer: ContextTransformer | None,
    messages: list[Any],
) -> list[Any]:
    """执行上下文变换，并确保下游拿到独立列表。"""

    if transformer is None:
        return list(messages)
    transformed = transformer(list(messages))
    if hasattr(transformed, "__await__"):
        transformed = await transformed
    return list(transformed)
