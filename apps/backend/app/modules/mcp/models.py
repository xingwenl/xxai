from __future__ import annotations

from datetime import datetime
from typing import Any
import json

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.base_model import BaseModel, TimeModel
from app.modules.agent.services import decrypt_secret


class McpServer(BaseModel, TimeModel):
    __tablename__ = "mcp_servers"
    __table_args__ = (UniqueConstraint("platform_id", "slug"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    platform_id: Mapped[int] = mapped_column(
        ForeignKey("platforms.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    endpoint_url: Mapped[str] = mapped_column(String(2000), nullable=False)
    auth_headers_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )


class McpTool(BaseModel, TimeModel):
    __tablename__ = "mcp_tools"
    __table_args__ = (UniqueConstraint("server_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    server_id: Mapped[int] = mapped_column(
        ForeignKey("mcp_servers.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_schema: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    is_allowed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    side_effect: Mapped[str] = mapped_column(
        String(30), nullable=False, default="external", server_default="external"
    )


class AgentMcpServer(BaseModel, TimeModel):
    __tablename__ = "agent_mcp_servers"
    __table_args__ = (UniqueConstraint("agent_id", "server_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), index=True
    )
    server_id: Mapped[int] = mapped_column(
        ForeignKey("mcp_servers.id", ondelete="CASCADE"), index=True
    )
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )


class McpToolCallAudit(BaseModel):
    __tablename__ = "mcp_tool_call_audits"
    __table_args__ = (
        CheckConstraint(
            "(user_id IS NOT NULL AND platform_end_user_id IS NULL) OR "
            "(user_id IS NULL AND platform_end_user_id IS NOT NULL)",
            name="ck_mcp_tool_call_audits_exactly_one_principal",
        ),
    )

    id: Mapped[int] = mapped_column(
        primary_key=True, autoincrement=True, comment="MCP 工具调用审计主键"
    )
    platform_id: Mapped[int] = mapped_column(
        ForeignKey("platforms.id", ondelete="CASCADE"),
        index=True,
        comment="调用所属平台 ID",
    )
    agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"),
        index=True,
        comment="发起调用的智能体 ID",
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
    server_id: Mapped[int] = mapped_column(
        ForeignKey("mcp_servers.id", ondelete="RESTRICT"),
        comment="被调用的 MCP 服务 ID",
    )
    tool_id: Mapped[int] = mapped_column(
        ForeignKey("mcp_tools.id", ondelete="RESTRICT"),
        comment="被调用的 MCP 工具 ID",
    )
    tool_name: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="调用时的 MCP 工具名称"
    )
    arguments: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict, comment="脱敏后的工具调用参数"
    )
    status: Mapped[str] = mapped_column(
        String(40), nullable=False, comment="工具调用审计状态"
    )
    result: Mapped[Any | None] = mapped_column(
        JSON, nullable=True, comment="脱敏后的工具调用结果"
    )
    error: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="工具调用失败信息"
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, comment="工具调用开始时间"
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="工具调用结束时间"
    )


class McpToolConfirmation(BaseModel, TimeModel):
    __tablename__ = "mcp_tool_confirmations"
    __table_args__ = (
        CheckConstraint(
            "(user_id IS NOT NULL AND platform_end_user_id IS NULL) OR "
            "(user_id IS NULL AND platform_end_user_id IS NOT NULL)",
            name="ck_mcp_tool_confirmations_exactly_one_principal",
        ),
    )

    id: Mapped[int] = mapped_column(
        primary_key=True, autoincrement=True, comment="MCP 工具确认请求主键"
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
    tool_id: Mapped[int] = mapped_column(
        ForeignKey("mcp_tools.id", ondelete="RESTRICT"),
        comment="等待确认的 MCP 工具 ID",
    )
    audit_id: Mapped[int] = mapped_column(
        ForeignKey("mcp_tool_call_audits.id", ondelete="CASCADE"),
        unique=True,
        comment="关联的 MCP 工具调用审计 ID",
    )
    arguments_encrypted: Mapped[str] = mapped_column(
        Text, nullable=False, comment="加密保存的待执行工具参数"
    )
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="pending",
        server_default="pending",
        comment="确认请求状态",
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="确认请求处理时间"
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, comment="确认请求过期时间"
    )
    tool: Mapped[McpTool] = relationship(lazy="joined")

    @property
    def arguments(self) -> dict[str, Any]:
        return json.loads(decrypt_secret(self.arguments_encrypted))
