"""将 sys_users.password 列加宽到 160，以容纳 scrypt 密码哈希

Revision ID: 20260831_0031
Revises: 20260828_0030
Create Date: 2026-08-31
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260831_0031"
down_revision: Union[str, None] = "20260828_0030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """将 password 列从 varchar(60) 加宽到 varchar(160)，与 ORM 模型对齐。

    scrypt 哈希形如 scrypt$<salt>$<key>，长度约 118 字符，
    varchar(60) 会导致新用户创建时抛出 StringDataRightTruncationError。
    """
    op.alter_column(
        "sys_users",
        "password",
        existing_type=sa.String(length=60),
        type_=sa.String(length=160),
        existing_nullable=False,
    )


def downgrade() -> None:
    """回退：将 password 列恢复为 varchar(60)，仅用于回滚场景。"""
    op.alter_column(
        "sys_users",
        "password",
        existing_type=sa.String(length=160),
        type_=sa.String(length=60),
        existing_nullable=False,
    )
