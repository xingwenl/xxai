from __future__ import annotations

import asyncio
from functools import wraps
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.modules.asset_processing.models import ProcessingStatus
from app.modules.gateway import runtime as gateway_runtime


def async_test(function):
    @wraps(function)
    def run(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))

    return run


def _conversation():
    return SimpleNamespace(id=1)


def _attachment(asset_id: str, filename: str, mime_type: str) -> dict:
    return {
        "assetId": asset_id,
        "filename": filename,
        "mimeType": mime_type,
        "size": 1024,
    }


@pytest.fixture
def attachment_repos(monkeypatch, tmp_path):
    """替换网关运行时使用的 asset/processing 仓库与存储解析。"""

    class FakeAssetRepository:
        def __init__(self, session):
            self.session = session

        async def get_for_embed_conversation(self, asset_id, **kwargs):
            if asset_id.startswith("img"):
                filename, mime_type = "pic.png", "image/png"
            else:
                filename, mime_type = "report.pdf", "application/pdf"
            return SimpleNamespace(
                id=asset_id,
                asset_id=asset_id,
                filename=filename,
                content_type=mime_type,
                storage_key=str(tmp_path / "original.bin"),
                size_bytes=1024,
            )

    monkeypatch.setattr(gateway_runtime, "AssetRepository", FakeAssetRepository)
    monkeypatch.setattr(
        gateway_runtime,
        "resolve_asset_path",
        lambda path: Path(path) if Path(path).exists() else tmp_path / Path(path).name,
    )
    return SimpleNamespace(tmp_path=tmp_path)


class TestLoadEmbedAttachmentParts:
    """网关按会话读取附件并转换为模型内容块。"""

    @async_test
    async def test_no_attachments_returns_empty(self):
        (
            image_parts,
            document_text_parts,
            blocks,
        ) = await gateway_runtime._load_embed_attachment_parts(
            SimpleNamespace(session=None),
            _conversation(),
            attachments=None,
            platform_id=1,
            agent_id=2,
            end_user_id=3,
        )

        assert image_parts == []
        assert document_text_parts == []
        assert blocks == []

    @async_test
    async def test_document_injects_extracted_text_and_file_block(
        self, monkeypatch, attachment_repos, tmp_path
    ):
        class FakeProcessingRepository:
            def __init__(self, session):
                self.session = session

            async def get_processing(self, asset_id, conversation_id):
                return SimpleNamespace(
                    status=ProcessingStatus.ready,
                    extracted_text="季度营收增长 30%",
                    extracted_text_storage_key=None,
                )

        monkeypatch.setattr(
            gateway_runtime,
            "AssetProcessingRepository",
            FakeProcessingRepository,
        )

        (
            image_parts,
            document_text_parts,
            blocks,
        ) = await gateway_runtime._load_embed_attachment_parts(
            SimpleNamespace(session=None),
            _conversation(),
            attachments=[_attachment("doc-1", "report.pdf", "application/pdf")],
            platform_id=1,
            agent_id=2,
            end_user_id=3,
        )

        assert image_parts == []
        assert len(document_text_parts) == 1
        assert document_text_parts[0]["type"] == "text"
        assert "季度营收增长 30%" in document_text_parts[0]["text"]
        assert "report.pdf" in document_text_parts[0]["text"]
        assert blocks[0]["type"] == "file"
        assert blocks[0]["fileName"] == "report.pdf"
        assert blocks[0]["asset_id"] == "doc-1"
        assert blocks[0]["url"] == "/api/v1/assets/doc-1"

    @async_test
    async def test_document_falls_back_to_storage_file_when_cache_missing(
        self, monkeypatch, attachment_repos, tmp_path
    ):
        extracted = tmp_path / "report.txt"
        extracted.write_text("旧数据文本", encoding="utf-8")

        class FakeProcessingRepository:
            def __init__(self, session):
                self.session = session

            async def get_processing(self, asset_id, conversation_id):
                return SimpleNamespace(
                    status=ProcessingStatus.ready,
                    extracted_text=None,
                    extracted_text_storage_key=str(extracted),
                )

        monkeypatch.setattr(
            gateway_runtime,
            "AssetProcessingRepository",
            FakeProcessingRepository,
        )

        (
            _image_parts,
            document_text_parts,
            _blocks,
        ) = await gateway_runtime._load_embed_attachment_parts(
            SimpleNamespace(session=None),
            _conversation(),
            attachments=[_attachment("doc-1", "report.pdf", "application/pdf")],
            platform_id=1,
            agent_id=2,
            end_user_id=3,
        )

        assert len(document_text_parts) == 1
        assert "旧数据文本" in document_text_parts[0]["text"]

    @async_test
    async def test_document_truncation_adds_search_hint(
        self, monkeypatch, attachment_repos, tmp_path
    ):
        class FakeProcessingRepository:
            def __init__(self, session):
                self.session = session

            async def get_processing(self, asset_id, conversation_id):
                return SimpleNamespace(
                    status=ProcessingStatus.ready,
                    extracted_text="长文档内容。" * 4000,
                    extracted_text_storage_key=None,
                )

        monkeypatch.setattr(
            gateway_runtime,
            "AssetProcessingRepository",
            FakeProcessingRepository,
        )

        (
            _image_parts,
            document_text_parts,
            _blocks,
        ) = await gateway_runtime._load_embed_attachment_parts(
            SimpleNamespace(session=None),
            _conversation(),
            attachments=[_attachment("doc-1", "report.pdf", "application/pdf")],
            platform_id=1,
            agent_id=2,
            end_user_id=3,
        )

        assert len(document_text_parts) == 1
        assert "以上仅为开头部分" in document_text_parts[0]["text"]
        assert "attachment_search" in document_text_parts[0]["text"]
        assert len(document_text_parts[0]["text"]) < 17000

    @async_test
    async def test_document_uses_retrieval_when_query_and_embedding_enabled(
        self, monkeypatch, attachment_repos, tmp_path
    ):
        class FakeProcessingRepository:
            def __init__(self, session):
                self.session = session

            async def get_processing(self, asset_id, conversation_id):
                return SimpleNamespace(
                    status=ProcessingStatus.ready,
                    extracted_text="季度营收增长 30%（全文不会被注入）",
                    extracted_text_storage_key=None,
                )

        monkeypatch.setattr(
            gateway_runtime,
            "AssetProcessingRepository",
            FakeProcessingRepository,
        )
        monkeypatch.setattr(
            gateway_runtime,
            "attachment_embedding_enabled",
            lambda _model_config: True,
        )

        async def fake_retrieve(
            processing_repo,
            asset,
            processing,
            conversation_id,
            query,
            *,
            model_config=None,
        ):
            assert query == "总金额是多少"
            return [
                (SimpleNamespace(position=0, content="金额: 100"), 0.92),
                (SimpleNamespace(position=3, content="统计: 总金额 100"), 0.85),
            ]

        monkeypatch.setattr(
            gateway_runtime,
            "_retrieve_attachment_chunks",
            fake_retrieve,
        )

        (
            _image_parts,
            document_text_parts,
            _blocks,
        ) = await gateway_runtime._load_embed_attachment_parts(
            SimpleNamespace(session=None),
            _conversation(),
            attachments=[_attachment("doc-1", "report.pdf", "application/pdf")],
            platform_id=1,
            agent_id=2,
            end_user_id=3,
            query="总金额是多少",
        )

        assert len(document_text_parts) == 1
        assert "[第1段] 金额: 100" in document_text_parts[0]["text"]
        assert "[第4段] 统计: 总金额 100" in document_text_parts[0]["text"]
        assert "全文不会被注入" not in document_text_parts[0]["text"]
        assert "可调用 attachment_search 工具" in document_text_parts[0]["text"]

    @async_test
    async def test_document_falls_back_to_full_text_when_retrieval_fails(
        self, monkeypatch, attachment_repos, tmp_path
    ):
        class FakeProcessingRepository:
            def __init__(self, session):
                self.session = session

            async def get_processing(self, asset_id, conversation_id):
                return SimpleNamespace(
                    status=ProcessingStatus.ready,
                    extracted_text="季度营收增长 30%",
                    extracted_text_storage_key=None,
                )

        monkeypatch.setattr(
            gateway_runtime,
            "AssetProcessingRepository",
            FakeProcessingRepository,
        )
        monkeypatch.setattr(
            gateway_runtime,
            "attachment_embedding_enabled",
            lambda _model_config: True,
        )

        async def fake_retrieve(
            processing_repo,
            asset,
            processing,
            conversation_id,
            query,
            *,
            model_config=None,
        ):
            raise RuntimeError("embedding service unavailable")

        monkeypatch.setattr(
            gateway_runtime,
            "_retrieve_attachment_chunks",
            fake_retrieve,
        )

        (
            _image_parts,
            document_text_parts,
            _blocks,
        ) = await gateway_runtime._load_embed_attachment_parts(
            SimpleNamespace(session=None),
            _conversation(),
            attachments=[_attachment("doc-1", "report.pdf", "application/pdf")],
            platform_id=1,
            agent_id=2,
            end_user_id=3,
            query="总金额是多少",
        )

        assert len(document_text_parts) == 1
        assert "季度营收增长 30%" in document_text_parts[0]["text"]

    @async_test
    async def test_document_not_ready_raises(self, monkeypatch, attachment_repos):
        class FakeProcessingRepository:
            def __init__(self, session):
                self.session = session

            async def get_processing(self, asset_id, conversation_id):
                return SimpleNamespace(
                    status=ProcessingStatus.processing,
                    extracted_text=None,
                    extracted_text_storage_key=None,
                )

        monkeypatch.setattr(
            gateway_runtime,
            "AssetProcessingRepository",
            FakeProcessingRepository,
        )

        with pytest.raises(ValueError, match="asset_not_ready"):
            await gateway_runtime._load_embed_attachment_parts(
                SimpleNamespace(session=None),
                _conversation(),
                attachments=[_attachment("doc-1", "report.pdf", "application/pdf")],
                platform_id=1,
                agent_id=2,
                end_user_id=3,
            )

    @async_test
    async def test_image_still_becomes_data_url(
        self, monkeypatch, attachment_repos, tmp_path
    ):
        original = tmp_path / "original.bin"
        original.write_bytes(b"fake-image-bytes")

        class FakeProcessingRepository:
            def __init__(self, session):
                self.session = session

            async def get_processing(self, asset_id, conversation_id):
                return SimpleNamespace(
                    status=ProcessingStatus.ready,
                    extracted_text=None,
                    extracted_text_storage_key=None,
                )

        monkeypatch.setattr(
            gateway_runtime,
            "AssetProcessingRepository",
            FakeProcessingRepository,
        )
        monkeypatch.setattr(
            gateway_runtime,
            "resolve_asset_path",
            lambda path: tmp_path / Path(path).name,
        )

        (
            image_parts,
            document_text_parts,
            blocks,
        ) = await gateway_runtime._load_embed_attachment_parts(
            SimpleNamespace(session=None),
            _conversation(),
            attachments=[_attachment("img-1", "pic.png", "image/png")],
            platform_id=1,
            agent_id=2,
            end_user_id=3,
        )

        assert len(image_parts) == 1
        assert image_parts[0]["image_url"]["url"].startswith("data:image/png;base64,")
        assert document_text_parts == []
        assert blocks[0]["type"] == "image"
        assert blocks[0]["asset_id"] == "img-1"


class TestLoadHistoryAttachmentParts:
    """历史消息附件内容恢复：按 asset 分组、去重、删除跳过。"""

    def _history_user_message(self, asset_ids, content="分析附件"):
        blocks = [
            {
                "type": "file" if not asset_id.startswith("img") else "image",
                "asset_id": asset_id,
            }
            for asset_id in asset_ids
        ]
        return SimpleNamespace(role="user", content=content, content_blocks=blocks)

    @async_test
    async def test_restores_parts_by_asset_and_dedupes(
        self, monkeypatch, attachment_repos, tmp_path
    ):
        calls = []

        class FakeProcessingRepository:
            def __init__(self, session):
                self.session = session

            async def get_processing(self, asset_id, conversation_id):
                calls.append(asset_id)
                return SimpleNamespace(
                    status=ProcessingStatus.ready,
                    extracted_text=f"内容 {asset_id}",
                    extracted_text_storage_key=None,
                )

        monkeypatch.setattr(
            gateway_runtime,
            "AssetProcessingRepository",
            FakeProcessingRepository,
        )

        history = [
            self._history_user_message(["doc-1"]),
            SimpleNamespace(role="assistant", content="已看过", content_blocks=None),
            self._history_user_message(["doc-1", "doc-2"]),
        ]
        parts = await gateway_runtime._load_history_attachment_parts(
            SimpleNamespace(session=None),
            _conversation(),
            history,
            platform_id=1,
            agent_id=2,
            end_user_id=3,
        )

        assert sorted(parts) == ["doc-1", "doc-2"]
        assert "内容 doc-1" in parts["doc-1"][0]["text"]
        assert "内容 doc-2" in parts["doc-2"][0]["text"]
        assert calls == ["doc-1", "doc-2"]

    @async_test
    async def test_skips_deleted_attachments(self, monkeypatch, attachment_repos):
        class FakeAssetRepository:
            def __init__(self, session):
                self.session = session

            async def get_for_embed_conversation(self, asset_id, **kwargs):
                return None

        class FakeProcessingRepository:
            def __init__(self, session):
                self.session = session

        monkeypatch.setattr(gateway_runtime, "AssetRepository", FakeAssetRepository)
        monkeypatch.setattr(
            gateway_runtime,
            "AssetProcessingRepository",
            FakeProcessingRepository,
        )

        history = [self._history_user_message(["deleted-1"])]
        parts = await gateway_runtime._load_history_attachment_parts(
            SimpleNamespace(session=None),
            _conversation(),
            history,
            platform_id=1,
            agent_id=2,
            end_user_id=3,
        )

        assert parts == {}
