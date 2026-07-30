from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.base_model import BaseModel, TimeModel


class Agent(BaseModel, TimeModel):
    __tablename__ = "agents"
    __table_args__ = (UniqueConstraint("platform_id", "slug"),)

    id: Mapped[int] = mapped_column(
        primary_key=True, autoincrement=True, comment="智能体主键"
    )
    platform_id: Mapped[int] = mapped_column(
        ForeignKey("platforms.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属平台 ID",
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False, comment="智能体名称")
    slug: Mapped[str] = mapped_column(String(80), nullable=False, comment="智能体唯一标识")
    description: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="智能体描述")
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false", comment="是否为平台默认智能体"
    )
    default_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("agent_versions.id", ondelete="SET NULL", use_alter=True),
        nullable=True,
        comment="当前发布版本 ID",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
        comment="智能体是否启用",
    )
    versions: Mapped[list[AgentVersion]] = relationship(
        back_populates="agent",
        foreign_keys="AgentVersion.agent_id",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    default_version: Mapped[AgentVersion | None] = relationship(
        foreign_keys=[default_version_id], uselist=False, viewonly=True
    )


class AgentVersion(BaseModel):
    __tablename__ = "agent_versions"
    __table_args__ = (UniqueConstraint("agent_id", "version"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, comment="智能体版本主键")
    agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True, comment="所属智能体 ID"
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, comment="版本号")
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False, comment="系统提示词")
    model_name: Mapped[str] = mapped_column(String(120), nullable=False, comment="模型名称")
    model_base_url: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="模型服务地址")
    api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True, comment="加密后的模型 API Key")
    temperature: Mapped[float] = mapped_column(
        nullable=False, default=0.2, server_default="0.2", comment="模型采样温度"
    )
    model_options: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict, comment="模型额外配置"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, comment="版本创建时间"
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="版本发布时间"
    )
    agent: Mapped[Agent] = relationship(
        back_populates="versions", foreign_keys=[agent_id]
    )
