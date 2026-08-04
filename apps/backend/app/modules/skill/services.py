from jinja2 import StrictUndefined, UndefinedError
from jinja2.sandbox import SandboxedEnvironment
from pathlib import Path
import shutil

from app.core.config import get_settings
from app.modules.skill.importers import (
    ParsedSkillPackage,
    parse_skill_package,
    store_skill_package_files,
)
from app.shared.exceptions import (
    BadRequestException,
    ConflictException,
    NotFoundException,
)

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
):
    parsed = parse_skill_package(filename, content)
    package_slug = await _unique_package_slug(repo, platform_id, parsed.slug)
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
                "name": parsed.name,
                "slug": package_slug,
                "package_type": parsed.package_type,
                "source_filename": filename,
                "storage_path": str(storage_path),
                "storage_key": str(storage_path.relative_to(storage_root)),
                "manifest": _manifest_with_candidates(parsed),
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
