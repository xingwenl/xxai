import asyncio
from types import SimpleNamespace

import pytest

from app.modules.skill_runner.schemas import ScriptExecuteResponse
from app.modules.skill_runner.services import execute_skill_script
from app.modules.skill_runner.tools import SkillScriptTool
from app.shared.exceptions import NotFoundException


class FakeRepo:
    def __init__(self, allowed=True) -> None:
        self.allowed = allowed
        self.completed = None
        self.failed = None

    async def get_allowed_script(self, **kwargs):
        if not self.allowed:
            return None
        return SimpleNamespace(id=7, storage_key="skill-packages/1/pkg"), object()

    async def create_script_execution(self, **values):
        assert values["arguments"] == ["[REDACTED]"]
        return SimpleNamespace(id=11)

    async def complete_script_execution(self, execution, result):
        self.completed = (execution, result)

    async def fail_script_execution(self, execution, error):
        self.failed = (execution, error)


class FakeClient:
    async def execute(self, payload):
        assert payload.storage_key == "skill-packages/1/pkg"
        return ScriptExecuteResponse(
            status="succeeded",
            exit_code=0,
            stdout="ok",
            duration_ms=12,
        )


def _tool() -> SkillScriptTool:
    return SkillScriptTool(
        name="run_skill_script_7",
        description="run",
        input_schema={"type": "object"},
        package_id=7,
        skill_id=9,
    )


def test_execute_skill_script_rechecks_permission_and_audits() -> None:
    repo = FakeRepo()

    outcome = asyncio.run(
        execute_skill_script(
            repo,
            FakeClient(),
            tool=_tool(),
            call={
                "args": {
                    "script_path": "scripts/run.py",
                    "arguments": ["secret"],
                }
            },
            platform_id=1,
            agent_id=2,
            user_id=3,
        )
    )

    assert outcome.status == "completed"
    assert outcome.result["execution_id"] == 11
    assert repo.completed is not None


def test_execute_skill_script_rejects_revoked_permission() -> None:
    with pytest.raises(NotFoundException, match="skill script is not allowed"):
        asyncio.run(
            execute_skill_script(
                FakeRepo(allowed=False),
                FakeClient(),
                tool=_tool(),
                call={"args": {"script_path": "scripts/run.py"}},
                platform_id=1,
                agent_id=2,
            )
        )
