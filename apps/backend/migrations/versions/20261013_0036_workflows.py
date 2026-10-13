"""新增工作流定义、工作流运行、步骤运行三张表，并给任务表加工作流外键

Revision ID: 20261013_0036
Revises: 20260919_0035
Create Date: 2026-10-13
"""

import sqlalchemy as sa
from alembic import op

revision: str = "20261013_0036"
down_revision: str = "20260919_0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """建立工作流模块的三张表，并把定时触发接到任务表上。

    背景：给平台加一条「无画布的多步编排」能力——在后台用有序表单定义一串
    步骤，手动或定时触发，按序执行并把每步结果落库。工作流做成独立模块而不是
    给 tasks 表加 kind 列，是为了让现有任务行为零回归（见 ADR 0002）。

    定时触发复用任务模块已定案的抢占式调度与看门狗：tasks.workflow_id 这条
    可空外键就是两条执行概念之间**唯一**的连接边，任务带值时就触发该工作流的
    一次运行，任务自身的 agent_id / prompt 不参与执行。
    """

    op.create_table(
        "workflows",
        sa.Column(
            "id", sa.Integer(), autoincrement=True, nullable=False, comment="工作流主键"
        ),
        sa.Column(
            "platform_id", sa.Integer(), nullable=False, comment="工作流所属平台 ID"
        ),
        sa.Column(
            "name", sa.String(length=200), nullable=False, comment="工作流名称"
        ),
        sa.Column(
            "description",
            sa.Text(),
            nullable=True,
            comment="工作流说明，供后台识别用途",
        ),
        sa.Column(
            "agent_id",
            sa.Integer(),
            nullable=False,
            comment="工作流级默认智能体 ID；步骤未覆盖 agent_id 时用它执行",
        ),
        sa.Column(
            "owner_user_id",
            sa.Integer(),
            nullable=True,
            comment="工作流归属用户 ID；为空表示平台级工作流（仅平台管理员可管理）",
        ),
        sa.Column(
            "created_by_type",
            sa.String(length=20),
            server_default="user",
            nullable=False,
            comment="创建者类型：user 用户 / agent 智能体 / integration 集成",
        ),
        sa.Column(
            "created_by_user_id",
            sa.Integer(),
            nullable=True,
            comment="创建者用户 ID；创建者被删除时置空以保留定义",
        ),
        sa.Column(
            "created_by_agent_id",
            sa.Integer(),
            nullable=True,
            comment="创建者智能体 ID；由智能体创建时有值",
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="active",
            nullable=False,
            comment="状态：active 启用 / paused 暂停（暂停期间到期触发会被跳过）",
        ),
        sa.Column(
            "version",
            sa.Integer(),
            server_default="1",
            nullable=False,
            comment="定义版本号：每次保存定义加一，运行记录用它标记当时执行的是哪一版",
        ),
        sa.Column(
            "max_steps",
            sa.Integer(),
            server_default="50",
            nullable=False,
            comment="步骤数上限（默认 50，对齐成熟实现的单路径节点上限）",
        ),
        sa.Column(
            "definition",
            sa.JSON(),
            server_default="{}",
            nullable=False,
            comment="定义本体：nodes[] 步骤节点 + edges[] 顺序边，节点与边都带稳定字符串 id",
        ),
        sa.Column(
            "timeout_seconds",
            sa.Integer(),
            server_default="600",
            nullable=False,
            comment="整条工作流单次执行的超时秒数",
        ),
        sa.Column(
            "auto_approve",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
            comment="是否自动批准需要确认的工具调用（沿用任务模块的无人值守策略）",
        ),
        sa.Column(
            "strict_approval",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
            comment="严格模式：只自动批准 navigation 类工具，其余仍需确认",
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
            name=op.f("fk_workflows_agent_id_agents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_agent_id"],
            ["agents.id"],
            name=op.f("fk_workflows_created_by_agent_id_agents"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["sys_users.id"],
            name=op.f("fk_workflows_created_by_user_id_sys_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["sys_users.id"],
            name=op.f("fk_workflows_owner_user_id_sys_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["platform_id"],
            ["platforms.id"],
            name=op.f("fk_workflows_platform_id_platforms"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workflows")),
    )
    op.create_index(
        op.f("ix_workflows_agent_id"), "workflows", ["agent_id"], unique=False
    )
    op.create_index(
        op.f("ix_workflows_owner_user_id"), "workflows", ["owner_user_id"], unique=False
    )
    op.create_index(
        op.f("ix_workflows_platform_id"), "workflows", ["platform_id"], unique=False
    )

    op.create_table(
        "workflow_runs",
        sa.Column(
            "id",
            sa.Integer(),
            autoincrement=True,
            nullable=False,
            comment="工作流运行主键",
        ),
        sa.Column(
            "workflow_id", sa.Integer(), nullable=False, comment="所属工作流 ID"
        ),
        sa.Column(
            "definition_version_id",
            sa.Integer(),
            nullable=False,
            comment="本次运行使用的定义版本号（对应 workflows.version，不建独立版本表）",
        ),
        sa.Column(
            "definition_snapshot",
            sa.JSON(),
            server_default="{}",
            nullable=False,
            comment="本次运行冻结的定义快照；定义被修改后历史运行仍能解释自己",
        ),
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
            server_default="manual",
            nullable=False,
            comment="触发方式：manual 手动运行 / scheduled 由任务定时触发",
        ),
        sa.Column(
            "run_as_type",
            sa.String(length=20),
            server_default="user",
            nullable=False,
            comment="执行身份类型：user 平台用户 / end_user 终端用户 / platform 平台预留",
        ),
        sa.Column(
            "run_as_user_id",
            sa.Integer(),
            nullable=True,
            comment="执行身份对应的平台用户 ID；身份由触发源决定，不在定义里存死",
        ),
        sa.Column(
            "run_as_end_user_id",
            sa.Integer(),
            nullable=True,
            comment="执行身份对应的终端用户 ID；定时触发时可能由任务带入",
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
            "error_message",
            sa.Text(),
            nullable=True,
            comment="失败原因（超时、步骤失败、模型错误等）",
        ),
        sa.Column(
            "skip_reason",
            sa.String(length=40),
            nullable=True,
            comment="跳过原因：overlapped 上一次未结束 / workflow_paused 工作流已暂停 / deadline_missed 错过触发点",
        ),
        sa.Column(
            "auto_approved_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
            comment="本轮各步骤自动批准的工具调用次数合计，用于无人值守审批的可追溯性",
        ),
        sa.Column(
            "total_steps",
            sa.Integer(),
            server_default="0",
            nullable=False,
            comment="本次运行按快照应执行的步骤总数",
        ),
        sa.Column(
            "completed_steps",
            sa.Integer(),
            server_default="0",
            nullable=False,
            comment="本次运行已成功完成的步骤数（含用兜底值继续的步骤）",
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
            ["run_as_end_user_id"],
            ["platform_end_users.id"],
            name=op.f("fk_workflow_runs_run_as_end_user_id_platform_end_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["run_as_user_id"],
            ["sys_users.id"],
            name=op.f("fk_workflow_runs_run_as_user_id_sys_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_id"],
            ["workflows.id"],
            name=op.f("fk_workflow_runs_workflow_id_workflows"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workflow_runs")),
    )
    op.create_index(
        op.f("ix_workflow_runs_workflow_id"),
        "workflow_runs",
        ["workflow_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_workflow_runs_status_started_at"),
        "workflow_runs",
        ["status", "started_at"],
        unique=False,
    )
    # 「同一工作流串行」的数据库级兜底：一个工作流最多一条 running 记录。
    # 两种方言都要写 where：只给 postgresql_where 时，sqlite 会退化成
    # 「workflow_id 全表唯一」，反而让第二条 skipped 记录也插不进去。
    op.create_index(
        "uq_workflow_runs_one_running_per_workflow",
        "workflow_runs",
        ["workflow_id"],
        unique=True,
        postgresql_where=sa.text("status = 'running'"),
        sqlite_where=sa.text("status = 'running'"),
    )

    op.create_table(
        "workflow_step_runs",
        sa.Column(
            "id",
            sa.Integer(),
            autoincrement=True,
            nullable=False,
            comment="步骤运行主键",
        ),
        sa.Column(
            "run_id", sa.Integer(), nullable=False, comment="所属工作流运行 ID"
        ),
        sa.Column(
            "step_id",
            sa.String(length=64),
            nullable=False,
            comment="步骤的稳定字符串标识（非自增行号），后续步骤用它引用本步输出",
        ),
        sa.Column(
            "seq",
            sa.Integer(),
            nullable=False,
            comment="步骤在本次运行中的执行顺序，从 0 开始",
        ),
        sa.Column(
            "node_type",
            sa.String(length=20),
            nullable=False,
            comment="步骤类型：agent 跑一轮 Agent / tool 直接调用一个工具",
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="running",
            nullable=False,
            comment="步骤状态：running 执行中 / succeeded 成功 / failed 失败 / skipped 已跳过 / waiting 等待人工（v1 预留未实现）",
        ),
        sa.Column(
            "model_visible_output",
            sa.Text(),
            nullable=True,
            comment="进下一步、对模型可见的输出；超过 50KB 会被截断并追加截断标记",
        ),
        sa.Column(
            "raw_output",
            sa.Text(),
            nullable=True,
            comment="完整未截断输出，仅供界面展示与审计",
        ),
        sa.Column(
            "retry_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
            comment="实际尝试次数：首跑成功记 1，重试过则按累计次数记（如 max_retries=2 且第 3 次成功记 3）",
        ),
        sa.Column(
            "on_error_applied",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
            comment="该步失败后是否改用了兜底值继续（on_error=continue_with_default 生效时为真）",
        ),
        sa.Column(
            "conversation_id",
            sa.Integer(),
            nullable=True,
            comment="该步自动创建的会话 ID（Agent 步骤）；删除会话时置空以保留步骤记录",
        ),
        sa.Column(
            "agent_loop_run_id",
            sa.Integer(),
            nullable=True,
            comment="该步对应的 Agent 运行记录 ID，用于回溯模型与工具调用",
        ),
        sa.Column(
            "error_message",
            sa.Text(),
            nullable=True,
            comment="失败原因（工具错误、模型错误、超时等）",
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="该步实际开始时刻（UTC）",
        ),
        sa.Column(
            "finished_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="该步实际结束时刻（UTC）",
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
            name=op.f("fk_workflow_step_runs_agent_loop_run_id_agent_loop_runs"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name=op.f("fk_workflow_step_runs_conversation_id_conversations"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["workflow_runs.id"],
            name=op.f("fk_workflow_step_runs_run_id_workflow_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workflow_step_runs")),
    )
    op.create_index(
        op.f("ix_workflow_step_runs_conversation_id"),
        "workflow_step_runs",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_workflow_step_runs_run_id"),
        "workflow_step_runs",
        ["run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_workflow_step_runs_run_seq"),
        "workflow_step_runs",
        ["run_id", "seq"],
        unique=False,
    )

    # 定时触发与工作流定义之间唯一的一条连接边：任务带 workflow_id 时，
    # 到点触发的是该工作流的一次运行，任务自身的 agent_id / prompt 不参与执行。
    # ondelete=CASCADE 是刻意的：触发任务只为工作流而存在，工作流被删掉不该留下
    # 一条还在跑自己 prompt 的僵尸任务。
    op.add_column(
        "tasks",
        sa.Column(
            "workflow_id",
            sa.Integer(),
            nullable=True,
            comment="由哪个工作流触发：为空是普通任务（行为与今天完全一致）；有值时到点触发的是该工作流的一次运行，任务自身的 agent_id/prompt 不参与执行",
        ),
    )
    op.create_index(
        op.f("ix_tasks_workflow_id"), "tasks", ["workflow_id"], unique=False
    )
    op.create_foreign_key(
        op.f("fk_tasks_workflow_id_workflows"),
        "tasks",
        "workflows",
        ["workflow_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    """逆序回滚：先拆任务表上的工作流外键，再删三张工作流表。

    先删 workflow_step_runs 再 workflow_runs 再 workflows，避免外键依赖顺序错误。
    """
    op.drop_constraint(
        op.f("fk_tasks_workflow_id_workflows"), "tasks", type_="foreignkey"
    )
    op.drop_index(op.f("ix_tasks_workflow_id"), table_name="tasks")
    op.drop_column("tasks", "workflow_id")

    op.drop_index(
        op.f("ix_workflow_step_runs_run_seq"), table_name="workflow_step_runs"
    )
    op.drop_index(
        op.f("ix_workflow_step_runs_run_id"), table_name="workflow_step_runs"
    )
    op.drop_index(
        op.f("ix_workflow_step_runs_conversation_id"),
        table_name="workflow_step_runs",
    )
    op.drop_table("workflow_step_runs")

    op.drop_index(
        "uq_workflow_runs_one_running_per_workflow",
        table_name="workflow_runs",
        postgresql_where=sa.text("status = 'running'"),
        sqlite_where=sa.text("status = 'running'"),
    )
    op.drop_index(
        op.f("ix_workflow_runs_status_started_at"), table_name="workflow_runs"
    )
    op.drop_index(op.f("ix_workflow_runs_workflow_id"), table_name="workflow_runs")
    op.drop_table("workflow_runs")

    op.drop_index(op.f("ix_workflows_platform_id"), table_name="workflows")
    op.drop_index(op.f("ix_workflows_owner_user_id"), table_name="workflows")
    op.drop_index(op.f("ix_workflows_agent_id"), table_name="workflows")
    op.drop_table("workflows")
