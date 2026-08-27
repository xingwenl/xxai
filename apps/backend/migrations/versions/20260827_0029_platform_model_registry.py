"""平台模型注册表与 Agent 模型绑定

Revision ID: 20260827_0029
Revises: 20260827_0028
Create Date: 2026-08-27
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260827_0029"
down_revision: Union[str, None] = "20260827_0028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "platform_models",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("platform_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("model_type", sa.String(length=40), nullable=False),
        sa.Column("model_name", sa.String(length=200), nullable=False),
        sa.Column("base_url", sa.String(length=500), nullable=True),
        sa.Column("api_key_encrypted", sa.Text(), nullable=True),
        sa.Column("capabilities", sa.JSON(), nullable=True),
        sa.Column(
            "options",
            sa.JSON(),
            server_default=sa.text("'{}'::json"),
            nullable=False,
        ),
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
        sa.ForeignKeyConstraint(
            ["platform_id"], ["platforms.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_platform_models")),
        sa.UniqueConstraint(
            "platform_id",
            "model_type",
            "model_name",
            name="uq_platform_models_platform_id",
        ),
    )
    op.create_index(
        op.f("ix_platform_models_platform_id"), "platform_models", ["platform_id"]
    )
    op.create_index(
        op.f("ix_platform_models_model_type"), "platform_models", ["model_type"]
    )
    op.create_table(
        "agent_model_bindings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("agent_id", sa.Integer(), nullable=False),
        sa.Column("model_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=40), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["agent_id"], ["agents.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["model_id"], ["platform_models.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_model_bindings")),
        sa.UniqueConstraint(
            "agent_id", "role", name="uq_agent_model_bindings_agent_id"
        ),
    )
    op.create_index(
        op.f("ix_agent_model_bindings_agent_id"),
        "agent_model_bindings",
        ["agent_id"],
    )
    op.create_index(
        op.f("ix_agent_model_bindings_model_id"),
        "agent_model_bindings",
        ["model_id"],
    )
    op.create_index(
        op.f("ix_agent_model_bindings_role"),
        "agent_model_bindings",
        ["role"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_agent_model_bindings_role"), table_name="agent_model_bindings"
    )
    op.drop_index(
        op.f("ix_agent_model_bindings_model_id"),
        table_name="agent_model_bindings",
    )
    op.drop_index(
        op.f("ix_agent_model_bindings_agent_id"),
        table_name="agent_model_bindings",
    )
    op.drop_table("agent_model_bindings")
    op.drop_index(
        op.f("ix_platform_models_model_type"), table_name="platform_models"
    )
    op.drop_index(
        op.f("ix_platform_models_platform_id"), table_name="platform_models"
    )
    op.drop_table("platform_models")
