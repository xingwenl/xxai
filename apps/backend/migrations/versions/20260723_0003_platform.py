"""create platforms and platform admins

Revision ID: 20260723_0003
Revises: 20260720_0002
"""

from alembic import op
import sqlalchemy as sa


revision = "20260723_0003"
down_revision = "20260720_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "platforms",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_platforms")),
    )
    op.create_index(op.f("ix_platforms_code"), "platforms", ["code"], unique=True)
    op.create_table(
        "platform_admins",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("platform_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["platform_id"], ["platforms.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["sys_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_platform_admins")),
        sa.UniqueConstraint("platform_id", "user_id", name="uq_platform_admins_platform_id"),
    )
    op.create_index(op.f("ix_platform_admins_platform_id"), "platform_admins", ["platform_id"])
    op.create_index(op.f("ix_platform_admins_user_id"), "platform_admins", ["user_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_platform_admins_user_id"), table_name="platform_admins")
    op.drop_index(op.f("ix_platform_admins_platform_id"), table_name="platform_admins")
    op.drop_table("platform_admins")
    op.drop_index(op.f("ix_platforms_code"), table_name="platforms")
    op.drop_table("platforms")
