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
