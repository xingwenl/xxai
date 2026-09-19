"""新增任务定义与任务运行两张表

Revision ID: 20260919_0034
Revises: 20260903_0033
Create Date: 2026-09-19
"""

import sqlalchemy as sa
from alembic import op

revision: str = "20260919_0034"
down_revision: str = "20260903_0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """建立任务（tasks）与任务运行（task_runs）两张表及其索引。"""
    op.create_table(
        "tasks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="任务主键"),
        sa.Column("platform_id", sa.Integer(), nullable=False, comment="任务所属平台 ID"),
        sa.Column("agent_id", sa.Integer(), nullable=False, comment="任务执行时使用的智能体 ID"),
        sa.Column(
            "owner_user_id",
            sa.Integer(),
            nullable=True,
            comment="任务归属用户 ID；为空表示平台级任务（仅平台管理员可管理）",
        ),
        sa.Column("name", sa.String(length=200), nullable=False, comment="任务名称，用于列表展示"),
        sa.Column("prompt", sa.Text(), nullable=False, comment="到点后发给智能体的指令内容"),
        sa.Column(
            "model_id",
            sa.Integer(),
            nullable=True,
            comment="可选：覆盖智能体默认模型；为空时沿用智能体自身配置",
        ),
        sa.Column(
            "trigger_type",
            sa.String(length=20),
            server_default="cron",
            nullable=False,
            comment="触发类型：cron 周期触发 / once 一次性触发",
        ),
        sa.Column(
            "cron_expression",
            sa.String(length=120),
            nullable=True,
            comment="五段式 cron 表达式（分 时 日 月 周）；trigger_type=cron 时必填",
        ),
        sa.Column(
            "run_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="一次性执行时刻（UTC）；trigger_type=once 时必填",
        ),
        sa.Column(
            "timezone",
            sa.String(length=64),
            server_default="Asia/Shanghai",
            nullable=False,
            comment="IANA 时区名，用于解释 cron 与 run_at（默认 Asia/Shanghai）",
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="active",
            nullable=False,
            comment="任务状态：active 启用 / paused 暂停",
        ),
        sa.Column(
            "next_run_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="下一次应触发的时刻（UTC），调度抢占依据；为空表示不再触发",
        ),
        sa.Column(
            "last_run_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="最近一次实际触发的时刻（UTC）",
        ),
        sa.Column(
            "created_by_type",
            sa.String(length=20),
            server_default="user",
            nullable=False,
            comment="创建者类型：user 用户 / agent 智能体 / integration 接入方",
        ),
        sa.Column(
            "created_by_user_id",
            sa.Integer(),
            nullable=True,
            comment="创建者用户 ID（created_by_type=user 时记录）",
        ),
        sa.Column(
            "created_by_agent_id",
            sa.Integer(),
            nullable=True,
            comment="创建者智能体 ID（created_by_type=agent 时记录）",
        ),
        sa.Column(
            "run_as_type",
            sa.String(length=20),
            server_default="user",
            nullable=False,
            comment="执行身份类型：user 以某个用户身份运行（v1 仅支持该取值）",
        ),
        sa.Column(
            "run_as_user_id",
            sa.Integer(),
            nullable=True,
            comment="以哪个用户身份执行（run_as_type=user 时必填）",
        ),
        sa.Column(
            "auto_approve",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
            comment="无人值守时是否自动批准需要确认的工具调用，默认开启",
        ),
        sa.Column(
            "strict_approval",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
            comment="严格模式：只自动批准 side_effect=navigation 的工具，默认关闭",
        ),
        sa.Column(
            "timeout_seconds",
            sa.Integer(),
            server_default="600",
            nullable=False,
            comment="单次执行超时秒数，默认 600",
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
            ["agent_id"],
            ["agents.id"],
            name=op.f("fk_tasks_agent_id_agents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_agent_id"],
            ["agents.id"],
            name=op.f("fk_tasks_created_by_agent_id_agents"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["sys_users.id"],
            name=op.f("fk_tasks_created_by_user_id_sys_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["model_id"],
            ["platform_models.id"],
            name=op.f("fk_tasks_model_id_platform_models"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["sys_users.id"],
            name=op.f("fk_tasks_owner_user_id_sys_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["platform_id"],
            ["platforms.id"],
            name=op.f("fk_tasks_platform_id_platforms"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_as_user_id"],
            ["sys_users.id"],
            name=op.f("fk_tasks_run_as_user_id_sys_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tasks")),
    )
    op.create_index(op.f("ix_tasks_agent_id"), "tasks", ["agent_id"], unique=False)
    op.create_index(
        op.f("ix_tasks_next_run_at"), "tasks", ["next_run_at"], unique=False
    )
    op.create_index(
        op.f("ix_tasks_owner_user_id"), "tasks", ["owner_user_id"], unique=False
    )
    op.create_index(
        op.f("ix_tasks_platform_id"), "tasks", ["platform_id"], unique=False
    )

    op.create_table(
        "task_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="任务运行主键"),
        sa.Column("task_id", sa.Integer(), nullable=False, comment="所属任务 ID"),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="running",
            nullable=False,
            comment="执行状态：running 执行中 / completed 已完成 / failed 已失败 / skipped 已跳过",
        ),
        sa.Column(
            "trigger_kind",
            sa.String(length=20),
            server_default="scheduled",
            nullable=False,
            comment="触发方式：scheduled 到点触发 / manual 手动立即运行",
        ),
        sa.Column(
            "planned_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="计划触发时刻（UTC），用于对齐这次运行对应哪个触发点",
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="实际开始时刻（UTC）",
        ),
        sa.Column(
            "finished_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="实际结束时刻（UTC）",
        ),
        sa.Column(
            "conversation_id",
            sa.Integer(),
            nullable=True,
            comment="本轮自动创建的会话 ID；删除会话时置空以保留执行记录",
        ),
        sa.Column(
            "agent_loop_run_id",
            sa.Integer(),
            nullable=True,
            comment="对应的 Agent 运行记录 ID，便于从执行记录回溯到具体运行",
        ),
        sa.Column(
            "error_message",
            sa.Text(),
            nullable=True,
            comment="失败原因（超时、模型错误等）",
        ),
        sa.Column(
            "skip_reason",
            sa.String(length=40),
            nullable=True,
            comment="跳过原因：overlapped 上一次未结束 / task_paused 任务已暂停 / deadline_missed 错过触发点",
        ),
        sa.Column(
            "auto_approved_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
            comment="本轮自动批准的工具调用次数，用于无人值守审批的可追溯性",
        ),
        sa.Column(
            "watchdog_checked_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="看门狗最近一次检查该记录的时刻（UTC）",
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
            ["agent_loop_run_id"],
            ["agent_loop_runs.id"],
            name=op.f("fk_task_runs_agent_loop_run_id_agent_loop_runs"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name=op.f("fk_task_runs_conversation_id_conversations"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["tasks.id"],
            name=op.f("fk_task_runs_task_id_tasks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_task_runs")),
    )
    op.create_index(
        op.f("ix_task_runs_conversation_id"),
        "task_runs",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_task_runs_status_started_at"),
        "task_runs",
        ["status", "started_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_task_runs_task_id"), "task_runs", ["task_id"], unique=False
    )
    # 「同一任务串行」的数据库级兜底：一个任务最多一条 running 记录。
    op.create_index(
        "uq_task_runs_one_running_per_task",
        "task_runs",
        ["task_id"],
        unique=True,
        postgresql_where=sa.text("status = 'running'"),
    )


def downgrade() -> None:
    """回滚删除任务运行与任务两张表。"""
    op.drop_index(
        "uq_task_runs_one_running_per_task",
        table_name="task_runs",
        postgresql_where=sa.text("status = 'running'"),
    )
    op.drop_index(op.f("ix_task_runs_task_id"), table_name="task_runs")
    op.drop_index(op.f("ix_task_runs_status_started_at"), table_name="task_runs")
    op.drop_index(op.f("ix_task_runs_conversation_id"), table_name="task_runs")
    op.drop_table("task_runs")
    op.drop_index(op.f("ix_tasks_platform_id"), table_name="tasks")
    op.drop_index(op.f("ix_tasks_owner_user_id"), table_name="tasks")
    op.drop_index(op.f("ix_tasks_next_run_at"), table_name="tasks")
    op.drop_index(op.f("ix_tasks_agent_id"), table_name="tasks")
    op.drop_table("tasks")
