from types import SimpleNamespace
import asyncio

import pytest

from app.modules.builtin_tool import image_generate, image_read
from app.modules.builtin_tool.image_generate import generate_images
from app.modules.builtin_tool.image_read import read_image


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
        image_max_bytes=1024 * 1024,
        image_max_count=4,
        agent_file_storage_path=str(tmp_path),
        builtin_http_get_timeout_seconds=2,
        builtin_http_get_text_max_bytes=1000,
        builtin_http_get_text_max_chars=1000,
    )
    monkeypatch.setattr(image_generate, "get_settings", lambda: settings)
    monkeypatch.setattr(image_read, "get_settings", lambda: settings)
    return settings


def test_generate_images_persists_base64_output(image_settings):
    repo = FakeAssetRepo()
    result = asyncio.run(
        generate_images(
            {"prompt": "a red kite"},
            asset_repo=repo,
            platform_id=1,
            agent_id=2,
            conversation_id=3,
            user_id=4,
            platform_end_user_id=None,
            client=FakeClient(),
        )
    )

    assert result[0]["content_type"] == "image/png"
    assert result[0]["download_url"].startswith("/api/v1/assets/")
    assert len(repo.items) == 1


def test_generate_images_requires_api_key(monkeypatch):
    monkeypatch.setattr(
        image_generate,
        "get_settings",
        lambda: SimpleNamespace(openai_api_key=None, image_max_count=4),
    )

    with pytest.raises(image_generate.ImageGenerationError) as exc:
        asyncio.run(
            generate_images(
                {"prompt": "test"},
                asset_repo=FakeAssetRepo(),
                platform_id=1,
                agent_id=2,
                conversation_id=3,
                user_id=4,
                platform_end_user_id=None,
            )
        )
    assert str(exc.value) == "image_generation_not_configured"


def test_read_image_rejects_non_image_result(monkeypatch, image_settings):
    monkeypatch.setattr(
        image_read,
        "fetch_http_get",
        _fake_fetch(kind="text", temp_path=None),
    )
    with pytest.raises(image_read.ImageReadError) as exc:
        asyncio.run(
            read_image(
                {"url": "https://example.com/not-image.txt"},
                asset_repo=FakeAssetRepo(),
                platform_id=1,
                agent_id=2,
                conversation_id=3,
                user_id=4,
                platform_end_user_id=None,
            )
        )
    assert str(exc.value) == "image_required"


def _fake_fetch(*, kind, temp_path):
    async def fetch(*_args, **_kwargs):
        return SimpleNamespace(kind=kind, temp_path=temp_path)

    return fetch
