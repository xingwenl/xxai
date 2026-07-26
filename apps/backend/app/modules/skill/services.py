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
