from __future__ import annotations

from typing import Any

from sqlalchemy import (
    Boolean,
    ForeignKey,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.base_model import BaseModel, TimeModel


class PlatformModel(BaseModel, TimeModel):
    """平台级模型注册表，维护可供平台内 Agent 绑定的模型条目。"""

    __tablename__ = "platform_models"
    __table_args__ = (UniqueConstraint("platform_id", "model_type", "model_name"),)

    id: Mapped[int] = mapped_column(
        primary_key=True, autoincrement=True, comment="模型注册表主键"
    )
    platform_id: Mapped[int] = mapped_column(
        ForeignKey("platforms.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属平台 ID",
    )
    name: Mapped[str] = mapped_column(
        String(120), nullable=False, comment="模型显示名称（后台维护用）"
    )
    model_type: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        index=True,
        comment="模型类型：chat/image_generate/image_read/embedding",
    )
    model_name: Mapped[str] = mapped_column(
        String(200), nullable=False, comment="上游模型名，如 gpt-image-1"
    )
    base_url: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="模型服务地址，为空时使用官方默认地址"
    )
    api_key_encrypted: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="加密后的模型 API Key"
    )
    capabilities: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
        default=None,
        comment=(
            "模型能力矩阵（image/native_file/text_retrieval），"
            "生图模型额外使用 output: image 标记输出能力"
        ),
    )
    options: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict, comment="模型额外参数（超时、尺寸默认值等）"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
        comment="模型是否启用，停用后不再参与能力路由",
    )
    bindings: Mapped[list[AgentModelBinding]] = relationship(
        back_populates="model",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class AgentModelBinding(BaseModel, TimeModel):
    """Agent 与注册表模型的绑定关系，按能力角色唯一。"""

    __tablename__ = "agent_model_bindings"
    __table_args__ = (UniqueConstraint("agent_id", "role"),)

    id: Mapped[int] = mapped_column(
        primary_key=True, autoincrement=True, comment="Agent 模型绑定主键"
    )
    agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属智能体 ID",
    )
    model_id: Mapped[int] = mapped_column(
        ForeignKey("platform_models.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="绑定的注册表模型 ID",
    )
    role: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        index=True,
        comment="能力角色：image_generate/image_read/embedding",
    )
    model: Mapped[PlatformModel] = relationship(
        back_populates="bindings", lazy="selectin"
    )
