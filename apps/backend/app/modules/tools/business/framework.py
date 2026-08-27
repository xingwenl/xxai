"""业务工具框架：业务上下文、注册表与装饰器。

职责边界：业务工具只做来源解析、鉴权、持久化、Agent 模型绑定解析与结果包装；
能力实现一律委托给基本工具。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any


class BusinessToolError(Exception):
    """业务工具统一异常：code 为 LLM 稳定错误码，status_code 可选透传。"""

    def __init__(self, code: str, message: str = "", *, status_code: int | None = None):
        super().__init__(code)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class BusinessToolContext:
    """基本工具不该知道的东西都放这里。"""

    platform_id: int
    agent_id: int
    conversation_id: int
    user_id: int | None = None
    platform_end_user_id: int | None = None
    session: Any | None = None  # DB 会话：查 asset / 模型绑定
    asset_repo: Any | None = None


@dataclass(frozen=True)
class BusinessTool:
    name: str  # LLM 看到的工具名
    description: str
    input_schema: dict[str, Any]  # LLM 看到的输入契约（业务化输入）
    handler: Callable[[dict[str, Any], BusinessToolContext], Awaitable[dict[str, Any]]]
    depends_on: tuple[str, ...] = ()  # 依赖的基本工具注册键


BUSINESS_TOOL_REGISTRY: dict[str, BusinessTool] = {}


def business_tool(
    name: str,
    *,
    description: str,
    input_schema: dict[str, Any],
    depends_on: tuple[str, ...] = (),
):
    """装饰器：定义与 handler 写在同一个文件，导入即注册。"""

    if name in BUSINESS_TOOL_REGISTRY:
        raise ValueError(f"business tool {name}: already registered")

    def decorator(handler):
        BUSINESS_TOOL_REGISTRY[name] = BusinessTool(
            name=name,
            description=description,
            input_schema=input_schema,
            handler=handler,
            depends_on=depends_on,
        )
        return handler

    return decorator


def validate_business_tool_dependencies(basic_resolver) -> list[str]:
    """启动校验：业务工具声明的依赖必须已在基本注册表中，返回缺失列表。"""

    missing: list[str] = []
    for tool in BUSINESS_TOOL_REGISTRY.values():
        for dependency in tool.depends_on:
            if basic_resolver(dependency) is None:
                missing.append(f"{tool.name} -> {dependency}")
    return missing
