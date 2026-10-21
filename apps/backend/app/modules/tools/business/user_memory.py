"""内置业务工具：让 Agent 读写「当前会话主体」自己的长期记忆。

三条工具都只作用于**会话主体本人**，没有跨主体入口。主体有两种：后台用户
（``ctx.user_id``，控制台与 REST 对话）和嵌入终端用户
（``ctx.client_id`` + ``ctx.platform_end_user_id``，第三方站点访客），
隔离口径见 docs/adr/0016-end-user-memory.md：

- ``remember_user_memory``：写事实（可按 key 覆盖）或经历（只追加）；
- ``forget_user_memory``：按 id / key / 关键词删除；
- ``memory_search``：按需检索，**记忆内容不预注入上下文**。

写入分两种模式。``mode=explicit`` 用于用户明确要求「记一下」，不设白名单；
``mode=inferred`` 用于模型从用户陈述里自动识别个人信息，只允许事实类、白名单
key、且命中敏感类别一律拒绝——判定在 ``memory.services`` 里，不在提示词里。

无人值守运行（任务、工作流）不写记忆：没有在场的人，静默写入的事实无法被纠正，
而记忆的正确性依赖用户能看见提示词外的这层变化。
"""

from __future__ import annotations

from datetime import datetime

from app.modules.memory.principal import (
    MemoryPrincipal,
    end_user_principal,
    user_principal,
)
from app.modules.memory.repositories import MemoryRepository
from app.modules.memory.services import (
    MODE_EXPLICIT,
    MODE_INFERRED,
    remember_memory,
    search_memory,
)
from app.modules.tools.business.framework import (
    BusinessToolContext,
    BusinessToolError,
    business_tool,
)
from app.shared.exceptions import AppException


def _parse_occurred_at(raw: object) -> datetime | None:
    """接受 ISO 8601 字符串（含 ``Z``）；空值视为「未提供」。"""

    if raw is None or raw == "":
        return None
    if not isinstance(raw, str):
        raise BusinessToolError("invalid_arguments", "occurred_at 必须是 ISO 8601 字符串")
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BusinessToolError(
            "invalid_arguments", "occurred_at 必须是 ISO 8601 字符串"
        ) from exc


def _require_principal(ctx: BusinessToolContext) -> MemoryPrincipal:
    """记忆写入与检索都要求「有在场主体」。

    后台用户优先；嵌入会话没有后台登录态，用「Client + 终端用户」表达归属。
    无人值守仍然一律拒绝——没有在场的人，静默写入的事实无法被纠正。
    """

    if ctx.unattended:
        raise BusinessToolError(
            "memory_principal_required",
            "当前为无人值守运行，无法写入或读取用户记忆",
        )
    if ctx.user_id is not None:
        return user_principal(ctx.platform_id, ctx.user_id)
    if ctx.client_id and ctx.platform_end_user_id is not None:
        return end_user_principal(
            platform_id=ctx.platform_id,
            client_id=ctx.client_id,
            end_user_id=ctx.platform_end_user_id,
        )
    raise BusinessToolError(
        "memory_principal_required", "当前会话没有可识别的用户"
    )


def _as_tool_error(exc: AppException) -> BusinessToolError:
    """把服务层的稳定错误码原样交给模型，方便它决定是改参数还是向用户解释。"""

    return BusinessToolError(getattr(exc, "error_code", None) or "invalid_arguments", str(exc))


@business_tool(
    name="remember_user_memory",
    description=(
        "把关于当前用户的个人信息记进长期记忆，跨会话、跨 Agent 生效。"
        "两类内容：kind=fact 是稳定事实（姓名、城市、时区、语言、工作角色、长期项目、"
        "偏好、忌讳等），同一 key 再次写入会关闭旧值、保留时间线；"
        "kind=event 是一次性经历（我做过什么、什么时候），只追加、不覆盖。"
        "写入模式：mode=explicit 仅用于用户明确要求记住（如「记一下」「记住」），"
        "不设关键词白名单；mode=inferred 用于从用户明确陈述中自动识别个人信息变化，"
        "只允许事实类与姓名/称呼/城市/时区/语言/工作/长期项目/偏好/忌讳等白名单 key，"
        "健康、财务、证件、联系方式、详细住址、政治宗教等敏感内容会被拒绝，"
        "此时应改为向用户确认后再以 explicit 写入。"
        "返回结果里的 message 是给用户看的回显（含原值），写完把它转述给用户。"
        "不确定是否该记时先问一句，不要批量写入猜测的内容。"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "kind": {
                "type": "string",
                "enum": ["fact", "event"],
                "description": "fact=稳定事实；event=一次性经历",
            },
            "content": {
                "type": "string",
                "minLength": 1,
                "maxLength": 2000,
                "description": "记忆正文，写成一句完整、脱离上下文也能读懂的话",
            },
            "key": {
                "type": "string",
                "minLength": 1,
                "maxLength": 80,
                "description": "仅仅 kind=fact 使用：事实的稳定标识，如 姓名、城市、时区",
            },
            "occurred_at": {
                "type": "string",
                "description": (
                    "ISO 8601 时间。事实=该信息从何时起有效；"
                    "经历=何时发生（不传取当前时间）"
                ),
            },
            "mode": {
                "type": "string",
                "enum": ["explicit", "inferred"],
                "description": "explicit=用户明确要求；inferred=模型自动识别个人信息变化",
            },
        },
        "required": ["kind", "content"],
        "additionalProperties": False,
    },
    side_effect="write",
)
async def remember_user_memory_business(
    args: dict, ctx: BusinessToolContext
) -> dict:
    principal = _require_principal(ctx)
    mode = str(args.get("mode") or MODE_EXPLICIT)
    if mode not in (MODE_EXPLICIT, MODE_INFERRED):
        raise BusinessToolError("memory_mode_invalid", "mode 只能是 explicit 或 inferred")
    try:
        return await remember_memory(
            MemoryRepository(ctx.session),
            principal=principal,
            kind=str(args.get("kind") or ""),
            key=args.get("key"),
            content=str(args.get("content") or ""),
            occurred_at=_parse_occurred_at(args.get("occurred_at")),
            mode=mode,
            source_conversation_id=ctx.conversation_id,
        )
    except AppException as exc:
        raise _as_tool_error(exc) from exc


@business_tool(
    name="forget_user_memory",
    description=(
        "删除当前用户的记忆。三种定位方式选一种："
        "memory_id 精确删除某条；key 删除某个事实的当前有效值（如「忘记我的城市」）；"
        "query 按关键词删除匹配项（用于「忘掉关于 X 的所有记录」，会删除全部匹配项）。"
        "传 all=true 清空全部记忆，只在用户明确要求清空时使用。"
        "删除会立即生效且不可恢复，执行前确认用户确实要求忘记；"
        "返回 message 里列出被删除的内容，转述给用户。"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "memory_id": {
                "type": "integer",
                "minimum": 1,
                "description": "精确删除某条记忆的 ID（可从 memory_search 结果取得）",
            },
            "key": {
                "type": "string",
                "minLength": 1,
                "maxLength": 80,
                "description": "删除某个事实的当前有效值，如 城市",
            },
            "query": {
                "type": "string",
                "minLength": 1,
                "maxLength": 100,
                "description": "按关键词删除全部匹配的记忆",
            },
            "all": {
                "type": "boolean",
                "description": "清空全部记忆（仅在用户明确要求清空时使用）",
            },
        },
        "additionalProperties": False,
    },
    side_effect="write",
)
async def forget_user_memory_business(args: dict, ctx: BusinessToolContext) -> dict:
    principal = _require_principal(ctx)
    repo = MemoryRepository(ctx.session)
    memory_id = args.get("memory_id")
    key = str(args.get("key") or "").strip() or None
    query = str(args.get("query") or "").strip() or None
    delete_all = bool(args.get("all"))

    if delete_all:
        deleted = await repo.delete_all_for(principal)
        return {"status": "forgotten", "deleted": deleted, "message": "已清空全部记忆"}

    if memory_id is not None:
        row = await repo.get_by_id(int(memory_id))
        if row is None or not principal.owns(row):
            raise BusinessToolError("memory_not_found", "没有找到这条记忆")
        content = row.content
        await repo.delete(row)
        return {
            "status": "forgotten",
            "deleted": 1,
            "message": f"已忘记：{content}",
        }

    if key is not None:
        row = await repo.find_active_fact(principal, key)
        if row is None:
            raise BusinessToolError("memory_not_found", f"没有记录过 {key}")
        content = row.content
        await repo.delete(row)
        return {
            "status": "forgotten",
            "deleted": 1,
            "message": f"已忘记：{key} = {content}",
        }

    if query is not None:
        rows = await repo.list_for(
            principal,
            include_history=True,
            query=query,
            limit=20,
        )
        if not rows:
            raise BusinessToolError("memory_not_found", f"没有找到包含「{query}」的记忆")
        contents = [row.content for row in rows]
        for row in rows:
            await repo.delete(row)
        return {
            "status": "forgotten",
            "deleted": len(rows),
            "message": "已忘记：" + "；".join(contents),
        }

    raise BusinessToolError(
        "memory_key_required", "需要提供 memory_id、key、query 之一，或 all=true"
    )


@business_tool(
    name="memory_search",
    description=(
        "检索当前用户的长期记忆。记忆内容不会自动出现在上下文里，"
        "涉及用户的姓名、称呼、城市、时区、语言、工作角色、长期项目、偏好、忌讳、"
        "过往经历时，先调用本工具再回答。"
        "不传 query 返回全部当前有效记忆（事实 + 最近经历）；传 query 按关键词过滤。"
        "include_history=true 可查看已被新值覆盖的历史事实（回答「我以前是做什么的」时用）。"
        "返回 items 每项含 id、kind、key、content、occurred_at、is_active。"
        "查不到就如实说没有记录，不要编造或从常识推断。"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "minLength": 1,
                "maxLength": 100,
                "description": "关键词，可选；不传返回全部当前有效记忆",
            },
            "kind": {
                "type": "string",
                "enum": ["fact", "event"],
                "description": "只看某一类记忆",
            },
            "include_history": {
                "type": "boolean",
                "description": "是否包含被覆盖的历史事实，默认 false",
            },
        },
        "additionalProperties": False,
    },
)
async def memory_search_business(args: dict, ctx: BusinessToolContext) -> dict:
    principal = _require_principal(ctx)
    try:
        return await search_memory(
            MemoryRepository(ctx.session),
            principal=principal,
            query=args.get("query"),
            include_history=bool(args.get("include_history")),
            kind=args.get("kind"),
        )
    except AppException as exc:
        raise _as_tool_error(exc) from exc
