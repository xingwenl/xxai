"""插件宿主配置与事件日志测试。

覆盖四层：
1. `manifest.settings[]` 协议校验（合法声明、六类非法声明）；
2. `plugin_config` 的默认值合并、取值校验与原子落盘；
3. `/api/desktop/plugins/{id}/config` 与 `/api/desktop/plugin-log` 端点行为；
4. `plugin_log` 的 JSONL 格式、白名单、截断与轮转。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from conftest import seed_plugin
import desktop_app.plugin_log as plugin_log_module
from desktop_app import paths
from desktop_app.manager import PluginManager
from desktop_app.plugin_config import (
    PluginConfigError,
    PluginConfigStore,
    merge_defaults,
    validate_values,
)
from desktop_app.plugin_log import MAX_DETAIL_LENGTH, PluginLog
from desktop_app.protocol import PluginManifest
from desktop_app.server import create_app


SETTINGS = [
    {"key": "greeting", "label": "问候语", "type": "text", "default": "你好"},
    {"key": "refresh", "label": "刷新间隔", "type": "number", "default": 30, "min": 5, "max": 300},
    {"key": "verbose", "label": "详细日志", "type": "boolean", "default": False},
    {
        "key": "theme",
        "label": "主题",
        "type": "select",
        "default": "auto",
        "options": [{"label": "跟随系统", "value": "auto"}, {"label": "深色", "value": "dark"}],
    },
]


def _manifest(**overrides) -> dict:
    base = {
        "id": "demo",
        "name": "演示",
        "version": "0.1.0",
        "permissions": ["settings"],
        "settings": SETTINGS,
    }
    base.update(overrides)
    return base


def _client(env: dict) -> TestClient:
    """构造隔离环境下的 TestClient：配置与日志都落在 tmp 目录。"""
    manager = PluginManager(
        builtin_dir=env["builtin"],
        user_dir=env["user"],
        state_file=env["state"],
    )
    config = PluginConfigStore(env["state"].parent / "plugin-config")
    return TestClient(create_app(manager, plugin_config=config))


def _seed_demo(env: dict) -> None:
    seed_plugin(env["user"], "demo", "演示", settings=SETTINGS)


# ---------- 1. manifest.settings[] 协议 ----------


def test_manifest_parses_settings() -> None:
    manifest = PluginManifest.model_validate(_manifest())
    assert [item.key for item in manifest.settings] == ["greeting", "refresh", "verbose", "theme"]
    theme = manifest.settings[3]
    assert theme.type == "select"
    assert [option.value for option in theme.options] == ["auto", "dark"]


def test_manifest_without_settings_defaults_to_empty() -> None:
    manifest = PluginManifest.model_validate({"id": "demo", "name": "演示", "version": "0.1.0"})
    assert manifest.settings == []


@pytest.mark.parametrize(
    "setting",
    [
        pytest.param({"key": "Bad-Key", "label": "大写键", "type": "text", "default": ""}, id="大写键"),
        pytest.param({"key": "a", "label": "数字", "type": "number", "default": True}, id="数字默认布尔"),
        pytest.param(
            {"key": "b", "label": "选项", "type": "select", "default": "z"},
            id="select缺候选项",
        ),
        pytest.param(
            {
                "key": "c",
                "label": "选项默认值",
                "type": "select",
                "default": "z",
                "options": [{"label": "甲", "value": "a"}],
            },
            id="select默认值不在候选项",
        ),
        pytest.param({"key": "d", "label": "范围", "type": "number", "default": 1, "min": 9, "max": 2}, id="min大于max"),
        pytest.param({"key": "e", "label": "文本", "type": "text", "default": "", "max": 2}, id="text不允许max"),
        pytest.param({"key": "f", "label": "文本", "type": "text", "default": 1}, id="text默认值非字符串"),
        pytest.param({"key": "g", "label": "布尔", "type": "boolean", "default": "true"}, id="boolean默认值非布尔"),
    ],
)
def test_invalid_setting_rejected(setting: dict) -> None:
    if "options" not in setting and setting["type"] == "select":
        setting = {**setting, "options": [{"label": "甲", "value": "a"}]}
    with pytest.raises(ValidationError):
        PluginManifest.model_validate(_manifest(settings=[setting]))


def test_duplicate_setting_key_rejected() -> None:
    duplicated = [SETTINGS[0], {**SETTINGS[0], "label": "重复"}]
    with pytest.raises(ValidationError, match="settings 的 key 不能重复"):
        PluginManifest.model_validate(_manifest(settings=duplicated))


def test_remote_plugin_cannot_declare_settings() -> None:
    with pytest.raises(ValidationError, match="remote"):
        PluginManifest.model_validate(
            _manifest(type="remote", url="https://example.com/", permissions=[])
        )


# ---------- 2. 配置合并、校验与落盘 ----------


def test_merge_defaults_drops_unknown_keys() -> None:
    manifest = PluginManifest.model_validate(_manifest())
    values = merge_defaults(manifest.settings, {"refresh": 60, "stale": "x"})
    assert values == {"greeting": "你好", "refresh": 60, "verbose": False, "theme": "auto"}


def test_validate_values_collects_all_errors() -> None:
    manifest = PluginManifest.model_validate(_manifest())
    errors = validate_values(
        manifest.settings,
        {"refresh": 999, "theme": "x", "nope": 1, "verbose": 1, "greeting": 5},
    )
    assert len(errors) == 5
    assert any("刷新间隔" in message and "300" in message for message in errors)
    assert any("主题" in message and "候选项" in message for message in errors)
    assert any("nope" in message and "未在 manifest" in message for message in errors)
    assert any("详细日志" in message and "true/false" in message for message in errors)
    assert any("问候语" in message and "字符串" in message for message in errors)


def test_validate_values_accepts_valid_input() -> None:
    manifest = PluginManifest.model_validate(_manifest())
    assert validate_values(
        manifest.settings,
        {"greeting": "hi", "refresh": 5, "verbose": True, "theme": "dark"},
    ) == []


def test_config_store_writes_compact_json_and_reads_back(tmp_path: Path) -> None:
    store = PluginConfigStore(tmp_path)
    store.write("demo", {"greeting": "你好", "refresh": 60})
    raw = store.file("demo").read_text(encoding="utf-8")
    assert raw == '{"greeting":"你好","refresh":60}'
    assert store.read("demo") == {"greeting": "你好", "refresh": 60}
    assert store.read("missing") == {}


def test_config_store_rejects_invalid_plugin_id(tmp_path: Path) -> None:
    store = PluginConfigStore(tmp_path)
    with pytest.raises(PluginConfigError):
        store.file("Bad/Id")


def test_config_store_rejects_non_object_file(tmp_path: Path) -> None:
    store = PluginConfigStore(tmp_path)
    store.file("demo").write_text("[]", encoding="utf-8")
    with pytest.raises(PluginConfigError):
        store.read("demo")


def test_registry_exposes_settings(plugin_env: dict) -> None:
    _seed_demo(plugin_env)
    manager = PluginManager(
        builtin_dir=plugin_env["builtin"],
        user_dir=plugin_env["user"],
        state_file=plugin_env["state"],
    )
    info = manager.get("demo")
    assert [item["key"] for item in info.settings] == ["greeting", "refresh", "verbose", "theme"]
    assert info.to_dict()["settings"][0]["label"] == "问候语"


# ---------- 3. HTTP 端点 ----------


def test_get_plugin_config_returns_defaults(plugin_env: dict) -> None:
    _seed_demo(plugin_env)
    resp = _client(plugin_env).get("/api/desktop/plugins/demo/config")
    assert resp.status_code == 200
    assert resp.json()["values"] == {
        "greeting": "你好",
        "refresh": 30,
        "verbose": False,
        "theme": "auto",
    }


def test_get_plugin_config_404_for_unknown_plugin(plugin_env: dict) -> None:
    resp = _client(plugin_env).get("/api/desktop/plugins/nope/config")
    assert resp.status_code == 404


def test_put_plugin_config_persists_and_logs(plugin_env: dict) -> None:
    _seed_demo(plugin_env)
    client = _client(plugin_env)
    resp = client.put(
        "/api/desktop/plugins/demo/config",
        json={"values": {"greeting": "机密问候", "refresh": 60, "verbose": True, "theme": "dark"}},
    )
    assert resp.status_code == 200
    assert resp.json()["values"]["refresh"] == 60

    config_file = plugin_env["state"].parent / "plugin-config" / "demo.json"
    assert json.loads(config_file.read_text(encoding="utf-8"))["greeting"] == "机密问候"

    log_path = plugin_env["state"].parent / "plugin.log"
    lines = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    saved = [line for line in lines if line["event"] == "config_saved"]
    assert saved, "保存配置应写入事件日志"
    assert saved[-1]["keys"] == "greeting,refresh,theme,verbose"
    # 只记键名不记值：日志里不能出现配置内容（可能含隐私）
    assert "机密问候" not in log_path.read_text(encoding="utf-8")


def test_put_invalid_config_returns_400_without_overwriting(plugin_env: dict) -> None:
    _seed_demo(plugin_env)
    client = _client(plugin_env)
    assert client.put("/api/desktop/plugins/demo/config", json={"values": {"refresh": 10}}).status_code == 200
    config_file = plugin_env["state"].parent / "plugin-config" / "demo.json"
    before = config_file.read_text(encoding="utf-8")

    resp = client.put(
        "/api/desktop/plugins/demo/config",
        json={"values": {"refresh": 999, "theme": "x", "unknown": 1}},
    )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "300" in detail and "候选项" in detail and "unknown" in detail
    assert config_file.read_text(encoding="utf-8") == before


def test_config_available_even_when_plugin_disabled(plugin_env: dict) -> None:
    _seed_demo(plugin_env)
    manager = PluginManager(
        builtin_dir=plugin_env["builtin"],
        user_dir=plugin_env["user"],
        state_file=plugin_env["state"],
    )
    manager.set_enabled("demo", False)
    client = TestClient(
        create_app(manager, plugin_config=PluginConfigStore(plugin_env["state"].parent / "plugin-config"))
    )
    assert client.get("/api/desktop/plugins/demo/config").status_code == 200


def test_plugin_log_endpoint_accepts_known_event(plugin_env: dict) -> None:
    _seed_demo(plugin_env)
    client = _client(plugin_env)
    resp = client.post(
        "/api/desktop/plugin-log",
        json={"pluginId": "demo", "event": "iframe_load", "detail": "/apps/demo/index.html"},
    )
    assert resp.status_code == 200
    lines = [
        json.loads(line)
        for line in (plugin_env["state"].parent / "plugin.log").read_text(encoding="utf-8").splitlines()
    ]
    assert lines[-1]["event"] == "iframe_load"
    assert lines[-1]["plugin"] == "demo"


def test_plugin_log_endpoint_rejects_unknown_event(plugin_env: dict) -> None:
    _seed_demo(plugin_env)
    resp = _client(plugin_env).post(
        "/api/desktop/plugin-log",
        json={"pluginId": "demo", "event": "原创事件"},
    )
    assert resp.status_code == 400
    assert "未知事件名" in resp.json()["detail"]


# ---------- 4. 日志写入器 ----------


def test_plugin_log_writes_jsonl_and_truncates_detail(tmp_path: Path) -> None:
    log_path = tmp_path / "plugin.log"
    PluginLog(log_path).append("demo", "sdk_injected", detail="异" * (MAX_DETAIL_LENGTH + 100))
    record = json.loads(log_path.read_text(encoding="utf-8").splitlines()[-1])
    assert record["event"] == "sdk_injected"
    assert len(record["detail"]) == MAX_DETAIL_LENGTH


def test_plugin_log_rotates_when_exceeding_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(plugin_log_module, "MAX_LOG_BYTES", 200)
    log_path = tmp_path / "plugin.log"
    log = PluginLog(log_path)
    for _ in range(6):
        log.append("demo", "enable")
    assert (tmp_path / "plugin.log.1").is_file()
    assert log_path.stat().st_size <= 200


def test_plugin_log_unknown_event_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="未知事件名"):
        PluginLog(tmp_path / "plugin.log").append("demo", "不存在的事件")


def test_plugin_log_unknown_plugin_id_normalized(tmp_path: Path) -> None:
    log_path = tmp_path / "plugin.log"
    PluginLog(log_path).append("Bad/Id", "enable")
    assert json.loads(log_path.read_text(encoding="utf-8").splitlines()[-1])["plugin"] == "unknown"


# ---------- 5. 内置演示插件（活样板） ----------


def test_hello_world_builtin_declares_settings() -> None:
    manifest_path = paths.builtin_plugins_dir() / "hello-world" / "manifest.json"
    manifest = PluginManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    keys = [item.key for item in manifest.settings]
    assert keys == ["greeting", "notify_on_start", "accent"]
    assert "settings" in manifest.permissions
