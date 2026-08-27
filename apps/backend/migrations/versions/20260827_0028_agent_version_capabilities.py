"""agent_versions 增加 capabilities 附件能力配置列

Revision ID: 20260827_0028
Revises: 20260827_0027
Create Date: 2026-08-27
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260827_0028"
down_revision: Union[str, None] = "20260827_0027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "agent_versions",
        sa.Column(
            "capabilities",
            sa.JSON(),
            nullable=True,
            comment=(
                "模型附件能力配置（image/native_file/text_retrieval），"
                "为空时按 OpenRouter input_modalities 探测并按模型名兜底"
            ),
        ),
    )


def downgrade() -> None:
    op.drop_column("agent_versions", "capabilities")
