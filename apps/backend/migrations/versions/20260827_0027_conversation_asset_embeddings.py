"""conversation_asset_embeddings 表：附件切块会话级向量缓存

Revision ID: 20260827_0027
Revises: 20260826_0026
Create Date: 2026-08-27
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector


revision: str = "20260827_0027"
down_revision: Union[str, None] = "20260826_0026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "conversation_asset_embeddings",
        sa.Column(
            "id",
            sa.Integer(),
            autoincrement=True,
            nullable=False,
            comment="向量记录内部主键",
        ),
        sa.Column("chunk_id", sa.Integer(), nullable=False, comment="关联的切块 ID"),
        sa.Column(
            "processing_id",
            sa.Integer(),
            nullable=False,
            comment="关联的处理记录 ID，便于按处理版本整批重建",
        ),
        sa.Column(
            "conversation_id",
            sa.Integer(),
            nullable=False,
            comment="资源所属会话 ID，冗余字段便于权限过滤",
        ),
        sa.Column(
            "asset_id", sa.Integer(), nullable=False, comment="关联的会话资源 ID"
        ),
        sa.Column(
            "provider",
            sa.String(50),
            nullable=False,
            comment="embedding 服务提供方，如 openai",
        ),
        sa.Column(
            "model", sa.String(120), nullable=False, comment="embedding 模型名称"
        ),
        sa.Column(
            "dimension",
            sa.Integer(),
            nullable=False,
            comment="向量维度，用于配置变更校验",
        ),
        sa.Column("embedding", Vector(), nullable=False, comment="切块文本的向量表示"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
            comment="记录创建时间",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
            comment="记录更新时间",
        ),
        sa.ForeignKeyConstraint(
            ["asset_id"], ["conversation_assets.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["chunk_id"], ["conversation_asset_chunks.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["processing_id"], ["conversation_asset_processing.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_conversation_asset_embeddings_asset_id"),
        "conversation_asset_embeddings",
        ["asset_id"],
    )
    op.create_index(
        op.f("ix_conversation_asset_embeddings_chunk_id"),
        "conversation_asset_embeddings",
        ["chunk_id"],
    )
    op.create_index(
        op.f("ix_conversation_asset_embeddings_conversation_id"),
        "conversation_asset_embeddings",
        ["conversation_id"],
    )
    op.create_index(
        op.f("ix_conversation_asset_embeddings_processing_id"),
        "conversation_asset_embeddings",
        ["processing_id"],
    )


def downgrade() -> None:
    op.drop_table("conversation_asset_embeddings")
