from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class BuiltinToolCatalogRead(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]
    side_effect: Literal["none"] = "none"


class AgentBuiltinToolRead(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]
    side_effect: Literal["none"] = "none"
    is_enabled: bool


class AgentBuiltinToolUpdate(BaseModel):
    is_enabled: bool


class BuiltinToolOutcome(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    status: Literal["completed", "failed"]
    result: Any
