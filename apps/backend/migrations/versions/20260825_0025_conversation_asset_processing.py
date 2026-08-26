"""conversation_asset_processing 和 conversation_asset_chunks 表

Revision ID: 20260825_0025
Revises: 20260823_0024
Create Date: 2026-08-25
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260825_0025"
down_revision: Union[str, None] = "20260823_0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "conversation_asset_processing",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="处理记录内部主键"),
        sa.Column("asset_id", sa.Integer(), nullable=False, comment="关联的会话资源 ID"),
        sa.Column("conversation_id", sa.Integer(), nullable=False, comment="资源所属会话 ID，与 asset 表冗余以便快速过滤"),
        sa.Column("status", sa.String(30), nullable=False, server_default="uploaded", comment="处理状态：uploaded/processing/ready/failed/unsupported"),
        sa.Column("parser_name", sa.String(80), nullable=False, comment="解析器名称，如 SimpleDirectoryReader"),
        sa.Column("parser_version", sa.String(40), nullable=False, comment="解析器版本，用于缓存版本键"),
        sa.Column("chunk_size", sa.Integer(), nullable=False, server_default="512", comment="切块大小，单位 token"),
        sa.Column("chunk_overlap", sa.Integer(), nullable=False, server_default="50", comment="切块重叠大小，单位 token"),
        sa.Column("processing_version", sa.String(128), nullable=False, comment="处理版本键，由文件 hash、解析器版本、chunk 参数等组成"),
        sa.Column("extracted_text_storage_key", sa.String(1000), nullable=True, comment="解析后规范化文本的存储键，相对存储根目录"),
        sa.Column("error_message", sa.Text(), nullable=True, comment="处理失败时的错误信息"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True, comment="处理开始时间"),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True, comment="处理完成时间"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, comment="记录创建时间"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, comment="记录更新时间"),
        sa.ForeignKeyConstraint(["asset_id"], ["conversation_assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_conversation_asset_processing_asset_id"),
        "conversation_asset_processing",
        ["asset_id"],
    )
    op.create_index(
        op.f("ix_conversation_asset_processing_conversation_id"),
        "conversation_asset_processing",
        ["conversation_id"],
    )
    op.create_index(
        op.f("ix_conversation_asset_processing_processing_version"),
        "conversation_asset_processing",
        ["processing_version"],
    )

    op.create_table(
        "conversation_asset_chunks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="切块内部主键"),
        sa.Column("processing_id", sa.Integer(), nullable=False, comment="关联的处理记录 ID"),
        sa.Column("conversation_id", sa.Integer(), nullable=False, comment="资源所属会话 ID，冗余字段便于权限过滤"),
        sa.Column("asset_id", sa.Integer(), nullable=False, comment="关联的会话资源 ID"),
        sa.Column("position", sa.Integer(), nullable=False, comment="切块在文档中的序号，从 0 开始"),
        sa.Column("content", sa.Text(), nullable=False, comment="切块文本内容"),
        sa.Column("page_number", sa.Integer(), nullable=True, comment="切块所在页码，从 1 开始；纯文本文件可为空"),
        sa.Column("token_count", sa.Integer(), nullable=False, server_default="0", comment="切块内容估算 token 数量"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, comment="切块创建时间"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, comment="切块更新时间"),
        sa.ForeignKeyConstraint(["processing_id"], ["conversation_asset_processing.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["asset_id"], ["conversation_assets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_conversation_asset_chunks_processing_id"),
        "conversation_asset_chunks",
        ["processing_id"],
    )
    op.create_index(
        op.f("ix_conversation_asset_chunks_conversation_id"),
        "conversation_asset_chunks",
        ["conversation_id"],
    )
    op.create_index(
        op.f("ix_conversation_asset_chunks_asset_id"),
        "conversation_asset_chunks",
        ["asset_id"],
    )


def downgrade() -> None:
    op.drop_table("conversation_asset_chunks")
    op.drop_table("conversation_asset_processing")
