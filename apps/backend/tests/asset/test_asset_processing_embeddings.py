from __future__ import annotations

import asyncio
from functools import wraps
from types import SimpleNamespace


def async_test(function):
    @wraps(function)
    def run(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))

    return run


def _reload_settings(monkeypatch, **env):
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    from app.core.config import get_settings

    get_settings.cache_clear()


class TestAttachmentEmbeddingEnabled:
    """附件向量检索启用的配置判定。"""

    def test_disabled_without_config(self, monkeypatch):
        _reload_settings(
            monkeypatch,
            ATTACHMENT_EMBEDDING_MODEL="",
            ATTACHMENT_EMBEDDING_DIMENSION="",
        )
        from app.modules.asset_processing.runtime import (
            attachment_embedding_enabled,
        )

        assert attachment_embedding_enabled() is False

    def test_enabled_with_api_key(self, monkeypatch):
        _reload_settings(
            monkeypatch,
            ATTACHMENT_EMBEDDING_MODEL="text-embedding-3-small",
            ATTACHMENT_EMBEDDING_DIMENSION="3",
            ATTACHMENT_EMBEDDING_API_KEY="test-key",
        )
        from app.modules.asset_processing.runtime import (
            attachment_embedding_enabled,
        )

        assert attachment_embedding_enabled() is True

    def test_enabled_with_local_endpoint_without_key(self, monkeypatch):
        _reload_settings(
            monkeypatch,
            ATTACHMENT_EMBEDDING_MODEL="embeddinggemma",
            ATTACHMENT_EMBEDDING_DIMENSION="768",
            ATTACHMENT_EMBEDDING_BASE_URL="http://localhost:11434/v1",
        )
        from app.modules.asset_processing.runtime import (
            attachment_embedding_enabled,
        )

        assert attachment_embedding_enabled() is True


class TestBuildAttachmentEmbeddings:
    """解析完成后批量生成并持久化切块向量。"""

    @async_test
    async def test_persists_embeddings_for_chunks(self, monkeypatch):
        _reload_settings(
            monkeypatch,
            ATTACHMENT_EMBEDDING_MODEL="text-embedding-3-small",
            ATTACHMENT_EMBEDDING_DIMENSION="3",
            ATTACHMENT_EMBEDDING_API_KEY="test-key",
            ATTACHMENT_EMBEDDING_PROVIDER="openai",
        )
        from app.modules.asset_processing import services

        class FakeModel:
            async def aget_text_embedding_batch(self, texts):
                assert texts == ["切块一", "切块二"]
                return [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]

        monkeypatch.setattr(
            services,
            "build_attachment_embedding_model",
            lambda _model_config: FakeModel(),
        )

        class FakeRepo:
            def __init__(self):
                self.saved = None

            async def save_embeddings(self, embeddings):
                self.saved = embeddings

        repo = FakeRepo()
        record = SimpleNamespace(id=7, asset_id=3, conversation_id=9)
        chunks = [
            SimpleNamespace(id=1, content="切块一"),
            SimpleNamespace(id=2, content="切块二"),
        ]

        await services._build_attachment_embeddings(repo, record, chunks)

        assert repo.saved is not None
        assert len(repo.saved) == 2
        assert repo.saved[0]["chunk_id"] == 1
        assert repo.saved[0]["processing_id"] == 7
        assert repo.saved[0]["conversation_id"] == 9
        assert repo.saved[0]["asset_id"] == 3
        assert repo.saved[0]["model"] == "text-embedding-3-small"
        assert repo.saved[0]["dimension"] == 3
        assert repo.saved[0]["embedding"] == [0.1, 0.2, 0.3]

    @async_test
    async def test_skips_when_dimension_mismatch(self, monkeypatch):
        _reload_settings(
            monkeypatch,
            ATTACHMENT_EMBEDDING_MODEL="text-embedding-3-small",
            ATTACHMENT_EMBEDDING_DIMENSION="3",
            ATTACHMENT_EMBEDDING_API_KEY="test-key",
        )
        from app.modules.asset_processing import services

        class FakeModel:
            async def aget_text_embedding_batch(self, texts):
                return [[0.1, 0.2]]

        monkeypatch.setattr(
            services,
            "build_attachment_embedding_model",
            lambda _model_config: FakeModel(),
        )

        class FakeRepo:
            def __init__(self):
                self.saved = None

            async def save_embeddings(self, embeddings):
                self.saved = embeddings

        repo = FakeRepo()
        record = SimpleNamespace(id=7, asset_id=3, conversation_id=9)

        await services._build_attachment_embeddings(
            repo, record, [SimpleNamespace(id=1, content="切块一")]
        )

        assert repo.saved is None

    @async_test
    async def test_embedding_failure_degrades_gracefully(self, monkeypatch):
        _reload_settings(
            monkeypatch,
            ATTACHMENT_EMBEDDING_MODEL="text-embedding-3-small",
            ATTACHMENT_EMBEDDING_DIMENSION="3",
            ATTACHMENT_EMBEDDING_API_KEY="test-key",
        )
        from app.modules.asset_processing import services

        class FakeModel:
            async def aget_text_embedding_batch(self, texts):
                raise RuntimeError("embedding service unavailable")

        monkeypatch.setattr(
            services,
            "build_attachment_embedding_model",
            lambda _model_config: FakeModel(),
        )

        class FakeRepo:
            def __init__(self):
                self.saved = None

            async def save_embeddings(self, embeddings):
                self.saved = embeddings

        repo = FakeRepo()
        record = SimpleNamespace(id=7, asset_id=3, conversation_id=9)

        await services._build_attachment_embeddings(
            repo, record, [SimpleNamespace(id=1, content="切块一")]
        )

        assert repo.saved is None

    @async_test
    async def test_disabled_does_not_call_embedding(self, monkeypatch):
        _reload_settings(
            monkeypatch,
            ATTACHMENT_EMBEDDING_MODEL="",
            ATTACHMENT_EMBEDDING_DIMENSION="",
        )
        from app.modules.asset_processing import services

        called = False

        def fake_build():
            nonlocal called
            called = True
            raise AssertionError("不应构建 embedding 模型")

        monkeypatch.setattr(services, "build_attachment_embedding_model", fake_build)

        class FakeRepo:
            async def save_embeddings(self, embeddings):
                raise AssertionError("不应保存向量")

        await services._build_attachment_embeddings(
            FakeRepo(),
            SimpleNamespace(id=7, asset_id=3, conversation_id=9),
            [SimpleNamespace(id=1, content="切块一")],
        )

        assert called is False
