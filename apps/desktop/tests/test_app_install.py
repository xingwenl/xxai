"""宿主自更新安装测试：.app 推导、包校验、安装脚本生成与安装编排。"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

from desktop_app import app_install


def _make_app(root: Path, name: str = "WW.app") -> tuple[Path, Path]:
    """在 root 下造一个最小 .app 结构，返回 (bundle, 可执行文件)。"""
    bundle = root / name
    exe = bundle / "Contents" / "MacOS" / "WW"
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (bundle / "Contents" / "Info.plist").write_text("<plist/>", encoding="utf-8")
    return bundle, exe


def _zip_app(app: Path, out: Path) -> Path:
    """用 ditto 打 zip（与 build/build.py 打安装包用的是同一个工具）。"""
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ditto", "-c", "-k", "--keepParent", str(app), str(out)], check=True)
    return out


def _package(app: Path, out: Path) -> tuple[Path, str, int]:
    """返回 (zip 路径, sha256, 字节数)，模拟下载完成后的更新包。"""
    package = _zip_app(app, out)
    payload = package.read_bytes()
    return package, hashlib.sha256(payload).hexdigest(), len(payload)


@pytest.fixture(autouse=True)
def isolated_updates(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """把安装脚本/日志目录指到 tmp，避免污染真实 HOME。"""
    monkeypatch.setattr(app_install.paths, "updates_dir", lambda: tmp_path / "updates")
    return tmp_path / "updates"


@pytest.fixture
def needs_ditto() -> None:
    """ditto 只在 macOS 上有；没有就跳过，避免 CI 上误报红。"""
    if sys.platform != "darwin":
        pytest.skip("ditto 只在 macOS 上可用")


# ---------- 1. .app 路径推导 ----------


def test_bundle_path_from_executable(tmp_path: Path) -> None:
    bundle, exe = _make_app(tmp_path)
    assert app_install.bundle_path(exe) == bundle


def test_bundle_path_rejects_non_bundle_executable(tmp_path: Path) -> None:
    exe = tmp_path / "bin" / "WW"
    exe.parent.mkdir()
    exe.write_text("x", encoding="utf-8")
    with pytest.raises(app_install.AppInstallError, match="不在 .app 包内"):
        app_install.bundle_path(exe)


def test_bundle_path_rejects_development_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    with pytest.raises(app_install.AppInstallError, match="开发模式"):
        app_install.bundle_path()


# ---------- 2. 安装包校验 ----------


def test_verify_package_accepts_matching_package(tmp_path: Path) -> None:
    package = tmp_path / "WW.zip"
    package.write_bytes(b"payload")
    digest = hashlib.sha256(b"payload").hexdigest()
    app_install.verify_package(package, expected_sha256=digest, expected_size=7)


def test_verify_package_rejects_size_and_sha(tmp_path: Path) -> None:
    package = tmp_path / "WW.zip"
    package.write_bytes(b"payload")
    digest = hashlib.sha256(b"payload").hexdigest()
    with pytest.raises(app_install.AppInstallError, match="大小与清单不一致"):
        app_install.verify_package(package, expected_sha256=digest, expected_size=99)
    with pytest.raises(app_install.AppInstallError, match="sha256 与清单不一致"):
        app_install.verify_package(package, expected_sha256="0" * 64, expected_size=7)


def test_verify_package_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(app_install.AppInstallError, match="更新包不存在"):
        app_install.verify_package(tmp_path / "none.zip", expected_sha256="0" * 64, expected_size=1)


# ---------- 3. 安装脚本 ----------


def test_script_text_waits_backs_up_and_rolls_back(tmp_path: Path) -> None:
    bundle = tmp_path / "WW.app"
    staged = tmp_path / ".WW-update-0.3.0" / "WW.app"
    backup = tmp_path / "WW.app.ww-old"
    log = tmp_path / "install.log"
    text = app_install.script_text(bundle, staged, backup, 4321, log)

    assert text.startswith("#!/bin/sh")
    assert f"APP={bundle}" in text
    assert f"NEW={staged}" in text
    assert f"BAK={backup}" in text
    assert "PID=4321" in text
    # 必须等宿主退出后再替换，且失败要回滚、成功才删备份
    assert "kill -TERM" in text
    assert 'mv "$APP" "$BAK"' in text
    assert 'mv "$NEW" "$APP"' in text
    # macOS 的 xattr 没有 -r，必须用 find 逐文件清 quarantine，否则脚本里那行必然报错
    assert 'find "$APP" -exec xattr -d com.apple.quarantine {}' in text
    assert 'rmdir "$(dirname "$NEW")"' in text
    assert 'mv "$BAK" "$APP"' in text


def test_script_text_quotes_paths_with_spaces(tmp_path: Path) -> None:
    bundle = tmp_path / "My App.app"
    text = app_install.script_text(
        bundle,
        tmp_path / "stage" / "My App.app",
        tmp_path / "backup",
        7,
        tmp_path / "install.log",
    )
    # 路径带空格时必须整体加引号，否则脚本会把 "My" 当成 APP，替换到错误位置
    assert f"APP='{bundle}'" in text


# ---------- 4. 安装编排 ----------


def test_install_package_spawns_script_for_new_bundle(tmp_path: Path, needs_ditto: None) -> None:
    current, _ = _make_app(tmp_path / "root", "WW.app")
    new_app, _ = _make_app(tmp_path / "new", "WW.app")
    (new_app / "marker.txt").write_text("new", encoding="utf-8")
    package, digest, size = _package(new_app, tmp_path / "pkg" / "WW-0.3.0.zip")
    spawned: list[Path] = []

    result = app_install.install_package(
        package,
        "0.3.0",
        expected_sha256=digest,
        expected_size=size,
        pid=999,
        platform_name="darwin",
        bundle=current,
        spawn=spawned.append,
    )

    script = Path(result["script"])
    assert script.is_file() and script.stat().st_mode & 0o111
    assert spawned == [script]
    staged = tmp_path / "root" / ".WW-update-0.3.0" / "WW.app"
    assert staged.is_dir()
    assert (staged / "marker.txt").read_text(encoding="utf-8") == "new"
    assert "PID=999" in script.read_text(encoding="utf-8")


def test_install_package_rejects_renamed_app(tmp_path: Path, needs_ditto: None) -> None:
    current, _ = _make_app(tmp_path / "root", "WW.app")
    other, _ = _make_app(tmp_path / "new", "Other.app")
    package, digest, size = _package(other, tmp_path / "pkg" / "WW-0.3.0.zip")
    with pytest.raises(app_install.AppInstallError, match="应用名"):
        app_install.install_package(
            package,
            "0.3.0",
            expected_sha256=digest,
            expected_size=size,
            platform_name="darwin",
            bundle=current,
            spawn=lambda _: None,
        )
    assert not (tmp_path / "root" / ".WW-update-0.3.0").exists()


def test_install_package_rejects_other_platforms(tmp_path: Path) -> None:
    bundle, _ = _make_app(tmp_path)
    with pytest.raises(app_install.AppInstallError, match="只支持 macOS"):
        app_install.install_package(
            tmp_path / "WW.zip",
            "0.3.0",
            expected_sha256="0" * 64,
            expected_size=1,
            platform_name="win32",
            bundle=bundle,
            spawn=lambda _: None,
        )


def test_install_package_rejects_readonly_parent(tmp_path: Path, needs_ditto: None) -> None:
    current, _ = _make_app(tmp_path / "root", "WW.app")
    new_app, _ = _make_app(tmp_path / "new", "WW.app")
    package, digest, size = _package(new_app, tmp_path / "pkg" / "WW-0.3.0.zip")
    folder = current.parent
    folder.chmod(0o500)
    try:
        with pytest.raises(app_install.AppInstallError, match="不可写"):
            app_install.install_package(
                package,
                "0.3.0",
                expected_sha256=digest,
                expected_size=size,
                platform_name="darwin",
                bundle=current,
                spawn=lambda _: None,
            )
    finally:
        folder.chmod(0o755)
