"""add knowledge retrieval threshold and top k"""

from alembic import op
import sqlalchemy as sa


revision = "20260806_0018"
down_revision = "20260805_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "knowledge_bases",
        sa.Column(
            "retrieval_threshold",
            sa.Float(),
            nullable=False,
            server_default="0.5",
            comment="知识库检索余弦相似度最低阈值",
        ),
    )
    op.add_column(
        "knowledge_bases",
        sa.Column(
            "retrieval_top_k",
            sa.Integer(),
            nullable=False,
            server_default="5",
            comment="每次检索最多注入的知识片段数量",
        ),
    )


def downgrade() -> None:
    op.drop_column("knowledge_bases", "retrieval_top_k")
    op.drop_column("knowledge_bases", "retrieval_threshold")
