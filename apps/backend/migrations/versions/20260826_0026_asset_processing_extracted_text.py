"""conversation_asset_processing 增加 extracted_text 缓存列

Revision ID: 20260826_0026
Revises: 20260825_0025
Create Date: 2026-08-26
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260826_0026"
down_revision: Union[str, None] = "20260825_0025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "conversation_asset_processing",
        sa.Column(
            "extracted_text",
            sa.Text(),
            nullable=True,
            comment="解析后规范化文本全文缓存，模型上下文直接读取，避免重复读文件",
        ),
    )


def downgrade() -> None:
    op.drop_column("conversation_asset_processing", "extracted_text")
