#!/usr/bin/env python3
"""发布子应用（插件）：打包 zip + 更新市场索引，一条命令走完「上架 / 升级」。

用法（在 `apps/desktop` 目录下）：

    # 打包 hello-world 并更新 market/index.json（最常用）
    .venv/bin/python scripts/make_plugin_release.py hello-world

    # 先递增 manifest 里的版本，再打包上架
    .venv/bin/python scripts/make_plugin_release.py hello-world --bump patch

    # 只校验（manifest / 索引 / 包 sha256 是否自洽），供 CI 用
    .venv/bin/python scripts/make_plugin_release.py hello-world --check-only

    # 只打包、不碰索引（本地联调）
    .venv/bin/python scripts/make_plugin_release.py hello-world --no-index --out-dir dist

脚本做四件事：
1. 校验插件目录：manifest.json 可解析、id 合法、entry 文件存在；
2. 确定性打包（固定 zip 时间戳 + 保留可执行位），同一个插件重复打包 sha256 不变；
3. 更新 `market/index.json`：同 id 条目就地覆盖（不重排其他条目），
   `download` 指向本仓库 raw 地址，`mirrors` 指向 Gitee raw 镜像；
4. 打印 sha256 / size / 索引变化与下一步命令（提交并推送 main，raw 地址推上去即生效）。

护栏：索引里已有的版本**高于**要发布的版本时拒绝（避免用户被降级）；
同版本但包内容变了也拒绝（否则缓存过索引的用户会装到不同包），
两处都要显式加 `--force` 才放行。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PLUGINS_DIR = PROJECT_ROOT / "plugins"
MARKET_DIR = PROJECT_ROOT / "market"
INDEX_PATH = MARKET_DIR / "index.json"
PACKAGES_DIR = MARKET_DIR / "packages"

GITHUB_REPO = "xingwenl/xxai"
GITEE_REPO = "xingwenl/xxai"
BRANCH = "main"

# 插件 id 规则与宿主 registry 保持一致：小写字母/数字开头，允许中划线
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")
# 只接受纯数字段（升级比较依赖它；带 -beta 之类预发布后缀时不允许自动 bump）
VERSION_PATTERN = re.compile(r"^\d+(?:\.\d+)*$")
# 打进包里的垃圾文件（不参与分发，避免每次构建 sha 漂移）
SKIP_NAMES = {".DS_Store", "__pycache__", "node_modules", ".git", ".pytest_cache"}
SKIP_SUFFIXES = (".pyc", ".pyo")

# 固定 zip 内文件时间戳：同一个插件内容不变，重复打包得到完全相同的字节与 sha256
ZIP_FIXED_TIME = (1980, 1, 1, 0, 0, 0)


class ReleaseError(Exception):
    """发布流程中的可预期错误（消息直接给用户看）。"""


def _fail(message: str) -> None:
    sys.exit(f"✗ {message}")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def bump_version(version: str, part: str) -> str:
    """把 x.y.z 递增指定段，返回新版本号。"""
    if not VERSION_PATTERN.match(version):
        raise ReleaseError(f"版本号 {version!r} 不是纯数字段（如 1.2.3），无法自动递增，请手工改 manifest")
    numbers = [int(item) for item in version.split(".")]
    while len(numbers) < 3:
        numbers.append(0)
    index = {"major": 0, "minor": 1, "patch": 2}[part]
    numbers[index] += 1
    for position in range(index + 1, len(numbers)):
        numbers[position] = 0
    return ".".join(str(item) for item in numbers)


def resolve_plugin_dir(target: str | None) -> Path:
    """target 可以是插件 id（在 plugins/ 下找）或直接是目录路径。"""
    if not target:
        target = "hello-world"
    candidate = Path(target).expanduser()
    if candidate.is_dir():
        return candidate.resolve()
    plugin_dir = (PLUGINS_DIR / target).resolve()
    if plugin_dir.is_dir():
        return plugin_dir
    available = sorted(path.name for path in PLUGINS_DIR.iterdir() if (path / "manifest.json").is_file())
    raise ReleaseError(f"找不到插件：{target}（plugins/ 下现有：{', '.join(available) or '无'}）")


def load_manifest(plugin_dir: Path) -> tuple[dict, Path]:
    manifest_path = plugin_dir / "manifest.json"
    if not manifest_path.is_file():
        raise ReleaseError(f"{plugin_dir} 里没有 manifest.json")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ReleaseError(f"manifest.json 不是合法 JSON：{exc}") from exc
    if not isinstance(manifest, dict):
        raise ReleaseError("manifest.json 顶层必须是对象")
    plugin_id = str(manifest.get("id") or "").strip()
    if not ID_PATTERN.match(plugin_id):
        raise ReleaseError(f"manifest.id {plugin_id!r} 不合法（只允许小写字母/数字/中划线）")
    if plugin_dir.name != plugin_id:
        raise ReleaseError(
            f"目录名 {plugin_dir.name!r} 与 manifest.id {plugin_id!r} 不一致（宿主按 id 安装，必须一致）"
        )
    if not str(manifest.get("name") or "").strip():
        raise ReleaseError("manifest.name 不能为空（市场列表要显示它）")
    version = str(manifest.get("version") or "").strip()
    if not version:
        raise ReleaseError("manifest.version 不能为空")
    entry = str(manifest.get("entry") or "").strip()
    if not entry:
        raise ReleaseError("manifest.entry 不能为空")
    if not (plugin_dir / entry).is_file():
        raise ReleaseError(f"manifest.entry 指向的文件不存在：{plugin_dir / entry}")
    icon = str(manifest.get("icon") or "").strip()
    if icon and not (plugin_dir / icon).is_file():
        raise ReleaseError(f"manifest.icon 指向的文件不存在：{plugin_dir / icon}")
    permissions = manifest.get("permissions", [])
    if not isinstance(permissions, list) or not all(isinstance(item, str) for item in permissions):
        raise ReleaseError("manifest.permissions 必须是字符串数组")
    return manifest, manifest_path


def build_zip(plugin_dir: Path, plugin_id: str, out_path: Path) -> Path:
    """确定性打包：包内顶层目录是 <id>/，固定时间戳，保留可执行位。"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink()
    files = []
    for path in sorted(plugin_dir.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(plugin_dir)
        if any(part in SKIP_NAMES for part in relative.parts):
            continue
        if path.name.endswith(SKIP_SUFFIXES):
            continue
        files.append((path, f"{plugin_id}/{relative.as_posix()}"))
    if not files:
        raise ReleaseError(f"{plugin_dir} 里没有可打包的文件")
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, arcname in files:
            info = zipfile.ZipInfo(arcname, date_time=ZIP_FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            mode = 0o755 if os.access(path, os.X_OK) else 0o644
            # 手动写 external_attr：ZipInfo.writestr 不会从源文件带权限位，可执行脚本会丢执行位
            info.external_attr = (0o100000 | mode) << 16
            archive.writestr(info, path.read_bytes())
    return out_path


def repo_prefix() -> str:
    """apps/desktop 在 git 仓库里的相对路径（拼 raw 地址要用仓库根相对路径）。"""
    try:
        completed = subprocess.run(
            [_require_git(), "rev-parse", "--show-toplevel"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        repo_root = Path(completed.stdout.strip()).resolve()
        relative = PROJECT_ROOT.resolve().relative_to(repo_root).as_posix()
        return "" if relative == "." else relative
    except (subprocess.CalledProcessError, OSError, ValueError):
        # 非 git 环境（例如解压出来的包）退回约定路径
        return "apps/desktop"


def asset_rel_path(out_path: Path) -> Path:
    """计算包在 git 仓库里的相对路径，用来拼 raw 下载地址。"""
    try:
        local = out_path.resolve().relative_to(PROJECT_ROOT)
    except ValueError:
        local = Path("market") / "packages" / out_path.name
    prefix = repo_prefix()
    return Path(prefix, local) if prefix else local


def display_path(path: Path) -> str:
    """把路径显示成 git 仓库相对路径（提交命令要用它，直接复制即可执行）。"""
    try:
        local = path.resolve().relative_to(PROJECT_ROOT)
    except ValueError:
        return str(path)
    prefix = repo_prefix()
    return f"{prefix}/{local.as_posix()}" if prefix else local.as_posix()


def build_entry(
    manifest: dict,
    *,
    out_path: Path,
    github_repo: str,
    gitee_repo: str,
    branch: str,
    existing: dict | None = None,
) -> dict:
    data = out_path.read_bytes()
    rel = asset_rel_path(out_path)
    github_url = f"https://raw.githubusercontent.com/{github_repo}/{branch}/{rel.as_posix()}"
    gitee_url = f"https://gitee.com/{gitee_repo}/raw/{branch}/{rel.as_posix()}"
    entry = dict(existing or {})
    description = str(manifest.get("description", "")).strip()
    previous_description = str(entry.get("description", "")).strip()
    # 市场索引里的文案允许比 manifest 更详细（例如多列几项能力）；
    # 若 manifest 的描述只是市场文案的前缀，就保留原来的市场文案，避免每次发版把介绍改短。
    if previous_description and description and previous_description.startswith(description):
        description = previous_description
    entry.update(
        {
            "id": manifest["id"],
            "name": manifest["name"],
            "version": str(manifest["version"]),
            "description": description,
            "download": github_url,
            "sha256": sha256_bytes(data),
            "size": len(data),
            "permissions": list(manifest.get("permissions", [])),
        }
    )
    if gitee_url != github_url:
        entry["mirrors"] = [gitee_url]
    else:
        entry.pop("mirrors", None)
    return entry


def load_index(index_path: Path) -> dict:
    if not index_path.is_file():
        return {"version": 1, "plugins": []}
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ReleaseError(f"{index_path} 不是合法 JSON：{exc}") from exc
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise ReleaseError(f"{index_path} 的 version 必须是 1")
    if not isinstance(payload.get("plugins"), list):
        raise ReleaseError(f"{index_path} 的 plugins 必须是数组")
    return payload


def merge_entry(index: dict, entry: dict) -> tuple[dict, dict | None, str]:
    """把条目就地更新进索引，返回 (索引, 旧条目, 变化说明)。"""
    plugins = index.setdefault("plugins", [])
    for position, current in enumerate(plugins):
        if isinstance(current, dict) and current.get("id") == entry["id"]:
            plugins[position] = entry
            return index, current, f"更新已有条目（第 {position + 1} 条）"
    plugins.append(entry)
    return index, None, f"追加新条目（第 {len(plugins)} 条）"


def check_version_guard(existing: dict | None, version: str, *, force: bool) -> None:
    """打包前的护栏：不允许发布比索引里更低的版本（市场只升不降）。"""
    if not existing:
        return
    existing_version = str(existing.get("version") or "")
    if not existing_version or existing_version == version:
        return
    if _version_greater(existing_version, version):
        if not force:
            raise ReleaseError(
                f"索引里 {existing.get('id')} 已经是 v{existing_version}，比本次的 v{version} 更高；"
                "市场只会提示升级不会降级，确要回退请加 --force"
            )
        print(f"⚠ 索引版本 v{existing_version} 高于本次 v{version}，已按 --force 覆盖")


def check_sha_guard(existing: dict | None, version: str, sha256: str, *, force: bool) -> None:
    """打包后的护栏：同版本换包会让缓存过索引的用户装到不一致的内容。"""
    if not existing or str(existing.get("version") or "") != version:
        return
    if existing.get("sha256") and existing["sha256"] != sha256:
        if not force:
            raise ReleaseError(
                f"v{version} 已经发布过且包内容不同（sha256 变了）；"
                "同版本换包会让缓存过索引的用户装到不一致的内容，请先递增 manifest.version，或加 --force"
            )
        print(f"⚠ 同版本 v{version} 内容发生变化，已按 --force 覆盖")


def _version_greater(left: str, right: str) -> bool:
    """与宿主 desktop_app/version.py 同口径的保守比较（脚本不 import 宿主包，避免 venv 依赖）。"""
    try:
        left_numbers = [int(item) for item in re.split(r"[.\-+]", left) if item.isdigit()]
        right_numbers = [int(item) for item in re.split(r"[.\-+]", right) if item.isdigit()]
    except ValueError:  # pragma: no cover - isdigit 过滤后不会发生
        return False
    size = max(len(left_numbers), len(right_numbers))
    left_numbers += [0] * (size - len(left_numbers))
    right_numbers += [0] * (size - len(right_numbers))
    if left_numbers != right_numbers:
        return left_numbers > right_numbers
    # 数字段相同：无预发布后缀的正式版更大（0.2.0 > 0.2.0-beta）
    left_pre = bool(re.search(r"[-+]", left))
    right_pre = bool(re.search(r"[-+]", right))
    return right_pre and not left_pre


def write_manifest(manifest_path: Path, manifest: dict) -> None:
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_index(index_path: Path, index: dict) -> None:
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def git_commit(paths: list[Path], message: str) -> None:
    git = _require_git()
    relative: list[str] = []
    for path in paths:
        try:
            relative.append(str(path.resolve().relative_to(PROJECT_ROOT)))
        except ValueError as exc:
            raise ReleaseError(f"--git 只能提交 {PROJECT_ROOT} 内的文件，收到：{path}") from exc
    subprocess.run([git, "add", *relative], cwd=PROJECT_ROOT, check=True)
    subprocess.run([git, "commit", "-m", message], cwd=PROJECT_ROOT, check=True)


def _require_git() -> str:
    import shutil

    git = shutil.which("git")
    if not git:
        raise ReleaseError("找不到 git 命令")
    return git


def describe_entry(entry: dict) -> str:
    permissions = ", ".join(entry.get("permissions") or []) or "无"
    mirrors = entry.get("mirrors") or []
    lines = [
        f"  id:          {entry['id']}",
        f"  version:     {entry['version']}",
        f"  size:        {entry['size']} 字节",
        f"  sha256:      {entry['sha256']}",
        f"  permissions: {permissions}",
        f"  download:    {entry['download']}",
    ]
    if mirrors:
        lines.append(f"  mirrors:     {', '.join(mirrors)}")
    return "\n".join(lines)


def run(args: argparse.Namespace) -> int:
    plugin_dir = resolve_plugin_dir(args.target)
    manifest, manifest_path = load_manifest(plugin_dir)
    plugin_id = manifest["id"]

    if args.bump and args.version:
        raise ReleaseError("--bump 与 --version 只能二选一")
    changed_version = None
    if args.bump:
        manifest["version"] = bump_version(str(manifest["version"]), args.bump)
        changed_version = manifest["version"]
    elif args.version:
        manifest["version"] = args.version
        changed_version = args.version

    version = str(manifest["version"])
    _original_version = version
    out_dir = Path(args.out_dir).expanduser() if args.out_dir else PACKAGES_DIR
    out_path = out_dir / f"{plugin_id}-{version}.zip"
    index_path = Path(args.index).expanduser() if args.index else INDEX_PATH

    if args.check_only:
        print(f"插件目录: {plugin_dir}")
        print(f"manifest: {display_path(manifest_path)}")
        print(f"版本:     {plugin_id} v{version}")
        if args.bump or args.version:
            print("⚠ --check-only 不写回 manifest 版本变更")
        if out_path.is_file():
            data = out_path.read_bytes()
            print(f"包:       {display_path(out_path)}（{len(data)} 字节，sha256 {sha256_bytes(data)}）")
        else:
            print(f"包:       {out_path.name} 还不存在（首次发布时生成）")
        index = load_index(index_path)
        existing = next((item for item in index.get("plugins", []) if item.get("id") == plugin_id), None)
        if not existing:
            print(f"索引:     尚未收录 {plugin_id}（发布后会追加）")
            return 0
        print(f"索引:     v{existing.get('version')} sha256 {existing.get('sha256')}")
        if str(existing.get("version")) != version:
            print(f"⚠ 清单版本（v{existing.get('version')}）与 manifest（v{version}）不一致，发布时会更新")
        elif out_path.is_file() and existing.get("sha256") != sha256_bytes(out_path.read_bytes()):
            print("⚠ 同版本但包内容不同（sha256 不一致），发布时会被拦下（需 --force 或先递增版本）")
        else:
            print("✓ 索引与 manifest / 包自洽")
        return 0

    index: dict | None = None
    existing: dict | None = None
    if not args.no_index:
        index = load_index(index_path)
        existing = next((item for item in index.get("plugins", []) if item.get("id") == plugin_id), None)
        # 版本护栏放在写 manifest 之前：被拦下时仓库保持原样
        check_version_guard(existing, version, force=args.force)

    if changed_version:
        action = "递增版本" if args.bump else "设置版本"
        print(f"{action}: {plugin_id} → v{version}")
        if not args.dry_run:
            write_manifest(manifest_path, manifest)

    print(f"打包: {plugin_dir} → {display_path(out_path)}")
    if args.dry_run:
        print("（--dry-run：不实际写文件、不更新索引）")
        return 0

    original_manifest_text = None
    if changed_version:
        original_manifest_text = (
            json.dumps({**manifest, "version": _original_version}, ensure_ascii=False, indent=2) + "\n"
        )

    try:
        build_zip(plugin_dir, plugin_id, out_path)
        entry = build_entry(
            manifest,
            out_path=out_path,
            github_repo=args.github_repo,
            gitee_repo=args.gitee_repo,
            branch=args.branch,
            existing=existing,
        )
        if index is not None:
            check_sha_guard(existing, version, entry["sha256"], force=args.force)
    except ReleaseError:
        # 打包或同版本换包校验失败：把 manifest 版本改回去，别留一个「版本改了但没发布」的脏工作区
        if original_manifest_text is not None:
            manifest_path.write_text(original_manifest_text, encoding="utf-8")
            print(f"↩ 已回滚 manifest 版本：{display_path(manifest_path)}")
        raise

    if args.no_index:
        print(f"✓ 已生成：{display_path(out_path)}")
        print(describe_entry(entry))
        print("\n（--no-index：未更新市场索引）")
        return 0

    assert index is not None
    index, old_entry, change = merge_entry(index, entry)
    write_index(index_path, index)
    print(f"✓ 已生成：{display_path(out_path)}")
    print(describe_entry(entry))
    print(f"✓ 索引已更新：{display_path(index_path)}（{change}）")
    if old_entry and old_entry != entry:
        print(f"  上一版：v{old_entry.get('version')}（sha256 {old_entry.get('sha256')}）")

    if args.git:
        message = f"chore(release): {plugin_id} v{version}"
        git_commit([manifest_path, out_path, index_path], message)
        print(f"✓ 已提交：{message}")

    print("\n下一步：")
    if args.git:
        print(f"  1. 推送：git push origin {args.branch}（raw 地址指向 {args.branch}，推上去即生效）")
    else:
        print(f"  1. 提交并推送：git add {display_path(out_path)} {display_path(index_path)}")
        print(f"     git commit -m 'chore(release): {plugin_id} v{version}' && git push origin {args.branch}")
    print("  2. 已装旧版的用户：设置页「插件市场」刷新后会看到「更新到 vX」，点一下即升级（旧目录自动备份）")
    print(f"  3. Gitee 镜像：把同一分支推一份到 Gitee（镜像地址 {GITEE_REPO}/{args.branch}），宿主主源失败会自动回退")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="发布子应用（打包 + 更新市场索引）")
    parser.add_argument(
        "target", nargs="?", default="hello-world", help="插件 id（plugins/ 下）或插件目录，默认 hello-world"
    )
    parser.add_argument("--bump", choices=("major", "minor", "patch"), help="打包前递增 manifest.version")
    parser.add_argument("--version", help="打包前把 manifest.version 直接改成该值")
    parser.add_argument("--out-dir", help="zip 输出目录，默认 market/packages")
    parser.add_argument("--index", help="市场索引路径，默认 market/index.json")
    parser.add_argument("--no-index", action="store_true", help="只打包，不更新索引")
    parser.add_argument("--check-only", action="store_true", help="只校验，不写任何文件")
    parser.add_argument("--force", action="store_true", help="允许覆盖更高版本 / 同版本换包")
    parser.add_argument("--git", action="store_true", help="提交 manifest / zip / 索引（不推送）")
    parser.add_argument("--dry-run", action="store_true", help="只打印将要做什么，不写文件")
    parser.add_argument("--branch", default=BRANCH, help=f"raw 地址指向的分支，默认 {BRANCH}")
    parser.add_argument("--github-repo", default=GITHUB_REPO, help=f"GitHub 仓库，默认 {GITHUB_REPO}")
    parser.add_argument("--gitee-repo", default=GITEE_REPO, help=f"Gitee 仓库，默认 {GITEE_REPO}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except ReleaseError as exc:
        _fail(str(exc))
    except subprocess.CalledProcessError as exc:  # pragma: no cover - git 失败时给出命令与返回码
        _fail(f"命令失败（退出码 {exc.returncode}）：{' '.join(map(str, exc.cmd))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
