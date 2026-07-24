"""create knowledge base, documents, chunks and ingestion tasks

Revision ID: 20260723_0005
Revises: 20260723_0004
"""

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

revision = "20260723_0005"
down_revision = "20260723_0004"
branch_labels = None
depends_on = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "knowledge_bases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "platform_id",
            sa.Integer(),
            sa.ForeignKey("platforms.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("slug", sa.String(80), nullable=False),
        sa.Column("embedding_model", sa.String(120), nullable=False),
        sa.Column("embedding_base_url", sa.String(500)),
        sa.Column("embedding_api_key_encrypted", sa.Text()),
        sa.Column("embedding_dimension", sa.Integer(), nullable=False),
        sa.Column(
            "active_index_version", sa.Integer(), server_default="1", nullable=False
        ),
        sa.Column("chunk_size", sa.Integer(), server_default="512", nullable=False),
        sa.Column("chunk_overlap", sa.Integer(), server_default="50", nullable=False),
        *_timestamps(),
        sa.UniqueConstraint(
            "platform_id", "slug", name="uq_knowledge_bases_platform_id"
        ),
    )
    op.create_index(
        op.f("ix_knowledge_bases_platform_id"), "knowledge_bases", ["platform_id"]
    )
    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "knowledge_base_id",
            sa.Integer(),
            sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_type", sa.String(20), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("source_url", sa.String(2000)),
        sa.Column("storage_path", sa.String(1000)),
        sa.Column("media_type", sa.String(120)),
        sa.Column("content", sa.Text()),
        sa.Column("status", sa.String(30), server_default="pending", nullable=False),
        sa.Column("error_message", sa.Text()),
        *_timestamps(),
    )
    op.create_index(
        op.f("ix_knowledge_documents_knowledge_base_id"),
        "knowledge_documents",
        ["knowledge_base_id"],
    )
    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "knowledge_base_id",
            sa.Integer(),
            sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "document_id",
            sa.Integer(),
            sa.ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("index_version", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "source_metadata",
            sa.JSON(),
            server_default=sa.text("'{}'::json"),
            nullable=False,
        ),
        sa.Column("embedding", Vector(), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint(
            "document_id",
            "index_version",
            "position",
            name="uq_knowledge_chunks_document_id",
        ),
    )
    op.create_index(
        op.f("ix_knowledge_chunks_knowledge_base_id"),
        "knowledge_chunks",
        ["knowledge_base_id"],
    )
    op.create_index(
        op.f("ix_knowledge_chunks_document_id"), "knowledge_chunks", ["document_id"]
    )
    op.create_table(
        "knowledge_ingestion_tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "knowledge_base_id",
            sa.Integer(),
            sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "document_id",
            sa.Integer(),
            sa.ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(30), server_default="queued", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_message", sa.Text()),
        *_timestamps(),
    )
    op.create_index(
        op.f("ix_knowledge_ingestion_tasks_knowledge_base_id"),
        "knowledge_ingestion_tasks",
        ["knowledge_base_id"],
    )
    op.create_index(
        op.f("ix_knowledge_ingestion_tasks_document_id"),
        "knowledge_ingestion_tasks",
        ["document_id"],
    )


def downgrade() -> None:
    op.drop_table("knowledge_ingestion_tasks")
    op.drop_table("knowledge_chunks")
    op.drop_table("knowledge_documents")
    op.drop_table("knowledge_bases")
