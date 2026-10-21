"""宿主应用更新测试：发布清单解析、平台映射、镜像回退、下载校验与 HTTP 契约。"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from desktop_app import app_update
from desktop_app.app_config import APP_VERSION
from desktop_app.manager import PluginManager
from desktop_app.server import create_app


def _make_asset(tmp_path: Path, payload: bytes = b"fake-app-zip", **overrides) -> dict:
    """在 tmp 下写一个「发布资产」，返回清单里的平台条目。"""
    name = overrides.pop("name", "WW-0.2.1-macos-arm64.zip")
    path = tmp_path / "release" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    asset = {
        "name": name,
        "url": f"file://{path}",
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size": len(payload),
    }
    asset.update(overrides)
    return asset


def _write_manifest(
    tmp_path: Path,
    platforms: dict | None = None,
    latest: str = "0.2.1",
    **overrides,
) -> Path:
    path = tmp_path / "latest.json"
    payload = {
        "version": 1,
        "latest": latest,
        "publishedAt": "2026-10-21T00:00:00Z",
        "notes": "修复若干问题",
        "releaseUrl": "https://github.com/xingwenl/xxai/releases/tag/desktop-v0.2.1",
        "platforms": platforms if platforms is not None else {"macos-arm64": _make_asset(tmp_path)},
    }
    payload.update(overrides)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def isolated_update(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """清缓存、把更新目录与清单地址都指到 tmp，避免污染真实 HOME 与网络。"""
    app_update.clear_cache()
    monkeypatch.setattr(app_update.paths, "updates_dir", lambda: tmp_path / "updates")
    monkeypatch.setattr(app_update, "platform_key", lambda: "macos-arm64")
    monkeypatch.delenv(app_update.APP_UPDATE_DISABLE_ENV, raising=False)
    monkeypatch.setenv(app_update.APP_UPDATE_ENV, f"file://{tmp_path / 'latest.json'}")
    monkeypatch.setenv(app_update.APP_UPDATE_MIRRORS_ENV, "")
    yield tmp_path / "latest.json"
    app_update.clear_cache()


# ---------- 1. 清单解析 ----------


def test_parse_manifest_valid(tmp_path: Path) -> None:
    manifest = app_update.parse_manifest(_write_manifest(tmp_path).read_bytes())
    assert manifest.latest == "0.2.1"
    assert manifest.release_url.endswith("desktop-v0.2.1")
    asset = manifest.platforms["macos-arm64"]
    assert asset.name == "WW-0.2.1-macos-arm64.zip"
    assert asset.to_dict()["platform"] == "macos-arm64"


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"version": 2}, "格式版本"),
        ({"latest": ""}, "latest"),
        ({"platforms": {}}, "没有可用平台资产"),
        ({"platforms": {"macos-arm64": {"name": "a.zip", "url": "", "sha256": "0" * 64, "size": 1}}}, "url"),
        (
            {
                "platforms": {
                    "macos-arm64": {
                        "name": "a.zip",
                        "url": "https://example.com/a.zip",
                        "sha256": "not-a-sha",
                        "size": 1,
                    }
                }
            },
            "sha256",
        ),
        (
            {
                "platforms": {
                    "macos-arm64": {
                        "name": "a.zip",
                        "url": "https://example.com/a.zip",
                        "sha256": "0" * 64,
                        "size": 0,
                    }
                }
            },
            "size",
        ),
        (
            {
                "platforms": {
                    "macos-arm64": {
                        "name": "../escape.zip",
                        "url": "https://example.com/a.zip",
                        "sha256": "0" * 64,
                        "size": 1,
                    }
                }
            },
            "纯文件名",
        ),
        ({"releaseUrl": "http://example.com/release"}, "https"),
    ],
)
def test_parse_manifest_rejects_invalid(tmp_path: Path, overrides: dict, match: str) -> None:
    path = _write_manifest(tmp_path, **overrides)
    with pytest.raises(app_update.AppUpdateValidationError, match=match):
        app_update.parse_manifest(path.read_bytes())


def test_parse_manifest_ignores_unknown_platform(tmp_path: Path) -> None:
    asset = _make_asset(tmp_path)
    path = _write_manifest(
        tmp_path,
        platforms={"macos-arm64": asset, "plan9-mips": asset},
    )
    manifest = app_update.parse_manifest(path.read_bytes())
    assert set(manifest.platforms) == {"macos-arm64"}


# ---------- 2. 平台映射 ----------


@pytest.mark.parametrize(
    ("system", "machine", "expected"),
    [
        ("darwin", "arm64", "macos-arm64"),
        ("darwin", "x86_64", "macos-x64"),
        ("win32", "AMD64", "windows-x64"),
        ("linux", "x86_64", "linux-x64"),
        ("linux", "aarch64", "linux-arm64"),
        ("freebsd", "x86_64", ""),
    ],
)
def test_platform_key(
    monkeypatch: pytest.MonkeyPatch, system: str, machine: str, expected: str
) -> None:
    monkeypatch.undo()  # 让 autouse fixture 里的 platform_key 替换失效，测真实实现
    monkeypatch.setattr(sys, "platform", system)
    monkeypatch.setattr(app_update.platform, "machine", lambda: machine)
    assert app_update.platform_key() == expected


# ---------- 3. 检查更新 ----------


def test_get_update_info_reports_newer_version(tmp_path: Path) -> None:
    _write_manifest(tmp_path)
    info = app_update.get_update_info("0.2.0")
    assert info.enabled is True
    assert info.latest == "0.2.1"
    assert info.has_update is True
    assert info.asset is not None and info.asset.key == "macos-arm64"
    assert info.downloaded_path == ""


def test_get_update_info_same_version_has_no_update(tmp_path: Path) -> None:
    _write_manifest(tmp_path)
    info = app_update.get_update_info("0.2.1")
    assert info.has_update is False
    assert info.latest == "0.2.1"


def test_get_update_info_reports_error_not_latest(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(app_update.APP_UPDATE_ENV, "file:///nonexistent/latest.json")
    info = app_update.get_update_info("0.2.0")
    assert info.has_update is False
    assert "不可用" in info.error
    assert info.latest == ""


def test_get_update_info_falls_back_to_mirror(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    real = _write_manifest(tmp_path)
    monkeypatch.setenv(app_update.APP_UPDATE_ENV, "file:///nonexistent/latest.json")
    monkeypatch.setenv(app_update.APP_UPDATE_MIRRORS_ENV, f"file://{real}")
    info = app_update.get_update_info("0.2.0")
    assert info.has_update is True
    assert info.error == ""


def test_get_update_info_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(app_update.APP_UPDATE_DISABLE_ENV, "0")
    info = app_update.get_update_info("0.2.0")
    assert info.enabled is False
    assert info.has_update is False


# ---------- 4. 下载与校验 ----------


def test_download_asset_writes_verified_file(tmp_path: Path) -> None:
    _write_manifest(tmp_path)
    info = app_update.get_update_info("0.2.0")
    target, size, digest = app_update.download_asset(info)
    assert target.parent == tmp_path / "updates" / "0.2.1"
    assert target.read_bytes() == b"fake-app-zip"
    assert size == info.asset.size
    assert digest == info.asset.sha256
    assert app_update.get_update_info("0.2.0").downloaded_path == str(target)


def test_download_asset_rejects_sha_mismatch(tmp_path: Path) -> None:
    asset = _make_asset(tmp_path)
    _write_manifest(tmp_path, platforms={"macos-arm64": {**asset, "sha256": "0" * 64}})
    info = app_update.get_update_info("0.2.0")
    with pytest.raises(app_update.AppUpdateValidationError, match="校验失败"):
        app_update.download_asset(info)
    assert not (tmp_path / "updates" / "0.2.1").exists()


def test_download_asset_rejects_size_mismatch(tmp_path: Path) -> None:
    asset = _make_asset(tmp_path)
    _write_manifest(tmp_path, platforms={"macos-arm64": {**asset, "size": asset["size"] + 1}})
    info = app_update.get_update_info("0.2.0")
    with pytest.raises(app_update.AppUpdateValidationError, match="校验失败"):
        app_update.download_asset(info)
    assert not (tmp_path / "updates" / "0.2.1").exists()


def test_download_asset_keeps_previous_package_on_bad_retry(tmp_path: Path) -> None:
    """先成功下载一次，再拿到坏清单重下：已校验的安装包不能被覆盖或删掉。"""
    asset = _make_asset(tmp_path)
    _write_manifest(tmp_path, platforms={"macos-arm64": asset})
    target, _, _ = app_update.download_asset(app_update.get_update_info("0.2.0"))

    _write_manifest(tmp_path, platforms={"macos-arm64": {**asset, "sha256": "0" * 64}})
    app_update.clear_cache()
    with pytest.raises(app_update.AppUpdateValidationError, match="校验失败"):
        app_update.download_asset(app_update.get_update_info("0.2.0"))

    assert target.is_file()
    assert target.read_bytes() == b"fake-app-zip"
    assert not list(target.parent.glob("*.part"))


def test_download_asset_missing_file_raises_download_error(tmp_path: Path) -> None:
    asset = _make_asset(tmp_path)
    _write_manifest(
        tmp_path,
        platforms={"macos-arm64": {**asset, "url": f"file://{tmp_path}/missing.zip"}},
    )
    info = app_update.get_update_info("0.2.0")
    with pytest.raises(app_update.AppUpdateDownloadError):
        app_update.download_asset(info)


# ---------- 5. HTTP 契约 ----------


def _client(env: dict) -> TestClient:
    manager = PluginManager(
        builtin_dir=env["builtin"],
        user_dir=env["user"],
        state_file=env["state"],
    )
    return TestClient(create_app(manager, dev_agent_enabled=False))


def test_app_update_endpoint(plugin_env: dict, tmp_path: Path) -> None:
    _write_manifest(tmp_path)
    client = _client(plugin_env)
    payload = client.get("/api/desktop/app-update").json()
    assert payload["enabled"] is True
    assert payload["hasUpdate"] is True
    assert payload["asset"]["platform"] == "macos-arm64"

    downloaded = client.post("/api/desktop/app-update/download")
    assert downloaded.status_code == 200
    body = downloaded.json()
    assert body["version"] == "0.2.1"
    assert Path(body["path"]).is_file()


def test_app_update_download_rejects_bad_sha(plugin_env: dict, tmp_path: Path) -> None:
    asset = _make_asset(tmp_path)
    _write_manifest(tmp_path, platforms={"macos-arm64": {**asset, "sha256": "0" * 64}})
    client = _client(plugin_env)
    response = client.post("/api/desktop/app-update/download")
    assert response.status_code == 400
    assert "校验失败" in response.json()["detail"]


def test_app_update_reveal_opens_updates_dir(
    plugin_env: dict, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    opened: list[Path] = []
    monkeypatch.setattr(
        app_update, "reveal_updates_dir", lambda: opened.append(tmp_path / "updates") or tmp_path / "updates"
    )
    client = _client(plugin_env)
    response = client.post("/api/desktop/app-update/reveal")
    assert response.status_code == 200
    assert opened


def test_settings_expose_app_update_source(plugin_env: dict, tmp_path: Path) -> None:
    _write_manifest(tmp_path)
    client = _client(plugin_env)
    settings = client.get("/api/desktop/settings").json()
    assert settings["appUpdateEnabled"] is True
    assert settings["appUpdateUrl"].startswith("file://")
    assert settings["version"] == APP_VERSION
