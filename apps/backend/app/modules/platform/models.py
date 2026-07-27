from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.base_model import BaseModel, TimeModel

if TYPE_CHECKING:
    from app.modules.embed.models import PlatformEmbedClient, PlatformEndUser


class Platform(BaseModel, TimeModel):
    __tablename__ = "platforms"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    code: Mapped[str] = mapped_column(
        String(80), nullable=False, unique=True, index=True
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    admins: Mapped[list[PlatformAdmin]] = relationship(
        back_populates="platform", cascade="all, delete-orphan", lazy="selectin"
    )
    embed_clients: Mapped[list["PlatformEmbedClient"]] = relationship(
        "PlatformEmbedClient", back_populates="platform", cascade="all, delete-orphan"
    )
    end_users: Mapped[list["PlatformEndUser"]] = relationship(
        "PlatformEndUser", back_populates="platform", cascade="all, delete-orphan"
    )


class PlatformAdmin(BaseModel, TimeModel):
    __tablename__ = "platform_admins"
    __table_args__ = (UniqueConstraint("platform_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    platform_id: Mapped[int] = mapped_column(
        ForeignKey("platforms.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("sys_users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    platform: Mapped[Platform] = relationship(back_populates="admins")
