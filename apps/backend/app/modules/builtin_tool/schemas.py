from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class BuiltinToolCatalogRead(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]
    side_effect: Literal["none"] = "none"


class AgentBuiltinToolRead(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]
    side_effect: Literal["none"] = "none"
    is_enabled: bool


class AgentBuiltinToolUpdate(BaseModel):
    is_enabled: bool


class BuiltinToolOutcome(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    status: Literal["completed", "failed"]
    result: Any
    # 不回填给模型、只带回落库链路的扩展信息（目前只有 delegate_tasks 用它回传
    # 派生子运行的 ID 列表）。内容来自 handler 结果里的保留键 ``_metadata``，
    # 该键在服务层被摘掉，因此模型看不到它。
    metadata: dict[str, Any] = Field(default_factory=dict)
