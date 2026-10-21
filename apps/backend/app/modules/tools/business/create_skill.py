"""内置业务工具：让 Agent 在会话中为自己创建、修改并绑定技能。

边界（与平台技能模型一致）：
- 技能落在**当前平台**的技能库（``skills``，``package_id`` 为空的手工技能），
  平台管理员可在管理端「技能」页面查看、编辑或删除；
- 新建后自动绑定到**当前 Agent**（``agent_skills``），否则技能不会被
  ``load_skill`` 暴露，创建了也永远用不上；
- 显式 slug 命中已有技能时按「更新」处理（upsert），但只允许改**当前 Agent
  已启用的手工技能**：平台没有「技能创建者」字段，不收紧范围的话 Agent 能
  覆盖掉其他 Agent 正在用的技能；技能包导入的技能（``package_id`` 非空）
  也不允许改，其内容以技能包为唯一来源，改了会与包内文件不一致；
- 本工具不涉及技能包导入，因此没有脚本、没有 ``lifecycle_hooks``。
"""

from __future__ import annotations

from app.modules.skill import services as skill_services
from app.modules.skill.importers import slugify
from app.modules.skill.repositories import SkillRepository
from app.modules.skill.schemas import AgentSkillBind, SkillCreate, SkillUpdate
from app.modules.tools.business.framework import (
    BusinessToolContext,
    BusinessToolError,
    business_tool,
)
from app.shared.exceptions import AppException, ConflictException

# 与 skills.slug 列宽一致；派生 slug 时截断长度要留出序号后缀的空间。
_MAX_SLUG_LENGTH = 80
# 派生 slug 撞名时的自动重试次数：纯中文名会统一退化成 skill，需要能区分开。
_MAX_SLUG_RETRY = 20


@business_tool(
    name="create_skill",
    description=(
        "创建或修改一个可复用的技能，并绑定到当前 Agent。"
        "适用场景：用户希望你把某套重复的做法「记下来、以后照着做」"
        "（例如固定的周报格式、固定的排查步骤、固定的数据处理流程），"
        "或明确要求「给我做个技能」「改一下这个技能」。"
        "技能是平台级资源：进入平台技能库，可在管理端技能页面查看和编辑；"
        "同时绑定到当前 Agent，从下一轮对话开始出现在你的技能清单里，"
        "需要用 load_skill 加载完整指令后按指令执行。"
        "用法：name 是技能名称（中文可读名）；instruction_template 是技能的完整指令正文，"
        "要写成独立可执行的操作说明（加载时看不到当前对话上下文）；"
        "slug 是平台内唯一标识，建议显式给出小写英文/连字符短名"
        "（省略时由 name 推导，纯中文名会退化重名）；description 用一句话说明适用场景。"
        "修改已有技能：显式传入该技能的 slug 即为更新，会整体覆盖 name 与 "
        "instruction_template；description 省略时保留原值。"
        "注意：只能修改当前 Agent 已启用的手工技能；"
        "技能包导入的技能、未绑定当前 Agent 或已被停用的技能会返回错误，不要重试。"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "minLength": 1,
                "maxLength": 120,
                "description": "技能名称，用于技能列表展示",
            },
            "slug": {
                "type": "string",
                "minLength": 2,
                "maxLength": 80,
                "pattern": "^[a-z0-9][a-z0-9_-]*$",
                "description": (
                    "平台内唯一标识，小写英文/数字/下划线/连字符，"
                    "如 weekly-report；省略时由 name 推导；"
                    "显式传入已有技能的 slug 表示修改该技能"
                ),
            },
            "description": {
                "type": "string",
                "maxLength": 500,
                "description": (
                    "一句话说明这个技能适用于什么任务；修改已有技能时省略则保留原描述"
                ),
            },
            "instruction_template": {
                "type": "string",
                "minLength": 1,
                "description": (
                    "技能的完整指令正文（Markdown）：说明适用条件、步骤、"
                    "输出格式与注意事项，必须独立可执行"
                ),
            },
        },
        "required": ["name", "instruction_template"],
        "additionalProperties": False,
    },
    side_effect="write",
)
async def create_skill_business(args: dict, ctx: BusinessToolContext) -> dict:
    """创建或修改平台技能，并保证它绑定到当前 Agent。"""

    if ctx.session is None:
        raise BusinessToolError(
            "skill_create_failed",
            "无法创建技能：当前工具上下文没有可用的数据库会话。",
        )

    name = str(args.get("name") or "").strip()[:120]
    instruction_template = str(args.get("instruction_template") or "").strip()
    if not name or not instruction_template:
        raise BusinessToolError(
            "invalid_arguments",
            "创建技能至少需要 name 与 instruction_template 两个字段。",
        )
    description_provided = "description" in args
    description = str(args.get("description") or "").strip()[:500] or None

    raw_slug = str(args.get("slug") or "").strip()
    explicit_slug = bool(raw_slug)
    base_slug = _normalize_slug(raw_slug or name)

    repo = SkillRepository(ctx.session)

    # 显式 slug 命中已有技能 → 按更新处理；否则新建（没给 slug 时自动派生可用值）。
    existing = (
        await repo.get_by_slug(ctx.platform_id, base_slug) if explicit_slug else None
    )
    if existing is not None:
        skill, binding = await _update_bound_skill(
            repo,
            ctx,
            existing,
            name=name,
            description=description,
            description_provided=description_provided,
            instruction_template=instruction_template,
        )
        return {
            "kind": "create_skill",
            "action": "updated",
            "skill": _skill_payload(skill),
            "binding": {
                "agent_id": ctx.agent_id,
                "sort_order": binding.sort_order,
                "is_enabled": binding.is_enabled,
            },
            "message": (
                f"技能「{skill.name}」（slug={skill.slug}）已更新，"
                "从下一轮对话开始按新指令执行。"
                "技能仍在平台技能库中，可在管理端技能页面查看或编辑。"
            ),
        }

    try:
        # 模型没给 slug 时（纯中文名很常见）自动向后找可用 slug：
        # 直接报「slug 已存在」会让中文名技能永远建不出来。
        slug = (
            base_slug
            if explicit_slug
            else await _unique_slug(repo, ctx.platform_id, base_slug)
        )
        skill = await skill_services.create_skill(
            repo,
            ctx.platform_id,
            SkillCreate(
                name=name,
                slug=slug,
                description=description,
                instruction_template=instruction_template,
            ),
        )
    except BusinessToolError:
        raise
    except ConflictException as exc:
        # create_skill 的预检查与唯一约束之间仍有并发窗口，兜底转稳定错误码。
        raise BusinessToolError(
            "skill_slug_exists",
            f"技能 slug「{slug}」已存在，请换一个 slug 重试。",
        ) from exc
    except AppException as exc:
        raise BusinessToolError("skill_create_failed", exc.message or "") from exc

    binding = await _bind_to_agent(repo, ctx, skill)
    return {
        "kind": "create_skill",
        "action": "created",
        "skill": _skill_payload(skill),
        "binding": {
            "agent_id": ctx.agent_id,
            "sort_order": binding.sort_order,
            "is_enabled": binding.is_enabled,
        },
        "message": (
            f"技能「{skill.name}」（slug={skill.slug}）已创建并绑定到当前 Agent，"
            "从下一轮对话开始可通过 load_skill 加载。"
            "技能已进入平台技能库，可在管理端技能页面查看、编辑或删除。"
        ),
    }


def _skill_payload(skill) -> dict:
    """返回给模型的技能摘要：不回传完整指令正文，避免重复占用上下文。"""

    return {
        "id": skill.id,
        "name": skill.name,
        "slug": skill.slug,
        "description": skill.description,
        "is_active": skill.is_active,
    }


async def _update_bound_skill(
    repo: SkillRepository,
    ctx: BusinessToolContext,
    skill,
    *,
    name: str,
    description: str | None,
    description_provided: bool,
    instruction_template: str,
):
    """更新当前 Agent 已启用的手工技能，拒绝越过边界覆盖别人的技能。"""

    if skill.package_id is not None:
        raise BusinessToolError(
            "skill_update_forbidden",
            f"技能「{skill.name}」（slug={skill.slug}）由技能包导入，"
            "不能通过本工具修改；请让管理员更新技能包，或换一个 slug 新建。",
        )
    if not skill.is_active:
        raise BusinessToolError(
            "skill_update_forbidden",
            f"技能「{skill.name}」（slug={skill.slug}）已被管理员停用，"
            "请让管理员在管理端重新启用后再修改。",
        )
    binding = await _find_binding(repo, ctx, skill.id)
    if binding is None or not binding.is_enabled:
        raise BusinessToolError(
            "skill_update_forbidden",
            f"技能「{skill.name}」（slug={skill.slug}）未启用绑定到当前 Agent，"
            "本工具只能修改当前 Agent 正在使用的技能；"
            "请换一个 slug 新建，或让管理员在管理端修改该技能。",
        )

    values: dict = {"name": name, "instruction_template": instruction_template}
    if description_provided:
        # 显式传 description（含空串）才覆盖，省略时保留原值，避免顺手清空简介。
        values["description"] = description or ""
    try:
        updated = await skill_services.update_skill(
            repo, ctx.platform_id, skill.id, SkillUpdate(**values)
        )
    except AppException as exc:
        raise BusinessToolError("skill_update_failed", exc.message or "") from exc
    return updated, binding


async def _find_binding(repo: SkillRepository, ctx: BusinessToolContext, skill_id: int):
    """在当前 Agent 的技能绑定里找目标技能（只读查询，不会新建绑定）。"""

    try:
        bindings = await repo.list_bindings(ctx.platform_id, ctx.agent_id)
    except AppException as exc:
        raise BusinessToolError("skill_update_failed", exc.message or "") from exc
    return next((item for item in bindings if item.skill_id == skill_id), None)


async def _bind_to_agent(repo: SkillRepository, ctx: BusinessToolContext, skill):
    """把新技能追加到当前 Agent 的技能绑定末尾（不改动已有顺序）。"""

    try:
        bindings = await repo.list_bindings(ctx.platform_id, ctx.agent_id)
        next_sort_order = max((item.sort_order for item in bindings), default=-1) + 1
        binding = await repo.bind(
            ctx.platform_id,
            ctx.agent_id,
            AgentSkillBind(skill_id=skill.id, sort_order=next_sort_order),
        )
    except AppException as exc:
        raise BusinessToolError(
            "skill_bind_failed",
            f"技能「{skill.name}」已创建，但绑定到当前 Agent 失败：{exc.message or ''}"
            "请让管理员在管理端技能的 Agent 绑定里手动添加。",
        ) from exc
    if binding is None:
        raise BusinessToolError(
            "skill_bind_failed",
            f"技能「{skill.name}」已创建，但当前 Agent 不在该平台下，绑定失败。"
            "请让管理员在管理端手动绑定。",
        )
    return binding


def _normalize_slug(value: str) -> str:
    """把工具入参转成满足 skills.slug 约束的取值。

    复用技能导入链路的 :func:`slugify`，保证「导入的技能」与「Agent 创建的技能」
    生成规则一致；再补上 schema 的 ``min_length=2`` 约束。
    """

    slug = slugify(value)
    if len(slug) < 2:
        slug = f"skill-{slug}" if slug else "skill"
    return slug[:_MAX_SLUG_LENGTH].rstrip("-_") or "skill"


async def _unique_slug(repo: SkillRepository, platform_id: int, base_slug: str) -> str:
    """派生 slug 撞名时追加 ``-2``、``-3``……直到可用。"""

    candidate = base_slug
    for index in range(_MAX_SLUG_RETRY):
        if await repo.get_by_slug(platform_id, candidate) is None:
            return candidate
        suffix = f"-{index + 2}"
        candidate = (
            f"{base_slug[: _MAX_SLUG_LENGTH - len(suffix)].rstrip('-_')}{suffix}"
        )
    raise BusinessToolError(
        "skill_slug_exists",
        f"技能 slug「{base_slug}」及其派生名均已被占用，请显式给出一个不同的 slug。",
    )
