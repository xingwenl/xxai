from __future__ import annotations

import json
import mimetypes
import re
import shutil
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4

import yaml

from app.shared.exceptions import BadRequestException

MAX_ZIP_BYTES = 25 * 1024 * 1024
MAX_ENTRY_COUNT = 300
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_TOTAL_UNCOMPRESSED_BYTES = 80 * 1024 * 1024
MAX_SKILL_MD_BYTES = 256 * 1024

SKILL_FILENAME_RE = re.compile(r"^skill\.md$", re.IGNORECASE)
SLUG_RE = re.compile(r"[^a-z0-9_-]+")


@dataclass(frozen=True)
class ParsedSkillCandidate:
    name: str
    slug: str
    description: str | None
    instruction_template: str
    skill_path: str


@dataclass(frozen=True)
class ParsedPackageFile:
    relative_path: str
    role: str
    size_bytes: int
    media_type: str | None


@dataclass(frozen=True)
class ParsedSkillPackage:
    name: str
    slug: str
    package_type: str
    manifest: dict
    warnings: list[str]
    files: list[ParsedPackageFile]
    candidates: list[ParsedSkillCandidate]


def parse_skill_package(filename: str, content: bytes) -> ParsedSkillPackage:
    if not filename.lower().endswith(".zip"):
        raise BadRequestException("skill package must be a zip file")
    if len(content) > MAX_ZIP_BYTES:
        raise BadRequestException("skill package is too large")

    try:
        archive = zipfile.ZipFile(BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise BadRequestException("invalid skill package zip") from exc

    with archive:
        infos = [info for info in archive.infolist() if not info.is_dir()]
        if len(infos) > MAX_ENTRY_COUNT:
            raise BadRequestException("skill package has too many files")
        if not infos:
            raise BadRequestException("skill package is empty")

        total_size = 0
        normalized_infos: list[tuple[zipfile.ZipInfo, str]] = []
        for info in infos:
            relative_path = _normalize_zip_path(info.filename)
            if info.file_size > MAX_FILE_BYTES:
                raise BadRequestException("skill package contains an oversized file")
            total_size += info.file_size
            if total_size > MAX_TOTAL_UNCOMPRESSED_BYTES:
                raise BadRequestException("skill package uncompressed size is too large")
            normalized_infos.append((info, relative_path))

        path_to_info = {path: info for info, path in normalized_infos}
        if len(path_to_info) != len(normalized_infos):
            raise BadRequestException("skill package contains duplicate paths")
        manifest = _read_plugin_manifest(archive, path_to_info)
        skill_paths = [
            path
            for path in path_to_info
            if SKILL_FILENAME_RE.match(PurePosixPath(path).name)
        ]
        if not skill_paths:
            raise BadRequestException("skill package does not contain SKILL.md")

        package_type = "codex_plugin" if manifest else "skill"
        candidates = [
            _parse_skill_candidate(archive, path_to_info[skill_path], skill_path)
            for skill_path in sorted(skill_paths)
        ]
        files = [
            ParsedPackageFile(
                relative_path=path,
                role=_classify_file(path),
                size_bytes=info.file_size,
                media_type=mimetypes.guess_type(path)[0],
            )
            for info, path in sorted(normalized_infos, key=lambda item: item[1])
        ]
        package_name = _package_name(filename, manifest, candidates)
        return ParsedSkillPackage(
            name=package_name,
            slug=slugify(package_name or Path(filename).stem),
            package_type=package_type,
            manifest=manifest,
            warnings=_build_warnings(files),
            files=files,
            candidates=candidates,
        )


def store_skill_package_files(
    storage_root: Path, platform_id: int, content: bytes
) -> Path:
    package_dir = storage_root / "skill-packages" / str(platform_id) / uuid4().hex
    package_dir.mkdir(parents=True, exist_ok=False)
    try:
        with zipfile.ZipFile(BytesIO(content)) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                relative_path = _normalize_zip_path(info.filename)
                target = package_dir / relative_path
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, target.open("wb") as destination:
                    shutil.copyfileobj(source, destination)
    except Exception:
        shutil.rmtree(package_dir, ignore_errors=True)
        raise
    return package_dir


def slugify(value: str) -> str:
    slug = SLUG_RE.sub("-", value.strip().lower()).strip("-_")
    slug = re.sub(r"-{2,}", "-", slug)
    if not slug or not re.match(r"^[a-z0-9]", slug):
        slug = f"skill-{slug}" if slug else "skill"
    return slug[:80].rstrip("-_") or "skill"


def _normalize_zip_path(raw_path: str) -> str:
    normalized = raw_path.replace("\\", "/").strip()
    path = PurePosixPath(normalized)
    if (
        not normalized
        or normalized.endswith("/")
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise BadRequestException("skill package contains an unsafe path")
    return path.as_posix()


def _read_plugin_manifest(
    archive: zipfile.ZipFile, path_to_info: dict[str, zipfile.ZipInfo]
) -> dict:
    for path, info in path_to_info.items():
        if path == ".codex-plugin/plugin.json" or path.endswith(
            "/.codex-plugin/plugin.json"
        ):
            try:
                return json.loads(archive.read(info).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise BadRequestException("invalid plugin manifest") from exc
    return {}


def _parse_skill_candidate(
    archive: zipfile.ZipFile, info: zipfile.ZipInfo, skill_path: str
) -> ParsedSkillCandidate:
    if info.file_size > MAX_SKILL_MD_BYTES:
        raise BadRequestException("SKILL.md is too large")
    try:
        text = archive.read(info).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BadRequestException("SKILL.md must be utf-8 text") from exc
    frontmatter, body = _split_frontmatter(text)
    fallback_name = PurePosixPath(skill_path).parent.name or Path(skill_path).stem
    name = str(frontmatter.get("name") or fallback_name).strip()
    description = frontmatter.get("description")
    return ParsedSkillCandidate(
        name=name[:120] or "Imported Skill",
        slug=slugify(str(frontmatter.get("name") or fallback_name)),
        description=str(description).strip()[:500] if description else None,
        instruction_template=body.strip() or text.strip(),
        skill_path=skill_path,
    )


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    match = re.match(
        r"^---[ \t]*\r?\n(?P<frontmatter>.*?)\r?\n---[ \t]*(?:\r?\n|$)",
        text,
        flags=re.DOTALL,
    )
    if match is None:
        return {}, text
    try:
        data = yaml.safe_load(match.group("frontmatter")) or {}
    except yaml.YAMLError as exc:
        raise BadRequestException("SKILL.md frontmatter must be valid YAML") from exc
    if not isinstance(data, dict):
        raise BadRequestException("SKILL.md frontmatter must be a YAML object")
    return data, text[match.end() :]


def _classify_file(path: str) -> str:
    parts = PurePosixPath(path).parts
    name = PurePosixPath(path).name
    if SKILL_FILENAME_RE.match(name):
        return "skill"
    if ".codex-plugin" in parts:
        return "manifest"
    if "scripts" in parts:
        return "script"
    if "references" in parts:
        return "reference"
    if "assets" in parts:
        return "asset"
    return "other"


def _package_name(
    filename: str, manifest: dict, candidates: list[ParsedSkillCandidate]
) -> str:
    if manifest:
        manifest_name = manifest.get("name") or manifest.get("displayName")
        if manifest_name:
            return str(manifest_name)[:120]
    if len(candidates) == 1:
        return candidates[0].name
    return Path(filename).stem[:120] or "Imported Skill Package"


def _build_warnings(files: list[ParsedPackageFile]) -> list[str]:
    warnings: list[str] = []
    if any(file.role == "script" for file in files):
        warnings.append("检测到 scripts 目录，脚本执行权限默认关闭")
    if any(file.role in {"asset", "reference"} for file in files):
        warnings.append("检测到资源或参考文件，已保留在受控存储目录")
    return warnings
