"""add agent active state

Revision ID: 20260729_0011
Revises: 20260728_0010
"""

from alembic import op
import sqlalchemy as sa

revision = "20260729_0011"
down_revision = "20260728_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
            comment="智能体是否启用",
        ),
    )


def downgrade() -> None:
    op.drop_column("agents", "is_active")
