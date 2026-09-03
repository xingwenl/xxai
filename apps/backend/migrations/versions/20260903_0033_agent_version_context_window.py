"""agent_versions 新增 context_window_tokens 可空列

Revision ID: 20260903_0033
Revises: 20260831_0032
Create Date: 2026-09-03
"""

import sqlalchemy as sa
from alembic import op

revision: str = "20260903_0033"
down_revision: str = "20260831_0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """为智能体版本新增模型上下文窗口声明列，用于对话预算护栏。"""
    op.add_column(
        "agent_versions",
        sa.Column(
            "context_window_tokens",
            sa.Integer(),
            nullable=True,
            comment="模型上下文窗口（token），用于对话上下文预算护栏；为空时按模型名映射推断或禁用护栏",
        ),
    )


def downgrade() -> None:
    """回滚删除 context_window_tokens 列。"""
    op.drop_column("agent_versions", "context_window_tokens")
