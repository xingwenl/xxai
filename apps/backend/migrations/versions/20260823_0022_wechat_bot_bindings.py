"""create wechat bot bindings

Revision ID: 20260823_0022
Revises: 20260813_0021
"""

from alembic import op
import sqlalchemy as sa

revision = "20260823_0022"
down_revision = "20260813_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "wechat_bot_bindings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("platform_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("agent_id", sa.Integer(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("bot_token_encrypted", sa.Text(), nullable=True),
        sa.Column("api_token_hash", sa.String(length=64), nullable=True),
        sa.Column("api_token_encrypted", sa.Text(), nullable=True),
        sa.Column("ilink_bot_id", sa.String(length=120), nullable=True),
        sa.Column("ilink_user_id", sa.String(length=120), nullable=True),
        sa.Column("qrcode", sa.Text(), nullable=True),
        sa.Column("qrcode_key", sa.String(length=255), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["platform_id"], ["platforms.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["sys_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_wechat_bot_bindings")),
        sa.UniqueConstraint(
            "platform_id",
            "user_id",
            name="uq_wechat_bot_bindings_platform_user",
        ),
    )
    op.create_index(
        op.f("ix_wechat_bot_bindings_platform_id"),
        "wechat_bot_bindings",
        ["platform_id"],
    )
    op.create_index(
        op.f("ix_wechat_bot_bindings_user_id"),
        "wechat_bot_bindings",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_wechat_bot_bindings_user_id"), table_name="wechat_bot_bindings")
    op.drop_index(
        op.f("ix_wechat_bot_bindings_platform_id"),
        table_name="wechat_bot_bindings",
    )
    op.drop_table("wechat_bot_bindings")
