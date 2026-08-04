from typing import Literal

from pydantic import BaseModel

from skill_runner_protocol import ScriptExecuteRequest, ScriptExecuteResponse

__all__ = ["ScriptExecuteRequest", "ScriptExecuteResponse", "SkillScriptToolOutcome"]


class SkillScriptToolOutcome(BaseModel):
    status: Literal["completed", "failed"]
    result: dict
