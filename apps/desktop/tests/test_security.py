"""zip 安全解压测试：路径穿越、绝对路径、符号链接与大小限制。"""

from __future__ import annotations

import stat
import zipfile
from pathlib import Path

import pytest

import desktop_app.security as security
from conftest import make_zip


def test_safe_extract_ok(tmp_path: Path) -> None:
    src = make_zip(tmp_path / "ok.zip", {"a.txt": "hello", "sub/b.txt": "world"})
    dest = tmp_path / "out"
    security.safe_extract_zip(src, dest)
    assert (dest / "a.txt").read_text() == "hello"
    assert (dest / "sub" / "b.txt").read_text() == "world"


@pytest.mark.parametrize("name", ["../evil.txt", "/tmp/evil.txt", "..\\evil.txt", "a/../evil.txt"])
def test_path_traversal_rejected(tmp_path: Path, name: str) -> None:
    src = make_zip(tmp_path / "evil.zip", {name: "x"})
    with pytest.raises(security.ZipSecurityError):
        security.safe_extract_zip(src, tmp_path / "out")


def test_symlink_entry_rejected(tmp_path: Path) -> None:
    src = tmp_path / "link.zip"
    with zipfile.ZipFile(src, "w") as zf:
        info = zipfile.ZipInfo("link")
        info.external_attr = (stat.S_IFLNK | 0o755) << 16
        zf.writestr(info, b"target")
    with pytest.raises(security.ZipSecurityError, match="符号链接"):
        security.safe_extract_zip(src, tmp_path / "out")


def test_entry_count_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(security, "MAX_ENTRIES", 3)
    src = make_zip(tmp_path / "many.zip", {f"f{i}.txt": "x" for i in range(4)})
    with pytest.raises(security.ZipSecurityError, match="条目数"):
        security.safe_extract_zip(src, tmp_path / "out")


def test_file_size_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(security, "MAX_FILE_SIZE", 4)
    src = make_zip(tmp_path / "big.zip", {"big.txt": "12345"})
    with pytest.raises(security.ZipSecurityError, match="单文件"):
        security.safe_extract_zip(src, tmp_path / "out")


def test_total_size_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(security, "MAX_FILE_SIZE", 100)
    monkeypatch.setattr(security, "MAX_ZIP_SIZE", 8)
    src = make_zip(tmp_path / "total.zip", {"a.txt": "12345", "b.txt": "67890"})
    with pytest.raises(security.ZipSecurityError, match="总大小"):
        security.safe_extract_zip(src, tmp_path / "out")
