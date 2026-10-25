"""插件资产存储（plugin-assets）：磁盘语义、配额与宿主 REST 契约测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import seed_plugin
from desktop_app import plugin_assets
from desktop_app.agent_config import AgentConfigStore
from desktop_app.manager import PluginManager
from desktop_app.plugin_assets import (
    MAX_FILE_BYTES,
    MAX_FILE_COUNT,
    MAX_TOTAL_BYTES,
    AssetQuotaExceeded,
    AssetTooLarge,
    InvalidPluginAssetKey,
    PluginAssetStore,
    UnsupportedAssetType,
    asset_url,
)
from desktop_app.plugin_data import PluginDataStore
from desktop_app.protocol import KNOWN_PERMISSIONS
from desktop_app.server import create_app

PNG_HEADER = b"\x89PNG\r\n\x1a\n"
JPEG_HEADER = b"\xff\xd8\xff\xe0"
GIF_HEADER = b"GIF89a"
WEBP_HEADER = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP"


def _png(padding: bytes = b"\x00" * 32) -> bytes:
    """构造以合法 PNG 魔数开头的假图片字节（测试不解析图像内容，只校验魔数）。"""
    return PNG_HEADER + padding


def _jpeg() -> bytes:
    return JPEG_HEADER + b"\x00" * 32


def _gif() -> bytes:
    return GIF_HEADER + b"\x00" * 32


def _webp() -> bytes:
    return WEBP_HEADER + b"\x00" * 32


def _store(tmp_path: Path) -> PluginAssetStore:
    return PluginAssetStore(root=tmp_path / "plugin-assets")


def _client(plugin_env: dict, tmp_path: Path) -> TestClient:
    manager = PluginManager(
        builtin_dir=plugin_env["builtin"],
        user_dir=plugin_env["user"],
        state_file=plugin_env["state"],
    )
    app = create_app(
        manager,
        plugin_data=PluginDataStore(root=tmp_path / "plugin-data"),
        plugin_assets=_store(tmp_path),
        dev_agent_enabled=False,
        # 显式隔离配置文件：本机若在设置页保存过真实 AI Base 凭证，默认 store 会读到它
        agent_config_store=AgentConfigStore(tmp_path / "agent.json"),
    )
    return TestClient(app)


def _upload(client: TestClient, plugin_id: str, data: bytes, mime: str = "image/png"):
    return client.post(
        f"/api/desktop/plugin-assets/{plugin_id}",
        content=data,
        headers={"content-type": mime},
    )


def _assets_dir(tmp_path: Path, plugin_id: str = "note") -> Path:
    return tmp_path / "plugin-assets" / plugin_id


# ---------- 存储层 ----------


def test_permission_and_quota_constants() -> None:
    """配额与白名单是 spec/ADR 的硬约束，改动必须同步改文档。"""
    assert "assets" in KNOWN_PERMISSIONS
    assert MAX_FILE_BYTES == 2 * 1024 * 1024
    assert MAX_TOTAL_BYTES == 64 * 1024 * 1024
    assert MAX_FILE_COUNT == 500
    assert plugin_assets.ALLOWED_MIME == {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }


def test_store_put_generates_key_from_content(tmp_path: Path) -> None:
    store = _store(tmp_path)
    info = store.put("note", _png(), "image/png")

    assert len(info.key) == 20 and info.key.endswith(".png")  # 16 位内容前缀 + ".png"
    assert info.size == len(_png())
    assert info.mime == "image/png"
    assert info.created is True
    assert info.created_at.endswith("Z")
    # 落盘位置：<root>/<plugin_id>/<key>，且不留临时文件
    assert (tmp_path / "plugin-assets" / "note" / info.key).is_file()
    assert list(_assets_dir(tmp_path).glob("*.tmp")) == []
    assert store.read("note", info.key) == (_png(), "image/png")


def test_store_put_is_deduped_and_not_rewritten(tmp_path: Path) -> None:
    store = _store(tmp_path)
    data = _png()
    first = store.put("note", data, "image/png")
    mtime_before = (_assets_dir(tmp_path) / first.key).stat().st_mtime_ns

    second = store.put("note", data, "image/png")

    assert second.key == first.key
    assert second.created is False
    assert second.created_at == first.created_at
    # 只留一个文件、不重写内容（mtime 不变）
    assert store.usage("note") == {
        "bytes": len(data),
        "count": 1,
        "limitBytes": MAX_TOTAL_BYTES,
        "limitCount": MAX_FILE_COUNT,
        "limitFileBytes": MAX_FILE_BYTES,
    }
    assert (_assets_dir(tmp_path) / first.key).stat().st_mtime_ns == mtime_before


def test_store_accepts_all_whitelisted_types(tmp_path: Path) -> None:
    store = _store(tmp_path)
    cases = [(_png(), "image/png", ".png"), (_jpeg(), "image/jpeg", ".jpg"),
             (_webp(), "image/webp", ".webp"), (_gif(), "image/gif", ".gif")]
    for data, mime, suffix in cases:
        info = store.put("note", data, mime)
        assert info.key.endswith(suffix)
        # mime 由扩展名反查，而不是回读上传时的声明
        assert store.read("note", info.key) == (data, mime)
    assert store.usage("note")["count"] == 4


def test_store_normalizes_content_type_parameters(tmp_path: Path) -> None:
    info = _store(tmp_path).put("note", _png(), "IMAGE/PNG; charset=binary")
    assert info.mime == "image/png"
    assert info.key.endswith(".png")


@pytest.mark.parametrize("mime", ["image/svg+xml", "application/octet-stream", "", "text/html"])
def test_store_rejects_non_whitelisted_type(tmp_path: Path, mime: str) -> None:
    with pytest.raises(UnsupportedAssetType):
        _store(tmp_path).put("note", _png(), mime)


@pytest.mark.parametrize("data,mime", [(b"<svg/>", "image/png"), (_jpeg(), "image/png"), (_png(), "image/webp")])
def test_store_rejects_magic_mismatch(tmp_path: Path, data: bytes, mime: str) -> None:
    store = _store(tmp_path)
    with pytest.raises(UnsupportedAssetType) as excinfo:
        store.put("note", data, mime)
    assert "魔数" in str(excinfo.value)
    assert store.usage("note")["count"] == 0


def test_store_rejects_empty_and_oversized(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(plugin_assets.PluginAssetError):
        store.put("note", b"", "image/png")
    too_big = _png(b"\x00" * (MAX_FILE_BYTES + 1))
    with pytest.raises(AssetTooLarge) as excinfo:
        store.put("note", too_big, "image/png")
    assert str(len(too_big)) in str(excinfo.value)
    assert store.usage("note")["count"] == 0


def test_store_file_count_quota(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(plugin_assets, "MAX_FILE_COUNT", 2)
    store = _store(tmp_path)
    store.put("note", _png(b"\x00"), "image/png")
    store.put("note", _png(b"\x01"), "image/png")
    with pytest.raises(AssetQuotaExceeded) as excinfo:
        store.put("note", _png(b"\x02"), "image/png")
    assert "2 / 2" in str(excinfo.value)
    # 已达上限时，重复上传已有内容仍应成功（去重发生在配额判断之前）
    again = store.put("note", _png(b"\x00"), "image/png")
    assert again.created is False


def test_store_total_bytes_quota(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(plugin_assets, "MAX_TOTAL_BYTES", 64)
    store = _store(tmp_path)
    store.put("note", _png(b"\x00" * 10), "image/png")  # 18 字节
    with pytest.raises(AssetQuotaExceeded) as excinfo:
        store.put("note", _png(b"\x01" * 60), "image/png")  # 68 字节
    assert "字节" in str(excinfo.value)
    assert store.usage("note")["count"] == 1


@pytest.mark.parametrize("key", ["", "..", "../escape", "short.png", "A1B2C3D4E5F60718.png", "a" * 16 + ".svg"])
def test_store_rejects_invalid_key(tmp_path: Path, key: str) -> None:
    store = _store(tmp_path)
    with pytest.raises(InvalidPluginAssetKey):
        store.read("note", key)


@pytest.mark.parametrize("plugin_id", ["../escape", "Note", "记账", ""])
def test_store_rejects_invalid_plugin_id(tmp_path: Path, plugin_id: str) -> None:
    with pytest.raises(InvalidPluginAssetKey):
        _store(tmp_path).plugin_dir(plugin_id)


def test_store_list_order_delete_and_missing(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first = store.put("note", _png(b"\x00"), "image/png")
    second = store.put("note", _png(b"\x01"), "image/png")

    listed = store.list("note")
    assert [item.key for item in listed] == [second.key, first.key]  # 按创建时间倒序
    assert store.read("note", second.key) == (_png(b"\x01"), "image/png")

    assert store.delete("note", first.key) is True
    assert store.delete("note", first.key) is False
    assert store.read("note", first.key) is None
    assert store.get_path("note", second.key) == _assets_dir(tmp_path) / second.key
    assert store.get_path("note", first.key) is None


def test_store_ignores_unrelated_files_and_symlinks(tmp_path: Path) -> None:
    store = _store(tmp_path)
    info = store.put("note", _png(), "image/png")
    directory = _assets_dir(tmp_path)
    # 非 key 形状的文件（临时文件、人工塞进来的东西）不计入用量
    (directory / "notes.txt").write_text("x", encoding="utf-8")
    (directory / ".abc.tmp").write_text("x", encoding="utf-8")
    # 符号链接不跟随：即使名字合法也不读、不计数
    outside = tmp_path / "outside.png"
    outside.write_bytes(_png(b"\xff" * 8))
    (directory / ("f" * 16 + ".png")).symlink_to(outside)

    assert [item.key for item in store.list("note")] == [info.key]
    assert store.usage("note")["count"] == 1
    assert store.read("note", "f" * 16 + ".png") is None
    assert store.get_path("note", "f" * 16 + ".png") is None


def test_store_persists_across_instances(tmp_path: Path) -> None:
    info = _store(tmp_path).put("note", _png(), "image/png")
    reloaded = PluginAssetStore(root=tmp_path / "plugin-assets")
    assert reloaded.read("note", info.key) == (_png(), "image/png")
    assert [item.key for item in reloaded.list("note")] == [info.key]


def test_asset_url_is_site_relative(tmp_path: Path) -> None:
    info = _store(tmp_path).put("note", _png(), "image/png")
    assert asset_url("note", info.key) == f"/api/desktop/plugin-assets/note/{info.key}"
    assert info.to_dict("note") == {
        "key": info.key,
        "url": f"/api/desktop/plugin-assets/note/{info.key}",
        "bytes": info.size,
        "mime": "image/png",
        "createdAt": info.created_at,
    }


# ---------- 宿主接口 ----------


def test_plugin_assets_requires_assets_permission(plugin_env: dict, tmp_path: Path) -> None:
    # conftest 预置的 hello-world 只声明 notify/settings
    client = _client(plugin_env, tmp_path)
    listed = client.get("/api/desktop/plugin-assets/hello-world")
    assert listed.status_code == 403
    assert "assets" in listed.json()["detail"]

    uploaded = _upload(client, "hello-world", _png())
    assert uploaded.status_code == 403
    assert "assets" in uploaded.json()["detail"]


def test_plugin_assets_upload_list_delete_roundtrip(plugin_env: dict, tmp_path: Path) -> None:
    seed_plugin(plugin_env["builtin"], "note", "念记", permissions=["assets"])
    client = _client(plugin_env, tmp_path)

    uploaded = _upload(client, "note", _png())
    assert uploaded.status_code == 200
    body = uploaded.json()
    assert body["created"] is True
    asset = body["asset"]
    assert asset["url"] == f"/api/desktop/plugin-assets/note/{asset['key']}"
    assert asset["bytes"] == len(_png())
    assert asset["mime"] == "image/png"
    assert asset["createdAt"].endswith("Z")
    assert body["usage"] == {
        "bytes": len(_png()),
        "count": 1,
        "limitBytes": MAX_TOTAL_BYTES,
        "limitCount": MAX_FILE_COUNT,
        "limitFileBytes": MAX_FILE_BYTES,
    }
    # 落盘位置与 server 拼出来的 url 一致
    assert (_assets_dir(tmp_path) / asset["key"]).is_file()

    listed = client.get("/api/desktop/plugin-assets/note")
    assert listed.status_code == 200
    assert listed.json()["assets"] == [asset]
    assert listed.json()["usage"]["count"] == 1

    deleted = client.delete(f"/api/desktop/plugin-assets/note/{asset['key']}")
    assert deleted.status_code == 204
    # 幂等：再删一次还是 204
    assert client.delete(f"/api/desktop/plugin-assets/note/{asset['key']}").status_code == 204
    assert client.get("/api/desktop/plugin-assets/note").json()["usage"]["count"] == 0
    assert client.get(asset["url"]).status_code == 404


def test_plugin_assets_upload_is_deduped(plugin_env: dict, tmp_path: Path) -> None:
    seed_plugin(plugin_env["builtin"], "note", "念记", permissions=["assets"])
    client = _client(plugin_env, tmp_path)

    first = _upload(client, "note", _png()).json()
    second = _upload(client, "note", _png(), mime="image/png").json()

    assert second["created"] is False
    assert second["asset"]["key"] == first["asset"]["key"]
    assert second["usage"]["count"] == 1
    assert len(list(_assets_dir(tmp_path).iterdir())) == 1


def test_plugin_assets_upload_rejects_bad_type_and_magic(plugin_env: dict, tmp_path: Path) -> None:
    seed_plugin(plugin_env["builtin"], "note", "念记", permissions=["assets"])
    client = _client(plugin_env, tmp_path)

    for mime in ("image/svg+xml", "application/octet-stream", "text/html"):
        resp = _upload(client, "note", b"<svg/>", mime=mime)
        assert resp.status_code == 415
        assert "仅允许" in resp.json()["detail"]

    # 声明 png、实际 jpeg：内容校验不通过
    mismatched = _upload(client, "note", _jpeg(), mime="image/png")
    assert mismatched.status_code == 415
    assert "魔数" in mismatched.json()["detail"]

    # 没带 Content-Type 的裸 POST 也按不支持处理
    bare = client.post("/api/desktop/plugin-assets/note", content=_png())
    assert bare.status_code == 415


def test_plugin_assets_upload_rejects_empty_and_oversized(plugin_env: dict, tmp_path: Path) -> None:
    seed_plugin(plugin_env["builtin"], "note", "念记", permissions=["assets"])
    client = _client(plugin_env, tmp_path)

    assert _upload(client, "note", b"").status_code == 400

    too_big = _upload(client, "note", _png(b"\x00" * (MAX_FILE_BYTES + 1)))
    assert too_big.status_code == 413
    assert "上限" in too_big.json()["detail"]
    assert client.get("/api/desktop/plugin-assets/note").json()["usage"]["count"] == 0


def test_plugin_assets_upload_quota_413(
    plugin_env: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_plugin(plugin_env["builtin"], "note", "念记", permissions=["assets"])
    client = _client(plugin_env, tmp_path)

    monkeypatch.setattr(plugin_assets, "MAX_FILE_COUNT", 1)
    assert _upload(client, "note", _png(b"\x00")).status_code == 200
    over_count = _upload(client, "note", _png(b"\x01"))
    assert over_count.status_code == 413
    assert "上限" in over_count.json()["detail"]

    # 换成只卡总字节的配额，确认 413 的错因确实来自配额而不是单文件上限
    monkeypatch.setattr(plugin_assets, "MAX_FILE_COUNT", MAX_FILE_COUNT)
    monkeypatch.setattr(plugin_assets, "MAX_TOTAL_BYTES", 64)
    over_bytes = _upload(client, "note", _png(b"\x02" * 64))
    assert over_bytes.status_code == 413
    assert "字节" in over_bytes.json()["detail"]


def test_plugin_assets_get_ignores_permission_and_enabled_state(
    plugin_env: dict, tmp_path: Path
) -> None:
    """读取只要求插件已知：<img src> 没有鉴权头，停用插件的历史图片必须还能显示。"""
    seed_plugin(plugin_env["builtin"], "note", "念记", permissions=["assets"])
    info = _store(tmp_path).put("note", _png(), "image/png")
    client = _client(plugin_env, tmp_path)

    first = client.get(f"/api/desktop/plugin-assets/note/{info.key}")
    assert first.status_code == 200
    assert first.content == _png()
    assert first.headers["content-type"] == "image/png"
    assert first.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert first.headers["x-content-type-options"] == "nosniff"

    # 停用后列表/上传被挡（与 plugin-data 一致：403），但读图仍然可用
    assert client.patch("/api/desktop/plugins/note", json={"enabled": False}).status_code == 200
    assert client.get("/api/desktop/plugin-assets/note").status_code == 403
    assert _upload(client, "note", _png(b"\xff" * 8)).status_code == 403
    still_readable = client.get(f"/api/desktop/plugin-assets/note/{info.key}")
    assert still_readable.status_code == 200

    # 未安装的插件：读取也 404
    assert client.get(f"/api/desktop/plugin-assets/not-installed/{info.key}").status_code == 404


def test_plugin_assets_get_unknown_or_invalid_key(plugin_env: dict, tmp_path: Path) -> None:
    seed_plugin(plugin_env["builtin"], "note", "念记", permissions=["assets"])
    client = _client(plugin_env, tmp_path)

    missing = client.get("/api/desktop/plugin-assets/note/" + "0" * 16 + ".png")
    assert missing.status_code == 404
    assert "资产不存在" in missing.json()["detail"]

    # key 不合法与 key 不存在同待遇（不在 URL 里泄露校验规则）
    assert client.get("/api/desktop/plugin-assets/note/bad-key.png").status_code == 404
    assert client.get("/api/desktop/plugin-assets/note/short.png").status_code == 404


def test_plugin_assets_delete_invalid_key_is_400(plugin_env: dict, tmp_path: Path) -> None:
    seed_plugin(plugin_env["builtin"], "note", "念记", permissions=["assets"])
    client = _client(plugin_env, tmp_path)
    resp = client.delete("/api/desktop/plugin-assets/note/bad-key.png")
    assert resp.status_code == 400
    assert "非法资产 key" in resp.json()["detail"]


def test_plugin_assets_unknown_plugin(plugin_env: dict, tmp_path: Path) -> None:
    client = _client(plugin_env, tmp_path)
    assert client.get("/api/desktop/plugin-assets/not-installed").status_code == 404
    assert _upload(client, "not-installed", _png()).status_code == 404
