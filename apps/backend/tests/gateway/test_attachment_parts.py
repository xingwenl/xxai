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
                id=1,
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
        extracted = tmp_path / "report.txt"
        extracted.write_text("季度营收增长 30%", encoding="utf-8")

        class FakeProcessingRepository:
            def __init__(self, session):
                self.session = session

            async def get_processing(self, asset_id, conversation_id):
                return SimpleNamespace(
                    status=ProcessingStatus.ready,
                    extracted_text_storage_key=str(extracted),
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

    @async_test
    async def test_document_not_ready_raises(self, monkeypatch, attachment_repos):
        class FakeProcessingRepository:
            def __init__(self, session):
                self.session = session

            async def get_processing(self, asset_id, conversation_id):
                return SimpleNamespace(
                    status=ProcessingStatus.processing,
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
