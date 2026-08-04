from app.core.config import get_settings
from app.modules.skill_runner.client import SkillRunnerClient
from app.modules.skill_runner.schemas import (
    ScriptExecuteRequest,
    SkillScriptToolOutcome,
)
from app.shared.exceptions import BadRequestException, NotFoundException


def _validate_arguments(arguments) -> list[str]:
    if arguments is None:
        return []
    if not isinstance(arguments, list) or len(arguments) > 32:
        raise BadRequestException("script arguments are invalid")
    if any(not isinstance(value, str) or len(value) > 1000 for value in arguments):
        raise BadRequestException("script arguments are invalid")
    if sum(len(value) for value in arguments) > 8000:
        raise BadRequestException("script arguments are too large")
    return arguments


async def execute_skill_script(
    repo,
    client: SkillRunnerClient,
    *,
    tool,
    call: dict,
    platform_id: int,
    agent_id: int,
    user_id: int | None = None,
    platform_end_user_id: int | None = None,
    conversation_id: int | None = None,
    request_id: str | None = None,
) -> SkillScriptToolOutcome:
    call_arguments = call.get("args", {})
    script_path = call_arguments.get("script_path")
    if not isinstance(script_path, str):
        raise BadRequestException("script path is required")
    arguments = _validate_arguments(call_arguments.get("arguments"))
    allowed = await repo.get_allowed_script(
        platform_id=platform_id,
        agent_id=agent_id,
        package_id=tool.package_id,
        skill_id=tool.skill_id,
        script_path=script_path,
    )
    if allowed is None:
        raise NotFoundException("skill script is not allowed")
    package, _file = allowed
    execution = await repo.create_script_execution(
        platform_id=platform_id,
        package_id=package.id,
        skill_id=tool.skill_id,
        agent_id=agent_id,
        user_id=user_id,
        platform_end_user_id=platform_end_user_id,
        conversation_id=conversation_id,
        request_id=request_id,
        script_path=script_path,
        arguments=["[REDACTED]" for _ in arguments],
    )
    settings = get_settings()
    try:
        result = await client.execute(
            ScriptExecuteRequest(
                execution_id=execution.id,
                storage_key=package.storage_key,
                script_path=script_path,
                arguments=arguments,
                timeout_seconds=settings.skill_runner_timeout_seconds,
                max_output_bytes=settings.skill_runner_max_output_bytes,
            )
        )
    except Exception as exc:
        await repo.fail_script_execution(execution, str(exc))
        return SkillScriptToolOutcome(
            status="failed",
            result={"execution_id": execution.id, "error": "skill runner failed"},
        )
    await repo.complete_script_execution(execution, result)
    return SkillScriptToolOutcome(
        status="completed" if result.status == "succeeded" else "failed",
        result={"execution_id": execution.id, **result.model_dump()},
    )
