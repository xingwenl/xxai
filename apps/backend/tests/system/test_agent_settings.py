from app.core.config import get_settings


def test_agent_settings_expose_runtime_configuration(monkeypatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("MODEL_DEFAULT_NAME", "gpt-4.1-mini")
    monkeypatch.setenv("MODEL_DEFAULT_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("MODEL_REQUEST_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("MODEL_MAX_RETRIES", "1")
    monkeypatch.setenv("AGENT_FILE_STORAGE_PATH", "/tmp/agent-files")
    monkeypatch.setenv("AGENT_MAX_UPLOAD_BYTES", "1048576")
    monkeypatch.setenv("AGENT_FETCH_TIMEOUT_SECONDS", "12")
    monkeypatch.setenv("AGENT_MASTER_KEY", "test-master-key")
    monkeypatch.setenv("CELERY_BROKER_URL", "redis://localhost:6379/1")

    settings = get_settings()

    assert settings.model_default_name == "gpt-4.1-mini"
    assert settings.model_default_base_url == "https://example.test/v1"
    assert settings.model_request_timeout_seconds == 45
    assert settings.model_max_retries == 1
    assert settings.agent_file_storage_path == "/tmp/agent-files"
    assert settings.agent_max_upload_bytes == 1048576
    assert settings.agent_fetch_timeout_seconds == 12
    assert settings.agent_master_key == "test-master-key"
    assert settings.celery_broker_url == "redis://localhost:6379/1"

    get_settings.cache_clear()
