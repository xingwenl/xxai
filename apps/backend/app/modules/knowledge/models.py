from __future__ import annotations

from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel, TimeModel


class KnowledgeBase(BaseModel, TimeModel):
    __tablename__ = "knowledge_bases"
    __table_args__ = (UniqueConstraint("platform_id", "slug"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    platform_id: Mapped[int] = mapped_column(
        ForeignKey("platforms.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(120), nullable=False)
    embedding_base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    embedding_api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding_dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    active_index_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    chunk_size: Mapped[int] = mapped_column(
        Integer, nullable=False, default=512, server_default="512"
    )
    chunk_overlap: Mapped[int] = mapped_column(
        Integer, nullable=False, default=50, server_default="50"
    )
    retrieval_threshold: Mapped[float] = mapped_column(
        comment="知识库检索余弦相似度最低阈值",
        nullable=False,
        default=0.5,
        server_default="0.5",
    )
    retrieval_top_k: Mapped[int] = mapped_column(
        Integer,
        comment="每次检索最多注入的知识片段数量",
        nullable=False,
        default=5,
        server_default="5",
    )


class AgentKnowledgeBase(BaseModel, TimeModel):
    __tablename__ = "agent_knowledge_bases"
    __table_args__ = (UniqueConstraint("agent_id", "knowledge_base_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), index=True
    )
    knowledge_base_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True
    )
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )


class KnowledgeDocument(BaseModel, TimeModel):
    __tablename__ = "knowledge_documents"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    knowledge_base_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True
    )
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    storage_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    media_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="pending", server_default="pending"
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class KnowledgeChunk(BaseModel, TimeModel):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (UniqueConstraint("document_id", "index_version", "position"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    knowledge_base_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"), index=True
    )
    index_version: Mapped[int] = mapped_column(Integer, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    embedding: Mapped[list[float]] = mapped_column(Vector(), nullable=False)


class IngestionTask(BaseModel, TimeModel):
    __tablename__ = "knowledge_ingestion_tasks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    knowledge_base_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="queued", server_default="queued"
    )
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
