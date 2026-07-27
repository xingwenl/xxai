"""add embed clients and platform end users"""

from alembic import op
import sqlalchemy as sa

revision = "20260726_0009"
down_revision = "20260725_0008"
branch_labels = None
depends_on = None


def _timestamps() -> list[sa.Column]:
    return [
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
    ]


def upgrade() -> None:
    op.create_table(
        "platform_embed_clients",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "platform_id",
            sa.Integer(),
            sa.ForeignKey("platforms.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("client_id", sa.String(80), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("secret_hash", sa.String(255), nullable=False),
        sa.Column(
            "allowed_origins",
            sa.JSON(),
            server_default=sa.text("'[]'::json"),
            nullable=False,
        ),
        sa.Column(
            "token_ttl_seconds", sa.Integer(), server_default="600", nullable=False
        ),
        sa.Column(
            "is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column("max_tokens_per_minute", sa.Integer()),
        sa.Column("max_connections", sa.Integer()),
        *_timestamps(),
        sa.UniqueConstraint("client_id"),
        sa.CheckConstraint(
            "token_ttl_seconds BETWEEN 300 AND 900",
            name="ck_platform_embed_clients_token_ttl",
        ),
    )
    op.create_index(
        "ix_platform_embed_clients_platform_id",
        "platform_embed_clients",
        ["platform_id"],
    )
    op.create_index(
        "ix_platform_embed_clients_client_id", "platform_embed_clients", ["client_id"]
    )

    op.create_table(
        "platform_embed_client_agents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "client_id",
            sa.Integer(),
            sa.ForeignKey("platform_embed_clients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "agent_id",
            sa.Integer(),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.UniqueConstraint("client_id", "agent_id"),
    )
    op.create_index(
        "ix_platform_embed_client_agents_client_id",
        "platform_embed_client_agents",
        ["client_id"],
    )
    op.create_index(
        "ix_platform_embed_client_agents_agent_id",
        "platform_embed_client_agents",
        ["agent_id"],
    )

    op.create_table(
        "platform_end_users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "platform_id",
            sa.Integer(),
            sa.ForeignKey("platforms.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("external_user_id", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(120)),
        sa.Column(
            "is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        *_timestamps(),
        sa.UniqueConstraint("platform_id", "external_user_id"),
    )
    op.create_index(
        "ix_platform_end_users_platform_id", "platform_end_users", ["platform_id"]
    )

    op.add_column(
        "conversations", sa.Column("platform_end_user_id", sa.Integer(), nullable=True)
    )
    op.create_index(
        "ix_conversations_platform_end_user_id",
        "conversations",
        ["platform_end_user_id"],
    )
    op.create_foreign_key(
        "fk_conversations_platform_end_user_id_platform_end_users",
        "conversations",
        "platform_end_users",
        ["platform_end_user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.alter_column(
        "conversations", "user_id", existing_type=sa.Integer(), nullable=True
    )
    op.create_check_constraint(
        "ck_conversations_exactly_one_principal",
        "conversations",
        "(user_id IS NOT NULL AND platform_end_user_id IS NULL) OR "
        "(user_id IS NULL AND platform_end_user_id IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_conversations_exactly_one_principal", "conversations", type_="check"
    )
    op.drop_constraint(
        "fk_conversations_platform_end_user_id_platform_end_users",
        "conversations",
        type_="foreignkey",
    )
    op.drop_column("conversations", "platform_end_user_id")
    op.alter_column(
        "conversations", "user_id", existing_type=sa.Integer(), nullable=False
    )
    op.drop_index("ix_platform_end_users_platform_id", table_name="platform_end_users")
    op.drop_table("platform_end_users")
    op.drop_index(
        "ix_platform_embed_client_agents_agent_id",
        table_name="platform_embed_client_agents",
    )
    op.drop_index(
        "ix_platform_embed_client_agents_client_id",
        table_name="platform_embed_client_agents",
    )
    op.drop_table("platform_embed_client_agents")
    op.drop_index(
        "ix_platform_embed_clients_client_id", table_name="platform_embed_clients"
    )
    op.drop_index(
        "ix_platform_embed_clients_platform_id", table_name="platform_embed_clients"
    )
    op.drop_table("platform_embed_clients")
