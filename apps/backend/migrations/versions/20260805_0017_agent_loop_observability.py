"""add agent loop observability and message content blocks"""

from alembic import op
import sqlalchemy as sa


revision = "20260805_0017"
down_revision = "20260804_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "conversation_messages",
        sa.Column("status", sa.String(30), server_default="completed", nullable=False, comment="消息状态"),
    )
    op.add_column(
        "conversation_messages",
        sa.Column("content_blocks", sa.JSON(), server_default=sa.text("'[]'::json"), nullable=False, comment="可渲染消息内容块数组"),
    )
    op.add_column(
        "conversation_messages",
        sa.Column("metadata", sa.JSON(), server_default=sa.text("'{}'::json"), nullable=False, comment="消息扩展元数据"),
    )

    op.create_table(
        "agent_loop_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, comment="AgentLoop 运行主键"),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, comment="所属会话 ID"),
        sa.Column("user_message_id", sa.Integer(), sa.ForeignKey("conversation_messages.id", ondelete="SET NULL"), nullable=True, comment="触发运行的用户消息 ID"),
        sa.Column("assistant_message_id", sa.Integer(), sa.ForeignKey("conversation_messages.id", ondelete="SET NULL"), nullable=True, comment="最终助手消息 ID"),
        sa.Column("request_id", sa.String(128), nullable=False, comment="前后端请求 ID"),
        sa.Column("status", sa.String(30), server_default="running", nullable=False, comment="运行状态"),
        sa.Column("summary", sa.Text(), nullable=True, comment="面向用户的安全过程摘要"),
        sa.Column("metadata", sa.JSON(), server_default=sa.text("'{}'::json"), nullable=False, comment="运行扩展元数据"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_agent_loop_runs_conversation_id", "agent_loop_runs", ["conversation_id"])
    op.create_index("ix_agent_loop_runs_request_id", "agent_loop_runs", ["request_id"])

    op.create_table(
        "agent_loop_steps",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, comment="AgentLoop 步骤主键"),
        sa.Column("loop_run_id", sa.Integer(), sa.ForeignKey("agent_loop_runs.id", ondelete="CASCADE"), nullable=False, comment="所属 AgentLoop 运行 ID"),
        sa.Column("sequence", sa.Integer(), nullable=False, comment="运行内步骤顺序"),
        sa.Column("step_type", sa.String(40), nullable=False, comment="步骤类型"),
        sa.Column("title", sa.String(255), nullable=False, comment="面向用户展示的步骤标题"),
        sa.Column("status", sa.String(30), server_default="queued", nullable=False, comment="步骤状态"),
        sa.Column("input_summary", sa.Text(), nullable=True, comment="脱敏后的输入摘要"),
        sa.Column("output_summary", sa.Text(), nullable=True, comment="脱敏后的输出摘要"),
        sa.Column("tool_name", sa.String(255), nullable=True, comment="工具名称"),
        sa.Column("skill_name", sa.String(255), nullable=True, comment="技能名称"),
        sa.Column("skill_version", sa.String(80), nullable=True, comment="技能版本"),
        sa.Column("tool_call_id", sa.String(255), nullable=True, comment="工具调用 ID"),
        sa.Column("citation_refs", sa.JSON(), server_default=sa.text("'[]'::json"), nullable=False, comment="关联知识库引用标识"),
        sa.Column("error", sa.JSON(), nullable=True, comment="错误码和脱敏错误摘要"),
        sa.Column("attempt", sa.Integer(), server_default="1", nullable=False, comment="步骤尝试次数"),
        sa.Column("parent_step_id", sa.Integer(), sa.ForeignKey("agent_loop_steps.id", ondelete="SET NULL"), nullable=True, comment="父步骤 ID"),
        sa.Column("metadata", sa.JSON(), server_default=sa.text("'{}'::json"), nullable=False, comment="步骤扩展元数据"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_agent_loop_steps_loop_run_id", "agent_loop_steps", ["loop_run_id"])
    op.create_index("ix_agent_loop_steps_parent_step_id", "agent_loop_steps", ["parent_step_id"])


def downgrade() -> None:
    op.drop_index("ix_agent_loop_steps_parent_step_id", table_name="agent_loop_steps")
    op.drop_index("ix_agent_loop_steps_loop_run_id", table_name="agent_loop_steps")
    op.drop_table("agent_loop_steps")
    op.drop_index("ix_agent_loop_runs_request_id", table_name="agent_loop_runs")
    op.drop_index("ix_agent_loop_runs_conversation_id", table_name="agent_loop_runs")
    op.drop_table("agent_loop_runs")
    op.drop_column("conversation_messages", "metadata")
    op.drop_column("conversation_messages", "content_blocks")
    op.drop_column("conversation_messages", "status")
