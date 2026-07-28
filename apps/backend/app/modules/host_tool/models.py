from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel, TimeModel


class HostToolPolicy(BaseModel, TimeModel):
    __tablename__ = "host_tool_policies"
    __table_args__ = (UniqueConstraint("platform_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    platform_id: Mapped[int] = mapped_column(
        ForeignKey("platforms.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(String(1000), nullable=False)
    input_schema: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    output_schema: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    schema_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    side_effect: Mapped[str] = mapped_column(
        String(30), nullable=False, default="external"
    )
    confirmation_policy: Mapped[str] = mapped_column(
        String(20), nullable=False, default="always"
    )
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )


class AgentHostTool(BaseModel, TimeModel):
    __tablename__ = "agent_host_tools"
    __table_args__ = (UniqueConstraint("agent_id", "tool_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), index=True
    )
    tool_id: Mapped[int] = mapped_column(
        ForeignKey("host_tool_policies.id", ondelete="CASCADE"), index=True
    )
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )


class EmbedClientHostTool(BaseModel):
    __tablename__ = "embed_client_host_tools"
    __table_args__ = (UniqueConstraint("client_id", "tool_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("platform_embed_clients.id", ondelete="CASCADE"), index=True
    )
    tool_id: Mapped[int] = mapped_column(
        ForeignKey("host_tool_policies.id", ondelete="CASCADE"), index=True
    )


class HostToolCallAudit(BaseModel):
    __tablename__ = "host_tool_call_audits"
    __table_args__ = (
        UniqueConstraint("call_id"),
        CheckConstraint(
            "status IN ('requested','awaiting_confirmation','running','succeeded','failed','rejected','expired')",
            name="ck_host_tool_call_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    call_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    platform_id: Mapped[int] = mapped_column(
        ForeignKey("platforms.id", ondelete="CASCADE"), index=True
    )
    agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), index=True
    )
    platform_end_user_id: Mapped[int] = mapped_column(
        ForeignKey("platform_end_users.id", ondelete="RESTRICT"), index=True
    )
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
    )
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    arguments: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    arguments_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    result: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
