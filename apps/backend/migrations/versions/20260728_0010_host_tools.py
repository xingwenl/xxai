"""add host tool policies and call audits"""

from alembic import op
import sqlalchemy as sa

revision = "20260728_0010"
down_revision = "20260726_0009"
branch_labels = None
depends_on = None


def _timestamps():
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "host_tool_policies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("platform_id", sa.Integer(), sa.ForeignKey("platforms.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.String(1000), nullable=False),
        sa.Column("input_schema", sa.JSON(), nullable=False),
        sa.Column("output_schema", sa.JSON()),
        sa.Column("schema_fingerprint", sa.String(64), nullable=False),
        sa.Column("side_effect", sa.String(30), server_default="external", nullable=False),
        sa.Column("confirmation_policy", sa.String(20), server_default="always", nullable=False),
        sa.Column("is_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("platform_id", "name"),
    )
    op.create_index("ix_host_tool_policies_platform_id", "host_tool_policies", ["platform_id"])

    op.create_table(
        "agent_host_tools",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tool_id", sa.Integer(), sa.ForeignKey("host_tool_policies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("agent_id", "tool_id"),
    )
    op.create_index("ix_agent_host_tools_agent_id", "agent_host_tools", ["agent_id"])
    op.create_index("ix_agent_host_tools_tool_id", "agent_host_tools", ["tool_id"])

    op.create_table(
        "embed_client_host_tools",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("platform_embed_clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tool_id", sa.Integer(), sa.ForeignKey("host_tool_policies.id", ondelete="CASCADE"), nullable=False),
        sa.UniqueConstraint("client_id", "tool_id"),
    )
    op.create_index("ix_embed_client_host_tools_client_id", "embed_client_host_tools", ["client_id"])
    op.create_index("ix_embed_client_host_tools_tool_id", "embed_client_host_tools", ["tool_id"])

    op.create_table(
        "host_tool_call_audits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("call_id", sa.String(128), nullable=False),
        sa.Column("platform_id", sa.Integer(), sa.ForeignKey("platforms.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("platform_end_user_id", sa.Integer(), sa.ForeignKey("platform_end_users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("conversations.id", ondelete="SET NULL")),
        sa.Column("request_id", sa.String(128)),
        sa.Column("tool_name", sa.String(128), nullable=False),
        sa.Column("arguments", sa.JSON(), nullable=False),
        sa.Column("arguments_fingerprint", sa.String(64), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("result", sa.JSON()),
        sa.Column("error", sa.Text()),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.UniqueConstraint("call_id"),
        sa.CheckConstraint(
            "status IN ('requested','awaiting_confirmation','running','succeeded','failed','rejected','expired')",
            name="ck_host_tool_call_status",
        ),
    )
    for index, column in (
        ("platform_id", "platform_id"),
        ("agent_id", "agent_id"),
        ("platform_end_user_id", "platform_end_user_id"),
        ("call_id", "call_id"),
    ):
        op.create_index(f"ix_host_tool_call_audits_{index}", "host_tool_call_audits", [column])


def downgrade() -> None:
    op.drop_table("host_tool_call_audits")
    op.drop_table("embed_client_host_tools")
    op.drop_table("agent_host_tools")
    op.drop_table("host_tool_policies")
