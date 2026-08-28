"""为已有 Agent 启用 attachment_search 内置工具

Revision ID: 20260828_0030
Revises: 20260827_0029
Create Date: 2026-08-28
"""

from alembic import op

revision: str = "20260828_0030"
down_revision: str = "20260827_0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """为已启用内置工具的 Agent 插入 attachment_search 绑定，冲突时跳过。"""
    op.execute(
        """
        INSERT INTO agent_builtin_tools
            (platform_id, agent_id, tool_name, is_enabled, created_at, updated_at)
        SELECT platform_id, agent_id, 'attachment_search', true, now(), now()
        FROM agent_builtin_tools
        WHERE tool_name = 'http_get' AND is_enabled = true
        ON CONFLICT (agent_id, tool_name) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM agent_builtin_tools WHERE tool_name = 'attachment_search'")
