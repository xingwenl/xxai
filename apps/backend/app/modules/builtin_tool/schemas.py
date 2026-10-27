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


class ToolGroupRead(BaseModel):
    """工具组清单条目：组名 + 展示信息 + 组内工具名。

    ``eager`` 表示该组每轮都绑定（不参与按需加载）；它来自运行期的
    ``EAGER_TOOL_GROUPS`` 与宿主兜底组，不是可以在管理台改的开关。
    """

    group: str
    title: str
    description: str
    eager: bool
    tool_names: list[str] = Field(default_factory=list)


class ToolGroupCatalogRead(BaseModel):
    """按组展示工具的目录：内置组与宿主组分开，组内工具名用于让前端建索引。

    不修改既有 ``BuiltinToolCatalogRead`` / ``AgentBuiltinToolRead``：那些响应已被
    前端与外部消费点依赖，分组信息通过这个独立接口增量提供。
    """

    builtin: list[ToolGroupRead] = Field(default_factory=list)
    host: list[ToolGroupRead] = Field(default_factory=list)


class AgentBuiltinToolUpdate(BaseModel):
    is_enabled: bool


class BuiltinToolOutcome(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    # rejected：需要用户确认但被拒绝（无人值守策略拒绝、用户拒绝、无确认通道）。
    # 它不是 failed——没有任何执行尝试，也没有发生错误。
    # confirmation_required：确认记录已落库、运行就此挂起，等解决端点续跑。
    status: Literal["completed", "failed", "rejected", "confirmation_required"]
    result: Any
    # 挂起等待确认时的确认记录主键。它随 outcome 一起被 conversation 层读取，
    # 用于把检查点与确认行关联起来（MCP 路径同样用它）。
    confirmation_id: int | None = None
    # 不回填给模型、只带回落库链路的扩展信息（目前只有 delegate_tasks 用它回传
    # 派生子运行的 ID 列表）。内容来自 handler 结果里的保留键 ``_metadata``，
    # 该键在服务层被摘掉，因此模型看不到它。
    metadata: dict[str, Any] = Field(default_factory=dict)
