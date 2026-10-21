#!/usr/bin/env python3
"""发布主应用（桌面宿主）：改版本 → 构建 → 打包 → 写更新清单 → 上传 Release。

用法（在 `apps/desktop` 目录下，各步骤可按需组合）：

    # 只校验三处版本号与清单是否自洽（CI 用，不出包）
    .venv/bin/python scripts/make_release.py --check-only

    # 递增版本 + 构建前端与 PyInstaller 产物 + 打 zip + 写清单
    .venv/bin/python scripts/make_release.py --bump patch --build --notes "修复若干问题"

    # 提交版本与清单、打 tag，并上传 GitHub / Gitee Release
    .venv/bin/python scripts/make_release.py --git --publish all --notes "本次更新了什么"

    # 只打印将要做什么，不落任何文件（预演）
    .venv/bin/python scripts/make_release.py --bump minor --build --git --publish all --dry-run

做了什么：
1. 版本号三处统一：`desktop_app/app_config.py` 的 APP_VERSION、`pyproject.toml` 的
   `[project] version`、`front/package.json` 的 version；`--bump` / `--set-version` 可代改。
2. `--build` 依次跑 `pnpm --dir front build` 与 `python build/build.py`。
3. 把 `dist/WW.app`（macOS）或 `dist/WW/`（onedir）打成 `WW-<version>-<platform>.zip`，
   保留可执行位，算 sha256/size，合并进 `releases/latest.json`（只更新当前平台条目）。
4. `--git`：提交版本文件与清单，并打本地 tag `desktop-v<version>`（不推送）。
5. `--publish`：调 GitHub / Gitee REST API 建 Release 并上传 zip，可重复执行
   （同名资产先删后传）。令牌优先取环境变量 `GITHUB_TOKEN`（或 `GH_TOKEN`）、`GITEE_TOKEN`，
   其次取 `~/.desktop-app/release-tokens.json`。用 `--set-github-token` / `--set-gitee-token`
   交互式保存一次，之后不必每次 export（文件权限 600，不随仓库提交）。

宿主只做「检查 → 下载 → 校验 → 引导手动安装」，不会自动替换自己；
清单里的 url 指向 GitHub Release，mirrors 指向 Gitee 同 tag 地址（宿主自动回退）。
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = PROJECT_ROOT / "dist"
RELEASES_DIR = PROJECT_ROOT / "releases"
MANIFEST_PATH = RELEASES_DIR / "latest.json"

GITHUB_REPO = "xingwenl/xxai"
GITEE_REPO = "xingwenl/xxai"
BRANCH = "main"
TAG_PREFIX = "desktop-v"

# 单平台包头：macOS 是 .app 目录，其余为 onedir 目录
APP_NAME = "WW"
VERSION_PATTERN = re.compile(r'^APP_VERSION\s*=\s*"([^"]+)"', re.MULTILINE)
TOML_VERSION_PATTERN = re.compile(r'^version\s*=\s*"([^"]+)"', re.MULTILINE)
APP_CONFIG_PATH = PROJECT_ROOT / "desktop_app" / "app_config.py"
PYPROJECT_PATH = PROJECT_ROOT / "pyproject.toml"
FRONT_PACKAGE_PATH = PROJECT_ROOT / "front" / "package.json"

# 版本号必须能自动递增：纯数字段（带 -beta 之类后缀时请用 --set-version）
NUMERIC_VERSION = re.compile(r"^\d+(?:\.\d+)*$")


class PublishError(Exception):
    """上传 Release 时的可预期错误（消息直接给用户看）。"""


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


# ---------- 版本号 ----------


def read_versions() -> dict[str, str]:
    """读取三处版本号：app_config.py / pyproject.toml / front/package.json。"""
    app_config = APP_CONFIG_PATH.read_text(encoding="utf-8")
    match = VERSION_PATTERN.search(app_config)
    if not match:
        _fail("desktop_app/app_config.py 里找不到 APP_VERSION")
    pyproject = PYPROJECT_PATH.read_text(encoding="utf-8")
    pyproject_version = TOML_VERSION_PATTERN.search(pyproject)
    if not pyproject_version:
        _fail("pyproject.toml 里找不到 [project] version")
    front = json.loads(FRONT_PACKAGE_PATH.read_text(encoding="utf-8"))
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


def bump_version(current: str, part: str) -> str:
    """把 x.y.z 递增指定段。"""
    if not NUMERIC_VERSION.match(current):
        _fail(f"当前版本 {current!r} 不是纯数字段（如 1.2.3），无法自动递增，请用 --set-version")
    numbers = [int(item) for item in current.split(".")]
    while len(numbers) < 3:
        numbers.append(0)
    position = {"major": 0, "minor": 1, "patch": 2}[part]
    numbers[position] += 1
    for later in range(position + 1, len(numbers)):
        numbers[later] = 0
    return ".".join(str(item) for item in numbers)


def rewrite_versions(version: str) -> None:
    """把三处版本号都改成 version（其余内容与格式不动）。"""
    app_config = APP_CONFIG_PATH.read_text(encoding="utf-8")
    new_app_config, count = re.subn(
        r'^APP_VERSION\s*=\s*"[^"]*"', f'APP_VERSION = "{version}"', app_config, count=1, flags=re.MULTILINE
    )
    if count != 1:
        _fail("desktop_app/app_config.py 里改写 APP_VERSION 失败")

    pyproject = PYPROJECT_PATH.read_text(encoding="utf-8")
    new_pyproject, count = re.subn(
        r'^version\s*=\s*"[^"]*"', f'version = "{version}"', pyproject, count=1, flags=re.MULTILINE
    )
    if count != 1:
        _fail("pyproject.toml 里改写 [project] version 失败")

    front = json.loads(FRONT_PACKAGE_PATH.read_text(encoding="utf-8"))
    front["version"] = version

    APP_CONFIG_PATH.write_text(new_app_config, encoding="utf-8")
    PYPROJECT_PATH.write_text(new_pyproject, encoding="utf-8")
    FRONT_PACKAGE_PATH.write_text(json.dumps(front, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"✓ 三处版本号已改为 {version}")


# ---------- 构建 ----------


def run_frontend_build() -> None:
    pnpm = shutil.which("pnpm")
    if not pnpm:
        _fail("找不到 pnpm，无法构建前端（可先手工构建，或用 --asset 直接登记已有产物）")
    print("▶ 构建前端：pnpm --dir front build")
    subprocess.run([pnpm, "--dir", "front", "build"], cwd=PROJECT_ROOT, check=True)


def run_pyinstaller_build() -> None:
    print("▶ 打包应用：python build/build.py")
    subprocess.run([sys.executable, "build/build.py"], cwd=PROJECT_ROOT, check=True)


# ---------- 打包 ----------


def find_bundle() -> tuple[Path, bool]:
    """返回 (待打包目录, 是否是 macOS .app)。"""
    app_bundle = DIST_DIR / f"{APP_NAME}.app"
    if app_bundle.is_dir():
        return app_bundle, True
    onedir = DIST_DIR / APP_NAME
    if onedir.is_dir():
        return onedir, False
    _fail(f"没有找到打包产物：{app_bundle} 或 {onedir}，请先运行 --build（或 build/build.py）")


def zip_bundle(src: Path, out_path: Path) -> None:
    """把 .app 或 onedir 目录打成 zip，保留可执行位，解压后顶层就是 WW.app / WW/。"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink()
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(src.rglob("*")):
            if path.is_dir():
                continue
            arcname = path.relative_to(src.parent)
            # ZipFile.write 通过 ZipInfo.from_file 保留 Unix 权限位（可执行位不能丢）
            zf.write(path, arcname.as_posix())


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ---------- 更新清单 ----------


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


# ---------- git ----------


def _require_git() -> str:
    git = shutil.which("git")
    if not git:
        _fail("找不到 git 命令")
    return git


def commit_and_tag(version: str) -> None:
    git = _require_git()
    tag = f"{TAG_PREFIX}{version}"
    paths = [
        str(APP_CONFIG_PATH.relative_to(PROJECT_ROOT)),
        str(PYPROJECT_PATH.relative_to(PROJECT_ROOT)),
        str(FRONT_PACKAGE_PATH.relative_to(PROJECT_ROOT)),
        str(MANIFEST_PATH.relative_to(PROJECT_ROOT)),
    ]
    subprocess.run([git, "add", *paths], cwd=PROJECT_ROOT, check=True)
    message = f"chore(release): 桌面 v{version}"
    subprocess.run([git, "commit", "-m", message], cwd=PROJECT_ROOT, check=True)
    print(f"✓ 已提交：{message}")
    existing = subprocess.run(
        [git, "tag", "--list", tag], cwd=PROJECT_ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()
    if existing:
        print(f"⚠ tag {tag} 已存在，跳过打 tag")
        return
    subprocess.run([git, "tag", "-a", tag, "-m", message], cwd=PROJECT_ROOT, check=True)
    print(f"✓ 已打 tag：{tag}")


# ---------- 令牌 ----------

TOKEN_FILE_NAME = "release-tokens.json"
TOKEN_ENV_NAMES = {"github": ("GITHUB_TOKEN", "GH_TOKEN"), "gitee": ("GITEE_TOKEN",)}
HOST_LABELS = {"github": "GitHub", "gitee": "Gitee"}
GITHUB_PERMISSION_HINT = (
    "GitHub 令牌权限不足。细粒度令牌：Repository access 里勾选该仓库，"
    "并给 Repository permissions → Contents 设为 Read and write（Metadata 会自动只读）；"
    "经典令牌：私有库需要 repo、公开库 public_repo 即可。改完重新 --set-github-token 保存。"
)


def token_path() -> Path:
    """令牌文件位置：用户数据目录下，不随仓库提交。"""
    return Path.home() / ".desktop-app" / TOKEN_FILE_NAME


def load_saved_tokens() -> dict[str, str]:
    """读取已保存的令牌；文件不存在时返回空字典。"""
    path = token_path()
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        _fail(f"{path} 不是合法 JSON：{exc}")
    if not isinstance(payload, dict):
        _fail(f"{path} 内容必须是 JSON 对象")
    tokens: dict[str, str] = {}
    for host in TOKEN_ENV_NAMES:
        value = payload.get(host)
        if isinstance(value, str) and value.strip():
            tokens[host] = value.strip()
    return tokens


def resolve_token(host: str) -> tuple[str, str]:
    """返回 (令牌, 来源说明)。环境变量优先于本地令牌文件（方便 CI 覆盖）。"""
    for name in TOKEN_ENV_NAMES[host]:
        value = os.environ.get(name, "").strip()
        if value:
            return value, f"环境变量 {name}"
    saved = load_saved_tokens().get(host, "")
    if saved:
        return saved, f"本地令牌文件 {token_path()}"
    return "", ""


def save_token(host: str, token: str) -> Path:
    """保存令牌到本地文件（0600），保留另一个平台的令牌。"""
    token = token.strip()
    if not token:
        _fail("令牌不能为空")
    path = token_path()
    tokens = load_saved_tokens()
    tokens[host] = token
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass
    path.write_text(json.dumps(tokens, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path


def clear_tokens() -> Path:
    """删除令牌文件（不报错）。"""
    path = token_path()
    path.unlink(missing_ok=True)
    return path


def mask_token(token: str) -> str:
    """只显示首尾几位，避免终端/日志泄露完整令牌。"""
    if len(token) <= 8:
        return "…"
    return f"{token[:4]}…{token[-4:]}"


def print_token_status() -> None:
    print(f"令牌文件: {token_path()}")
    for host, label in HOST_LABELS.items():
        token, source = resolve_token(host)
        if token:
            print(f"  {label}: 已配置 {mask_token(token)}（来源：{source}）")
        else:
            print(f"  {label}: 未配置（用 --set-{host}-token 保存）")


# ---------- 上传 Release ----------


def _http(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    data: bytes | None = None,
    timeout: int = 180,
) -> tuple[int, bytes]:
    request = urllib.request.Request(url, data=data, method=method)
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except urllib.error.URLError as exc:
        raise PublishError(f"请求失败：{url}（{exc.reason}）") from exc


def _json_dict(raw: bytes, *, what: str) -> dict:
    try:
        payload = json.loads(raw.decode("utf-8") or "{}")
    except json.JSONDecodeError as exc:
        raise PublishError(f"{what} 返回的不是 JSON：{exc}") from exc
    if not isinstance(payload, dict):
        raise PublishError(f"{what} 返回的不是 JSON 对象")
    return payload


def _github_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "WW-Desktop-Release",
    }


def publish_github(*, repo: str, version: str, asset_path: Path, notes: str) -> str:
    """建/取 GitHub Release，删同名旧资产后上传当前 zip，返回 release 页面地址。"""
    token, source = resolve_token("github")
    if not token:
        raise PublishError(
            "缺少 GitHub 令牌：先运行 --set-github-token 保存一次，或临时 export GITHUB_TOKEN / GH_TOKEN"
        )
    print(f"  使用 GitHub 令牌（{source}）")
    tag = f"{TAG_PREFIX}{version}"
    headers = _github_headers(token)
    api = f"https://api.github.com/repos/{repo}"
    page = f"https://github.com/{repo}/releases/tag/{tag}"

    status, body = _http(f"{api}/releases/tags/{tag}", headers=headers)
    if status == 200:
        release = _json_dict(body, what="GitHub Release")
    elif status == 404:
        payload = json.dumps(
            {
                "tag_name": tag,
                "name": f"桌面 v{version}",
                "body": notes,
                "target_commitish": BRANCH,
                "draft": False,
                "prerelease": False,
            }
        ).encode("utf-8")
        status, body = _http(
            f"{api}/releases",
            method="POST",
            headers={**headers, "Content-Type": "application/json"},
            data=payload,
        )
        if status not in (200, 201):
            hint = GITHUB_PERMISSION_HINT if status in (401, 403) else ""
            raise PublishError(
                f"创建 GitHub Release 失败（HTTP {status}）：{body.decode('utf-8', 'replace')[:300]}\n{hint}"
            )
        release = _json_dict(body, what="GitHub Release")
    else:
        hint = GITHUB_PERMISSION_HINT if status in (401, 403) else ""
        raise PublishError(
            f"查询 GitHub Release 失败（HTTP {status}）：{body.decode('utf-8', 'replace')[:300]}\n{hint}"
        )

    release_id = int(release.get("id") or 0)
    if not release_id:
        raise PublishError("GitHub Release 响应里没有 id")

    # 同名资产先删（重复发同一版本时 GitHub 不覆盖，会变成重复文件）
    status, body = _http(f"{api}/releases/{release_id}/assets", headers=headers)
    if status == 200:
        try:
            assets = json.loads(body.decode("utf-8") or "[]")
        except json.JSONDecodeError:
            assets = []
        for asset in assets if isinstance(assets, list) else []:
            if isinstance(asset, dict) and asset.get("name") == asset_path.name:
                _http(f"{api}/releases/assets/{asset.get('id')}", method="DELETE", headers=headers)

    upload_url = (
        f"https://uploads.github.com/repos/{repo}/releases/{release_id}/assets"
        f"?name={urllib.parse.quote(asset_path.name)}"
    )
    status, body = _http(
        upload_url,
        method="POST",
        headers={**headers, "Content-Type": "application/zip"},
        data=asset_path.read_bytes(),
    )
    if status not in (200, 201):
        hint = GITHUB_PERMISSION_HINT if status in (401, 403) else ""
        raise PublishError(f"上传 GitHub 资产失败（HTTP {status}）：{body.decode('utf-8', 'replace')[:300]}\n{hint}")
    return str(release.get("html_url") or page)


def _multipart(fields: dict[str, str], file_field: str, file_path: Path) -> tuple[bytes, str]:
    """拼一个最小 multipart/form-data 请求体（Gitee 附件上传用）。"""
    boundary = f"----WWRelease{os.urandom(8).hex()}"
    chunks: list[bytes] = []
    for key, value in fields.items():
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"))
        chunks.append(f"{value}\r\n".encode("utf-8"))
    chunks.append(f"--{boundary}\r\n".encode("utf-8"))
    chunks.append(
        f'Content-Disposition: form-data; name="{file_field}"; filename="{file_path.name}"\r\n'.encode("utf-8")
    )
    chunks.append(b"Content-Type: application/zip\r\n\r\n")
    chunks.append(file_path.read_bytes())
    chunks.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def publish_gitee(*, repo: str, version: str, asset_path: Path, notes: str) -> str:
    """建/取 Gitee 发行版并上传附件，返回发行版页面地址。"""
    token, source = resolve_token("gitee")
    if not token:
        raise PublishError("缺少 Gitee 令牌：先运行 --set-gitee-token 保存一次，或临时 export GITEE_TOKEN")
    print(f"  使用 Gitee 令牌（{source}）")
    tag = f"{TAG_PREFIX}{version}"
    api = f"https://gitee.com/api/v5/repos/{repo}"
    page = f"https://gitee.com/{repo}/releases/tag/{tag}"
    form = urllib.parse.urlencode(
        {
            "access_token": token,
            "tag_name": tag,
            "name": f"桌面 v{version}",
            "body": notes,
            "target_commitish": BRANCH,
        }
    ).encode("utf-8")

    status, body = _http(
        f"{api}/releases",
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data=form,
    )
    if status in (200, 201):
        release = _json_dict(body, what="Gitee Release")
    else:
        # 已存在同名 tag/发行版时 Gitee 返回 400，回查一次
        status, body = _http(f"{api}/releases/tags/{tag}?access_token={urllib.parse.quote(token)}")
        if status != 200:
            raise PublishError(f"创建 Gitee 发行版失败（HTTP {status}）：{body.decode('utf-8', 'replace')[:300]}")
        release = _json_dict(body, what="Gitee Release")

    release_id = int(release.get("id") or 0)
    if not release_id:
        raise PublishError("Gitee 发行版响应里没有 id")

    data, content_type = _multipart({"access_token": token}, "file", asset_path)
    status, body = _http(
        f"{api}/releases/{release_id}/attach_files",
        method="POST",
        headers={"Content-Type": content_type},
        data=data,
    )
    if status not in (200, 201):
        raise PublishError(f"上传 Gitee 附件失败（HTTP {status}）：{body.decode('utf-8', 'replace')[:300]}")
    return str(release.get("html_url") or page)


PUBLISHERS = {"github": publish_github, "gitee": publish_gitee}


# ---------- 入口 ----------


def _publish_hosts(value: str) -> list[str]:
    if value == "none":
        return []
    if value == "all":
        return ["github", "gitee"]
    return [value]


def plan_lines(args: argparse.Namespace, platform_key: str, planned_version: str) -> list[str]:
    """--dry-run 时列出将执行的步骤。"""
    lines = []
    if args.bump or args.set_version:
        lines.append(f"改写三处版本号 → {planned_version}")
    if args.build:
        lines.append("构建前端：pnpm --dir front build")
        lines.append("打包应用：python build/build.py")
    if not args.asset:
        lines.append(f"打 zip：dist/releases/{APP_NAME}-{planned_version}-{platform_key}.zip")
    lines.append("更新清单：releases/latest.json")
    if args.git:
        lines.append(f"git 提交 + 打 tag：{TAG_PREFIX}{planned_version}")
    for host in _publish_hosts(args.publish):
        token, source = resolve_token(host)
        lines.append(f"上传 {host} Release（令牌：{source if token else '未配置，先 --set-' + host + '-token'}）")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="发布主应用（构建 + 打包 + 更新清单 + 上传 Release）")
    parser.add_argument("--check-only", action="store_true", help="只校验版本号与清单自洽，不出包")
    parser.add_argument("--bump", choices=("major", "minor", "patch"), help="递增三处版本号后再打包")
    parser.add_argument("--set-version", help="把三处版本号直接改成该值")
    parser.add_argument("--build", action="store_true", help="打包前跑「前端构建 + PyInstaller 打包」")
    parser.add_argument("--asset", type=Path, help="已有 zip 产物路径，跳过重新打包")
    parser.add_argument("--notes", default="", help="更新说明，写进清单与 Release 正文")
    parser.add_argument("--reset", action="store_true", help="丢弃清单里其他平台的旧条目")
    parser.add_argument("--platform", help="平台键，默认按当前系统识别（macos-arm64 等）")
    parser.add_argument("--git", action="store_true", help="提交版本文件与清单，并打本地 tag（不推送）")
    parser.add_argument(
        "--publish",
        choices=("none", "github", "gitee", "all"),
        default="none",
        help="上传到哪个 Release（默认不上传）",
    )
    parser.add_argument("--dry-run", action="store_true", help="只打印将要执行的步骤，不写文件、不跑构建、不上传")
    parser.add_argument("--github-repo", default=GITHUB_REPO, help=f"GitHub 仓库，默认 {GITHUB_REPO}")
    parser.add_argument("--gitee-repo", default=GITEE_REPO, help=f"Gitee 仓库，默认 {GITEE_REPO}")
    parser.add_argument(
        "--set-github-token",
        nargs="?",
        const="",
        default=None,
        metavar="TOKEN",
        help="保存 GitHub 令牌到本地（不带值则交互输入，不回显）",
    )
    parser.add_argument(
        "--set-gitee-token",
        nargs="?",
        const="",
        default=None,
        metavar="TOKEN",
        help="保存 Gitee 令牌到本地（不带值则交互输入，不回显）",
    )
    parser.add_argument("--token-status", action="store_true", help="查看已配置的令牌（只显示首尾几位）")
    parser.add_argument("--clear-tokens", action="store_true", help="删除本地保存的令牌")
    args = parser.parse_args(argv)

    if args.bump and args.set_version:
        _fail("--bump 与 --set-version 只能二选一")

    # 令牌管理是独立动作，做完直接退出（不打包、不上传）
    token_actions = (("github", args.set_github_token), ("gitee", args.set_gitee_token))
    handled_token = False
    for host, value in token_actions:
        if value is None:
            continue
        if value:
            raw = value
        else:
            try:
                raw = getpass.getpass(f"粘贴 {HOST_LABELS[host]} 令牌（不回显）: ")
            except (EOFError, KeyboardInterrupt):
                _fail("没有读到令牌，已取消")
        path = save_token(host, raw)
        print(f"✓ 已保存 {HOST_LABELS[host]} 令牌到 {path}（权限 600，不随仓库提交）")
        handled_token = True
    if handled_token:
        return 0
    if args.token_status:
        print_token_status()
        return 0
    if args.clear_tokens:
        print(f"✓ 已删除令牌文件：{clear_tokens()}")
        return 0

    if args.check_only:
        if args.bump or args.set_version or args.build or args.git or args.publish != "none" or args.dry_run:
            _fail("--check-only 只做校验，不能与其他动作组合")
        version = check_versions()
        print(f"✓ 三处版本号一致：{version}")
        print(f"清单文件: {MANIFEST_PATH.relative_to(PROJECT_ROOT)}")
        if not MANIFEST_PATH.is_file():
            print("⚠ 清单文件还不存在，首次发版会创建")
            return 0
        check_manifest(version)
        print("✓ 清单校验通过")
        return 0

    platform_key = args.platform or _arch_key()

    if args.dry_run:
        current = check_versions()
        planned = bump_version(current, args.bump) if args.bump else (args.set_version or current)
        print("▶ --dry-run，将要执行：")
        for line in plan_lines(args, platform_key, planned):
            print(f"  - {line}")
        return 0

    if args.bump:
        rewrite_versions(bump_version(check_versions(), args.bump))
    elif args.set_version:
        rewrite_versions(args.set_version)

    version = check_versions()
    print(f"✓ 三处版本号一致：{version}")

    if args.build:
        run_frontend_build()
        run_pyinstaller_build()

    if args.asset:
        asset_path = args.asset.resolve()
        if not asset_path.is_file():
            _fail(f"指定的产物不存在：{asset_path}")
        out_path = asset_path
    else:
        bundle, _is_macos = find_bundle()
        out_path = DIST_DIR / "releases" / f"{APP_NAME}-{version}-{platform_key}.zip"
        print(f"▶ 打包 {bundle.name} → {out_path.relative_to(PROJECT_ROOT)}")
        zip_bundle(bundle, out_path)
        asset_path = out_path

    notes = args.notes or default_notes(version)
    manifest = build_manifest(
        version=version,
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

    if args.git:
        commit_and_tag(version)

    published: list[tuple[str, str]] = []
    for host in _publish_hosts(args.publish):
        print(f"▶ 上传 {host} Release：{asset_path.name}")
        try:
            url = PUBLISHERS[host](
                repo=args.github_repo if host == "github" else args.gitee_repo,
                version=version,
                asset_path=asset_path,
                notes=notes,
            )
        except PublishError as exc:
            _fail(str(exc))
        published.append((host, url))
        print(f"✓ {host}：{url}")

    tag = f"{TAG_PREFIX}{version}"
    print("\n下一步：")
    if args.git:
        print(f"  1. 推送 main 与 tag：git push origin {BRANCH} && git push origin {tag}")
    else:
        print(f"  1. 提交版本与清单并打 tag：git add -u && git commit -m 'chore(release): 桌面 v{version}'")
        print(f"     git tag -a {tag} -m 'chore(release): 桌面 v{version}'")
    if args.publish == "none":
        print(f"  2. 上传 {asset_path.name} 到 GitHub Release（tag {tag}），并同步一份到 Gitee Release")
        print(
            "     可改用 --publish github|gitee|all 自动上传（令牌用 --set-github-token / --set-gitee-token 保存一次即可）"
        )
    else:
        pending = [host for host in ("github", "gitee") if host not in {item[0] for item in published}]
        if pending:
            print(f"  2. 还没上传：{', '.join(pending)}（补跑 --publish {pending[0]}）")
        else:
            print("  2. GitHub / Gitee 均已上传")
    print(f"  3. 清单 url 指向 GitHub Release、mirrors 指向 Gitee 同 tag，推送 main 后宿主即可检查到 v{version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
