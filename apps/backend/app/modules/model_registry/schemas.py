from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ModelType(str, Enum):
    """模型注册表支持的类型。"""

    CHAT = "chat"
    IMAGE_GENERATE = "image_generate"
    IMAGE_READ = "image_read"
    EMBEDDING = "embedding"


class BindingRole(str, Enum):
    """Agent 可绑定的能力角色，含对话主模型与三类辅助能力。"""

    CHAT = "chat"
    IMAGE_GENERATE = "image_generate"
    IMAGE_READ = "image_read"
    EMBEDDING = "embedding"


class PlatformModelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    model_type: ModelType
    model_name: str = Field(min_length=1, max_length=200)
    base_url: str | None = Field(default=None, max_length=500)
    api_key: str | None = Field(default=None, min_length=1)
    capabilities: dict[str, Any] | None = Field(
        default=None,
        description="模型能力矩阵：image/native_file/text_retrieval；生图模型可用 output: image",
    )
    options: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True


class PlatformModelUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    model_type: ModelType | None = None
    model_name: str | None = Field(default=None, min_length=1, max_length=200)
    base_url: str | None = Field(default=None, max_length=500)
    api_key: str | None = Field(default=None, min_length=1)
    capabilities: dict[str, Any] | None = None
    options: dict[str, Any] | None = None
    is_active: bool | None = None


class PlatformModelRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    platform_id: int
    name: str
    model_type: str
    model_name: str
    base_url: str | None = None
    capabilities: dict[str, Any] | None = None
    options: dict[str, Any]
    is_active: bool
    has_api_key: bool = False
    created_at: datetime
    updated_at: datetime


class PlatformModelListData(BaseModel):
    page_no: int
    page_size: int
    items: list[PlatformModelRead]
    total: int
    pages: int


class AgentModelBindingItem(BaseModel):
    """绑定列表项：能力角色与注册表模型摘要。"""

    model_config = ConfigDict(from_attributes=True)

    role: str
    model_id: int
    model_name: str
    model_type: str
    is_active: bool


class AgentModelBindingsRead(BaseModel):
    items: list[AgentModelBindingItem]


class AgentModelBindingUpdateItem(BaseModel):
    role: BindingRole
    model_id: int


class AgentModelBindingsUpdate(BaseModel):
    bindings: list[AgentModelBindingUpdateItem] = Field(default_factory=list)
