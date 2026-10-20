from __future__ import annotations

import asyncio
from functools import wraps
from types import SimpleNamespace

import pytest

from app.modules.asset_processing.models import (
    ConversationAssetChunk,
    ConversationAssetProcessing,
    ProcessingStatus,
)


def async_test(function):
    @wraps(function)
    def run(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))

    return run


class TestProcessingStatus:
    """处理状态枚举覆盖。"""

    def test_status_values(self):
        assert ProcessingStatus.uploaded == "uploaded"
        assert ProcessingStatus.processing == "processing"
        assert ProcessingStatus.ready == "ready"
        assert ProcessingStatus.failed == "failed"
        assert ProcessingStatus.unsupported == "unsupported"

    def test_status_transitions_ready(self):
        assert ProcessingStatus.can_transition("ready", "processing")

    def test_status_transitions_failed(self):
        assert ProcessingStatus.can_transition("failed", "processing")

    def test_status_transitions_reject_during_processing(self):
        assert not ProcessingStatus.can_transition("processing", "processing")

    def test_status_transitions_unsupported(self):
        assert ProcessingStatus.can_transition("unsupported", "processing")


class TestProcessingModels:
    """确保处理记录和 chunk 模型字段都有中文 comment。"""

    def test_processing_model_has_comments(self):
        for col in ConversationAssetProcessing.__table__.columns:
            assert col.comment, (
                f"ConversationAssetProcessing.{col.name} 缺少中文 comment"
            )

    def test_chunk_model_has_comments(self):
        for col in ConversationAssetChunk.__table__.columns:
            assert col.comment, (
                f"ConversationAssetChunk.{col.name} 缺少中文 comment"
            )

    def test_processing_has_required_fields(self):
        cols = {c.name for c in ConversationAssetProcessing.__table__.columns}
        required = {
            "id", "asset_id", "conversation_id", "status",
            "parser_name", "parser_version", "chunk_size", "chunk_overlap",
            "extracted_text_storage_key", "error_message",
            "started_at", "completed_at", "created_at", "updated_at",
        }
        missing = required - cols
        assert not missing, f"ConversationAssetProcessing 缺少字段: {missing}"

    def test_chunk_has_required_fields(self):
        cols = {c.name for c in ConversationAssetChunk.__table__.columns}
        required = {
            "id", "processing_id", "conversation_id", "asset_id",
            "position", "content", "page_number", "token_count",
            "created_at", "updated_at",
        }
        missing = required - cols
        assert not missing, f"ConversationAssetChunk 缺少字段: {missing}"


class TestUploadValidation:
    """上传接口的 MIME、大小、扩展名校验。"""

    def test_allowed_mime_types(self):
        from app.modules.asset_processing.runtime import ALLOWED_MIME_TYPES
        allowed = ALLOWED_MIME_TYPES
        assert "text/plain" in allowed
        assert "text/markdown" in allowed
        assert "application/pdf" in allowed
        assert "application/vnd.openxmlformats-officedocument.wordprocessingml.document" in allowed
        assert "image/png" in allowed
        assert "image/jpeg" in allowed
        assert "image/gif" in allowed
        assert "image/webp" in allowed

    def test_reject_unknown_mime(self):
        from app.modules.asset_processing.runtime import ALLOWED_MIME_TYPES
        assert "application/x-msdownload" not in ALLOWED_MIME_TYPES


class TestAssetIsolation:
    """附件必须绑定当前会话，跨会话访问应被拒绝。"""

    @async_test
    async def test_reject_cross_conversation_asset(self):
        from app.modules.asset_processing.services import (
            validate_asset_conversation,
        )

        class FakeAsset:
            conversation_id = 10

        from app.shared.exceptions import BadRequestException
        with pytest.raises(BadRequestException, match="不"):
            validate_asset_conversation(FakeAsset(), 20)


class TestGatewayAttachmentSchema:
    """message_send 中的 attachments 字段校验。"""

    def test_attachments_field_optional(self):
        from app.modules.gateway.schemas import MessageSendPayload
        payload = MessageSendPayload(text="你好")
        assert payload.attachments is None or payload.attachments == []

    def test_attachments_with_valid_asset_id(self):
        from app.modules.gateway.schemas import MessageSendPayload, AttachmentRef
        payload = MessageSendPayload(
            text="分析附件",
            attachments=[
                AttachmentRef(
                    assetId="abc123def456",
                    filename="report.pdf",
                    mimeType="application/pdf",
                    size=12345,
                )
            ],
        )
        assert len(payload.attachments) == 1
        assert payload.attachments[0].assetId == "abc123def456"

    def test_attachments_empty_asset_id_rejected(self):
        from app.modules.gateway.schemas import AttachmentRef
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            AttachmentRef(assetId="", filename="report.pdf", mimeType="application/pdf", size=12345)

    def test_attachments_max_limit(self):
        from app.modules.gateway.schemas import MessageSendPayload, AttachmentRef
        from pydantic import ValidationError
        refs = [
            AttachmentRef(assetId=f"asset_{i}", filename=f"file_{i}.pdf", mimeType="application/pdf", size=100)
            for i in range(20)
        ]
        with pytest.raises(ValidationError):
            MessageSendPayload(text="分析", attachments=refs)

    def test_asset_id_format_validation(self):
        from app.modules.gateway.schemas import AttachmentRef
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            AttachmentRef(assetId="../../../etc/passwd", filename="evil.pdf", mimeType="application/pdf", size=100)


class FakeProcessingRepo:
    """记录 update_processing / create_chunks 调用的最小仓库替身。"""

    def __init__(self) -> None:
        self.session = object()
        self.updates: list[dict] = []
        self.chunks: list[dict] = []

    async def update_processing(self, record, **values):
        self.updates.append(values)
        record.status = values.get("status", getattr(record, "status", None))
        return record

    async def create_chunks(self, records):
        self.chunks.extend(records)
        return [SimpleNamespace(**item) for item in records]


def _parse_asset():
    return SimpleNamespace(
        id=1,
        asset_id="a" * 32,
        filename="scores.xlsx",
        conversation_id=9,
        content_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        storage_key="assets/1/scores.xlsx",
        platform_id=1,
        agent_id=2,
    )


def _processing_record():
    return SimpleNamespace(id=1, chunk_size=512, chunk_overlap=50, status=None)


class TestExecuteProcessingFailures:
    """解析失败必须落成 failed；静默 ready 会让附件永远检索不到内容。"""

    @async_test
    async def test_parse_error_marks_failed(self, monkeypatch):
        from app.modules.asset_processing import services

        def _raise(*_args, **_kwargs):
            raise ValueError("未能从文件解析出文本（嗅探格式: markup）: scores.xlsx")

        monkeypatch.setattr(services, "load_file_text", _raise)
        repo = FakeProcessingRepo()

        result = await services.execute_processing(
            repo, _parse_asset(), _processing_record()
        )

        assert result.status == ProcessingStatus.failed
        assert "未能从文件解析出文本" in repo.updates[-1]["error_message"]
        assert repo.chunks == []

    @async_test
    async def test_empty_text_marks_failed(self, monkeypatch):
        from app.modules.asset_processing import services

        monkeypatch.setattr(services, "load_file_text", lambda *_a, **_k: "   ")
        repo = FakeProcessingRepo()

        result = await services.execute_processing(
            repo, _parse_asset(), _processing_record()
        )

        assert result.status == ProcessingStatus.failed
        assert "未能从文件中解析出文本" in repo.updates[-1]["error_message"]
        assert repo.chunks == []


class TestSplitTextToChunks:
    """切块必须走 SentenceSplitter，不能静默退化成按字符硬切。"""

    def test_sentences_are_not_cut_in_the_middle(self):
        from app.modules.asset_processing.services import _split_text_to_chunks

        text = "这是第一句话，用于验证切块不会切断句子。" * 80

        chunks = _split_text_to_chunks(text, chunk_size=128, chunk_overlap=16)

        assert len(chunks) > 1
        assert all(chunk["text"].endswith("。") for chunk in chunks)
        assert all(chunk["token_count"] >= 1 for chunk in chunks)
