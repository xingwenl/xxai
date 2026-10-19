"""新增运行检查点表 agent_loop_run_checkpoints

REST/SSE 通路里内置写工具要弹确认，并且确认解决后必须在**同一次运行内续跑**。
续跑需要「等待确认那一刻喂给模型的完整上下文」，而这份上下文无法从库里反推：
system prompt 现算不落库，assistant 的 tool_calls 消息与工具结果从不写
`conversation_messages`。这张表就是那份上下文的持久化载体：

- 一个运行最多一个待确认检查点（`loop_run_id` 唯一），解决入口即 `loop_run_id`；
- 按 `confirmation_source` 在 `tool_confirmations` / `mcp_tool_confirmations`
  之间分派，`confirmation_id` 因此不建外键；
- 状态机 pending → resolved → consumed，超时未处理由解决请求惰性判定为 expired；
- 续跑消费后清空 `context`，避免长期留存模型上下文。

设计取舍见 docs/adr/0010-run-confirmation-resume.md。

Revision ID: 20261019_0041
Revises: 20261019_0040
Create Date: 2026-10-19
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261019_0041"
down_revision: Union[str, None] = "20261019_0040"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_loop_run_checkpoints",
        sa.Column(
            "id",
            sa.BigInteger(),
            autoincrement=True,
            nullable=False,
            comment="运行检查点主键",
        ),
        sa.Column(
            "loop_run_id",
            sa.BigInteger(),
            nullable=False,
            comment="所属 AgentLoop 运行 ID；一个运行最多一个待确认检查点，故唯一",
        ),
        sa.Column(
            "conversation_id",
            sa.BigInteger(),
            nullable=False,
            comment="所属会话 ID，用于归属校验",
        ),
        sa.Column(
            "platform_id",
            sa.BigInteger(),
            nullable=False,
            comment="所属平台 ID",
        ),
        sa.Column(
            "agent_id",
            sa.BigInteger(),
            nullable=False,
            comment="发起本次运行的智能体 ID",
        ),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            nullable=True,
            comment="后台用户 ID，与 Embed 最终用户互斥",
        ),
        sa.Column(
            "platform_end_user_id",
            sa.BigInteger(),
            nullable=True,
            comment="Embed 最终用户 ID，与后台用户互斥",
        ),
        sa.Column(
            "confirmation_source",
            sa.String(length=40),
            nullable=False,
            comment="确认记录来源表：tool_confirmations 或 mcp_tool_confirmations",
        ),
        sa.Column(
            "confirmation_id",
            sa.BigInteger(),
            nullable=False,
            comment="跨两张确认表的确认记录 ID，不建外键，按 confirmation_source 分派",
        ),
        sa.Column(
            "tool_call_id",
            sa.String(length=255),
            nullable=False,
            comment="等待确认的模型工具调用 ID，续跑时回填结果",
        ),
        sa.Column(
            "tool_name",
            sa.String(length=120),
            nullable=False,
            comment="等待确认的工具名",
        ),
        sa.Column(
            "tool_type",
            sa.String(length=40),
            nullable=True,
            comment="工具来源类型：builtin_tool / skill_script / mcp_tool",
        ),
        sa.Column(
            "side_effect",
            sa.String(length=30),
            nullable=True,
            comment="工具副作用类型，用于 SSE 事件展示",
        ),
        sa.Column(
            "status",
            sa.String(length=30),
            server_default="pending",
            nullable=False,
            comment="检查点状态：pending / resolved / expired / consumed",
        ),
        sa.Column(
            "context",
            sa.JSON(),
            nullable=False,
            comment="等待确认那一刻喂给模型的完整上下文，续跑后清空",
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="检查点失效时间，超过后解决请求返回过期错误码",
        ),
        sa.Column(
            "resolved_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="确认被解决（批准或拒绝）的时间",
        ),
        sa.Column(
            "consumed_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="续跑消费检查点并清空上下文的时间",
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
            ["loop_run_id"],
            ["agent_loop_runs.id"],
            name=op.f("fk_agent_loop_run_checkpoints_loop_run_id_agent_loop_runs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name=op.f("fk_agent_loop_run_checkpoints_conversation_id_conversations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["platform_id"],
            ["platforms.id"],
            name=op.f("fk_agent_loop_run_checkpoints_platform_id_platforms"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f("fk_agent_loop_run_checkpoints_agent_id_agents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["sys_users.id"],
            name=op.f("fk_agent_loop_run_checkpoints_user_id_sys_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["platform_end_user_id"],
            ["platform_end_users.id"],
            # 命名约定展开后有 69 个字符，超过 PG 的 63 字符标识符上限；SQLAlchemy
            # 会截断并追加确定性摘要后缀，这里必须用同一个名字，否则 autogenerate
            # 会反复尝试重建这个外键（见 tests 里的元数据命名对照）。
            name="fk_agent_loop_run_checkpoints_platform_end_user_id_plat_54a1",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "(user_id IS NOT NULL AND platform_end_user_id IS NULL) OR "
            "(user_id IS NULL AND platform_end_user_id IS NOT NULL)",
            name="ck_agent_loop_run_checkpoints_exactly_one_principal",
        ),
        # loop_run_id 唯一：一个运行最多一个待确认检查点。用命名唯一约束而不是唯一
        # 索引，是为了和模型里 `unique=True` 声明出的实际元数据完全一致（PG 编译后
        # 是 CONSTRAINT uq_..._loop_run_id UNIQUE），否则 autogenerate 会漂移。
        sa.UniqueConstraint(
            "loop_run_id",
            name="uq_agent_loop_run_checkpoints_loop_run_id",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_loop_run_checkpoints")),
    )
    op.create_index(
        "ix_agent_loop_run_checkpoints_conversation_id",
        "agent_loop_run_checkpoints",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(
        "ix_agent_loop_run_checkpoints_platform_id",
        "agent_loop_run_checkpoints",
        ["platform_id"],
        unique=False,
    )
    op.create_index(
        "ix_agent_loop_run_checkpoints_agent_id",
        "agent_loop_run_checkpoints",
        ["agent_id"],
        unique=False,
    )
    op.create_index(
        "ix_agent_loop_run_checkpoints_user_id",
        "agent_loop_run_checkpoints",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_agent_loop_run_checkpoints_platform_end_user_id",
        "agent_loop_run_checkpoints",
        ["platform_end_user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_agent_loop_run_checkpoints_platform_end_user_id",
        table_name="agent_loop_run_checkpoints",
    )
    op.drop_index(
        "ix_agent_loop_run_checkpoints_user_id",
        table_name="agent_loop_run_checkpoints",
    )
    op.drop_index(
        "ix_agent_loop_run_checkpoints_agent_id",
        table_name="agent_loop_run_checkpoints",
    )
    op.drop_index(
        "ix_agent_loop_run_checkpoints_platform_id",
        table_name="agent_loop_run_checkpoints",
    )
    op.drop_index(
        "ix_agent_loop_run_checkpoints_conversation_id",
        table_name="agent_loop_run_checkpoints",
    )
    op.drop_table("agent_loop_run_checkpoints")
