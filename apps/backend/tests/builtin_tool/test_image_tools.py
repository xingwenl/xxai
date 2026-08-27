import asyncio
from types import SimpleNamespace

import pytest

from app.modules.tools.basic.framework import BasicToolError
from app.modules.tools.basic.image_gen import generate_images
from app.modules.tools.business.framework import (
    BusinessToolContext,
    BusinessToolError,
)
from app.modules.tools.business.registry import get_business_tool


class FakeAssetRepo:
    def __init__(self):
        self.items = []

    async def create(self, **values):
        asset = SimpleNamespace(**values)
        self.items.append(asset)
        return asset

    async def get_for_user_conversation(self, *_args):
        return None

    async def get_for_embed_conversation(self, **_kwargs):
        return None


class FakeImages:
    async def generate(self, **kwargs):
        assert "response_format" not in kwargs
        return SimpleNamespace(data=[SimpleNamespace(b64_json="iVBORw0KGgo=")])


class FakeClient:
    images = FakeImages()


@pytest.fixture
def image_settings(tmp_path, monkeypatch):
    settings = SimpleNamespace(
        openai_api_key="test-key",
        openai_base_url=None,
        openai_image_model="gpt-image-1",
        image_generation_timeout_seconds=10,
        read_image_timeout_seconds=10,
        read_image_model="vision-model",
        read_image_base_url=None,
        read_image_api_key=None,
        image_max_bytes=1024 * 1024,
        image_max_count=4,
        agent_file_storage_path=str(tmp_path),
        builtin_http_get_timeout_seconds=2,
        builtin_http_get_text_max_bytes=1000,
        builtin_http_get_text_max_chars=1000,
    )
    monkeypatch.setattr(
        "app.modules.tools.basic.image_gen.get_settings", lambda: settings
    )
    monkeypatch.setattr(
        "app.modules.tools.basic.http_get.get_settings", lambda: settings
    )
    monkeypatch.setattr(
        "app.modules.tools.business.image_generate.get_settings", lambda: settings
    )
    monkeypatch.setattr(
        "app.modules.tools.business.image_read.get_settings", lambda: settings
    )
    return settings


async def _no_model(*_args, **_kwargs):
    return None


def _business_ctx(repo, **kwargs) -> BusinessToolContext:
    values = dict(
        platform_id=1,
        agent_id=2,
        conversation_id=3,
        user_id=4,
        platform_end_user_id=None,
        session=None,
        asset_repo=repo,
    )
    values.update(kwargs)
    return BusinessToolContext(**values)


def test_generate_images_persists_base64_output(image_settings, monkeypatch):
    repo = FakeAssetRepo()
    monkeypatch.setattr(
        "app.modules.tools.basic.image_gen.AsyncOpenAI",
        lambda **_kwargs: FakeClient(),
    )
    monkeypatch.setattr(
        "app.modules.tools.business.image_generate.resolve_agent_model", _no_model
    )
    tool = get_business_tool("image_generate")
    result = asyncio.run(tool.handler({"prompt": "a red kite"}, _business_ctx(repo)))

    assert result["kind"] == "image"
    assert result["assets"][0]["content_type"] == "image/png"
    assert result["assets"][0]["download_url"].startswith("/api/v1/assets/")
    assert len(repo.items) == 1


def test_generate_images_requires_api_key(monkeypatch):
    monkeypatch.setattr(
        "app.modules.tools.basic.image_gen.get_settings",
        lambda: SimpleNamespace(openai_api_key=None, image_max_count=4),
    )

    with pytest.raises(BasicToolError) as exc:
        asyncio.run(
            generate_images(
                {
                    "prompt": "test",
                    "model": {"model_name": "gpt-image-1", "api_key": None},
                }
            )
        )
    assert str(exc.value) == "image_generation_not_configured"


def test_generate_images_uses_bound_model_config(image_settings, monkeypatch):
    captured = {}

    class RecordingClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.images = FakeImages()

    monkeypatch.setattr(
        "app.modules.tools.basic.image_gen.AsyncOpenAI", RecordingClient
    )
    result = asyncio.run(
        generate_images(
            {
                "prompt": "a red kite",
                "model": {
                    "model_name": "gpt-image-1",
                    "base_url": "https://gateway.example.com/v1",
                    "api_key": "bound-key",
                    "options": {},
                },
            }
        )
    )

    assert captured["api_key"] == "bound-key"
    assert captured["base_url"] == "https://gateway.example.com/v1"
    assert result["images"][0]["size_bytes"] > 0


def test_generate_images_bound_model_without_key_fails(image_settings):
    with pytest.raises(BasicToolError) as exc:
        asyncio.run(
            generate_images(
                {
                    "prompt": "test",
                    "model": {"model_name": "gpt-image-1", "api_key": None},
                }
            )
        )
    assert str(exc.value) == "image_generation_not_configured"


class _FakeHttpTool:
    async def handler(self, inputs):
        return {
            "kind": "text",
            "temp_path": None,
            "final_url": "https://example.com/not-image.txt",
        }


def test_read_image_rejects_non_image_result(monkeypatch, image_settings):
    monkeypatch.setattr(
        "app.modules.tools.business.image_read.get_basic_tool",
        lambda _name: _FakeHttpTool(),
    )
    monkeypatch.setattr(
        "app.modules.tools.business.image_read.resolve_agent_model", _no_model
    )
    tool = get_business_tool("image_read")
    with pytest.raises(BusinessToolError) as exc:
        asyncio.run(
            tool.handler(
                {"url": "https://example.com/not-image.txt"},
                _business_ctx(FakeAssetRepo()),
            )
        )
    assert str(exc.value) == "image_required"


def test_read_image_description_non_json_response_logs_hint(
    monkeypatch, image_settings, caplog, tmp_path
):
    monkeypatch.setattr(
        "app.modules.asset.services.get_settings",
        lambda: SimpleNamespace(agent_file_storage_path=str(tmp_path)),
    )
    storage_path = tmp_path / "sample.png"
    storage_path.write_bytes(b"fake-image-bytes")
    asset = SimpleNamespace(
        asset_id="asset-1",
        storage_key="sample.png",
        filename="sample.png",
        content_type="image/png",
        size_bytes=16,
    )

    class BrokenChat:
        def __init__(self, **_kwargs):
            pass

        async def ainvoke(self, messages):
            raise AttributeError("'str' object has no attribute 'model_dump'")

    monkeypatch.setattr("langchain_openai.ChatOpenAI", BrokenChat)

    class Repo:
        async def get_for_embed_conversation(self, *_args, **_kwargs):
            return asset

    async def bound_model(*_args, **_kwargs):
        return SimpleNamespace(
            model_name="vision-model",
            base_url="https://example.com",
            api_key="k",
            capabilities=None,
            options={},
        )

    monkeypatch.setattr(
        "app.modules.tools.business.image_read.resolve_agent_model", bound_model
    )
    tool = get_business_tool("image_read")
    result = asyncio.run(
        tool.handler(
            {"asset_id": "asset-1"},
            _business_ctx(Repo(), user_id=None, platform_end_user_id=9),
        )
    )

    assert result["kind"] == "image"
    assert result["asset"]["asset_id"] == "asset-1"
    assert result["description"] is None
    assert "vision.describe failed" in caplog.text
    assert "非 JSON" in caplog.text
