from jinja2 import StrictUndefined, UndefinedError
from jinja2.sandbox import SandboxedEnvironment

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
