from __future__ import annotations

from datetime import datetime
from typing import Any
import json

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel, TimeModel
from app.modules.agent.services import decrypt_secret


class ToolConfirmation(BaseModel, TimeModel):
    """一条待用户确认的工具调用记录。

    为什么落库而不是只放在内存：确认卡可能跨请求/跨连接存活（用户离开页面再回来），
    需要 TTL 过期、会话内确认记忆查询与事后审计三类能力，都必须有一份持久记录。
    """

    __tablename__ = "tool_confirmations"
    __table_args__ = (
        CheckConstraint(
            "(user_id IS NOT NULL AND platform_end_user_id IS NULL) OR "
            "(user_id IS NULL AND platform_end_user_id IS NOT NULL)",
            name="ck_tool_confirmations_exactly_one_principal",
        ),
    )

    id: Mapped[int] = mapped_column(
        primary_key=True, autoincrement=True, comment="工具确认请求主键"
    )
    platform_id: Mapped[int] = mapped_column(
        ForeignKey("platforms.id", ondelete="CASCADE"),
        index=True,
        comment="确认请求所属平台 ID",
    )
    agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"),
        index=True,
        comment="发起确认的智能体 ID",
    )
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="确认所属会话 ID；无会话的运行（如无会话上下文）为空",
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("sys_users.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
        comment="后台用户 ID，与 Embed 最终用户互斥",
    )
    platform_end_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("platform_end_users.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
        comment="Embed 最终用户 ID，与后台用户互斥",
    )
    tool_name: Mapped[str] = mapped_column(
        String(120), nullable=False, comment="等待确认的工具名"
    )
    tool_type: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        comment="工具来源类型：builtin_tool / skill_script / mcp_tool",
    )
    side_effect: Mapped[str] = mapped_column(
        String(30), nullable=False, comment="工具副作用类型（规范五值）"
    )
    arguments_encrypted: Mapped[str] = mapped_column(
        Text, nullable=False, comment="加密保存的待执行工具参数"
    )
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="pending",
        server_default="pending",
        comment="确认请求状态：pending / approved / rejected / expired",
    )
    resolved_by: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
        comment="解决者：end_user / user / policy / timeout",
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="确认请求处理时间"
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, comment="确认请求过期时间"
    )

    @property
    def arguments(self) -> dict[str, Any]:
        return json.loads(decrypt_secret(self.arguments_encrypted))
