"""智能体增加「可派子智能体」绑定关系

需求（`docs/harness/requests/2026-10-21-subagent-bindings/`）：主智能体下发的
委派任务要能限定在后台配置过的一组子智能体里，而不是永远面向「本平台全部已
发布智能体」。

绑定单独建表而不是往 ``agents`` 加 JSON 字段：绑定是双向可查的关系（父查子、
将来也可能校验子被谁引用），需要唯一约束与排序，JSON 数组会在并发写时互相
覆盖。表里只存关系与开关，不复制子 Agent 的配置——子 Agent 的工具、技能与
模型始终由它自己的发布版本决定。

数据约束：两端同平台、禁止自指都由应用层校验；外键 ``CASCADE`` 保证删除
Agent 时绑定自动清理。存量 Agent 没有任何绑定，运行期回退到「全平台已发布
智能体」的老口径，行为不变。

Revision ID: 20261021_0045
Revises: 20261021_0044
Create Date: 2026-10-21
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261021_0045"
down_revision: Union[str, None] = "20261021_0044"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_subagents",
        sa.Column(
            "id", sa.Integer(), autoincrement=True, nullable=False, comment="绑定关系主键"
        ),
        sa.Column(
            "parent_agent_id",
            sa.Integer(),
            nullable=False,
            comment="父智能体 ID（下发委派的一方）",
        ),
        sa.Column(
            "child_agent_id",
            sa.Integer(),
            nullable=False,
            comment="子智能体 ID（被委派执行的一方）",
        ),
        sa.Column(
            "sort_order",
            sa.Integer(),
            server_default="0",
            nullable=False,
            comment="展示与提示清单的排序值，升序",
        ),
        sa.Column(
            "enabled",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
            comment="是否允许被委派；停用后不进入候选清单但保留绑定与排序",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
            comment="记录创建时间（UTC）",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
            comment="记录最后更新时间（UTC）",
        ),
        sa.ForeignKeyConstraint(
            ["child_agent_id"],
            ["agents.id"],
            name="fk_agent_subagents_child_agent_id_agents",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parent_agent_id"],
            ["agents.id"],
            name="fk_agent_subagents_parent_agent_id_agents",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_agent_subagents"),
        sa.UniqueConstraint(
            "parent_agent_id",
            "child_agent_id",
            name="uq_agent_subagents_parent_child",
        ),
    )
    op.create_index(
        op.f("ix_agent_subagents_parent_agent_id"),
        "agent_subagents",
        ["parent_agent_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_agent_subagents_child_agent_id"),
        "agent_subagents",
        ["child_agent_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_agent_subagents_child_agent_id"), table_name="agent_subagents"
    )
    op.drop_index(
        op.f("ix_agent_subagents_parent_agent_id"), table_name="agent_subagents"
    )
    op.drop_table("agent_subagents")
