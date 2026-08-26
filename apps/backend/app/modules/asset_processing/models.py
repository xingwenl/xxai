from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel, TimeModel


class ProcessingStatus:
    """附件处理状态枚举，提供状态机校验方法。"""

    uploaded = "uploaded"
    processing = "processing"
    ready = "ready"
    failed = "failed"
    unsupported = "unsupported"

    _ALLOWED_TRANSITIONS: dict[str, set[str]] = {
        uploaded: {processing},
        processing: {ready, failed, unsupported},
        ready: {processing},
        failed: {processing},
        unsupported: {processing},
    }

    @classmethod
    def can_transition(cls, current: str, target: str) -> bool:
        return target in cls._ALLOWED_TRANSITIONS.get(current, set())


class ConversationAssetProcessing(BaseModel, TimeModel):
    """附件处理记录，记录每次解析任务的状态、版本和结果存储键。"""

    __tablename__ = "conversation_asset_processing"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True, comment="处理记录内部主键"
    )
    asset_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("conversation_assets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="关联的会话资源 ID",
    )
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="资源所属会话 ID，与 asset 表冗余以便快速过滤",
    )
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default=ProcessingStatus.uploaded,
        server_default=ProcessingStatus.uploaded,
        comment="处理状态：uploaded/processing/ready/failed/unsupported",
    )
    parser_name: Mapped[str] = mapped_column(
        String(80), nullable=False, comment="解析器名称，如 SimpleDirectoryReader"
    )
    parser_version: Mapped[str] = mapped_column(
        String(40), nullable=False, comment="解析器版本，用于缓存版本键"
    )
    chunk_size: Mapped[int] = mapped_column(
        Integer, nullable=False, default=512, comment="切块大小，单位 token"
    )
    chunk_overlap: Mapped[int] = mapped_column(
        Integer, nullable=False, default=50, comment="切块重叠大小，单位 token"
    )
    processing_version: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        index=True,
        comment="处理版本键，由文件 hash、解析器版本、chunk 参数等组成",
    )
    extracted_text_storage_key: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
        comment="解析后规范化文本的存储键，相对存储根目录",
    )
    extracted_text: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="解析后规范化文本全文缓存，模型上下文直接读取，避免重复读文件",
    )
    error_message: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="处理失败时的错误信息"
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="处理开始时间"
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="处理完成时间"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="记录创建时间",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        comment="记录更新时间",
    )


class ConversationAssetChunk(BaseModel, TimeModel):
    """附件文本切块，按位置排序保存，支持页码和 token 数量追踪。"""

    __tablename__ = "conversation_asset_chunks"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True, comment="切块内部主键"
    )
    processing_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("conversation_asset_processing.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="关联的处理记录 ID",
    )
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="资源所属会话 ID，冗余字段便于权限过滤",
    )
    asset_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("conversation_assets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="关联的会话资源 ID",
    )
    position: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="切块在文档中的序号，从 0 开始"
    )
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="切块文本内容")
    page_number: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="切块所在页码，从 1 开始；纯文本文件可为空"
    )
    token_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="切块内容估算 token 数量"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="切块创建时间",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        comment="切块更新时间",
    )
