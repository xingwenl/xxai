"""新增工具确认表 tool_confirmations

交互式会话里的内置写工具需要弹确认卡：模型要求调用有副作用的工具时，平台先把
这次调用挂起，等用户点「同意 / 拒绝」后再决定是否真正执行。这张表就是那条挂起
记录的持久化载体，它同时支撑三件事：

- TTL：等待有上限（CONFIRMATION_TTL_SECONDS），过期未处理必须留下一条明确的
  「未执行」记录，而不是让请求无限等待或静默放行；
- 会话内确认记忆：同一会话里刚刚批准过的同类工具，后续调用直接复用这次批准；
- 审计：谁在什么时候批准或拒绝了哪个工具、参数是什么，都可回溯。

设计取舍见 docs/adr/0009-tool-approval-wiring.md。

Revision ID: 20261019_0040
Revises: 20261016_0039
Create Date: 2026-10-19
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261019_0040"
down_revision: Union[str, None] = "20261016_0039"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tool_confirmations",
        sa.Column(
            "id",
            sa.Integer(),
            autoincrement=True,
            nullable=False,
            comment="工具确认请求主键",
        ),
        sa.Column(
            "platform_id",
            sa.Integer(),
            nullable=False,
            comment="确认请求所属平台 ID",
        ),
        sa.Column(
            "agent_id", sa.Integer(), nullable=False, comment="发起确认的智能体 ID"
        ),
        sa.Column(
            "conversation_id",
            sa.Integer(),
            nullable=True,
            comment="确认所属会话 ID；无会话的运行（如无会话上下文）为空",
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            nullable=True,
            comment="后台用户 ID，与 Embed 最终用户互斥",
        ),
        sa.Column(
            "platform_end_user_id",
            sa.Integer(),
            nullable=True,
            comment="Embed 最终用户 ID，与后台用户互斥",
        ),
        sa.Column(
            "tool_name",
            sa.String(length=120),
            nullable=False,
            comment="等待确认的工具名",
        ),
        sa.Column(
            "tool_type",
            sa.String(length=30),
            nullable=False,
            comment="工具来源类型：builtin_tool / skill_script / mcp_tool",
        ),
        sa.Column(
            "side_effect",
            sa.String(length=30),
            nullable=False,
            comment="工具副作用类型（规范五值）",
        ),
        sa.Column(
            "arguments_encrypted",
            sa.Text(),
            nullable=False,
            comment="加密保存的待执行工具参数",
        ),
        sa.Column(
            "status",
            sa.String(length=30),
            server_default="pending",
            nullable=False,
            comment="确认请求状态：pending / approved / rejected / expired",
        ),
        sa.Column(
            "resolved_by",
            sa.String(length=20),
            nullable=True,
            comment="解决者：end_user / user / policy / timeout",
        ),
        sa.Column(
            "resolved_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="确认请求处理时间",
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="确认请求过期时间",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="记录创建时间（UTC）",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="记录最后更新时间（UTC）",
        ),
        sa.ForeignKeyConstraint(
            ["platform_id"],
            ["platforms.id"],
            name=op.f("fk_tool_confirmations_platform_id_platforms"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f("fk_tool_confirmations_agent_id_agents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name=op.f("fk_tool_confirmations_conversation_id_conversations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["sys_users.id"],
            name=op.f("fk_tool_confirmations_user_id_sys_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["platform_end_user_id"],
            ["platform_end_users.id"],
            name=op.f("fk_tool_confirmations_platform_end_user_id_platform_end_users"),
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "(user_id IS NOT NULL AND platform_end_user_id IS NULL) OR "
            "(user_id IS NULL AND platform_end_user_id IS NOT NULL)",
            name="ck_tool_confirmations_exactly_one_principal",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tool_confirmations")),
    )
    op.create_index(
        "ix_tool_confirmations_platform_id",
        "tool_confirmations",
        ["platform_id"],
        unique=False,
    )
    op.create_index(
        "ix_tool_confirmations_agent_id",
        "tool_confirmations",
        ["agent_id"],
        unique=False,
    )
    op.create_index(
        "ix_tool_confirmations_conversation_id",
        "tool_confirmations",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(
        "ix_tool_confirmations_user_id",
        "tool_confirmations",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_tool_confirmations_platform_end_user_id",
        "tool_confirmations",
        ["platform_end_user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_tool_confirmations_platform_end_user_id", table_name="tool_confirmations")
    op.drop_index("ix_tool_confirmations_user_id", table_name="tool_confirmations")
    op.drop_index("ix_tool_confirmations_conversation_id", table_name="tool_confirmations")
    op.drop_index("ix_tool_confirmations_agent_id", table_name="tool_confirmations")
    op.drop_index("ix_tool_confirmations_platform_id", table_name="tool_confirmations")
    op.drop_table("tool_confirmations")
