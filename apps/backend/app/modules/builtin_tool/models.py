from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel, TimeModel


class AgentBuiltinTool(BaseModel, TimeModel):
    __tablename__ = "agent_builtin_tools"
    __table_args__ = (UniqueConstraint("agent_id", "tool_name"),)

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True, comment="Agent 内置工具绑定主键"
    )
    platform_id: Mapped[int] = mapped_column(
        ForeignKey("platforms.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="绑定所属平台 ID",
    )
    agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="绑定所属智能体 ID",
    )
    tool_name: Mapped[str] = mapped_column(
        String(80), nullable=False, comment="代码注册表中的内置工具名称"
    )
    is_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
        comment="是否允许智能体加载并调用该工具",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="绑定创建时间",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        comment="绑定更新时间",
    )
