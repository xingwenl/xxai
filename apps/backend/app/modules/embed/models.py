from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    JSON,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.base_model import BaseModel, TimeModel

if TYPE_CHECKING:
    from app.modules.platform.models import Platform


class PlatformEmbedClient(BaseModel, TimeModel):
    __tablename__ = "platform_embed_clients"
    __table_args__ = (
        UniqueConstraint("client_id"),
        CheckConstraint(
            "token_ttl_seconds BETWEEN 300 AND 900",
            name="ck_platform_embed_clients_token_ttl",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    platform_id: Mapped[int] = mapped_column(
        ForeignKey("platforms.id", ondelete="CASCADE"), nullable=False, index=True
    )
    client_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    secret_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    allowed_origins: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    token_ttl_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=600, server_default="600"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    max_tokens_per_minute: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_connections: Mapped[int | None] = mapped_column(Integer, nullable=True)

    platform: Mapped["Platform"] = relationship(
        "Platform", back_populates="embed_clients"
    )
    agent_bindings: Mapped[list["PlatformEmbedClientAgent"]] = relationship(
        back_populates="client", cascade="all, delete-orphan"
    )


class PlatformEmbedClientAgent(BaseModel):
    __tablename__ = "platform_embed_client_agents"
    __table_args__ = (UniqueConstraint("client_id", "agent_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("platform_embed_clients.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )

    client: Mapped[PlatformEmbedClient] = relationship(back_populates="agent_bindings")


class PlatformEndUser(BaseModel, TimeModel):
    __tablename__ = "platform_end_users"
    __table_args__ = (UniqueConstraint("platform_id", "external_user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    platform_id: Mapped[int] = mapped_column(
        ForeignKey("platforms.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    platform: Mapped["Platform"] = relationship("Platform", back_populates="end_users")
