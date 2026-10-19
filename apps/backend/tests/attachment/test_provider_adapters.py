from __future__ import annotations

import asyncio
from functools import wraps
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.modules.attachment import provider
from app.modules.attachment.provider import (
    ProviderAttachmentCapabilities,
    image_reference_text_part,
    is_openrouter,
    resolve_attachment_capabilities,
)
from app.modules.gateway import runtime as gateway_runtime


def async_test(function):
    @wraps(function)
    def run(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))

    return run


def _version(**overrides):
    values = {
        "model_name": "deepseek/deepseek-v4-flash",
        "model_base_url": "https://openrouter.ai/api/v1",
        "api_key_encrypted": None,
        "capabilities": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _resolve(version, **overrides):
    """按新签名解析：模型三要素由调用方显式传入（版本行只贡献 capabilities）。"""
    return resolve_attachment_capabilities(
        version,
        model_name=overrides.pop("model_name", version.model_name),
        base_url=overrides.pop("base_url", version.model_base_url),
        api_key=overrides.pop("api_key", version.api_key_encrypted),
    )


@pytest.fixture(autouse=True)
def _clear_capability_cache():
    provider._CAPABILITY_CACHE.clear()
    yield
    provider._CAPABILITY_CACHE.clear()


@pytest.fixture
def capability_settings(monkeypatch):
    settings = SimpleNamespace(
        provider_capability_cache_ttl_seconds=600,
        provider_capability_query_timeout_seconds=5,
    )
    monkeypatch.setattr(provider, "get_settings", lambda: settings)
    return settings


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeAsyncClient:
    """记录请求并按测试预设返回模型元数据。"""

    payload = {"data": []}
    calls: list[dict] = []

    def __init__(self, **kwargs):
        self._kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def get(self, url, headers=None):
        FakeAsyncClient.calls.append({"url": url, "headers": headers})
        return FakeResponse(FakeAsyncClient.payload)


class TestProviderAttachmentCapabilities:
    """能力矩阵的配置映射与默认值。"""

    def test_full_mapping(self):
        capabilities = ProviderAttachmentCapabilities.from_mapping(
            {"image": True, "native_file": True, "text_retrieval": True}
        )
        assert capabilities.image is True
        assert capabilities.native_file is True
        assert capabilities.text_retrieval is True

    def test_partial_mapping_defaults(self):
        capabilities = ProviderAttachmentCapabilities.from_mapping({"image": True})
        assert capabilities.image is True
        assert capabilities.native_file is False
        assert capabilities.text_retrieval is True

    def test_invalid_mapping_rejected(self):
        assert ProviderAttachmentCapabilities.from_mapping({"image": "yes"}) is None
        assert ProviderAttachmentCapabilities.from_mapping(None) is None


class TestModelNameFallback:
    """按模型名兜底推导能力。"""

    def test_vision_keywords(self):
        for name in (
            "qwen2.5-vl-7b",
            "openai/gpt-4o",
            "google/gemini-2.0-flash",
            "anthropic/claude-3.5-sonnet",
        ):
            assert _infer(name).image is True, name

    def test_text_only_keywords(self):
        for name in (
            "deepseek/deepseek-chat",
            "openai/gpt-3.5-turbo",
            "qwen-turbo",
        ):
            assert _infer(name).image is False, name

    def test_unknown_model_conservative(self):
        assert _infer("custom/unknown-model").image is False
        assert _infer("custom/unknown-model").text_retrieval is True

    def test_vision_wins_over_text_keyword(self):
        # deepseek 视觉实验模型同时命中文本与视觉关键词，视觉必须优先
        assert _infer("deepseek/deepseek-v4-flash-vision-exp").image is True


def _infer(model_name):
    return provider._infer_from_model_name(model_name)


class TestOpenRouterQuery:
    """OpenRouter /models 实时探测与缓存。"""

    @async_test
    async def test_query_resolves_modalities(self, monkeypatch, capability_settings):
        FakeAsyncClient.calls.clear()
        FakeAsyncClient.payload = {
            "data": [
                {
                    "id": "deepseek/deepseek-v4-flash-vision-exp",
                    "architecture": {"input_modalities": ["text", "image"]},
                }
            ]
        }
        monkeypatch.setattr(provider.httpx, "AsyncClient", FakeAsyncClient)

        version = _version(model_name="deepseek/deepseek-v4-flash-vision-exp")
        capabilities = await _resolve(version)

        assert capabilities.image is True
        assert capabilities.native_file is False
        assert len(FakeAsyncClient.calls) == 1
        assert FakeAsyncClient.calls[0]["url"] == "https://openrouter.ai/api/v1/models"

    @async_test
    async def test_result_cached(self, monkeypatch, capability_settings):
        FakeAsyncClient.calls.clear()
        FakeAsyncClient.payload = {
            "data": [
                {
                    "id": "openai/gpt-4o",
                    "architecture": {"input_modalities": ["text", "image"]},
                }
            ]
        }
        monkeypatch.setattr(provider.httpx, "AsyncClient", FakeAsyncClient)

        version = _version(model_name="openai/gpt-4o")
        first = await _resolve(version)
        second = await _resolve(version)

        assert first.image is True
        assert second.image is True
        assert len(FakeAsyncClient.calls) == 1

    @async_test
    async def test_query_failure_falls_back_to_model_name(
        self, monkeypatch, capability_settings
    ):
        class BrokenClient:
            def __init__(self, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            async def get(self, url, headers=None):
                raise OSError("network down")

        monkeypatch.setattr(provider.httpx, "AsyncClient", BrokenClient)

        capabilities = await _resolve(_version(model_name="google/gemini-2.0-flash"))

        assert capabilities.image is True


class TestResolveCapabilities:
    """能力解析优先级：显式配置 > OpenRouter > 模型名。"""

    @async_test
    async def test_explicit_config_wins(self, monkeypatch, capability_settings):
        version = _version(
            model_name="deepseek/deepseek-chat",
            capabilities={"image": False, "native_file": False},
        )
        capabilities = await _resolve(version)
        assert capabilities.image is False

    @async_test
    async def test_non_openrouter_uses_model_name(
        self, monkeypatch, capability_settings
    ):
        monkeypatch.setattr(provider.httpx, "AsyncClient", FakeAsyncClient)
        version = _version(model_base_url="https://api.deepseek.com/v1")
        capabilities = await _resolve(version)
        assert capabilities.image is False


def test_is_openrouter():
    assert is_openrouter("https://openrouter.ai/api/v1") is True
    assert is_openrouter("https://api.deepseek.com/v1") is False
    assert is_openrouter(None) is False


def test_image_reference_text_part():
    asset = SimpleNamespace(
        asset_id="asset_1",
        filename="pic.png",
        content_type="image/png",
        size_bytes=1024,
    )
    part = image_reference_text_part(asset)
    assert part["type"] == "text"
    assert "pic.png" in part["text"]
    assert "/api/v1/assets/asset_1" in part["text"]
    assert "image_read" in part["text"]


class TestGatewayImageAdaptation:
    """网关按能力矩阵适配图片输入。"""

    def _asset(self, tmp_path):
        original = tmp_path / "original.png"
        original.write_bytes(b"fake-image-bytes")
        return SimpleNamespace(
            id=1,
            asset_id="img-1",
            filename="pic.png",
            content_type="image/png",
            storage_key=str(original),
            size_bytes=1024,
        )

    async def _call(self, tmp_path, monkeypatch, capabilities):
        asset = self._asset(tmp_path)
        monkeypatch.setattr(
            gateway_runtime, "resolve_asset_path", lambda path: Path(path)
        )

        class FakeAssetRepository:
            def __init__(self, session):
                self.session = session

            async def get_for_embed_conversation(self, asset_id, **kwargs):
                return asset

        class FakeProcessingRepository:
            def __init__(self, session):
                self.session = session

            async def get_processing(self, asset_id, conversation_id):
                return SimpleNamespace(
                    status="ready",
                    extracted_text=None,
                    extracted_text_storage_key=None,
                )

        parts, _block = await gateway_runtime._load_single_attachment_parts(
            FakeAssetRepository(None),
            FakeProcessingRepository(None),
            asset_id="img-1",
            conversation_id=1,
            platform_id=1,
            agent_id=2,
            end_user_id=3,
            capabilities=capabilities,
        )
        return parts

    @async_test
    async def test_vision_model_gets_image_url(self, tmp_path, monkeypatch):
        parts = await self._call(
            tmp_path,
            monkeypatch,
            ProviderAttachmentCapabilities(image=True),
        )
        assert parts[0]["type"] == "image_url"
        assert parts[0]["image_url"]["url"].startswith("data:image/png;base64,")

    @async_test
    async def test_text_only_model_gets_reference(self, tmp_path, monkeypatch):
        parts = await self._call(
            tmp_path,
            monkeypatch,
            ProviderAttachmentCapabilities(image=False),
        )
        assert parts[0]["type"] == "text"
        assert "pic.png" in parts[0]["text"]
        assert "image_read" in parts[0]["text"]

    @async_test
    async def test_unspecified_capabilities_defaults_to_vision(
        self, tmp_path, monkeypatch
    ):
        parts = await self._call(tmp_path, monkeypatch, None)
        assert parts[0]["type"] == "image_url"
