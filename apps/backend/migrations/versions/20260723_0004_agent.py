"""create agents and immutable agent versions

Revision ID: 20260723_0004
Revises: 20260723_0003
"""

from alembic import op
import sqlalchemy as sa

revision = "20260723_0004"
down_revision = "20260723_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agents",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("platform_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column(
            "is_default", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("default_version_id", sa.Integer(), nullable=True),
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
        sa.ForeignKeyConstraint(["platform_id"], ["platforms.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agents")),
        sa.UniqueConstraint("platform_id", "slug", name="uq_agents_platform_id"),
    )
    op.create_index(op.f("ix_agents_platform_id"), "agents", ["platform_id"])
    op.create_table(
        "agent_versions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("agent_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column("model_name", sa.String(length=120), nullable=False),
        sa.Column("model_base_url", sa.String(length=500), nullable=True),
        sa.Column("api_key_encrypted", sa.Text(), nullable=True),
        sa.Column("temperature", sa.Float(), server_default="0.2", nullable=False),
        sa.Column(
            "model_options",
            sa.JSON(),
            server_default=sa.text("'{}'::json"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_versions")),
        sa.UniqueConstraint("agent_id", "version", name="uq_agent_versions_agent_id"),
    )
    op.create_index(op.f("ix_agent_versions_agent_id"), "agent_versions", ["agent_id"])
    op.create_foreign_key(
        op.f("fk_agents_default_version_id_agent_versions"),
        "agents",
        "agent_versions",
        ["default_version_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_agents_default_version_id_agent_versions"),
        "agents",
        type_="foreignkey",
    )
    op.drop_index(op.f("ix_agent_versions_agent_id"), table_name="agent_versions")
    op.drop_table("agent_versions")
    op.drop_index(op.f("ix_agents_platform_id"), table_name="agents")
    op.drop_table("agents")
