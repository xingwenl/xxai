"""add model usage detail records

Revision ID: 20260730_0012
Revises: 20260729_0011
"""

from alembic import op
import sqlalchemy as sa

revision = "20260730_0012"
down_revision = "20260729_0011"
branch_labels = None
depends_on = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="记录创建时间",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="记录更新时间",
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "model_usage_records",
        sa.Column("id", sa.Integer(), primary_key=True, comment="模型用量明细主键"),
        sa.Column(
            "platform_id",
            sa.Integer(),
            sa.ForeignKey("platforms.id", ondelete="CASCADE"),
            nullable=False,
            comment="所属平台 ID",
        ),
        sa.Column(
            "agent_id",
            sa.Integer(),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
            comment="产生用量的智能体 ID",
        ),
        sa.Column(
            "agent_version_id",
            sa.Integer(),
            sa.ForeignKey("agent_versions.id", ondelete="SET NULL"),
            nullable=True,
            comment="产生用量的智能体版本 ID",
        ),
        sa.Column(
            "client_id",
            sa.String(80),
            nullable=True,
            comment="Embed Client 公开标识；后台会话为空",
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("sys_users.id", ondelete="SET NULL"),
            nullable=True,
            comment="后台用户 ID；Embed 会话为空",
        ),
        sa.Column(
            "platform_end_user_id",
            sa.Integer(),
            sa.ForeignKey("platform_end_users.id", ondelete="SET NULL"),
            nullable=True,
            comment="平台最终用户 ID；后台会话为空",
        ),
        sa.Column(
            "conversation_id",
            sa.Integer(),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
            comment="关联会话 ID",
        ),
        sa.Column(
            "message_id",
            sa.Integer(),
            sa.ForeignKey("conversation_messages.id", ondelete="SET NULL"),
            nullable=True,
            comment="关联助手消息 ID",
        ),
        sa.Column(
            "request_id",
            sa.String(128),
            nullable=True,
            comment="网关请求 ID",
        ),
        sa.Column("model_name", sa.String(120), nullable=True, comment="模型名称"),
        sa.Column(
            "prompt_tokens",
            sa.Integer(),
            server_default="0",
            nullable=False,
            comment="输入 token 数",
        ),
        sa.Column(
            "completion_tokens",
            sa.Integer(),
            server_default="0",
            nullable=False,
            comment="输出 token 数",
        ),
        sa.Column(
            "total_tokens",
            sa.Integer(),
            server_default="0",
            nullable=False,
            comment="总 token 数",
        ),
        *_timestamps(),
    )
    for column in (
        "platform_id",
        "agent_id",
        "agent_version_id",
        "client_id",
        "user_id",
        "platform_end_user_id",
        "conversation_id",
        "message_id",
        "request_id",
    ):
        op.create_index(
            op.f(f"ix_model_usage_records_{column}"),
            "model_usage_records",
            [column],
        )


def downgrade() -> None:
    for column in (
        "request_id",
        "message_id",
        "conversation_id",
        "platform_end_user_id",
        "user_id",
        "client_id",
        "agent_version_id",
        "agent_id",
        "platform_id",
    ):
        op.drop_index(
            op.f(f"ix_model_usage_records_{column}"),
            table_name="model_usage_records",
        )
    op.drop_table("model_usage_records")
