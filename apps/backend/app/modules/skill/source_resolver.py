"""按 GitHub 源导入技能：来源解析、目录列举与技能包打包。

平台侧不执行 ``npx skills add``，也不执行 ``git``：后端镜像是
``python:3.12-slim``，没有 Node 与 git 二进制；而且 ``skills add`` 的产物落在
``./<agent>/skills/`` 这类本机目录，与平台的 ``SkillPackage`` + 受控存储模型
对不上。这里改为在服务端复刻「解析来源 → 取技能目录 → 交给既有导入链路」。

安全边界：用户只能提供仓库定位（``owner/repo[/subpath]``）与分支名，所有出网
请求都由本模块按固定模板拼到 ``api.github.com``，输入无法决定目标主机；
重定向也只在白名单主机之间跟随。因此本模块不存在由输入驱动的 SSRF 面。
"""

from __future__ import annotations

import base64
import json
import re
import time
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePosixPath
from urllib.parse import quote, urlsplit

import httpx

from app.core.config import get_settings
from app.modules.skill.importers import MAX_FILE_BYTES, SKILL_FILENAME_RE, slugify
from app.shared.exceptions import BadRequestException

GITHUB_API_BASE = "https://api.github.com"
# 允许出现为来源链接的主机，以及允许跟随重定向的目标主机。
GITHUB_LINK_HOSTS = {"github.com", "www.github.com"}
GITHUB_REQUEST_HOSTS = {"api.github.com", "objects.githubusercontent.com"}
# 不指定分支时交给 GitHub 自己解析默认分支，省掉一次查询
# default_branch 的请求（也避免踩到 master/main 命名的差异）。
DEFAULT_REF = "HEAD"
MAX_REDIRECTS = 2

# ``contents`` 接口在文件较大时不再内联返回内容，超过该阈值改走 ``git/blobs``。
INLINE_CONTENT_LIMIT = 1024 * 1024
# GitHub 目录树接口在响应过大时会返回 truncated，此时直接拒绝而不是猜。
MAX_TREE_ENTRIES = 60000

# 仓库 owner/仓库名/分支名的合法字符。这里刻意收得比 GitHub 实际规则更严：
# 任何可能被解释成 URL 路径分隔符或查询串的输入都不放行。
_OWNER_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
_REPO_RE = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
_REF_RE = re.compile(r"^[A-Za-z0-9._/-]{1,200}$")

_TREE_CACHE_TTL_SECONDS = 300
_TREE_CACHE_MAX_ENTRIES = 8
_tree_cache: dict[str, tuple[float, list[dict]]] = {}


@dataclass(frozen=True)
class ResolvedSource:
    owner: str
    repo: str
    ref: str
    subpath: str

    @property
    def repository(self) -> str:
        return f"{self.owner}/{self.repo}"


@dataclass(frozen=True)
class SourceSkillEntry:
    """仓库中被识别为一个技能的目录。"""

    name: str
    slug: str
    path: str
    skill_path: str
    file_count: int
    total_bytes: int
    has_scripts: bool


def parse_source(source: str) -> ResolvedSource:
    """把用户输入解析成受控的仓库定位信息。

    支持 ``owner/repo``、``owner/repo/<subpath>``、``https://github.com/owner/repo``
    与 ``https://github.com/owner/repo/tree/<ref>/<subpath>``，对标
    ``npx skills add`` 的 Source Formats（首期只支持 GitHub 公开仓库）。
    """
    raw = (source or "").strip()
    if not raw:
        raise BadRequestException("技能来源不能为空")
    if len(raw) > 500:
        raise BadRequestException("技能来源过长")
    if "://" in raw:
        return _parse_link_source(raw)
    segments = [segment for segment in raw.strip("/").split("/") if segment]
    if len(segments) < 2:
        raise BadRequestException("技能来源需形如 owner/repo，或 github.com 的仓库链接")
    return _build_source(segments[0], segments[1], None, "/".join(segments[2:]))


def _parse_link_source(raw: str) -> ResolvedSource:
    parsed = urlsplit(raw)
    if parsed.scheme != "https":
        raise BadRequestException("技能来源链接必须使用 https")
    host = (parsed.hostname or "").lower()
    if host not in GITHUB_LINK_HOSTS:
        raise BadRequestException(
            f"当前只支持 github.com 来源，收到 {host or '未知主机'}"
        )
    if parsed.username or parsed.password:
        raise BadRequestException("技能来源不能包含凭据")
    segments = [segment for segment in parsed.path.split("/") if segment]
    if len(segments) < 2:
        raise BadRequestException("技能来源链接需包含 owner/repo")
    owner, repo, rest = segments[0], segments[1], segments[2:]
    if not rest:
        return _build_source(owner, repo, None, "")
    if rest[0] not in {"tree", "blob"}:
        raise BadRequestException("技能来源链接只支持指向仓库或 tree/<分支>/<目录>")
    if len(rest) < 2:
        raise BadRequestException("技能来源链接缺少分支名")
    return _build_source(owner, repo, rest[1], "/".join(rest[2:]))


def _build_source(
    owner: str, repo: str, ref: str | None, subpath: str | None
) -> ResolvedSource:
    owner = (owner or "").strip()
    repo = (repo or "").strip()
    if repo.endswith(".git"):
        repo = repo[: -len(".git")]
    if not _OWNER_RE.match(owner):
        raise BadRequestException("仓库 owner 名称不合法")
    if not _REPO_RE.match(repo) or repo in {".", ".."}:
        raise BadRequestException("仓库名称不合法")
    resolved_ref = (ref or "").strip() or DEFAULT_REF
    if not _REF_RE.match(resolved_ref) or ".." in resolved_ref.split("/"):
        raise BadRequestException("分支名不合法")
    return ResolvedSource(
        owner=owner, repo=repo, ref=resolved_ref, subpath=_normalize_subpath(subpath)
    )


def _normalize_subpath(subpath: str | None) -> str:
    parts: list[str] = []
    for part in (subpath or "").strip().strip("/").split("/"):
        if part in {"", "."}:
            continue
        if part == "..":
            raise BadRequestException("技能来源目录包含非法路径")
        parts.append(part)
    return "/".join(parts)


async def list_source_skills(
    source: str,
) -> tuple[ResolvedSource, list[SourceSkillEntry]]:
    """列出仓库中可选的技能，只读且不落库。"""
    resolved = parse_source(source)
    tree = await _fetch_tree(resolved)
    return resolved, _collect_skill_entries(tree, resolved)


def select_skill_entries(
    entries: list[SourceSkillEntry], requested: list[str]
) -> list[SourceSkillEntry]:
    """按用户选择筛出技能目录，``'*'`` 表示全选。"""
    if any(item.strip() == "*" for item in requested):
        return list(entries)
    wanted = {item.strip().strip("/") for item in requested if item.strip()}
    matched: list[SourceSkillEntry] = []
    seen: set[str] = set()
    for entry in entries:
        if entry.path in wanted or entry.name in wanted or entry.slug in wanted:
            if entry.path not in seen:
                seen.add(entry.path)
                matched.append(entry)
    if not matched:
        available = "、".join(entry.name for entry in entries[:20]) or "（无）"
        raise BadRequestException(f"未找到指定技能，可选：{available}")
    missing = (
        wanted
        - {entry.path for entry in matched}
        - {entry.name for entry in matched}
        - {entry.slug for entry in matched}
    )
    if missing:
        raise BadRequestException(f"未找到指定技能：{'、'.join(sorted(missing))}")
    return matched


async def build_source_package_zip(
    resolved: ResolvedSource, entries: list[SourceSkillEntry]
) -> tuple[bytes, str]:
    """把选中的技能目录打成内存 zip，交给既有 ``parse_skill_package`` 校验。

    zip 内路径保留仓库相对路径，因此天然不会在选中多个技能时发生路径冲突，
    且 ``_parse_skill_candidate`` 的目录名兜底仍能取到技能目录名。
    """
    settings = get_settings()
    tree = await _fetch_tree(resolved)
    blobs = _blob_entries(tree)
    selected: list[dict] = []
    total_bytes = 0
    for entry in entries:
        prefix = f"{entry.path}/"
        for blob in blobs:
            if blob["path"].startswith(prefix):
                size = _blob_size(blob)
                if size > MAX_FILE_BYTES:
                    raise BadRequestException(f"技能包内文件过大：{blob['path']}")
                total_bytes += size
                selected.append(blob)
    if not selected:
        raise BadRequestException("选中的技能不包含任何文件")
    if len(selected) > settings.skill_source_max_files:
        raise BadRequestException(
            f"选中的文件数超过上限（{settings.skill_source_max_files}）"
        )
    if total_bytes > settings.skill_source_max_total_bytes:
        raise BadRequestException("选中的技能体积超过上限")

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for blob in selected:
            _ensure_safe_member_path(blob["path"])
            archive.writestr(blob["path"], await _fetch_blob_content(resolved, blob))
    content = buffer.getvalue()
    if not content:
        raise BadRequestException("生成的技能包为空")
    filename = f"{resolved.repo}-skills.zip"
    return content, filename


def _collect_skill_entries(
    tree: list[dict], resolved: ResolvedSource
) -> list[SourceSkillEntry]:
    prefix = f"{resolved.subpath}/" if resolved.subpath else ""
    blobs = [blob for blob in _blob_entries(tree) if blob["path"].startswith(prefix)]
    entries: list[SourceSkillEntry] = []
    for blob in blobs:
        path = blob["path"]
        if not SKILL_FILENAME_RE.match(PurePosixPath(path).name):
            continue
        directory = PurePosixPath(path).parent.as_posix()
        if directory == ".":
            directory = ""
        own_prefix = f"{directory}/" if directory else ""
        own = [item for item in blobs if item["path"].startswith(own_prefix)]
        name = (PurePosixPath(directory).name if directory else resolved.repo).strip()
        entries.append(
            SourceSkillEntry(
                name=name or resolved.repo,
                slug=slugify(name or resolved.repo),
                path=directory,
                skill_path=path,
                file_count=len(own),
                total_bytes=sum(_blob_size(item) for item in own),
                has_scripts=any(
                    "scripts" in PurePosixPath(item["path"]).parts for item in own
                ),
            )
        )
    return sorted(entries, key=lambda entry: entry.path)


def _blob_entries(tree: list[dict]) -> list[dict]:
    """挑出可读取的文件条目。

    git 符号链接在目录树里同样以 ``type=blob`` 出现（``mode=120000``），但内容
    接口对它只返回链接目标、没有文件正文，因此直接排除——避免把链接目标当成
    技能文件内容写进技能包。
    """
    return [
        entry
        for entry in tree
        if entry.get("type") == "blob"
        and isinstance(entry.get("path"), str)
        and not _is_symlink(entry)
    ]


def _is_symlink(blob: dict) -> bool:
    return str(blob.get("mode") or "") == "120000"


def _ensure_safe_member_path(path: str) -> None:
    """纵深防御：写入 zip 的成员路径不得越出包根。

    路径来自远端目录树返回值，正常情况下不会是绝对路径或含 ``..``，但一旦出现
    就必须立刻拒绝，而不是静默丢弃（静默丢弃会让技能包缺文件却看起来导入成功）。
    """
    if not path or path.startswith("/") or "\\" in path or "\x00" in path:
        raise BadRequestException(f"技能包内路径非法：{path}")
    if ".." in PurePosixPath(path).parts:
        raise BadRequestException(f"技能包内路径包含越级目录：{path}")


def _blob_size(blob: dict) -> int:
    try:
        return int(blob.get("size") or 0)
    except (TypeError, ValueError):
        return 0


async def _fetch_tree(resolved: ResolvedSource) -> list[dict]:
    cache_key = f"{resolved.repository}@{resolved.ref}"
    cached = _tree_cache.get(cache_key)
    if cached is not None and time.monotonic() - cached[0] < _TREE_CACHE_TTL_SECONDS:
        return cached[1]
    url = (
        f"{GITHUB_API_BASE}/repos/{resolved.owner}/{resolved.repo}"
        f"/git/trees/{quote(resolved.ref, safe='/')}?recursive=1"
    )
    payload = await _github_json(
        url,
        not_found_message=(f"仓库或分支不存在：{resolved.repository}@{resolved.ref}"),
    )
    tree = payload.get("tree")
    if not isinstance(tree, list):
        raise BadRequestException("GitHub 返回了无法识别的目录树")
    if payload.get("truncated") or len(tree) > MAX_TREE_ENTRIES:
        raise BadRequestException("仓库目录树过大，无法完整列出")
    _remember_tree(cache_key, tree)
    return tree


def _remember_tree(cache_key: str, tree: list[dict]) -> None:
    _tree_cache[cache_key] = (time.monotonic(), tree)
    if len(_tree_cache) > _TREE_CACHE_MAX_ENTRIES:
        oldest = min(_tree_cache, key=lambda key: _tree_cache[key][0])
        _tree_cache.pop(oldest, None)


async def _fetch_blob_content(resolved: ResolvedSource, blob: dict) -> bytes:
    path = blob["path"]
    if _blob_size(blob) > INLINE_CONTENT_LIMIT:
        # 大文件用 blobs 接口按 sha 取（contents 接口对这类文件不再内联内容）。
        sha = blob.get("sha")
        if not isinstance(sha, str) or not sha:
            raise BadRequestException(f"文件缺少内容标识：{path}")
        url = f"{GITHUB_API_BASE}/repos/{resolved.owner}/{resolved.repo}/git/blobs/{quote(sha)}"
        payload = await _github_json(url, not_found_message=f"文件不存在：{path}")
        encoded = payload.get("content")
        if not isinstance(encoded, str):
            raise BadRequestException(f"无法读取文件内容：{path}")
        try:
            return base64.b64decode(encoded)
        except (ValueError, TypeError) as exc:
            raise BadRequestException(f"文件内容解码失败：{path}") from exc
    url = (
        f"{GITHUB_API_BASE}/repos/{resolved.owner}/{resolved.repo}"
        f"/contents/{quote(path, safe='/')}"
    )
    return await _github_bytes(url, not_found_message=f"文件不存在：{path}")


def _github_headers(accept: str) -> dict[str, str]:
    headers = {
        "Accept": accept,
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "ai-base-skill-source-import",
    }
    token = get_settings().github_token
    if token:
        # Token 只提升 REST 限流额度（匿名 60 次/小时 → 5000 次/小时），不改变带宽。
        headers["Authorization"] = f"Bearer {token}"
    return headers


async def _github_request(url: str, accept: str) -> httpx.Response:
    host = (urlsplit(url).hostname or "").lower()
    if host not in GITHUB_REQUEST_HOSTS:
        raise BadRequestException("技能来源只允许访问 GitHub 接口")
    settings = get_settings()
    try:
        async with httpx.AsyncClient(
            timeout=settings.skill_source_http_timeout_seconds
        ) as client:
            for _ in range(MAX_REDIRECTS + 1):
                response = await client.get(
                    url, headers=_github_headers(accept), follow_redirects=False
                )
                if not response.is_redirect:
                    return response
                location = response.headers.get("location", "")
                next_url = str(httpx.URL(url).join(location))
                next_host = (urlsplit(next_url).hostname or "").lower()
                if next_host not in GITHUB_REQUEST_HOSTS:
                    raise BadRequestException("GitHub 返回了指向非白名单主机的跳转")
                url = next_url
    except httpx.HTTPError as exc:
        raise BadRequestException("访问 GitHub 失败，请检查网络后重试") from exc
    raise BadRequestException("GitHub 重定向次数过多")


def _raise_for_status(response: httpx.Response, *, not_found_message: str) -> None:
    if response.status_code == 404:
        raise BadRequestException(not_found_message)
    if response.status_code in {401, 403, 429}:
        raise _access_exception(response)
    if response.status_code >= 400:
        raise BadRequestException(f"GitHub 接口返回 {response.status_code}")


def _access_exception(response: httpx.Response) -> BadRequestException:
    if response.headers.get("x-ratelimit-remaining") == "0":
        return BadRequestException(
            "GitHub 调用额度已用尽（匿名每小时 60 次），请稍后重试或配置 GITHUB_TOKEN"
        )
    return BadRequestException("GitHub 拒绝了本次请求，请检查仓库是否为公开仓库")


async def _github_json(url: str, *, not_found_message: str) -> dict:
    response = await _github_request(url, "application/vnd.github+json")
    _raise_for_status(response, not_found_message=not_found_message)
    try:
        payload = response.json()
    except json.JSONDecodeError as exc:
        raise BadRequestException("GitHub 返回的内容无法解析") from exc
    if not isinstance(payload, dict):
        raise BadRequestException("GitHub 返回了无法识别的数据结构")
    return payload


async def _github_bytes(url: str, *, not_found_message: str) -> bytes:
    response = await _github_request(url, "application/vnd.github.raw")
    _raise_for_status(response, not_found_message=not_found_message)
    return response.content
