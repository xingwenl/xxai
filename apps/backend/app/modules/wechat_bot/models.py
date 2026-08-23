"""微信助手绑定数据模型。"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.base_model import BaseModel, TimeModel

if TYPE_CHECKING:
    from app.modules.agent.models import Agent
    from app.modules.platform.models import Platform
    from app.modules.user.models import User


class WeChatBotBinding(BaseModel, TimeModel):
    """后台用户与微信号的绑定关系（每个平台管理员最多绑定 1 个微信号）。"""

    __tablename__ = "wechat_bot_bindings"
    __table_args__ = (
        UniqueConstraint(
            "platform_id", "user_id", name="uq_wechat_bot_bindings_platform_user"
        ),
    )

    id: Mapped[int] = mapped_column(
        primary_key=True, autoincrement=True, comment="绑定记录主键"
    )
    platform_id: Mapped[int] = mapped_column(
        ForeignKey("platforms.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属平台 ID",
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("sys_users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="绑定的后台用户 ID",
    )
    agent_id: Mapped[int | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
        comment="对话使用的智能体 ID（空则用平台默认智能体）",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
        server_default="pending",
        comment="绑定状态：pending 待扫码 / active 已生效 / disabled 已停用 / expired 会话过期",
    )
    bot_token_encrypted: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="微信 bot_token（Fernet 加密存储，禁止明文）"
    )
    api_token_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="微信助手服务 token 的 sha256 哈希（chat 接口认证用）",
    )
    api_token_encrypted: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="微信助手服务 token 明文（Fernet 加密，worker 调 chat 接口用）",
    )
    ilink_bot_id: Mapped[str | None] = mapped_column(
        String(120), nullable=True, comment="iLink 机器人 ID"
    )
    ilink_user_id: Mapped[str | None] = mapped_column(
        String(120), nullable=True, comment="iLink 用户 ID（绑定微信号）"
    )
    qrcode: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="待扫码的二维码内容（仅 pending 阶段使用）"
    )
    qrcode_key: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="二维码轮询凭据（仅 pending 阶段使用）"
    )
    qrcode_base_url: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        comment="二维码轮询基址（IDC 重定向后更新，仅 pending 阶段使用）",
    )
    pending_verify_code: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
        comment="扫码配对码（need_verifycode 流程，用户从微信端读取后提交）",
    )
    last_error: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="最近一次错误信息（供后台展示）"
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="最近一次扫码确认时间"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
        comment="绑定是否启用（停用后 worker 停止该实例）",
    )
    platform: Mapped["Platform"] = relationship("Platform")
    user: Mapped["User"] = relationship("User")
    agent: Mapped["Agent | None"] = relationship("Agent")
