"""运行期委派子 Agent：给运行记录加父运行列，让子运行可回溯到父运行

Revision ID: 20261015_0038
Revises: 20261014_0037
Create Date: 2026-10-15
"""

import sqlalchemy as sa
from alembic import op

revision: str = "20261015_0038"
down_revision: str = "20261014_0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """给 ``agent_loop_runs`` 加一个可空自引用外键，表达"子运行挂在谁下面"。

    背景：本轮新增「运行期动态委派」——主 Agent 可以调用 ``delegate_tasks``
    派生若干子 Agent 运行。子运行复用既有执行入口（每轮新建会话），所以它本身
    就是一条普通的 ``agent_loop_runs`` 记录；缺的只是"它是被谁派出来的"。

    ``parent_loop_run_id`` 用自引用 ``ondelete=SET NULL``：父运行被删（会话级联
    删除）时子运行不跟着消失，而是失去归属——子运行有自己的会话与消息，不该被
    父会话的删除连坐。列可空，存量运行记录不受影响，未委派的运行恒为 NULL。

    **"哪一次派生调用产生了这些子运行"不落在本表**：父运行的工具步骤记录是在
    整轮运行收尾时才创建的（``conversation/services.py`` 从 ``result.tool_events``
    逐个补建），而子运行在工具执行**期间**就已落库，那一刻父步骤行还不存在。
    因此"同一次扇出"的分组键记在父步骤自己的扩展元数据里
    （``agent_loop_steps.metadata`` 的 ``delegatedRunIds``），不需要给本表再加
    一个指向 ``agent_loop_steps`` 的外键——那还会与 ``agent_loop_steps.loop_run_id``
    构成表间环，徒增 ``use_alter`` 的拓扑排序负担。
    """

    op.add_column(
        "agent_loop_runs",
        sa.Column(
            "parent_loop_run_id",
            sa.Integer(),
            nullable=True,
            comment="父运行 ID：非空表示这是一次被派生的子运行",
        ),
    )
    op.create_foreign_key(
        op.f("fk_agent_loop_runs_parent_loop_run_id_agent_loop_runs"),
        "agent_loop_runs",
        "agent_loop_runs",
        ["parent_loop_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_agent_loop_runs_parent_loop_run_id",
        "agent_loop_runs",
        ["parent_loop_run_id"],
    )


def downgrade() -> None:
    """逆序回滚：先删索引，再删外键与列。"""

    op.drop_index("ix_agent_loop_runs_parent_loop_run_id", table_name="agent_loop_runs")
    op.drop_constraint(
        op.f("fk_agent_loop_runs_parent_loop_run_id_agent_loop_runs"),
        "agent_loop_runs",
        type_="foreignkey",
    )
    op.drop_column("agent_loop_runs", "parent_loop_run_id")
