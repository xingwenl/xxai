from __future__ import annotations

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel, TimeModel


class User(BaseModel, TimeModel):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
