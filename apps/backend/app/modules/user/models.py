from __future__ import annotations

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.modules.role.models import Role
from app.shared.base_model import BaseModel, TimeModel


class User(BaseModel, TimeModel):
    __tablename__ = "sys_users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    account: Mapped[str] = mapped_column(String(40), nullable=False, unique=True, index=True)
    password: Mapped[str] = mapped_column(String(60), nullable=False)
    roles: Mapped[list[Role]] = relationship(
        secondary="sys_user_roles",
        back_populates="users",
        lazy="selectin",
    )
