"""enable http_post for agents already using http_get

Revision ID: 20260823_0024
Revises: 20260823_0023
"""

from alembic import op

revision = "20260823_0024"
down_revision = "20260823_0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO agent_builtin_tools
            (platform_id, agent_id, tool_name, is_enabled, created_at, updated_at)
        SELECT platform_id, agent_id, 'http_post', true, now(), now()
        FROM agent_builtin_tools
        WHERE tool_name = 'http_get' AND is_enabled = true
        ON CONFLICT (agent_id, tool_name) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM agent_builtin_tools WHERE tool_name = 'http_post'")
