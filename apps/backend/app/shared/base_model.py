from __future__ import annotations

import re
from datetime import datetime

from sqlalchemy.orm import Mapped,DeclarativeBase, declared_attr,mapped_column
from sqlalchemy import MetaData, DateTime, func


NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def _camel_to_snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


class BaseModel(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    @declared_attr.directive
    def __tablename__(cls) -> str:
        return _camel_to_snake(cls.__name__)

class TimeModel:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )