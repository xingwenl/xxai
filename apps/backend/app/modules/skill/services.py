from jinja2 import StrictUndefined, UndefinedError
from jinja2.sandbox import SandboxedEnvironment
from pathlib import Path
import shutil

from app.core.config import get_settings
from app.modules.skill.importers import (
    ParsedSkillPackage,
    parse_skill_package,
    slugify,
    store_skill_package_files,
)
from app.modules.skill.schemas import (
    SkillPackageDetail,
    SkillPackageImportResult,
    SkillSourceImportRequest,
    SkillSourcePreviewData,
    SkillSourceSkillItem,
)
from app.modules.skill.source_resolver import (
    build_source_package_zip,
    list_source_skills,
    select_skill_entries,
)
from app.shared.exceptions import (
    BadRequestException,
    ConflictException,
    NotFoundException,
)
from app.modules.skill_runner.schemas import SkillScriptToolOutcome

_environment = SandboxedEnvironment(undefined=StrictUndefined, autoescape=False)


def render_skill_instruction(template: str, parameters: dict) -> str:
    try:
        return _environment.from_string(template).render(**parameters)
    except UndefinedError as exc:
        raise BadRequestException("skill parameter is missing") from exc


async def create_skill(repo, platform_id: int, payload):
    if await repo.get_by_slug(platform_id, payload.slug) is not None:
        raise ConflictException("skill slug already exists")
    return await repo.create(platform_id, payload)


async def import_skill_package(
    repo,
    platform_id: int,
    *,
    filename: str,
    content: bytes,
    manifest_extra: dict | None = None,
    package_name: str | None = None,
):
    """解析并落库一个技能包 zip。

    ``package_name`` 为用户显式指定的技能包名称：留空时沿用 ``parse_skill_package``
    推导出的名称（manifest 名 > 单技能名 > zip 文件名）。显式指定时以用户输入为准，
    否则页面上填写的名称会被 SKILL.md 里的 name 悄悄覆盖。
    """
    parsed = parse_skill_package(filename, content)
    display_name = (package_name or "").strip()[:120] or parsed.name
    package_slug = await _unique_package_slug(
        repo, platform_id, slugify(display_name) or parsed.slug
    )
    skill_values = []
    for candidate in parsed.candidates:
        skill_values.append(
            {
                "name": candidate.name,
                "slug": await _unique_skill_slug(repo, platform_id, candidate.slug),
                "description": candidate.description,
                "instruction_template": candidate.instruction_template,
                "parameter_schema": {},
                "lifecycle_hooks": {},
                "package_skill_path": candidate.skill_path,
                "is_active": True,
            }
        )

    storage_path = store_skill_package_files(
        Path(get_settings().agent_file_storage_path),
        platform_id,
        content,
    )
    storage_root = Path(get_settings().agent_file_storage_path)
    try:
        return await repo.create_package_with_assets(
            platform_id,
            package_values={
                "name": display_name,
                "slug": package_slug,
                "package_type": parsed.package_type,
                "source_filename": filename,
                "storage_path": str(storage_path),
                "storage_key": str(storage_path.relative_to(storage_root)),
                "manifest": {
                    **_manifest_with_candidates(parsed),
                    **(manifest_extra or {}),
                },
                "warnings": parsed.warnings,
                "allow_script_execution": False,
                "is_active": True,
            },
            file_values=[
                {
                    "relative_path": file.relative_path,
                    "role": file.role,
                    "size_bytes": file.size_bytes,
                    "media_type": file.media_type,
                }
                for file in parsed.files
            ],
            skill_values=skill_values,
        )
    except Exception:
        shutil.rmtree(storage_path, ignore_errors=True)
        raise


async def preview_source_skills(source: str) -> SkillSourcePreviewData:
    """列出某个 GitHub 源中可选的技能，只读且不落库。"""
    _require_source_import_enabled()
    resolved, entries = await list_source_skills(source)
    return SkillSourcePreviewData(
        repository=resolved.repository,
        ref=resolved.ref,
        subpath=resolved.subpath,
        skills=[
            SkillSourceSkillItem(
                name=entry.name,
                slug=entry.slug,
                path=entry.path,
                skill_path=entry.skill_path,
                file_count=entry.file_count,
                total_bytes=entry.total_bytes,
                has_scripts=entry.has_scripts,
            )
            for entry in entries
        ],
    )


async def import_skill_package_from_source(
    repo, platform_id: int, payload: SkillSourceImportRequest
):
    """按 GitHub 源导入技能：拉取选中目录后复用既有 zip 导入链路落库。

    这里刻意不另写一份落库逻辑——打包成 zip 之后交给 ``import_skill_package``，
    校验、上限、role 分类、manifest 组装全部沿用既有实现。
    """
    _require_source_import_enabled()
    resolved, entries = await list_source_skills(payload.source)
    selected = select_skill_entries(entries, payload.skills)
    content, filename = await build_source_package_zip(resolved, selected)
    package = await import_skill_package(
        repo,
        platform_id,
        filename=filename,
        content=content,
        package_name=payload.package_name,
        manifest_extra={
            "source": {
                "type": "github",
                "repository": resolved.repository,
                "ref": resolved.ref,
                "path": resolved.subpath,
                "skills": [entry.path for entry in selected],
            }
        },
    )
    return SkillPackageImportResult(
        package=SkillPackageDetail.model_validate(package),
        warnings=package.warnings,
    )


def _require_source_import_enabled() -> None:
    if not get_settings().skill_source_import_enabled:
        raise BadRequestException("按 GitHub 源添加技能的功能已关闭")


async def update_skill_package(repo, platform_id: int, package_id: int, payload):
    package = await repo.get_package(package_id, platform_id)
    if package is None:
        raise NotFoundException("skill package not found")
    values = payload.model_dump(exclude_unset=True)
    return await repo.update_package(package, values)


def build_runtime_skill_instruction(skill) -> str:
    package = getattr(skill, "package", None)
    if package is None:
        return skill.instruction_template
    script_status = (
        "允许执行包内脚本"
        if package.allow_script_execution
        else "不允许执行包内脚本"
    )
    return (
        f"{skill.instruction_template}\n\n"
        f"[技能包上下文]\n"
        f"- 包名称：{package.name}\n"
        f"- 包内入口：{skill.package_skill_path or 'SKILL.md'}\n"
        f"- 脚本权限：{script_status}\n"
        f"- 包存储路径：{package.storage_path}"
    )


def build_runtime_skill_metadata(skill) -> str:
    """常驻上下文只保留可区分技能和触发按需加载的最小信息。"""
    name = getattr(skill, "name", None) or getattr(skill, "slug", None) or "未命名技能"
    slug = getattr(skill, "slug", None) or name
    return (
        f"- 技能名称：{name}\n"
        f"- 技能 slug：{slug}\n"
        f"- 技能描述：{getattr(skill, 'description', None) or '未提供描述'}\n"
        "需要使用某个技能时，先调用 load_skill 获取完整指令。"
    )


async def load_bound_skill_instruction(repo, platform_id: int, agent_id: int, slug: str):
    if not isinstance(slug, str) or not slug.strip():
        return SkillScriptToolOutcome(status="failed", result={"error": "技能 slug 无效"})
    skill = await repo.get_enabled_skill_for_agent(agent_id, platform_id, slug.strip())
    if skill is None:
        return SkillScriptToolOutcome(status="failed", result={"error": "技能未绑定或不可用"})
    return SkillScriptToolOutcome(
        status="completed",
        result={
            "slug": skill.slug,
            "name": skill.name,
            "instruction": build_runtime_skill_instruction(skill),
        },
    )


async def bind_skill(repo, platform_id: int, agent_id: int, payload):
    binding = await repo.bind(platform_id, agent_id, payload)
    if binding is None:
        raise NotFoundException("agent or skill not found")
    return binding


async def update_skill(repo, platform_id: int, skill_id: int, payload):
    skill = await repo.get_skill(skill_id, platform_id)
    if skill is None:
        raise NotFoundException("skill not found")
    return await repo.update_skill(skill, payload)


async def delete_skill(repo, platform_id: int, skill_id: int) -> None:
    skill = await repo.get_skill(skill_id, platform_id)
    if skill is None:
        raise NotFoundException("skill not found")
    await repo.delete_skill(skill)


async def unbind_skill(repo, platform_id: int, agent_id: int, skill_id: int) -> None:
    if not await repo.unbind(platform_id, agent_id, skill_id):
        raise NotFoundException("agent skill binding not found")


async def _unique_skill_slug(repo, platform_id: int, base_slug: str) -> str:
    return await _unique_slug(base_slug, lambda slug: repo.get_by_slug(platform_id, slug))


async def _unique_package_slug(repo, platform_id: int, base_slug: str) -> str:
    return await _unique_slug(
        base_slug, lambda slug: repo.get_package_by_slug(platform_id, slug)
    )


async def _unique_slug(base_slug: str, exists_fn) -> str:
    candidate = base_slug[:80].rstrip("-_") or "skill"
    if await exists_fn(candidate) is None:
        return candidate
    suffix = 2
    while suffix < 1000:
        suffix_text = f"-{suffix}"
        candidate = f"{base_slug[: 80 - len(suffix_text)].rstrip('-_')}{suffix_text}"
        if await exists_fn(candidate) is None:
            return candidate
        suffix += 1
    raise ConflictException("skill slug already exists")


def _manifest_with_candidates(parsed: ParsedSkillPackage) -> dict:
    return {
        **parsed.manifest,
        "_parsed": {
            "package_type": parsed.package_type,
            "candidates": [
                {
                    "name": candidate.name,
                    "slug": candidate.slug,
                    "description": candidate.description,
                    "skill_path": candidate.skill_path,
                }
                for candidate in parsed.candidates
            ],
        },
    }
