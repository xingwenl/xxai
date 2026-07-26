"""create agent knowledge bindings and conversations

Revision ID: 20260725_0008
Revises: 20260725_0007
"""

from alembic import op
import sqlalchemy as sa

revision = "20260725_0008"
down_revision = "20260725_0007"
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
        "agent_knowledge_bases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "agent_id",
            sa.Integer(),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "knowledge_base_id",
            sa.Integer(),
            sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "is_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        *_timestamps(),
        sa.UniqueConstraint(
            "agent_id",
            "knowledge_base_id",
            name="uq_agent_knowledge_bases_agent_id",
        ),
    )
    op.create_index(
        op.f("ix_agent_knowledge_bases_agent_id"),
        "agent_knowledge_bases",
        ["agent_id"],
    )
    op.create_index(
        op.f("ix_agent_knowledge_bases_knowledge_base_id"),
        "agent_knowledge_bases",
        ["knowledge_base_id"],
    )
    op.create_table(
        "conversations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "platform_id",
            sa.Integer(),
            sa.ForeignKey("platforms.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "agent_id",
            sa.Integer(),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("sys_users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(255)),
        sa.Column("status", sa.String(30), server_default="active", nullable=False),
        *_timestamps(),
    )
    for column in ("platform_id", "agent_id", "user_id"):
        op.create_index(op.f(f"ix_conversations_{column}"), "conversations", [column])
    op.create_table(
        "conversation_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.Integer(),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "citations", sa.JSON(), server_default=sa.text("'[]'::json"), nullable=False
        ),
        sa.Column(
            "knowledge_grounded",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("tool_call_id", sa.String(255)),
        *_timestamps(),
    )
    op.create_index(
        op.f("ix_conversation_messages_conversation_id"),
        "conversation_messages",
        ["conversation_id"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_conversation_messages_conversation_id"),
        table_name="conversation_messages",
    )
    op.drop_table("conversation_messages")
    for column in ("user_id", "agent_id", "platform_id"):
        op.drop_index(op.f(f"ix_conversations_{column}"), table_name="conversations")
    op.drop_table("conversations")
    op.drop_index(
        op.f("ix_agent_knowledge_bases_knowledge_base_id"),
        table_name="agent_knowledge_bases",
    )
    op.drop_index(
        op.f("ix_agent_knowledge_bases_agent_id"), table_name="agent_knowledge_bases"
    )
    op.drop_table("agent_knowledge_bases")
