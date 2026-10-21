#!/usr/bin/env python3
"""打包桌面发行包并生成/合并宿主更新清单。

用法（在 `apps/desktop` 目录下）：

    # 1) 先构建前端与 PyInstaller 产物
    pnpm --dir front build
    poetry run python build/build.py

    # 2) 打包 + 写清单（自动识别平台，默认 up 到 GitHub/Gitee Release）
    python scripts/make_release.py --notes "修复若干问题"

    # 只校验三处版本号与清单是否自洽，不出包
    python scripts/make_release.py --check-only

清单结构见 `releases/latest.json`，宿主 `desktop_app/app_update.py` 读取它。
宿主只做「检查 → 下载 → 校验 → 引导手动安装」，不会自动替换自己。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = PROJECT_ROOT / "dist"
RELEASES_DIR = PROJECT_ROOT / "releases"
MANIFEST_PATH = RELEASES_DIR / "latest.json"

GITHUB_REPO = "xingwenl/xxai"
GITEE_REPO = "xingwenl/xxai"
TAG_PREFIX = "desktop-v"

# 单平台包头：macOS 是 .app 目录，其余为 onedir 目录
APP_NAME = "WW"
VERSION_PATTERN = re.compile(r'^APP_VERSION\s*=\s*"([^"]+)"', re.MULTILINE)
TOML_VERSION_PATTERN = re.compile(r'^version\s*=\s*"([^"]+)"', re.MULTILINE)


def _fail(message: str) -> None:
    sys.exit(f"✗ {message}")


def _arch_key() -> str:
    machine = platform.machine().lower()
    arch = "arm64" if machine in {"arm64", "aarch64"} else "x64"
    system = sys.platform
    if system == "darwin":
        return f"macos-{arch}"
    if system.startswith(("win", "cygwin", "msys")):
        return f"windows-{arch}"
    if system.startswith("linux"):
        return f"linux-{arch}"
    _fail(f"不支持的平台：{system}（可在清单里手动补条目）")
    return ""  # 不可达，仅为类型检查


def read_versions() -> dict[str, str]:
    """读取三处版本号：app_config.py / pyproject.toml / front/package.json。"""
    app_config = (PROJECT_ROOT / "desktop_app" / "app_config.py").read_text(encoding="utf-8")
    match = VERSION_PATTERN.search(app_config)
    if not match:
        _fail("desktop_app/app_config.py 里找不到 APP_VERSION")
    pyproject = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    pyproject_version = TOML_VERSION_PATTERN.search(pyproject)
    if not pyproject_version:
        _fail("pyproject.toml 里找不到 [project] version")
    front = json.loads((PROJECT_ROOT / "front" / "package.json").read_text(encoding="utf-8"))
    return {
        "desktop_app/app_config.py": match.group(1),
        "pyproject.toml": pyproject_version.group(1),
        "front/package.json": str(front.get("version", "")),
    }


def check_versions() -> str:
    versions = read_versions()
    distinct = set(versions.values())
    if "" in distinct or len(distinct) != 1:
        lines = "\n".join(f"  {path}: {version or '<缺失>'}" for path, version in versions.items())
        _fail(f"三处版本号不一致，请先统一：\n{lines}")
    return versions["desktop_app/app_config.py"]


def find_bundle() -> tuple[Path, bool]:
    """返回 (待打包目录, 是否是 macOS .app)。"""
    app_bundle = DIST_DIR / f"{APP_NAME}.app"
    if app_bundle.is_dir():
        return app_bundle, True
    onedir = DIST_DIR / APP_NAME
    if onedir.is_dir():
        return onedir, False
    _fail(f"没有找到打包产物：{app_bundle} 或 {onedir}，请先运行 build/build.py")


def zip_bundle(src: Path, out_path: Path) -> None:
    """把 .app 或 onedir 目录打成 zip，保留可执行位，解压后顶层就是 WW.app / WW/。"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink()
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(src.rglob("*")):
            # 符号链接与 .app 里的 Contents 都要原样保留相对路径
            arcname = path.relative_to(src.parent)
            if path.is_dir():
                continue
            # ZipFile.write 通过 ZipInfo.from_file 保留 Unix 权限位（可执行位不能丢）
            zf.write(path, arcname.as_posix())


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest() -> dict:
    if not MANIFEST_PATH.is_file():
        return {"version": 1, "latest": "", "publishedAt": "", "notes": "", "releaseUrl": "", "platforms": {}}
    try:
        payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        _fail(f"{MANIFEST_PATH} 不是合法 JSON：{exc}")
    if payload.get("version") != 1:
        _fail(f"{MANIFEST_PATH} 的 version 必须是 1")
    payload.setdefault("platforms", {})
    return payload


def default_notes(version: str) -> str:
    return f"桌面版本 v{version}"


def build_manifest(
    *,
    version: str,
    asset_path: Path,
    platform_key: str,
    notes: str,
    reset: bool,
    repo_owner_github: str,
    repo_owner_gitee: str,
) -> dict:
    tag = f"{TAG_PREFIX}{version}"
    name = f"{APP_NAME}-{version}-{platform_key}.zip"
    data_size = asset_path.stat().st_size
    github_url = f"https://github.com/{repo_owner_github}/releases/download/{tag}/{name}"
    gitee_url = f"https://gitee.com/{repo_owner_gitee}/releases/download/{tag}/{name}"
    manifest = (
        {"version": 1, "latest": "", "publishedAt": "", "notes": "", "releaseUrl": "", "platforms": {}}
        if reset
        else load_manifest()
    )
    manifest["latest"] = version
    manifest["publishedAt"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    manifest["notes"] = notes
    manifest["releaseUrl"] = f"https://github.com/{repo_owner_github}/releases/tag/{tag}"
    manifest["platforms"][platform_key] = {
        "name": name,
        "url": github_url,
        "mirrors": [gitee_url],
        "sha256": sha256_file(asset_path),
        "size": data_size,
    }
    return manifest


def check_manifest(version: str) -> None:
    manifest = load_manifest()
    latest = str(manifest.get("latest") or "")
    platforms = manifest.get("platforms") or {}
    print(f"清单版本号: {latest or '<空>'}")
    print(f"平台资产:   {', '.join(sorted(platforms)) or '<空>'}")
    if not platforms:
        print("⚠ 清单里还没有任何平台资产，首次发版后由本脚本写入")
    if latest and latest != version:
        _fail(f"清单 latest（{latest}）与本机版本（{version}）不一致，请确认是否漏跑发版")
    for key, entry in platforms.items():
        sha = str(entry.get("sha256", ""))
        if len(sha) != 64 or any(ch not in "0123456789abcdef" for ch in sha):
            _fail(f"清单里 {key}.sha256 不是 64 位十六进制")
        if not entry.get("url") or not entry.get("name"):
            _fail(f"清单里 {key} 缺少 url 或 name")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="打包桌面发行包并生成宿主更新清单")
    parser.add_argument("--check-only", action="store_true", help="只校验版本号与清单自洽，不出包")
    parser.add_argument("--version", help="覆盖清单 latest（默认读 app_config.py）")
    parser.add_argument("--platform", help="平台键，默认按当前系统识别（macos-arm64 等）")
    parser.add_argument("--asset", type=Path, help="已有 zip 产物路径，跳过重新打包")
    parser.add_argument("--notes", default="", help="更新说明，写进清单 notes")
    parser.add_argument("--reset", action="store_true", help="丢弃清单里其他平台的旧条目")
    parser.add_argument("--github-repo", default=GITHUB_REPO, help=f"GitHub 仓库，默认 {GITHUB_REPO}")
    parser.add_argument("--gitee-repo", default=GITEE_REPO, help=f"Gitee 仓库，默认 {GITEE_REPO}")
    args = parser.parse_args(argv)

    version = check_versions()
    print(f"✓ 三处版本号一致：{version}")
    if args.check_only:
        print(f"清单文件: {MANIFEST_PATH.relative_to(PROJECT_ROOT)}")
        if not MANIFEST_PATH.is_file():
            print("⚠ 清单文件还不存在，首次发版会创建")
            return 0
        check_manifest(version)
        print("✓ 清单校验通过")
        return 0

    release_version = args.version or version
    platform_key = args.platform or _arch_key()

    if args.asset:
        asset_path = args.asset.resolve()
        if not asset_path.is_file():
            _fail(f"指定的产物不存在：{asset_path}")
        out_path = asset_path
    else:
        bundle, _is_macos = find_bundle()
        out_path = DIST_DIR / "releases" / f"{APP_NAME}-{release_version}-{platform_key}.zip"
        print(f"打包 {bundle.name} → {out_path.relative_to(PROJECT_ROOT)}")
        zip_bundle(bundle, out_path)
        asset_path = out_path

    notes = args.notes or default_notes(release_version)
    manifest = build_manifest(
        version=release_version,
        asset_path=asset_path,
        platform_key=platform_key,
        notes=notes,
        reset=args.reset,
        repo_owner_github=args.github_repo,
        repo_owner_gitee=args.gitee_repo,
    )
    RELEASES_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    entry = manifest["platforms"][platform_key]
    print(f"✓ 产物：{out_path}")
    print(f"  sha256: {entry['sha256']}")
    print(f"  size:   {entry['size']}")
    print(f"✓ 清单已更新：{MANIFEST_PATH.relative_to(PROJECT_ROOT)}（latest={manifest['latest']}）")
    print("\n下一步：")
    print(f"  1. 上传 {out_path.name} 到 GitHub Release（tag {TAG_PREFIX}{release_version}）")
    print(f"  2. 同步到 Gitee Release（镜像清单与安装包，GitHub 不可达时宿主会回退）")
    print(f"  3. 提交 releases/latest.json 与版本号变更，再推送 main 分支")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
