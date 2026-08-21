"""Chrome 书签整理逻辑与上报接口测试。"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from desktop_app.bookmarks import (
    BookmarkItem,
    domain_of,
    is_internal_url,
    load_snapshot,
    normalize_url,
    organize_bookmarks,
    save_snapshot,
)
from desktop_app.manager import PluginManager
from desktop_app.server import create_app


def _client(env: dict, snapshot_path: Path) -> TestClient:
    manager = PluginManager(
        builtin_dir=env["builtin"],
        user_dir=env["user"],
        state_file=env["state"],
    )
    return TestClient(create_app(manager, bookmarks_snapshot_path=snapshot_path))


def _bookmark(**overrides) -> BookmarkItem:
    defaults = {
        "id": "1",
        "title": "示例书签",
        "url": "https://example.com/page",
        "folderPath": "书签栏",
    }
    defaults.update(overrides)
    return BookmarkItem(**defaults)


def test_is_internal_url() -> None:
    assert is_internal_url("chrome://settings/")
    assert is_internal_url("CHROME-EXTENSION://abc/popup.html")
    assert is_internal_url("about:blank")
    assert is_internal_url("file:///etc/hosts")
    assert not is_internal_url("https://example.com/a")


def test_normalize_url_and_domain() -> None:
    assert normalize_url("HTTPS://Example.COM/a?b=1#frag") == "https://example.com/a?b=1"
    assert normalize_url("https://example.com/a#frag") == "https://example.com/a"
    assert domain_of("https://www.example.com:8443/path") == "example.com"
    assert domain_of("https://user@example.com/") == "example.com"
    assert domain_of("not-a-url") == "unknown"


def test_organize_bookmarks_dedupe_group_by_folder_and_order() -> None:
    bookmarks = [
        _bookmark(id="1", title="重复-深层", url="https://example.com/a#x", folderPath="书签栏/深层"),
        _bookmark(id="2", title="重复-根级", url="https://example.com/a", folderPath="书签栏"),
        _bookmark(id="3", title="内部页", url="chrome://settings/"),
        _bookmark(id="4", title="空 URL", url=""),
        _bookmark(id="5", title="GitHub 首页", url="https://github.com/", folderPath="开发"),
        _bookmark(id="6", title="GitHub 议题", url="https://github.com/issues", folderPath="开发/工作"),
        _bookmark(id="7", title="根级未分类", url="https://root.example.com/", folderPath=""),
    ]
    snapshot = organize_bookmarks(bookmarks)

    assert snapshot["total"] == 7
    assert snapshot["filtered"] == 2  # chrome:// 与空 URL
    assert snapshot["unique"] == 4  # 重复 URL 只保留一条

    groups = snapshot["groups"]
    # 分组按文件夹路径字典序排列
    assert [g["folderPath"] for g in groups] == ["书签栏", "开发", "开发/工作", "未分类"]
    # 开发 组内按标题排序
    dev = next(g for g in groups if g["folderPath"] == "开发")
    assert dev["count"] == 1
    assert dev["items"][0]["title"] == "GitHub 首页"
    # 去重保留文件夹路径更短的书签（重复-根级），且按用户分类归入「书签栏」
    shuqianlan = next(g for g in groups if g["folderPath"] == "书签栏")
    assert shuqianlan["count"] == 1
    assert shuqianlan["items"][0]["title"] == "重复-根级"
    # 根目录直接存放的书签归入「未分类」
    unclassified = next(g for g in groups if g["folderPath"] == "未分类")
    assert unclassified["items"][0]["url"] == "https://root.example.com/"


def test_snapshot_roundtrip(tmp_path: Path) -> None:
    target = tmp_path / "snapshot.json"
    save_snapshot({"total": 1, "groups": []}, target)
    assert load_snapshot(target) == {"total": 1, "groups": []}
    assert load_snapshot(tmp_path / "missing.json") is None
    (tmp_path / "broken.json").write_text("{not-json", encoding="utf-8")
    assert load_snapshot(tmp_path / "broken.json") is None


def test_collect_and_summary_roundtrip(plugin_env: dict, tmp_path: Path) -> None:
    client = _client(plugin_env, tmp_path / "snapshot.json")
    resp = client.post(
        "/api/desktop/bookmarks/collect",
        json={
            "source": "chrome-extension",
            "bookmarks": [
                _bookmark(id="1", title="A", url="https://example.com/a", folderPath="书签栏").model_dump(),
                _bookmark(id="2", title="B", url="https://example.com/b", folderPath="书签栏").model_dump(),
                _bookmark(id="3", title="内部", url="chrome://version/").model_dump(),
            ],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 3
    assert data["filtered"] == 1
    assert data["unique"] == 2
    assert data["groups"][0]["folderPath"] == "书签栏"
    assert data["groups"][0]["items"][0]["title"] == "A"

    summary = client.get("/api/desktop/bookmarks/summary")
    assert summary.status_code == 200
    assert summary.json()["unique"] == 2


def test_summary_404_without_snapshot(plugin_env: dict, tmp_path: Path) -> None:
    client = _client(plugin_env, tmp_path / "snapshot.json")
    resp = client.get("/api/desktop/bookmarks/summary")
    assert resp.status_code == 404
    assert "整理" in resp.json()["detail"]


def test_collect_rejects_oversize_report(plugin_env: dict, tmp_path: Path) -> None:
    client = _client(plugin_env, tmp_path / "snapshot.json")
    bookmarks = [_bookmark(id=str(i), url=f"https://example.com/{i}") for i in range(20001)]
    resp = client.post(
        "/api/desktop/bookmarks/collect",
        json={"source": "chrome-extension", "bookmarks": [b.model_dump() for b in bookmarks]},
    )
    assert resp.status_code == 400
    assert "上限" in resp.json()["detail"]
