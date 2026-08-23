"""add qr flow fields to wechat bot bindings

Revision ID: 20260823_0023
Revises: 20260823_0022
"""

from alembic import op
import sqlalchemy as sa

revision = "20260823_0023"
down_revision = "20260823_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "wechat_bot_bindings",
        sa.Column("qrcode_base_url", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "wechat_bot_bindings",
        sa.Column("pending_verify_code", sa.String(length=20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("wechat_bot_bindings", "pending_verify_code")
    op.drop_column("wechat_bot_bindings", "qrcode_base_url")
