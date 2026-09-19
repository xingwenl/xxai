"""CORS 允许来源配置单测：默认值保持现状，并支持通过环境变量登记新来源。"""

import pytest

from app.core.config import DEFAULT_CORS_ORIGINS, get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    """get_settings 带 lru_cache，环境变量变更前后都需要清理。"""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_cors_origins_default_matches_legacy_list(monkeypatch):
    """未配置 CORS_ORIGINS 时，允许来源必须与改造前的硬编码列表逐条一致。"""
    monkeypatch.delenv("CORS_ORIGINS", raising=False)

    assert list(get_settings().cors_origins) == list(DEFAULT_CORS_ORIGINS)


def test_cors_origins_reads_env_and_normalizes(monkeypatch):
    """CORS_ORIGINS 支持逗号分隔，并忽略空项、去掉尾斜杠。"""
    monkeypatch.setenv(
        "CORS_ORIGINS", " http://127.0.0.1:5390 , https://shop.example.com/ ,, "
    )

    assert get_settings().cors_origins == [
        "http://127.0.0.1:5390",
        "https://shop.example.com",
    ]


def test_cors_middleware_uses_configured_origins(monkeypatch):
    """应用中间件必须使用配置值，而不是残留的硬编码列表。"""
    from app import create_app

    monkeypatch.setenv("CORS_ORIGINS", "http://127.0.0.1:5390")

    app = create_app()
    entries = [
        middleware
        for middleware in app.user_middleware
        if "allow_origins" in middleware.kwargs
    ]

    assert entries, "CORS middleware is not registered"
    assert entries[0].kwargs["allow_origins"] == ["http://127.0.0.1:5390"]
