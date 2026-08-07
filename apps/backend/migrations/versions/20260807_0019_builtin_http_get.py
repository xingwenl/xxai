"""add builtin HTTP GET bindings and conversation assets"""

from alembic import op
import sqlalchemy as sa

revision = "20260807_0019"
down_revision = "20260806_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_builtin_tools",
        sa.Column(
            "id",
            sa.Integer(),
            autoincrement=True,
            nullable=False,
            comment="Agent 内置工具绑定主键",
        ),
        sa.Column(
            "platform_id", sa.Integer(), nullable=False, comment="绑定所属平台 ID"
        ),
        sa.Column(
            "agent_id", sa.Integer(), nullable=False, comment="绑定所属智能体 ID"
        ),
        sa.Column(
            "tool_name",
            sa.String(length=80),
            nullable=False,
            comment="代码注册表中的内置工具名称",
        ),
        sa.Column(
            "is_enabled",
            sa.Boolean(),
            server_default="true",
            nullable=False,
            comment="是否允许智能体加载并调用该工具",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="绑定创建时间",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="绑定更新时间",
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["platform_id"], ["platforms.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_id", "tool_name"),
    )
    op.create_index(
        op.f("ix_agent_builtin_tools_agent_id"), "agent_builtin_tools", ["agent_id"]
    )
    op.create_index(
        op.f("ix_agent_builtin_tools_platform_id"),
        "agent_builtin_tools",
        ["platform_id"],
    )

    op.create_table(
        "conversation_assets",
        sa.Column(
            "id",
            sa.Integer(),
            autoincrement=True,
            nullable=False,
            comment="会话资源内部主键",
        ),
        sa.Column(
            "asset_id",
            sa.String(length=64),
            nullable=False,
            comment="对外不可枚举的资源标识",
        ),
        sa.Column(
            "platform_id", sa.Integer(), nullable=False, comment="资源所属平台 ID"
        ),
        sa.Column(
            "agent_id", sa.Integer(), nullable=False, comment="资源所属智能体 ID"
        ),
        sa.Column(
            "conversation_id", sa.Integer(), nullable=False, comment="资源所属会话 ID"
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            nullable=True,
            comment="后台会话用户 ID，与 Embed 最终用户互斥",
        ),
        sa.Column(
            "platform_end_user_id",
            sa.Integer(),
            nullable=True,
            comment="Embed 最终用户 ID，与后台用户互斥",
        ),
        sa.Column(
            "storage_key",
            sa.String(length=1000),
            nullable=False,
            comment="相对平台存储根目录的文件定位键",
        ),
        sa.Column(
            "filename",
            sa.String(length=255),
            nullable=False,
            comment="经过安全化处理的下载文件名",
        ),
        sa.Column(
            "content_type",
            sa.String(length=255),
            nullable=False,
            comment="受控的资源媒体类型",
        ),
        sa.Column(
            "size_bytes", sa.Integer(), nullable=False, comment="资源实际字节大小"
        ),
        sa.Column(
            "source_url",
            sa.Text(),
            nullable=True,
            comment="移除查询参数和片段后的来源地址",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="资源创建时间",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="资源更新时间",
        ),
        sa.CheckConstraint(
            "(user_id IS NOT NULL AND platform_end_user_id IS NULL) OR "
            "(user_id IS NULL AND platform_end_user_id IS NOT NULL)",
            name=op.f(
                "ck_conversation_assets_ck_conversation_assets_exactly_one_principal"
            ),
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["platform_end_user_id"], ["platform_end_users.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["platform_id"], ["platforms.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["sys_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("asset_id"),
    )
    for column in (
        "agent_id",
        "asset_id",
        "conversation_id",
        "platform_end_user_id",
        "platform_id",
        "user_id",
    ):
        op.create_index(
            op.f(f"ix_conversation_assets_{column}"), "conversation_assets", [column]
        )


def downgrade() -> None:
    op.drop_table("conversation_assets")
    op.drop_table("agent_builtin_tools")
