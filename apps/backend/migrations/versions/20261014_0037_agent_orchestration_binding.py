"""Agent 绑定编排工作流：新增绑定列，并把「同一工作流串行」的约束让开会话内触发

Revision ID: 20261014_0037
Revises: 20261013_0036
Create Date: 2026-10-14
"""

import sqlalchemy as sa
from alembic import op

revision: str = "20261014_0037"
down_revision: str = "20261013_0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """给 Agent 加一条「绑定编排工作流」的可空外键，并调整两处约束。

    背景：编排要能由**终端用户的每一轮消息**触发。触发方是 Agent 而不是工作流
    （工作流到 Agent 已有 NOT NULL 外键 ``workflows.agent_id``，反向加列会形成
    双向强绑定），所以绑定加在 Agent 侧。

    另外两处不是新功能，而是并行/会话内触发带来的既有约束调整：

    1. ``workflow_step_runs`` 补 ``(run_id, step_id)`` 唯一索引。线性执行时
       「一步骤一条记录」由循环天然保证；并行调度下多个分支会同时插入，
       只能靠数据库兜底。
    2. ``uq_workflow_runs_one_running_per_workflow`` 的谓词加
       ``trigger_kind <> 'conversation'``。原约束是为了「定时/手动触发不重叠」，
       但会话内接管是每轮消息跑一次的高频触发，多个会话同时对话是常态；
       若也串行，后来的会话会被改写成 skipped。并行风险由「分支内只允许
       side_effect=none 的工具」承担（见 workflows/services.py）。

    绑定列用 ``ondelete=SET NULL``：工作流被删掉时 Agent 退回普通单 Agent 对话，
    而不是整个 Agent 不可用——绑定是可选增强，不是必备属性。
    """

    op.add_column(
        "agents",
        sa.Column(
            "orchestration_workflow_id",
            sa.Integer(),
            nullable=True,
            comment="绑定的编排工作流 ID：非空时该 Agent 每轮消息由这条工作流接管编排",
        ),
    )
    op.create_foreign_key(
        op.f("fk_agents_orchestration_workflow_id_workflows"),
        "agents",
        "workflows",
        ["orchestration_workflow_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_index(
        "uq_workflow_step_runs_run_step",
        "workflow_step_runs",
        ["run_id", "step_id"],
        unique=True,
    )

    # 部分索引改谓词必须先删后建：PostgreSQL 没有 ALTER INDEX 改 WHERE 的入口。
    # 两种方言都要写 where，否则 sqlite 会退化成「workflow_id 全表唯一」。
    op.drop_index(
        "uq_workflow_runs_one_running_per_workflow",
        table_name="workflow_runs",
        postgresql_where=sa.text("status = 'running'"),
        sqlite_where=sa.text("status = 'running'"),
    )
    op.create_index(
        "uq_workflow_runs_one_running_per_workflow",
        "workflow_runs",
        ["workflow_id"],
        unique=True,
        postgresql_where=sa.text(
            "status = 'running' AND trigger_kind <> 'conversation'"
        ),
        sqlite_where=sa.text("status = 'running' AND trigger_kind <> 'conversation'"),
    )

    # 以下三条只是同步列注释：语义变了，注释不改会误导后来读库的人。
    op.alter_column(
        "workflow_runs",
        "trigger_kind",
        existing_type=sa.String(length=20),
        existing_nullable=False,
        existing_server_default="manual",
        comment=(
            "触发方式：manual 手动运行 / scheduled 由任务定时触发 / "
            "conversation 会话内接管（Agent 绑定编排后每轮消息触发，不参与同一工作流串行约束）"
        ),
    )
    op.alter_column(
        "workflows",
        "definition",
        existing_type=sa.JSON(),
        existing_nullable=False,
        existing_server_default="{}",
        comment=(
            "定义本体：nodes[] 步骤节点（含 depends_on 依赖与 position 画布坐标）"
            "+ edges[] 由依赖编译出的边，节点与边都带稳定字符串 id"
        ),
    )
    op.alter_column(
        "workflow_step_runs",
        "seq",
        existing_type=sa.Integer(),
        existing_nullable=False,
        comment=(
            "步骤在定义 nodes[] 中的位次（从 0 开始），只用于稳定排序展示；"
            "真实执行顺序由 depends_on 决定，同一层内的步骤会并发执行"
        ),
    )


def downgrade() -> None:
    """逆序回滚：先还原注释与索引谓词，再拆唯一索引与绑定列。

    注意 ``trigger_kind`` 的取值集合缩回两档；若库里已存在 conversation 记录，
    还原后的部分唯一索引会因为「同一工作流多条 running」而创建失败——这是
    有意的：该回滚要求先清理会话内触发产生的运行记录。
    """

    op.alter_column(
        "workflow_step_runs",
        "seq",
        existing_type=sa.Integer(),
        existing_nullable=False,
        comment="步骤在本次运行中的执行顺序，从 0 开始",
    )
    op.alter_column(
        "workflows",
        "definition",
        existing_type=sa.JSON(),
        existing_nullable=False,
        existing_server_default="{}",
        comment="定义本体：nodes[] 步骤节点 + edges[] 顺序边，节点与边都带稳定字符串 id",
    )
    op.alter_column(
        "workflow_runs",
        "trigger_kind",
        existing_type=sa.String(length=20),
        existing_nullable=False,
        existing_server_default="manual",
        comment="触发方式：manual 手动运行 / scheduled 由任务定时触发",
    )

    op.drop_index(
        "uq_workflow_runs_one_running_per_workflow",
        table_name="workflow_runs",
        postgresql_where=sa.text(
            "status = 'running' AND trigger_kind <> 'conversation'"
        ),
        sqlite_where=sa.text("status = 'running' AND trigger_kind <> 'conversation'"),
    )
    op.create_index(
        "uq_workflow_runs_one_running_per_workflow",
        "workflow_runs",
        ["workflow_id"],
        unique=True,
        postgresql_where=sa.text("status = 'running'"),
        sqlite_where=sa.text("status = 'running'"),
    )

    op.drop_index("uq_workflow_step_runs_run_step", table_name="workflow_step_runs")

    op.drop_constraint(
        op.f("fk_agents_orchestration_workflow_id_workflows"),
        "agents",
        type_="foreignkey",
    )
    op.drop_column("agents", "orchestration_workflow_id")
