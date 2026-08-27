"""基本工具框架：能力原子、注册表与装饰器。

原则：
- 单一职责：一个文件只放一个基本工具，一个工具只做一件事。
- 零业务上下文：不知道 platform/agent/conversation/user，不落库、不鉴权。
- 输入即数据（url/base64/file/bytes/prompt），异常只抛稳定错误码。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

_ALLOWED_SIDE_EFFECTS = {"none", "create"}


class BasicToolError(Exception):
    """基本工具统一异常：code 为稳定错误码，message 仅用于日志。"""

    def __init__(self, code: str, message: str = "", *, status_code: int | None = None):
        super().__init__(code)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class BasicTool:
    name: str  # 注册键，命名空间形式：http.get / vision.describe
    description: str
    input_schema: dict[str, Any]  # JSON Schema，约束入参
    side_effect: str  # "none"（只读）| "create"（产生新数据）
    handler: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


BASIC_TOOL_REGISTRY: dict[str, BasicTool] = {}


def basic_tool(
    name: str,
    *,
    description: str,
    input_schema: dict[str, Any],
    side_effect: str = "none",
):
    """装饰器：定义与 handler 写在同一个文件，导入即注册。

    校验：side_effect 取值合法、工具名不重复，违反即在启动时报错（快速失败）。
    """

    if side_effect not in _ALLOWED_SIDE_EFFECTS:
        raise ValueError(f"basic tool {name}: invalid side_effect {side_effect!r}")
    if name in BASIC_TOOL_REGISTRY:
        raise ValueError(f"basic tool {name}: already registered")

    def decorator(handler):
        BASIC_TOOL_REGISTRY[name] = BasicTool(
            name=name,
            description=description,
            input_schema=input_schema,
            side_effect=side_effect,
            handler=handler,
        )
        return handler

    return decorator
