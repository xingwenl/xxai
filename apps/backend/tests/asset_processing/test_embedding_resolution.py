"""附件 embedding 绑定模型解析与配置回退测试。"""

from types import SimpleNamespace

from app.modules.asset_processing import runtime


def _settings():
    return SimpleNamespace(
        attachment_embedding_dimension=1536,
        attachment_embedding_model=None,
        attachment_embedding_base_url=None,
        attachment_embedding_api_key=None,
        embedding_batch_size=16,
    )


def _model_config(**overrides):
    values = {
        "model_name": "custom-embed",
        "base_url": "http://ollama:11434/v1",
        "api_key": None,
        "capabilities": None,
        "options": {},
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_embedding_enabled_with_bound_local_model(monkeypatch):
    monkeypatch.setattr(runtime, "get_settings", lambda: _settings())
    assert runtime.attachment_embedding_enabled(_model_config()) is True


def test_embedding_enabled_rejects_bound_model_without_key_or_local_endpoint(
    monkeypatch,
):
    monkeypatch.setattr(runtime, "get_settings", lambda: _settings())
    assert (
        runtime.attachment_embedding_enabled(
            _model_config(base_url="https://api.example.com", api_key=None)
        )
        is False
    )


def test_embedding_enabled_falls_back_to_global_config(monkeypatch):
    settings = _settings()
    settings.attachment_embedding_model = "text-embedding-3-small"
    settings.attachment_embedding_api_key = "global-key"
    monkeypatch.setattr(runtime, "get_settings", lambda: settings)
    assert runtime.attachment_embedding_enabled(None) is True


def test_embedding_enabled_disabled_without_dimension(monkeypatch):
    settings = _settings()
    settings.attachment_embedding_dimension = None
    monkeypatch.setattr(runtime, "get_settings", lambda: settings)
    assert runtime.attachment_embedding_enabled(_model_config()) is False


def test_build_embedding_model_uses_bound_config(monkeypatch):
    monkeypatch.setattr(runtime, "get_settings", lambda: _settings())
    model = runtime.build_attachment_embedding_model(_model_config())
    assert model.model_name == "custom-embed"
    assert model.api_base == "http://ollama:11434/v1"
    assert model.api_key == "ollama"
    assert model.embed_batch_size == 16


def test_build_embedding_model_falls_back_to_global_config(monkeypatch):
    settings = _settings()
    settings.attachment_embedding_model = "text-embedding-3-small"
    settings.attachment_embedding_api_key = "global-key"
    monkeypatch.setattr(runtime, "get_settings", lambda: settings)
    model = runtime.build_attachment_embedding_model(None)
    assert model.model_name == "text-embedding-3-small"
    assert model.api_key == "global-key"
