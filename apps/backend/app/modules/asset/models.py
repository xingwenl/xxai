from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel, TimeModel


class ConversationAsset(BaseModel, TimeModel):
    __tablename__ = "conversation_assets"
    __table_args__ = (
        UniqueConstraint("asset_id"),
        CheckConstraint(
            "(user_id IS NOT NULL AND platform_end_user_id IS NULL) OR "
            "(user_id IS NULL AND platform_end_user_id IS NOT NULL)",
            name="ck_conversation_assets_exactly_one_principal",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True, comment="会话资源内部主键"
    )
    asset_id: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True, comment="对外不可枚举的资源标识"
    )
    platform_id: Mapped[int] = mapped_column(
        ForeignKey("platforms.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="资源所属平台 ID",
    )
    agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="资源所属智能体 ID",
    )
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="资源所属会话 ID",
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("sys_users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="后台会话用户 ID，与 Embed 最终用户互斥",
    )
    platform_end_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("platform_end_users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="Embed 最终用户 ID，与后台用户互斥",
    )
    storage_key: Mapped[str] = mapped_column(
        String(1000), nullable=False, comment="相对平台存储根目录的文件定位键"
    )
    filename: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="经过安全化处理的下载文件名"
    )
    content_type: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="受控的资源媒体类型"
    )
    size_bytes: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="资源实际字节大小"
    )
    source_url: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="移除查询参数和片段后的来源地址"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="资源创建时间",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        comment="资源更新时间",
    )
