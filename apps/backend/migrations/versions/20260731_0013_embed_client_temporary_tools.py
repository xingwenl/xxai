"""add temporary tool capability to embed clients

Revision ID: 20260731_0013
Revises: 20260730_0012
"""

from alembic import op
import sqlalchemy as sa

revision = "20260731_0013"
down_revision = "20260730_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "platform_embed_clients",
        sa.Column(
            "allow_temporary_tools",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
            comment="是否允许当前 Embed Client 注册仅存在于连接内存的临时工具",
        ),
    )


def downgrade() -> None:
    op.drop_column("platform_embed_clients", "allow_temporary_tools")
