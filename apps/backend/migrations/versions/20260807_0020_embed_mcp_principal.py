"""allow Embed principals in MCP audit and confirmation records"""

from alembic import op
import sqlalchemy as sa


revision = "20260807_0020"
down_revision = "20260807_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table_name in ("mcp_tool_call_audits", "mcp_tool_confirmations"):
        op.alter_column(table_name, "user_id", existing_type=sa.Integer(), nullable=True)
        op.add_column(
            table_name,
            sa.Column(
                "platform_end_user_id",
                sa.Integer(),
                nullable=True,
                comment="Embed 最终用户 ID，与后台用户互斥",
            ),
        )
        op.create_foreign_key(
            op.f(f"fk_{table_name}_platform_end_user_id_platform_end_users"),
            table_name,
            "platform_end_users",
            ["platform_end_user_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        op.create_index(
            op.f(f"ix_{table_name}_platform_end_user_id"),
            table_name,
            ["platform_end_user_id"],
        )
        op.create_check_constraint(
            f"ck_{table_name}_exactly_one_principal",
            table_name,
            "(user_id IS NOT NULL AND platform_end_user_id IS NULL) OR "
            "(user_id IS NULL AND platform_end_user_id IS NOT NULL)",
        )


def downgrade() -> None:
    for table_name in ("mcp_tool_confirmations", "mcp_tool_call_audits"):
        op.drop_constraint(
            f"ck_{table_name}_exactly_one_principal",
            table_name,
            type_="check",
        )
        op.drop_index(
            op.f(f"ix_{table_name}_platform_end_user_id"), table_name=table_name
        )
        op.drop_constraint(
            op.f(f"fk_{table_name}_platform_end_user_id_platform_end_users"),
            table_name,
            type_="foreignkey",
        )
        op.drop_column(table_name, "platform_end_user_id")
        op.alter_column(table_name, "user_id", existing_type=sa.Integer(), nullable=False)
