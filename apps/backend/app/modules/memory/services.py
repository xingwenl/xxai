"""用户记忆服务层：写入判定、覆盖语义、检索视图与索引行构造。

这里的规则分三类，全部**由代码执行**而不是只写进提示词：

1. 谁能写：没有可识别主体（既没有后台用户，也不是带 Client 的终端用户）
   一律拒绝，无人值守同样拒绝；
2. 能自动写什么：``mode=inferred`` 只允许事实类、只允许白名单 key、不许碰
   敏感类别、不许写长文；
3. 写了之后看到什么：事实返回「新值 + 原值」的回显，让用户在聊天里就能看出
   模型记错了没有。

提示词是建议，代码才是边界——模型偶尔会把人名当城市、把玩笑当真话，这些
判断不能交给它自己。

主体有两种（后台用户 / 「Client + 终端用户」），见
docs/adr/0016-end-user-memory.md；本层只接收 ``MemoryPrincipal``，不再自己
拼 platform_id + user_id，避免某条路径漏掉 Client 隔离。
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.modules.memory.principal import MemoryPrincipal, user_principal
from app.shared.exceptions import BadRequestException

FACT = "fact"
EVENT = "event"

MODE_EXPLICIT = "explicit"
MODE_INFERRED = "inferred"

# 自动写入（inferred）允许的事实 key。白名单窄是刻意的：宁可让模型问一句
# 「要我记一下吗」，也不要把一堆它自认为重要的东西写进用户档案。
INFERRED_FACT_KEYS = frozenset(
    {
        "姓名",
        "称呼",
        "昵称",
        "城市",
        "常住地",
        "时区",
        "语言",
        "工作",
        "职业",
        "角色",
        "长期项目",
        "偏好",
        "忌讳",
    }
)

# 敏感类别关键字：即使看起来是「事实」，inferred 也一律拒绝，必须用户明说。
# 这些内容一旦自动记错，代价远高于「多问一句」。
SENSITIVE_KEYWORDS = (
    # 健康与医疗
    "健康",
    "疾病",
    "病史",
    "病历",
    "用药",
    "服药",
    "体检",
    "过敏",
    "手术",
    "抑郁",
    "焦虑",
    "失眠",
    "残疾",
    "怀孕",
    # 财务
    "收入",
    "工资",
    "月薪",
    "年薪",
    "薪资",
    "存款",
    "贷款",
    "负债",
    "债务",
    "信用卡",
    "余额",
    "资产",
    "投资",
    "税务",
    "缴税",
    # 证件与账号
    "身份证",
    "护照",
    "驾照",
    "银行卡",
    "社保",
    "医保",
    "密码",
    "验证码",
    "账号",
    # 联系方式与详细住址（城市级别的常住地不在此列）
    "手机号",
    "电话号码",
    "邮箱",
    "门牌",
    "详细地址",
    "家庭住址",
    "邮编",
    # 政治、宗教、性与家庭关系
    "政治",
    "党派",
    "宗教",
    "信仰",
    "性取向",
    "性向",
    "婚姻",
    "离婚",
    "子女",
    "家庭关系",
)

# 「本人范围写入」工具：写的是用户自己的记忆，读的也是本人，不改变他人可见性，
# 因此在交互式会话里直通审批闸口。集合由单测锁定，新增时必须同步评估代价。
SELF_SCOPED_WRITE_TOOLS = frozenset({"remember_user_memory", "forget_user_memory"})

# 自动写入的事实正文上限：事实是短条目，长文多半是模型把一段对话整段塞进来。
INFERRED_FACT_MAX_CHARS = 200

# 单次检索返回的正文总字符上限，防止把记忆全量倒进模型上下文。
SEARCH_MAX_CHARS = 4000

# 单次检索最多返回的条数（只影响工具返回量，不影响注入内容）。
SEARCH_MAX_ITEMS = 200


def normalize_kind(kind: str) -> str:
    if kind not in (FACT, EVENT):
        raise BadRequestException("unsupported memory kind", error_code="memory_kind_invalid")
    return kind


def is_sensitive(text: str) -> bool:
    """命中任一敏感关键字即视为敏感内容。宁可误判，不可漏判。"""

    haystack = text or ""
    return any(keyword in haystack for keyword in SENSITIVE_KEYWORDS)


def validate_write(
    *,
    kind: str,
    key: str | None,
    content: str,
    mode: str,
) -> tuple[str, str | None]:
    """校验一次写入是否被允许，返回 (kind, 归一化后的 key)。

    失败时抛带稳定错误码的 ``BadRequestException``——工具层会把它转成模型可读的
    错误码，前端会把它转成 400，两处读的是同一套判定。
    """

    kind = normalize_kind(kind)
    text = (content or "").strip()
    if not text:
        raise BadRequestException("memory content is empty", error_code="memory_empty")
    if mode not in (MODE_EXPLICIT, MODE_INFERRED):
        raise BadRequestException(
            "unsupported memory write mode", error_code="memory_mode_invalid"
        )

    if mode == MODE_INFERRED:
        if kind != FACT:
            # 经历只能显式写：只追加的条目写错了无法被下一条覆盖，会在时间线上
            # 留下一段假历史，代价不可逆。
            raise BadRequestException(
                "inferred memory must be a fact", error_code="memory_inferred_requires_fact"
            )
        if len(text) > INFERRED_FACT_MAX_CHARS:
            raise BadRequestException(
                "inferred memory content too long",
                error_code="memory_content_too_long",
            )
        if is_sensitive(f"{key or ''}{text}"):
            raise BadRequestException(
                "sensitive memory requires explicit write",
                error_code="memory_sensitive_requires_explicit",
            )

    if kind == FACT:
        normalized_key = (key or "").strip()
        if not normalized_key:
            raise BadRequestException(
                "fact memory requires a key", error_code="memory_key_required"
            )
        if mode == MODE_INFERRED and normalized_key not in INFERRED_FACT_KEYS:
            raise BadRequestException(
                "key is not allowed for inferred write",
                error_code="memory_key_not_allowed_for_inferred",
            )
        return kind, normalized_key

    return kind, None


def build_memory_index_line(fact_count: int, event_count: int) -> str:
    """构造注入系统提示的记忆索引行——**只有条数与使用规则，没有任何事实值**。

    它的作用不是提供信息，而是让模型知道「有记忆可查」：不注入这一行时，
    被问「我叫什么」的模型更可能直接说不知道或编造一个答案。
    """

    total = fact_count + event_count
    if total == 0:
        head = "当前用户还没有保存任何个人记忆（事实 0 条 / 经历 0 条）。"
    else:
        head = (
            f"当前用户已保存 {total} 条个人记忆"
            f"（事实 {fact_count} 条 / 经历 {event_count} 条），内容不在本次上下文里。"
        )
    return (
        "【用户记忆】\n"
        f"{head}\n"
        "使用规则：\n"
        "1. 回答涉及用户姓名、称呼、所在城市、时区、语言、工作角色、长期项目、"
        "偏好、忌讳或过往经历时，先调用 memory_search 查记忆，再据此回答；"
        "不要仅凭当前对话猜测这些信息。\n"
        "2. 记忆里查不到就直接说没有记录，不要编造，也不要用一般常识补全。\n"
        "3. 用户明确要求记住某事（如「记一下」「记住」）时，调用 remember_user_memory "
        "并传 mode=explicit；用户明确陈述了个人信息的现状或变化、且不属于敏感类别时，"
        "可以用 mode=inferred 自动记住。\n"
        "4. 用户要求忘掉某事时，调用 forget_user_memory；不要用新的记忆内容去抵消。"
    )


async def load_memory_index_line_for_principal(
    memory_repo, principal: MemoryPrincipal | None
) -> str | None:
    """读取主体当前记忆条数并构造索引行；没有主体时返回 None（不注入）。"""

    if principal is None:
        return None
    fact_count, event_count = await memory_repo.count_active_by_kind(principal)
    return build_memory_index_line(fact_count, event_count)


async def load_memory_index_line(
    memory_repo, *, platform_id: int, user_id: int | None
) -> str | None:
    """后台用户主体的索引行。

    保留这个签名是因为 REST 对话路径（conversation/services.py）只知道后台
    用户；它内部转成 ``MemoryPrincipal``，与嵌入路径共用同一套条数查询。
    """

    if user_id is None:
        return None
    return await load_memory_index_line_for_principal(
        memory_repo, user_principal(platform_id, user_id)
    )


def _format_month_day(value: datetime | None) -> str:
    if value is None:
        return "未记录时间"
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d")


def format_remember_message(
    kind: str,
    *,
    key: str | None,
    content: str,
    occurred_at: datetime | None,
    previous_content: str | None,
) -> str:
    """写入后的回显文案。原值必须出现在回显里——用户靠它发现「记错了」。"""

    if kind == EVENT:
        return f"已记录经历：{_format_month_day(occurred_at)} {content}"
    if previous_content and previous_content != content:
        return (
            f"已记住：{key} = {content}"
            f"（原值：{previous_content}，{_format_month_day(occurred_at)} 起）"
        )
    return f"已记住：{key} = {content}"


def memory_payload(row) -> dict:
    """工具返回的单条记忆视图：字段名对模型友好，不暴露内部列。"""

    return {
        "id": row.id,
        "kind": row.kind,
        "key": row.key,
        "content": row.content,
        "occurred_at": row.occurred_at.isoformat() if row.occurred_at else None,
        "valid_until": row.valid_until.isoformat() if row.valid_until else None,
        "is_active": row.valid_until is None,
        "source": row.source,
    }


def truncate_payloads(payloads: list[dict], max_chars: int = SEARCH_MAX_CHARS) -> list[dict]:
    """按总字符预算截断，保留顺序；超预算的条目直接丢弃而不是截半句。"""

    kept: list[dict] = []
    used = 0
    for payload in payloads:
        size = len(payload.get("content") or "")
        if kept and used + size > max_chars:
            break
        kept.append(payload)
        used += size
    return kept


async def remember_memory(
    memory_repo,
    *,
    principal: MemoryPrincipal | None,
    kind: str,
    key: str | None,
    content: str,
    occurred_at: datetime | None,
    mode: str,
    source_conversation_id: int | None = None,
) -> dict:
    """写入一条记忆并返回回显结果。"""

    if principal is None:
        raise BadRequestException(
            "memory write requires a present user",
            error_code="memory_principal_required",
        )
    kind, normalized_key = validate_write(
        kind=kind, key=key, content=content, mode=mode
    )
    text = content.strip()

    if kind == FACT:
        row, previous = await memory_repo.upsert_fact(
            principal=principal,
            key=normalized_key,
            content=text,
            occurred_at=occurred_at,
            source=mode,
            source_conversation_id=source_conversation_id,
        )
        return {
            "id": row.id,
            "status": "remembered",
            "kind": FACT,
            "key": row.key,
            "content": row.content,
            "occurred_at": row.occurred_at.isoformat() if row.occurred_at else None,
            "previous_content": previous.content if previous is not None else None,
            "message": format_remember_message(
                FACT,
                key=row.key,
                content=row.content,
                occurred_at=row.occurred_at,
                previous_content=previous.content if previous is not None else None,
            ),
        }

    row = await memory_repo.create_event(
        principal=principal,
        content=text,
        occurred_at=occurred_at or datetime.now(timezone.utc),
        source=mode,
        source_conversation_id=source_conversation_id,
    )
    return {
        "id": row.id,
        "status": "remembered",
        "kind": EVENT,
        "key": None,
        "content": row.content,
        "occurred_at": row.occurred_at.isoformat() if row.occurred_at else None,
        "previous_content": None,
        "message": format_remember_message(
            EVENT,
            key=None,
            content=row.content,
            occurred_at=row.occurred_at,
            previous_content=None,
        ),
    }


async def search_memory(
    memory_repo,
    *,
    principal: MemoryPrincipal | None,
    query: str | None,
    include_history: bool = False,
    kind: str | None = None,
) -> dict:
    """按需检索记忆：全量 active 返回（不走向量），可选关键词过滤。"""

    if principal is None:
        raise BadRequestException(
            "memory search requires a present user",
            error_code="memory_principal_required",
        )
    rows = await memory_repo.list_for(
        principal,
        kind=normalize_kind(kind) if kind else None,
        include_history=include_history,
        query=query,
        limit=SEARCH_MAX_ITEMS,
    )
    payloads = truncate_payloads([memory_payload(row) for row in rows])
    return {
        "items": payloads,
        "total": len(payloads),
        "include_history": include_history,
        "message": (
            "没有找到匹配的记忆记录。不要编造，直接告诉用户没有记录。"
            if not payloads
            else f"共找到 {len(payloads)} 条相关记忆。"
        ),
    }
