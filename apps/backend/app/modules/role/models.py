from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.base_model import BaseModel, TimeModel

if TYPE_CHECKING:
    from app.modules.user.models import User


class Role(BaseModel, TimeModel):
    __tablename__ = "sys_roles"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    users: Mapped[list["User"]] = relationship(
        secondary="sys_user_roles",
        back_populates="roles",
        lazy="selectin",
    )


class UserRole(BaseModel):
    __tablename__ = "sys_user_roles"
    __table_args__ = (
        UniqueConstraint("user_id", "role_id", name="uq_sys_user_roles_user_id_role_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("sys_users.id", ondelete="CASCADE"), nullable=False, index=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("sys_roles.id", ondelete="RESTRICT"), nullable=False, index=True)
