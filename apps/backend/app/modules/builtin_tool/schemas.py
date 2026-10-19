from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.tools.side_effects import SideEffect


class BuiltinToolCatalogRead(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]
    # 规范五值：none/navigation/write/financial/external。
    # 此前写死 Literal["none"]，把「所有内置工具都无副作用」这个错误事实固化成契约。
    side_effect: SideEffect = "none"


class AgentBuiltinToolRead(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]
    side_effect: SideEffect = "none"
    is_enabled: bool


class AgentBuiltinToolUpdate(BaseModel):
    is_enabled: bool


class BuiltinToolOutcome(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    # rejected：需要用户确认但被拒绝（无人值守策略拒绝、用户拒绝、无确认通道）。
    # 它不是 failed——没有任何执行尝试，也没有发生错误。
    status: Literal["completed", "failed", "rejected"]
    result: Any
    # 不回填给模型、只带回落库链路的扩展信息（目前只有 delegate_tasks 用它回传
    # 派生子运行的 ID 列表）。内容来自 handler 结果里的保留键 ``_metadata``，
    # 该键在服务层被摘掉，因此模型看不到它。
    metadata: dict[str, Any] = Field(default_factory=dict)
