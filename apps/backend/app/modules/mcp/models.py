from __future__ import annotations

from datetime import datetime
from typing import Any
import json

from sqlalchemy import (
    Boolean,
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

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    platform_id: Mapped[int] = mapped_column(
        ForeignKey("platforms.id", ondelete="CASCADE"), index=True
    )
    agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("sys_users.id", ondelete="RESTRICT"), index=True
    )
    server_id: Mapped[int] = mapped_column(
        ForeignKey("mcp_servers.id", ondelete="RESTRICT")
    )
    tool_id: Mapped[int] = mapped_column(
        ForeignKey("mcp_tools.id", ondelete="RESTRICT")
    )
    tool_name: Mapped[str] = mapped_column(String(255), nullable=False)
    arguments: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    result: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class McpToolConfirmation(BaseModel, TimeModel):
    __tablename__ = "mcp_tool_confirmations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    platform_id: Mapped[int] = mapped_column(
        ForeignKey("platforms.id", ondelete="CASCADE"), index=True
    )
    agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("sys_users.id", ondelete="RESTRICT"), index=True
    )
    tool_id: Mapped[int] = mapped_column(
        ForeignKey("mcp_tools.id", ondelete="RESTRICT")
    )
    audit_id: Mapped[int] = mapped_column(
        ForeignKey("mcp_tool_call_audits.id", ondelete="CASCADE"), unique=True
    )
    arguments_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="pending", server_default="pending"
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    tool: Mapped[McpTool] = relationship(lazy="joined")

    @property
    def arguments(self) -> dict[str, Any]:
        return json.loads(decrypt_secret(self.arguments_encrypted))
