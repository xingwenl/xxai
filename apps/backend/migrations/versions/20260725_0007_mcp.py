"""create remote MCP configuration, confirmations and audit logs

Revision ID: 20260725_0007
Revises: 20260723_0006
"""

from alembic import op
import sqlalchemy as sa

revision = "20260725_0007"
down_revision = "20260723_0006"
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
        "mcp_servers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "platform_id",
            sa.Integer(),
            sa.ForeignKey("platforms.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("slug", sa.String(80), nullable=False),
        sa.Column("endpoint_url", sa.String(2000), nullable=False),
        sa.Column("auth_headers_encrypted", sa.Text()),
        sa.Column(
            "is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        *_timestamps(),
        sa.UniqueConstraint("platform_id", "slug", name="uq_mcp_servers_platform_id"),
    )
    op.create_index(op.f("ix_mcp_servers_platform_id"), "mcp_servers", ["platform_id"])
    op.create_table(
        "mcp_tools",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "server_id",
            sa.Integer(),
            sa.ForeignKey("mcp_servers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column(
            "input_schema",
            sa.JSON(),
            server_default=sa.text("'{}'::json"),
            nullable=False,
        ),
        sa.Column(
            "is_allowed", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column(
            "side_effect", sa.String(30), server_default="external", nullable=False
        ),
        *_timestamps(),
        sa.UniqueConstraint("server_id", "name", name="uq_mcp_tools_server_id"),
    )
    op.create_index(op.f("ix_mcp_tools_server_id"), "mcp_tools", ["server_id"])
    op.create_table(
        "agent_mcp_servers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "agent_id",
            sa.Integer(),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "server_id",
            sa.Integer(),
            sa.ForeignKey("mcp_servers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "is_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        *_timestamps(),
        sa.UniqueConstraint(
            "agent_id", "server_id", name="uq_agent_mcp_servers_agent_id"
        ),
    )
    op.create_index(
        op.f("ix_agent_mcp_servers_agent_id"), "agent_mcp_servers", ["agent_id"]
    )
    op.create_index(
        op.f("ix_agent_mcp_servers_server_id"), "agent_mcp_servers", ["server_id"]
    )
    op.create_table(
        "mcp_tool_call_audits",
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
            sa.ForeignKey("sys_users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "server_id",
            sa.Integer(),
            sa.ForeignKey("mcp_servers.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "tool_id",
            sa.Integer(),
            sa.ForeignKey("mcp_tools.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("tool_name", sa.String(255), nullable=False),
        sa.Column(
            "arguments", sa.JSON(), server_default=sa.text("'{}'::json"), nullable=False
        ),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("result", sa.JSON()),
        sa.Column("error", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    for column in ("platform_id", "agent_id", "user_id"):
        op.create_index(
            op.f(f"ix_mcp_tool_call_audits_{column}"), "mcp_tool_call_audits", [column]
        )
    op.create_table(
        "mcp_tool_confirmations",
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
            sa.ForeignKey("sys_users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "tool_id",
            sa.Integer(),
            sa.ForeignKey("mcp_tools.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "audit_id",
            sa.Integer(),
            sa.ForeignKey("mcp_tool_call_audits.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("arguments_encrypted", sa.Text(), nullable=False),
        sa.Column("status", sa.String(30), server_default="pending", nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        *_timestamps(),
    )
    for column in ("platform_id", "agent_id", "user_id"):
        op.create_index(
            op.f(f"ix_mcp_tool_confirmations_{column}"),
            "mcp_tool_confirmations",
            [column],
        )


def downgrade() -> None:
    op.drop_table("mcp_tool_confirmations")
    op.drop_table("mcp_tool_call_audits")
    op.drop_table("agent_mcp_servers")
    op.drop_table("mcp_tools")
    op.drop_table("mcp_servers")
