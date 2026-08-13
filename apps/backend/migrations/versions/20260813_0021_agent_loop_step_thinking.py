"""add thinking text to agent loop steps"""

from alembic import op
import sqlalchemy as sa


revision = "20260813_0021"
down_revision = "20260807_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_loop_steps",
        sa.Column(
            "thinking_text",
            sa.Text(),
            nullable=True,
            comment="模型思考内容（reasoning/thinking），流式累计后落库，普通模型为 NULL",
        ),
    )


def downgrade() -> None:
    op.drop_column("agent_loop_steps", "thinking_text")
