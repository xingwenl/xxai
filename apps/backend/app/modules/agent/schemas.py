from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    slug: str = Field(min_length=2, max_length=80, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    description: str | None = Field(default=None, max_length=500)


class AgentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    platform_id: int
    name: str
    slug: str
    description: str | None = None
    is_default: bool = False
    is_active: bool = True
    default_version_id: int | None = None
    orchestration_workflow_id: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AgentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    slug: str | None = Field(
        default=None, min_length=2, max_length=80, pattern=r"^[a-z0-9][a-z0-9_-]*$"
    )
    description: str | None = Field(default=None, max_length=500)
    is_active: bool | None = None
    orchestration_workflow_id: int | None = Field(
        default=None,
        description=(
            "绑定的编排工作流 ID：非空时该 Agent 每轮消息由这条工作流接管编排；"
            "显式传 null 表示解绑，字段不传表示不改动"
        ),
    )


class AgentListData(BaseModel):
    page_no: int
    page_size: int
    items: list[AgentRead]
    total: int
    pages: int


class AgentVersionCreate(BaseModel):
    system_prompt: str = Field(min_length=1)
    temperature: float = Field(default=0.2, ge=0, le=2)
    model_options: dict[str, Any] = Field(default_factory=dict)
    context_window_tokens: int | None = Field(
        default=None,
        ge=1024,
        description="模型上下文窗口（token）；不传时按模型名映射推断或禁用护栏",
    )
    capabilities: dict[str, Any] | None = Field(
        default=None,
        description=(
            "模型附件能力配置，至少包含 image/native_file/text_retrieval "
            "三项布尔能力；不传时按 OpenRouter input_modalities 自动探测"
        ),
    )


class AgentVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    agent_id: int
    version: int
    system_prompt: str
    temperature: float
    model_options: dict[str, Any]
    context_window_tokens: int | None = None
    capabilities: dict[str, Any] | None = None
    created_at: datetime
    published_at: datetime | None = None


class AgentDetailRead(AgentRead):
    current_version: AgentVersionRead | None = None


class AgentSubagentRead(BaseModel):
    """配置页里的一条「已绑定子智能体」。

    ``published``/``active`` 是读时计算的状态而非绑定字段：绑定不会因为子 Agent
    取消发布而消失，但界面必须提示「这条绑定当前派不出去」。
    """

    child_agent_id: int
    slug: str
    name: str
    description: str | None = None
    enabled: bool
    sort_order: int
    published: bool
    active: bool


class AgentSubagentCandidate(BaseModel):
    """可添加到绑定列表的候选（本平台已发布启用、尚未绑定）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    name: str
    description: str | None = None


class AgentSubagentListData(BaseModel):
    items: list[AgentSubagentRead]
    # 没有任何绑定时为 True：运行期回退「全平台已发布智能体（排除自己）」。
    fallback: bool
    available: list[AgentSubagentCandidate] = Field(default_factory=list)


class AgentSubagentItemInput(BaseModel):
    child_agent_id: int
    enabled: bool = True


class AgentSubagentReplace(BaseModel):
    """整表替换：数组顺序即展示/提示清单顺序，空数组表示清空绑定。"""

    items: list[AgentSubagentItemInput] = Field(default_factory=list, max_length=50)
