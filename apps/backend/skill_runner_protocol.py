from typing import Literal

from pydantic import BaseModel, Field


class ScriptExecuteRequest(BaseModel):
    execution_id: int = Field(ge=1)
    storage_key: str = Field(min_length=1, max_length=500)
    script_path: str = Field(min_length=1, max_length=500)
    arguments: list[str] = Field(default_factory=list, max_length=32)
    timeout_seconds: int = Field(default=30, ge=1, le=120)
    max_output_bytes: int = Field(default=64 * 1024, ge=1024, le=1024 * 1024)


class ScriptExecuteResponse(BaseModel):
    status: Literal["succeeded", "failed"]
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = Field(ge=0)
    error: str | None = None
