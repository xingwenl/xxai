from dataclasses import dataclass


SUPPORTED_SCRIPT_SUFFIXES = {".py", ".js", ".mjs", ".sh"}


@dataclass(frozen=True)
class SkillScriptTool:
    name: str
    description: str
    input_schema: dict
    package_id: int
    skill_id: int
    kind: str = "skill_script"
    skill_name: str | None = None
    skill_version: str | None = None


@dataclass(frozen=True)
class SkillInstructionTool:
    name: str
    description: str
    input_schema: dict
    kind: str = "skill_instruction"
    skill_name: str | None = None
    skill_version: str | None = None


def build_skill_instruction_tool(bindings) -> SkillInstructionTool | None:
    """只暴露当前 Agent 的技能元数据，完整指令通过工具按需加载。"""
    if not bindings:
        return None
    skills = []
    for binding in bindings:
        skill = binding.skill
        package = getattr(skill, "package", None)
        manifest = getattr(package, "manifest", {}) or {}
        version = manifest.get("version") if isinstance(manifest, dict) else None
        skills.append(
            {
                "slug": getattr(skill, "slug", None) or getattr(skill, "name", "skill"),
                "name": getattr(skill, "name", None) or getattr(skill, "slug", "未命名技能"),
                "description": getattr(skill, "description", None) or "未提供技能描述",
                "version": version,
            }
        )
    return SkillInstructionTool(
        name="load_skill",
        description="按需加载当前 Agent 已绑定技能的完整指令。只能使用清单中的 slug。",
        input_schema={
            "type": "object",
            "properties": {
                "slug": {
                    "type": "string",
                    "enum": [item["slug"] for item in skills],
                    "description": "要加载的技能 slug",
                }
            },
            "required": ["slug"],
            "additionalProperties": False,
        },
    )


def build_skill_script_tools(bindings) -> list[SkillScriptTool]:
    tools: list[SkillScriptTool] = []
    seen_packages: set[int] = set()
    for binding in bindings:
        skill = binding.skill
        package = skill.package
        if (
            package is None
            or package.id in seen_packages
            or not package.is_active
            or not package.allow_script_execution
        ):
            continue
        paths = sorted(
            file.relative_path
            for file in package.files
            if file.role == "script"
            and any(file.relative_path.endswith(suffix) for suffix in SUPPORTED_SCRIPT_SUFFIXES)
        )
        if not paths:
            continue
        seen_packages.add(package.id)
        tools.append(
            SkillScriptTool(
                name=f"run_skill_script_{package.id}",
                description=(
                    f"执行技能包 {package.name} 内已授权脚本。"
                    f"允许路径：{', '.join(paths)}"
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "script_path": {"type": "string", "enum": paths},
                        "arguments": {
                            "type": "array",
                            "items": {"type": "string", "maxLength": 1000},
                            "maxItems": 32,
                            "default": [],
                        },
                    },
                    "required": ["script_path"],
                    "additionalProperties": False,
                },
                package_id=package.id,
                skill_id=skill.id,
                skill_name=getattr(skill, "name", None) or getattr(skill, "slug", None),
                skill_version=(getattr(package, "manifest", {}) or {}).get("version") if isinstance(getattr(package, "manifest", {}), dict) else None,
            )
        )
    return tools
