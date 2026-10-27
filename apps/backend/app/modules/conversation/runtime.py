"""
对话运行时模块

本模块实现了对话系统的核心运行时逻辑，负责：
- 管理对话图的执行流程（流式 / 非流式）
- 处理大模型的流式和非流式调用
- 支持工具（Tool）的绑定与调用循环
- 统一 Token 使用量的提取与合并
- 构建系统提示词（包含知识库引用、技能指令、宿主工具等）
- 加载运行时上下文（Agent 配置、知识库、技能、MCP 工具等）

核心执行流程：
    REST / SSE / WS 统一接入 AgentRuntime.AgentLoop 作为唯一主循环，本模块只
    提供协议与服务层共享的辅助能力：历史/快照消息组装、上下文护栏、工具事件
    到 loop step / 图片与自定义内容块的转换、错误 payload 与 Token 用量规整。

数据流向：
    load_runtime_context() → build_system_prompt() →（协议层）AgentRuntime → GraphResult
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import math
import re
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from app.core.config import get_settings
from app.core.logging import get_logger
from app.modules.agent_runtime.error_codes import ErrorCode
from app.modules.skill.services import build_runtime_skill_metadata
from app.modules.skill_runner.tools import (
    build_skill_instruction_tool,
    build_skill_script_tools,
)
from app.modules.conversation.schemas import RuntimeContext
from app.modules.agent_runtime.contracts import ToolOutcome, merge_usage
from app.modules.agent_runtime.usage import normalize_cache_tokens
from app.modules.agent_runtime.events import (
    # 事件模型下沉到 agent_runtime/events.py 后按原路径再导出：REST/网关两侧
    # 只在 events.py 定义一次 payload 与 SSE 编码，这里保留历史 import 位置。
    build_step_payload as build_step_payload,
    format_sse_event as format_sse_event,
)
from app.modules.agent_runtime.tool_events import (
    build_tool_event as build_runtime_tool_event,
    normalize_tool_step_status,
)

logger = get_logger(__name__)

# 工具结果快照：落库键、注入文本约定与上下文护栏相关常量
SNAPSHOT_METADATA_KEY = "tool_snapshots"
_SNAPSHOT_SECTION_TITLE = "以下为此前工具查询到的数据快照（数据截至各自查询时间）："
_SNAPSHOT_INJECT_TAIL = (
    "回答与快照同范围的问题时可直接使用快照；"
    "用户要求最新数据、变更时间/查询条件或快照未覆盖时，应重新调用工具查询。"
)
_SNAPSHOT_LIMIT_NOTE = "此前工具查询快照因上下文限制未保留，需要时可重新查询最新数据。"

# 压缩摘要注入抬头：模型据此区分「被压缩的历史」与逐条回放的历史正文，
# 上下文护栏也把摘要消息视为不可删除（见 _guardrail_protected_starts）。
COMPACTION_SUMMARY_TITLE = (
    "以下内容是此前对话的压缩摘要（原始消息仍完整保留在会话记录中）："
)

# 内置「模型名 → 已知上下文窗口」小映射：仅收录已核对的已知别名，
# 其余模型须在智能体版本上显式填写 context_window_tokens。
# DeepSeek 窗口事实 2026-09-03 按官方 news260424/news250821 核对。
KNOWN_MODEL_CONTEXT_WINDOWS: dict[str, int] = {
    "deepseek-v4-pro": 1_000_000,
    "deepseek-v4-flash": 1_000_000,
    "deepseek-v4-flash-vision-exp": 1_000_000,
    # V3.1/V3.2 时代别名：官方 API 已于 2026-07-24 退役，仅镜像/代理兼容。
    "deepseek-chat": 128_000,
    "deepseek-reasoner": 128_000,
}

# 平台工具结果的成功状态词：MCP/Builtin/宿主工具/技能 runner 的成功态均为
# "completed"（ToolInvocationOutcome/BuiltinToolOutcome），部分测试桩用
# "succeeded"；两者都视为可落快照的成功结果。
_SUCCESSFUL_OUTCOME_STATUSES = frozenset({"completed", "succeeded"})

_CONTEXT_DEGRADE_NOTE = (
    "此前对话与工具查询结果因超过模型上下文上限未纳入本次计算，需要时可重新查询。"
)


def convert_history_row(
    item: Any,
    attachment_parts: dict[str, list[dict]] | None = None,
    *,
    now: datetime | None = None,
) -> Any | None:
    """把一条持久化消息转成模型消息。

    不支持的角色、空正文、超出历史回放窗口的消息返回 None，由调用方跳过；
    带附件的用户消息恢复为多模态内容，保证后续轮次仍能读取历史附件。
    """

    settings = get_settings()
    now = now or datetime.now(timezone.utc)
    content = getattr(item, "content", "")
    if not isinstance(content, str) or not content.strip():
        return None
    role = getattr(item, "role", None)
    if role in ("user", "assistant", "tool") and not _message_within_window(
        item, now, settings.conversation_history_window_seconds
    ):
        # 快照保留期大于历史窗口时，超窗消息仅贡献快照、不再回放正文。
        return None
    if role == "user":
        parts = _history_attachment_parts(item, attachment_parts)
        message_content = (
            [{"type": "text", "text": content}, *parts] if parts else content
        )
        return HumanMessage(content=message_content)
    if role == "assistant":
        return AIMessage(content=content)
    if role == "tool":
        return ToolMessage(
            content=content,
            tool_call_id=getattr(item, "tool_call_id", None) or "history-tool",
        )
    return None


def build_history_view(
    history: list[Any] | None = None,
    attachment_parts: dict[str, list[dict]] | None = None,
    compaction: Any | None = None,
) -> tuple[list[Any], list[tuple[int, Any]]]:
    """构建历史消息视图，并返回「行 id → 消息对象」绑定表。

    ``compaction`` 是当前生效的压缩记录：摘要作为 SystemMessage 注入历史首位
    代替被压缩的旧行，``first_kept_message_id`` 之前的行不再逐条回放。绑定表
    供请求内控制器按边界筛选保留行使用。
    """

    now = datetime.now(timezone.utc)
    boundary_id = getattr(compaction, "first_kept_message_id", None)
    converted: list[Any] = []
    bindings: list[tuple[int, Any]] = []
    for item in history or []:
        row_id = getattr(item, "id", None)
        if boundary_id is not None and isinstance(row_id, int) and row_id < boundary_id:
            # 已被压缩摘要覆盖的历史行不再逐条回放。
            continue
        message = convert_history_row(item, attachment_parts, now=now)
        if message is None:
            continue
        converted.append(message)
        bindings.append((row_id if isinstance(row_id, int) else 0, message))
    # 摘要消息紧跟在系统提示之后（历史区首位），位于快照之前。
    summary_message = build_compaction_summary_message(compaction)
    if summary_message is not None:
        converted.insert(0, summary_message)
    # 历史末尾注入工具快照 SystemMessage（当前用户消息之前），无快照时零注入。
    snapshot_message = build_snapshot_injection_message(history, now=now)
    if snapshot_message is not None:
        converted.append(snapshot_message)
    return converted, bindings


def build_history_messages(
    history: list[Any] | None = None,
    attachment_parts: dict[str, list[dict]] | None = None,
    compaction: Any | None = None,
) -> list[Any]:
    """将持久化消息转换为模型消息（只取视图，不含行绑定）。"""

    return build_history_view(
        history, attachment_parts=attachment_parts, compaction=compaction
    )[0]


def _history_attachment_parts(
    item: Any,
    attachment_parts: dict[str, list[dict]] | None,
) -> list[dict]:
    """按消息内容块引用，组装该条历史用户消息的附件内容块。"""
    if not attachment_parts:
        return []
    parts: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for block in getattr(item, "content_blocks", None) or []:
        if not isinstance(block, dict):
            continue
        if block.get("type") not in {"image", "file"}:
            continue
        asset_id = block.get("asset_id") or block.get("assetId")
        if not asset_id:
            continue
        for part in attachment_parts.get(str(asset_id), []):
            key = (str(asset_id), part.get("type", ""))
            if key in seen:
                continue
            seen.add(key)
            parts.append(part)
    return parts


def _message_within_window(item: Any, now: datetime, window_seconds: int) -> bool:
    """判断持久化消息正文是否在历史回放窗口内；无时间戳的消息视为窗口内。"""
    created_at = getattr(item, "created_at", None)
    if created_at is None:
        return True
    try:
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        return (now - created_at).total_seconds() <= window_seconds
    except (TypeError, ValueError):
        return True


def _parse_iso_datetime(value: str) -> datetime | None:
    """解析 ISO8601 时间；无时区按 UTC 处理，解析失败返回 None。"""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _snapshot_entry_time(entry: dict) -> datetime:
    """取快照查询时间用于去重/排序；缺失或解析失败退化为最早时间。"""
    queried_at = entry.get("queried_at")
    parsed = _parse_iso_datetime(queried_at) if queried_at else None
    if parsed is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    return parsed


def _snapshot_list_text(result: dict, list_key: str, *, max_chars: int) -> str:
    """列表型工具结果分档保留：概要计数 + 预算内条目 + 未保留提示。"""
    items = result.get(list_key) or []
    total = result.get("total", len(items))
    texts: list[str] = []
    head = f"{list_key}: 共 {total} 条"
    used = len(head)
    for item in items:
        text = _summarize_json(item, limit=max_chars)
        if not text:
            continue
        if used + len(text) + 2 > max_chars:
            break
        texts.append(text)
        used += len(text) + 2
    # 未保留提示本身也占预算：若最终文本溢出，则逐步回退条目直到放得下。
    while True:
        kept = len(texts)
        note = ""
        if kept < len(items):
            note = (
                f"（共 {total} 条，仅保留前 {kept} 条，其余未保留；"
                "需要具体某条时可缩小查询条件重新查询）"
            )
        body = "\n".join(texts)
        final = f"{head}{note}" + (f"\n{body}" if body else "")
        if len(final) <= max_chars or not texts:
            return final if len(final) <= max_chars else head[:max_chars]
        texts.pop()


def _snapshot_summary_text(event: dict, *, max_chars: int) -> str:
    """构造脱敏快照文本：列表型结果按计数与预算分档保留，其余按长度截断。"""
    outcome = event.get("outcome")
    if outcome is None:
        return ""
    result = getattr(outcome, "result", None)
    if result is None:
        return ""
    if isinstance(result, dict):
        list_key = next(
            (key for key, value in result.items() if isinstance(value, list) and value),
            None,
        )
        if list_key is not None:
            return _snapshot_list_text(result, list_key, max_chars=max_chars)
    text = _summarize_json(result, limit=max_chars)
    return text


def _is_successful_outcome(outcome) -> bool:
    """判断工具结果是否为成功态；拒绝/过期/失败与 error 载荷不落快照。"""
    status = getattr(outcome, "status", None)
    if status not in _SUCCESSFUL_OUTCOME_STATUSES:
        return False
    result = getattr(outcome, "result", None)
    if not isinstance(result, dict):
        return True
    if "error" in result:
        return False
    inner = result.get("status")
    return inner not in {"rejected", "expired", "failed", "error"}


def build_tool_snapshots(
    tool_events: list[dict] | None,
    *,
    now: datetime | None = None,
    max_chars: int | None = None,
    total_chars: int | None = None,
    max_entries: int | None = None,
) -> list[dict]:
    """从一轮工具事件构造快照：只收 succeeded，按单条/合计/条数预算收敛。"""
    settings = get_settings()
    max_chars = max_chars or settings.tool_snapshot_max_chars
    total_chars = total_chars or settings.tool_snapshot_total_chars
    max_entries = max_entries or settings.tool_snapshot_max_entries
    if max_chars <= 0 or total_chars <= 0 or max_entries <= 0:
        return []
    now = now or datetime.now(timezone.utc)
    queried_at = now.isoformat()
    entries: list[dict] = []
    for event in tool_events or []:
        outcome = event.get("outcome")
        if outcome is None or not _is_successful_outcome(outcome):
            continue
        summary = _snapshot_summary_text(event, max_chars=max_chars)
        if not summary:
            continue
        entries.append(
            {
                "tool": event.get("tool", "unknown"),
                "queried_at": queried_at,
                "params": (
                    event.get("input_summary")
                    or _runtime_arguments_summary(event, limit=300)
                    or ""
                )[:120],
                "summary": summary,
            }
        )
    return _cap_snapshot_entries(
        entries, max_entries=max_entries, total_chars=total_chars
    )


def _cap_snapshot_entries(
    entries: list[dict],
    *,
    max_entries: int | None = None,
    total_chars: int | None = None,
) -> list[dict]:
    """按条数与合计字符预算裁剪快照：超预算时丢弃最旧条目。"""
    settings = get_settings()
    max_entries = (
        max_entries if max_entries is not None else settings.tool_snapshot_max_entries
    )
    total_chars = (
        total_chars if total_chars is not None else settings.tool_snapshot_total_chars
    )
    if max_entries <= 0 or total_chars <= 0:
        return []
    ascending = sorted(entries, key=_snapshot_entry_time)
    # 最新优先保留，超出条数/合计预算时丢弃最旧条目。
    newest_first = ascending[::-1][:max_entries]
    kept_reversed: list[dict] = []
    used = 0
    for entry in newest_first:
        summary = entry.get("summary") or ""
        if used + len(summary) > total_chars:
            continue
        kept_reversed.append(entry)
        used += len(summary)
    kept_reversed.reverse()
    return kept_reversed


def attach_tool_snapshots(metadata: dict | None, snapshots: list[dict]) -> dict:
    """把快照写入消息扩展元数据；无快照时保持原元数据不变。"""
    merged = dict(metadata or {})
    if snapshots:
        merged[SNAPSHOT_METADATA_KEY] = snapshots
    return merged


def collect_tool_snapshots(
    history: list[Any] | None,
    *,
    now: datetime | None = None,
    retention_seconds: int | None = None,
) -> list[dict]:
    """跨历史 assistant 消息收集快照：按保留期过滤并做同参数去重（保留最新）。"""
    settings = get_settings()
    if retention_seconds is None:
        retention_seconds = settings.tool_snapshot_retention_seconds
    if retention_seconds is None:
        retention_seconds = settings.conversation_history_window_seconds
    now = now or datetime.now(timezone.utc)
    entries: list[dict] = []
    for item in history or []:
        metadata = getattr(item, "message_metadata", None) or {}
        for entry in metadata.get(SNAPSHOT_METADATA_KEY) or []:
            if not isinstance(entry, dict) or not entry.get("summary"):
                continue
            queried_at = entry.get("queried_at")
            if queried_at and retention_seconds:
                parsed = _parse_iso_datetime(queried_at)
                if (
                    parsed is not None
                    and (now - parsed).total_seconds() > retention_seconds
                ):
                    continue
            entries.append(entry)
    # 同一查询条件（tool+params）多版本并存时只保留最新一份，避免歧义并省 token。
    best: dict[tuple[str, str], dict] = {}
    for entry in entries:
        key = (str(entry.get("tool", "")), str(entry.get("params", "")))
        current = best.get(key)
        if current is None or _snapshot_entry_time(entry) >= _snapshot_entry_time(
            current
        ):
            best[key] = entry
    return _cap_snapshot_entries(list(best.values()))


def build_snapshot_injection_message(
    history: list[Any] | None,
    *,
    now: datetime | None = None,
) -> SystemMessage | None:
    """把收集到的工具快照组装为轻量 SystemMessage；无快照时返回 None。"""
    snapshots = collect_tool_snapshots(history, now=now)
    if not snapshots:
        return None
    lines = [
        _SNAPSHOT_SECTION_TITLE,
        _SNAPSHOT_INJECT_TAIL,
        (
            "基于快照回答时请自然带出查询时间（如「根据您 14:02 的查询结果……」），"
            "让用户知晓结论来自快照数据；涉及付款、改单、发货等变更动作的执行前提，"
            "必须先调用工具查询最新数据，快照仅用于描述性回答。"
        ),
    ]
    for entry in snapshots:
        lines.append("")
        lines.append(
            f"[{entry.get('tool', 'unknown')}] 查询时间 {entry.get('queried_at', '未知')}"
        )
        params = entry.get("params")
        if params:
            lines.append(f"查询条件：{params}")
        lines.append(entry["summary"])
    return SystemMessage(content="\n".join(lines))


def resolve_context_window_tokens(
    version: Any, *, model_name: str | None = None
) -> int | None:
    """解析版本模型的上下文窗口：显式列值 > 内置模型名映射 > 未命中返回 None。

    模型名由调用方传入（来自平台模型注册表的解析结果）；版本行自本次改动起
    不再承载模型名，因此没有可回落的兜底来源。
    """
    explicit = getattr(version, "context_window_tokens", None)
    if explicit is not None and int(explicit) > 0:
        return int(explicit)
    name = (model_name or "").strip()
    if not name:
        return None
    if name in KNOWN_MODEL_CONTEXT_WINDOWS:
        return KNOWN_MODEL_CONTEXT_WINDOWS[name]
    # 兼容镜像/代理的 provider/model 前缀写法（如 openrouter/deepseek-chat）。
    suffix = name.rsplit("/", 1)[-1]
    return KNOWN_MODEL_CONTEXT_WINDOWS.get(suffix)


def is_context_length_exceeded(error: BaseException) -> bool:
    """识别 OpenAI/DeepSeek 兼容的「输入超出模型上下文上限」错误。"""
    code = getattr(error, "code", None)
    if isinstance(code, str) and ErrorCode.CONTEXT_LENGTH_EXCEEDED in code.lower():
        return True
    raw = str(error).lower()
    return any(
        marker in raw
        for marker in (
            "maximum context length",
            ErrorCode.CONTEXT_LENGTH_EXCEEDED,
            "maximum context",
            "prompt is too long",
        )
    )


def _should_degrade_context(error: BaseException) -> bool:
    """判断是否触发超限降级重试：开关开启且命中超限错误特征。"""
    return get_settings().context_exceeded_retry_enabled and is_context_length_exceeded(
        error
    )


def _degraded_messages(system_prompt: str, user_message: str) -> list[Any]:
    """构造超限降级重试消息：仅系统提示 + 当前用户消息并附注。"""
    return [
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"{user_message}\n\n{_CONTEXT_DEGRADE_NOTE}"),
    ]


def make_context_degrade_recoverer(system_prompt: str, user_message: str):
    """构造 AgentRuntime 的 on_model_error：上下文超限时降级重试一次。

    上下文超限属真实模型偶发错误：把历史全部丢弃、只保留系统提示与当前用户
    消息后重试一次即可恢复，不必整请求失败。恢复器返回待重试的新消息列表
    （与 build_langchain_messages 同为 LangChain 消息），非超限错误返回 None
    让 AgentLoop 原样上抛，避免把供应商故障误判成可恢复输入。
    """

    def recover(error, messages):
        if _should_degrade_context(error):
            return _degraded_messages(system_prompt, user_message)
        return None

    return recover


def make_multimodal_degrade_recoverer(system_prompt: str, user_message: str):
    """AgentRuntime 的多模态降级恢复器（WS embed 专用）。

    依次处理两种真实供应商错误，各自只降级重试一次：
    - 纯文本模型拒绝图片输入：去掉上下文中的 image_url 内容块（保留文本与
      文档），用裁图后的上下文重试；
    - 上下文超限：丢弃历史，仅保留系统提示与当前用户消息重试。
    其余错误返回 None，交由 AgentLoop 原样上抛。
    """

    def recover(error, messages):
        if _is_text_only_image_error(error):
            stripped = _strip_image_parts_from_messages(list(messages))
            if stripped:
                return stripped
            # 极端兜底：若裁图后没有剩余消息，退回“系统 + 当前用户文本”。
            return _degraded_messages(system_prompt, user_message)
        if _should_degrade_context(error):
            return _degraded_messages(system_prompt, user_message)
        return None

    return recover


def _messages_chars(messages: list[Any]) -> int:
    """估算消息列表字符数，兼容文本与多模态内容块。"""
    total = 0
    for message in messages:
        if isinstance(message, ToolOutcome):
            # runtime 上下文中的工具结果没有 content 字段，忽略会严重低估
            # 预算；这里按结果文本估算占用，避免护栏不触发。
            value = message.result
            if isinstance(value, str):
                total += len(value)
            elif value is not None:
                total += len(str(value))
            continue
        content = getattr(message, "content", None)
        if isinstance(content, str):
            total += len(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    text = block.get("text")
                    if isinstance(text, str):
                        total += len(text)
    return total


def _resolve_guardrail_budget(
    window_tokens: int,
    *,
    input_ratio: float | None,
    chars_per_token: float | None,
) -> int:
    """按上下文窗口与估算比例计算护栏允许的字符预算。"""

    settings = get_settings()
    ratio = input_ratio if input_ratio is not None else settings.context_input_ratio
    cpt = (
        chars_per_token
        if chars_per_token is not None
        else settings.context_estimate_chars_per_token
    )
    return int(window_tokens * ratio * cpt)


def _assistant_tool_call_ids(message: Any) -> set[str]:
    """提取一条 assistant 消息声明的工具调用 ID。"""

    calls = getattr(message, "tool_calls", None) or []
    ids = set()
    for call in calls:
        call_id = (
            call.get("id") if isinstance(call, dict) else getattr(call, "id", None)
        )
        if call_id:
            ids.add(str(call_id))
    return ids


def _tool_result_call_id(message: Any) -> str | None:
    """返回工具结果关联的 assistant 调用 ID，未知时返回 None。"""

    if isinstance(message, ToolOutcome):
        return message.call_id or message.metadata.get("call_id")
    return getattr(message, "tool_call_id", None)


def _resolve_chars_per_token(chars_per_token: float | None) -> float:
    """取本地估算使用的 chars/token 比例，非法值退化为保守默认。"""

    settings = get_settings()
    cpt = (
        chars_per_token
        if chars_per_token is not None
        else settings.context_estimate_chars_per_token
    )
    if not cpt or cpt <= 0:
        return 1.0
    return float(cpt)


def _message_payload_chars(message: Any) -> int:
    """估算单条消息计入上下文的字符数（含工具调用参数）。

    护栏使用的 ``_messages_chars`` 只统计正文；工具调用参数同样会进入模型
    输入，占用估算漏计它会让判断长期偏低，因此这里额外累加声明参数长度。
    """

    total = _messages_chars([message])
    calls = getattr(message, "tool_calls", None) or []
    for call in calls:
        args = (
            call.get("args") if isinstance(call, dict) else getattr(call, "args", None)
        )
        if args is None:
            continue
        try:
            total += len(json.dumps(args, ensure_ascii=False, default=str))
        except (TypeError, ValueError):
            total += len(str(args))
    return total


def _message_row_chars(row: Any) -> int:
    """估算一条持久化消息行的字符数（正文 + 内容块 + 元数据）。"""

    total = 0
    content = getattr(row, "content", None)
    if isinstance(content, str):
        total += len(content)
    for value in (
        getattr(row, "content_blocks", None),
        getattr(row, "message_metadata", None),
    ):
        if value is None:
            continue
        try:
            total += len(json.dumps(value, ensure_ascii=False, default=str))
        except (TypeError, ValueError):
            total += len(str(value))
    return total


def estimate_context_tokens(
    messages: list[Any],
    *,
    baseline_usage: int | None = None,
    chars_per_token: float | None = None,
) -> int:
    """估算一次模型调用的输入 token 数。

    口径与成熟 Agent 实现一致：优先用上一轮 provider 真实 usage 作为基线
    （它已经覆盖当时的系统提示、工具定义与历史），只对基线之后新增的内容做
    本地字符估算；拿不到真值时才退化为整份输入的估算。本地估算按 chars/token
    比例折算，宁可高估也不低估。
    """

    cpt = _resolve_chars_per_token(chars_per_token)
    chars = sum(_message_payload_chars(message) for message in messages)
    baseline = (
        int(baseline_usage)
        if isinstance(baseline_usage, int) and baseline_usage > 0
        else 0
    )
    return baseline + math.ceil(chars / cpt)


def estimate_row_tokens(row: Any, *, chars_per_token: float | None = None) -> int:
    """估算一条持久化消息行的 token 数，至少计 1。"""

    cpt = _resolve_chars_per_token(chars_per_token)
    return max(1, math.ceil(_message_row_chars(row) / cpt))


def resolve_compaction_threshold(
    window_tokens: int | None,
    *,
    reserve_tokens: int | None = None,
    input_ratio: float | None = None,
) -> int:
    """计算自动压缩的触发阈值（token）。

    取「窗口 - 预留」与「现有护栏预算」两者较小值：护栏会自行按 ``input_ratio``
    硬删历史，若压缩阈值更高，护栏会先把历史删光，压缩永远没有机会运行。
    """

    settings = get_settings()
    reserve = (
        reserve_tokens
        if reserve_tokens is not None
        else settings.context_compaction_reserve_tokens
    )
    ratio = input_ratio if input_ratio is not None else settings.context_input_ratio
    window = int(window_tokens or 0)
    if window <= 0:
        return 0
    return max(1, min(window - max(0, int(reserve)), int(window * ratio)))


def _is_valid_cut(history: list[Any], cut: int) -> bool:
    """判断切点是否落在合法边界：保留区不能以孤立工具结果开头。"""

    return getattr(history[cut], "role", None) != "tool"


def plan_compaction_cut(
    history: list[Any] | None,
    *,
    keep_recent_tokens: int,
    chars_per_token: float | None = None,
) -> int | None:
    """在历史行上选择压缩切点：返回首个保留行的下标，None 表示不值得压缩。

    从最新一行往前累加估算 token，凑够 ``keep_recent_tokens`` 即停；切点不能
    落在 tool 行（否则保留区以孤立工具结果开头，供应商可能直接拒绝该消息
    序列），必要时向前回退到合法边界。全部历史加起来都凑不够保留量时返回
    None，「没有可压缩内容」与「压缩无收益」用同一结论表达。
    """

    rows = list(history or [])
    if not rows:
        return None
    cpt = _resolve_chars_per_token(chars_per_token)
    accumulated = 0
    cut: int | None = None
    for index in range(len(rows) - 1, -1, -1):
        accumulated += max(1, math.ceil(_message_row_chars(rows[index]) / cpt))
        if accumulated >= keep_recent_tokens:
            cut = index
            break
    if cut is None:
        return None
    while cut > 0 and not _is_valid_cut(rows, cut):
        cut -= 1
    if cut <= 0:
        return None
    return cut


def build_compaction_summary_message(compaction: Any | None) -> SystemMessage | None:
    """把一条压缩记录转成注入模型上下文的摘要消息；无摘要返回 None。"""

    summary = getattr(compaction, "summary", None)
    if not isinstance(summary, str) or not summary.strip():
        return None
    return SystemMessage(content=f"{COMPACTION_SUMMARY_TITLE}\n\n{summary.strip()}")


def _split_guardrail_units(
    messages: list[Any],
) -> list[tuple[int, int]]:
    """把历史区段划分为整轮删除单元。

    assistant 工具调用与其紧随的工具结果必须属于同一单元，避免护栏单条
    删除造成孤立工具结果回填模型。
    """

    units: list[tuple[int, int]] = []
    index = 1
    total = len(messages)
    while index < total - 1:
        call_ids = _assistant_tool_call_ids(messages[index])
        if not call_ids:
            units.append((index, index))
            index += 1
            continue
        end = index
        cursor = index + 1
        consumed: set[str] = set()
        while cursor < total:
            if (
                isinstance(messages[cursor], (ToolMessage, ToolOutcome))
                and _tool_result_call_id(messages[cursor]) in call_ids
            ):
                call_id = _tool_result_call_id(messages[cursor])
                if call_id not in consumed:
                    consumed.add(call_id)
                    end = cursor
                    cursor += 1
                    continue
            break
        units.append((index, end))
        index = end + 1
    return units


def _guardrail_protected_starts(
    messages: list[Any],
    units: list[tuple[int, int]],
) -> tuple[set[int], set[int]]:
    """返回护栏不可删除的单元起点，以及快照消息下标。

    所有 SystemMessage（系统提示、工具快照、压缩摘要）所属单元都不可删：
    摘要消息本身就是被压缩历史的全部内容，删掉它等于让模型彻底失忆。
    摘要消息注入后，护栏与压缩都会保留它，直到下一次压缩替换。
    """

    protected: set[int] = {0}
    snapshot_indices: set[int] = set()
    for start, end in units:
        for index in range(start, end + 1):
            message = messages[index]
            if isinstance(message, SystemMessage):
                protected.add(start)
                if str(message.content).startswith(_SNAPSHOT_SECTION_TITLE):
                    snapshot_indices.add(index)
    last_unit_start = None
    for start, end in units:
        if end == len(messages) - 1:
            last_unit_start = start
    if last_unit_start is not None:
        protected.add(last_unit_start)
    return protected, snapshot_indices


def apply_runtime_context_guardrail(
    messages: list[Any],
    *,
    window_tokens: int | None,
    input_ratio: float | None = None,
    chars_per_token: float | None = None,
) -> list[Any]:
    """AgentRuntime 灰度路径的上下文护栏。

    AgentLoop 的上下文包含 LangChain 消息以及内部的 ModelTurn/ToolOutcome。
    legacy 护栏按单条消息裁剪会把工具结果与其 assistant 调用拆散，产生供应商
    拒绝的非法消息序列；因此这里以「整轮」为最小删除单元：系统提示、快照消息、
    压缩摘要和最近一轮（含其工具配对）保留，超预算时整轮丢弃最旧历史。
    """

    if not window_tokens or window_tokens <= 0:
        return messages
    budget_chars = _resolve_guardrail_budget(
        window_tokens,
        input_ratio=input_ratio,
        chars_per_token=chars_per_token,
    )
    original_chars = _messages_chars(messages)
    if original_chars <= budget_chars:
        return messages

    kept = list(messages)
    total = len(kept)
    if total <= 2:
        return kept

    units = _split_guardrail_units(kept)
    protected_starts, snapshot_indices = _guardrail_protected_starts(kept, units)

    dropped_units = 0
    while _messages_chars(kept) > budget_chars:
        removed = False
        for start, end in units:
            if start in protected_starts:
                continue
            del kept[start : end + 1]
            dropped_units += 1
            removed = True
            break
        if not removed:
            break
        units = _split_guardrail_units(kept)
        protected_starts, snapshot_indices = _guardrail_protected_starts(kept, units)

    kept_chars = _messages_chars(kept)
    if kept_chars > budget_chars and snapshot_indices:
        for index in snapshot_indices:
            kept[index].content = _SNAPSHOT_LIMIT_NOTE
            kept_chars = _messages_chars(kept)
            break
    if kept_chars > budget_chars:
        logger.warning(
            "Runtime context guardrail cannot fit budget window_tokens=%s "
            "budget_chars=%s kept_chars=%s; system+current still exceed",
            window_tokens,
            budget_chars,
            kept_chars,
        )
    logger.debug(
        "Runtime context guardrail trimmed window_tokens=%s budget_chars=%s "
        "original_chars=%s kept_chars=%s dropped_units=%s",
        window_tokens,
        budget_chars,
        original_chars,
        kept_chars,
        dropped_units,
    )
    return kept


def _strip_image_parts_from_messages(messages: list[Any]) -> list[Any]:
    """重建消息列表，移除所有 image_url 内容块，保留文本和文档内容。"""
    rebuilt: list[Any] = []
    for message in messages:
        content = getattr(message, "content", None)
        if isinstance(content, list):
            text_parts = [part for part in content if part.get("type") != "image_url"]
            if text_parts:
                message = type(message)(content=text_parts)
        rebuilt.append(message)
    return rebuilt


def classify_tool_type(tool) -> str:
    """按工具来源归类协议展示用的工具类型。"""
    if hasattr(tool, "server_id"):
        return "mcp_tool"
    kind = getattr(tool, "kind", None)
    if kind in {"skill_script", "skill_instruction"}:
        return "skill_tool"
    if kind == "builtin":
        return "builtin_tool"
    return "host_tool"


def _build_tool_event(
    tool,
    call,
    *,
    waiting_status: str | None = None,
) -> dict[str, Any]:
    """构造工具调用事件的基础字段，供流式与非流式执行路径共用。"""
    event = build_runtime_tool_event(tool, call, waiting_status=waiting_status)
    return event


def build_user_content(
    user_message: str,
    image_parts: list[dict] | None = None,
    document_text_parts: list[dict] | None = None,
):
    """仅在存在图片/文档内容时构造多模态内容，保持纯文本模型调用兼容。"""
    if not image_parts and not document_text_parts:
        return user_message
    return [
        {"type": "text", "text": user_message},
        *(document_text_parts or []),
        *(image_parts or []),
    ]


def _is_text_only_image_error(error: Exception) -> bool:
    """识别兼容网关返回的“模型仅支持 text”错误。"""
    text = str(error)
    return "messages.content.type" in text and "text" in text


def _summarize_json(value: Any, *, limit: int) -> str:
    """把工具参数或结果转换为截断后的 JSON/文本摘要，避免超长或敏感内容直接外发。"""
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(
                value, ensure_ascii=False, default=str, separators=(",", ":")
            )
        except (TypeError, ValueError):
            text = str(value)
    return text[:limit]


def _tool_result_summary(outcome) -> str:
    """提取工具结果的展示摘要，空结果返回空字符串。"""
    return (
        _summarize_json(getattr(outcome, "result", None), limit=500)
        if getattr(outcome, "result", None) is not None
        else ""
    )


def _runtime_arguments_summary(tool_event: dict, *, limit: int) -> str | None:
    """灰度 runtime 工具事件没有预生成 input_summary 时的参数摘要回退。

    AgentLoop 只透出结构化 ``arguments``，是否序列化由协议层决定；这里与
    legacy 事件保持同一截断口径，确保工具步骤和快照的参数展示一致。
    """

    arguments = tool_event.get("arguments")
    if arguments is None:
        return None
    return _summarize_json(arguments, limit=limit)


def tool_step_values(tool_event: dict, sequence: int) -> dict:
    """把工具事件转换为 Loop 步骤落库字段。"""
    outcome = tool_event["outcome"]
    outcome_status = getattr(outcome, "status", "succeeded")
    status = normalize_tool_step_status(outcome_status)
    result_detail = _tool_result_summary(outcome)
    input_summary = tool_event.get("input_summary") or _runtime_arguments_summary(
        tool_event, limit=300
    )
    values = {
        "sequence": sequence,
        "step_type": tool_event.get("tool_type", "host_tool"),
        "title": f"调用工具：{tool_event['tool']}",
        "status": status,
        "input_summary": input_summary,
        "output_summary": (
            "等待用户确认"
            if status == "waiting_confirmation"
            else "等待用户选择"
            if status == "waiting_question"
            else "工具调用已取消"
            if status == "cancelled"
            else "工具调用已达到预算限制"
            if status == "budget_exceeded"
            else (
                f"工具执行{'失败' if status == 'failed' else '完成'}"
                + (f"：{result_detail}" if result_detail else "")
            )
        ),
        "tool_name": tool_event["tool"],
        "skill_name": tool_event.get("skill_name"),
        "skill_version": tool_event.get("skill_version"),
        "tool_call_id": str(tool_event.get("tool_call_id", tool_event["tool"])),
        "error": (
            {"code": "tool_failed", "message": "工具执行失败"}
            if status == "failed"
            else {
                "code": status,
                "message": (
                    "工具调用已取消"
                    if status == "cancelled"
                    else "工具调用已达到预算限制"
                ),
            }
            if status in {"cancelled", "budget_exceeded"}
            else None
        ),
    }
    # 工具自带的私有元数据（目前只有委派工具用它回传派生子运行 ID）。
    # 仅在有内容时写入：未使用该通道的工具，落库形状与改造前逐字一致。
    tool_metadata = getattr(outcome, "metadata", None)
    if isinstance(tool_metadata, dict) and tool_metadata:
        values["step_metadata"] = tool_metadata
    return values


def _iter_image_assets(tool_events: list[dict] | None):
    """遍历图片工具结果中的受保护图片资源。"""
    for event in tool_events or []:
        outcome = event.get("outcome")
        result = getattr(outcome, "result", None)
        if not isinstance(result, dict) or result.get("kind") != "image":
            continue
        assets = result.get("assets") or (
            [result["asset"]] if result.get("asset") else []
        )
        for asset in assets:
            if isinstance(asset, dict) and asset.get("asset_id"):
                yield asset


def image_content_blocks(tool_events: list[dict] | None) -> list[dict]:
    """把图片工具结果转换为消息内容块，避免把 base64 写入消息。"""
    blocks: list[dict] = []
    for index, asset in enumerate(_iter_image_assets(tool_events)):
        asset_id = str(asset["asset_id"])
        blocks.append(
            {
                "id": f"image_{asset_id}_{index}",
                "type": "image",
                "status": "completed",
                "asset_id": asset_id,
                "url": asset.get("download_url"),
                "mime_type": asset.get("content_type", "image/png"),
                "size": asset.get("size_bytes"),
                "alt": "图片工具输出",
            }
        )
    return blocks


def custom_content_blocks(tool_events: list[dict] | None) -> list[dict]:
    """把业务工具返回的 custom 结果转换为消息内容块，驱动宿主渲染自定义组件。

    协议约定：块字段统一使用 component_name（snake_case），SDK 按该字段查找
    宿主注册的组件；fallback 必须非空，组件未注册时前端展示兜底文本。
    """
    blocks: list[dict] = []
    for index, event in enumerate(tool_events or []):
        outcome = event.get("outcome")
        result = getattr(outcome, "result", None)
        if not isinstance(result, dict) or result.get("kind") != "custom":
            continue
        component_name = str(result.get("component_name") or "").strip()
        if not component_name:
            continue
        fallback = str(result.get("fallback") or "").strip()[:2_000]
        props = result.get("props") if isinstance(result.get("props"), dict) else {}
        blocks.append(
            {
                "id": f"custom_{component_name}_{index}",
                "type": "custom",
                "status": "completed",
                "component_name": component_name,
                "props": props,
                "fallback": fallback or f"组件 {component_name} 暂不可用",
            }
        )
    return blocks


def rewrite_image_markdown(content: str, tool_events: list[dict] | None) -> str:
    """把模型输出的 Markdown 图片链接中误用的裸 asset_id 改写为 download_url。

    模型可能把 image_read/image_generate 返回的 asset_id 直接当成图片地址，
    前端无法渲染；这里按本轮工具结果做确定性兜底替换，避免依赖模型自觉。
    """
    asset_urls = {
        str(asset["asset_id"]): str(asset["download_url"])
        for asset in _iter_image_assets(tool_events)
        if asset.get("download_url")
    }
    if not asset_urls or not content:
        return content

    def _replace(match: re.Match) -> str:
        url = match.group(2).strip()
        if url in asset_urls:
            return f"![{match.group(1)}]({asset_urls[url]})"
        return match.group(0)

    return re.sub(r"!\[([^\]]*)\]\(\s*([^)\s]+)\s*\)", _replace, content)


def build_agent_error_payload(error: BaseException) -> dict[str, Any]:
    """将模型/Agent 异常转换为可安全展示且可重试判断的错误事件。"""
    if is_context_length_exceeded(error):
        return {
            "code": ErrorCode.CONTEXT_LENGTH_EXCEEDED,
            "message": (
                "对话或本次查询结果超过模型上下文上限，请缩小查询范围或开启新对话"
            ),
            "retryable": False,
            "details": {
                "statusCode": "",
                "error": str(error).strip()[:500] or type(error).__name__,
                "exceptionType": type(error).__name__,
            },
        }
    # 平台侧自带稳定错误码的异常（如对话模型被停用的 chat_model_unavailable）
    # 原样上报，便于客户端区分「配置问题」与「上游故障」：这类问题重试无用。
    stable_code = getattr(error, "error_code", None)
    if isinstance(stable_code, str) and stable_code:
        raw_message = str(error).strip() or type(error).__name__
        return {
            "code": stable_code,
            "message": raw_message[:500],
            "retryable": False,
            "details": {
                "statusCode": str(getattr(error, "status_code", "") or ""),
                "error": raw_message[:500],
                "exceptionType": type(error).__name__,
            },
        }
    raw_message = str(error).strip() or type(error).__name__
    status_code = getattr(error, "status_code", None)
    response = getattr(error, "response", None)
    if status_code is None:
        status_code = getattr(response, "status_code", None)
    if not isinstance(status_code, int):
        match = re.search(r"\b([45]\d{2})\b", raw_message)
        status_code = int(match.group(1)) if match else None

    is_connection_error = isinstance(error, (ConnectionError, TimeoutError)) or any(
        token in raw_message.lower()
        for token in ("connection", "connect", "timeout", "bad gateway", "upstream")
    )
    retryable = is_connection_error or bool(status_code and status_code >= 500)
    if status_code == 502:
        code = ErrorCode.AGENT_UPSTREAM_UNAVAILABLE
        message = "Agent 连接失败（HTTP 502），本轮对话已结束"
    elif status_code and status_code >= 500:
        code = ErrorCode.AGENT_UPSTREAM_UNAVAILABLE
        message = f"Agent 连接失败（HTTP {status_code}），本轮对话已结束"
    elif is_connection_error:
        code = ErrorCode.AGENT_UPSTREAM_UNAVAILABLE
        message = "Agent 连接失败，本轮对话已结束"
    else:
        code = ErrorCode.AGENT_REQUEST_FAILED
        message = "Agent 请求失败，本轮对话已结束"
    return {
        "code": code,
        "message": message,
        "retryable": retryable,
        "details": {
            "statusCode": str(status_code) if status_code else "",
            "error": raw_message[:500],
            "exceptionType": type(error).__name__,
        },
    }


@dataclass
class GraphResult:
    """
    对话图执行结果

    封装一次对话交互的完整输出结果，包含模型回复内容、引用信息、
    工具调用事件、Token 用量统计等数据。

    Attributes:
        content: 模型生成的文本回复内容
        citations: 本次回复涉及的知识库引用列表
        knowledge_grounded: 回复是否基于知识库知识增强
        pending_confirmation_id: 挂起的确认请求 ID（当工具调用需要用户确认时）
        pending_context: 等待确认那一刻的消息快照（活的 adapter 层对象），
            仅用于落运行检查点，不参与对外序列化
        tool_events: 工具调用事件列表，记录每次工具调用的结果
        usage: Token 用量统计（包含 prompt_tokens、completion_tokens、total_tokens）
        loop_id: 循环 ID（多轮对话场景下用于标识对话轮次）
    """

    content: str
    citations: list[dict[str, Any]]
    knowledge_grounded: bool
    thinking_text: str | None = None
    pending_confirmation_id: int | None = None
    pending_context: list[Any] | None = None
    tool_events: list[dict[str, Any]] | None = None
    usage: dict[str, int] | None = None
    loop_id: int | None = None
    content_blocks: list[dict] = field(default_factory=list)


def extract_token_usage(message: Any) -> dict[str, int] | None:
    """
    从模型响应消息中提取 Token 使用量

    兼容不同版本的 LangChain/OpenAI 接口，从消息对象中解析出
    prompt_tokens、completion_tokens、total_tokens 三个指标。

    提取优先级：
        1. 优先从 message.usage_metadata 获取
        2. 其次从 message.response_metadata.token_usage 获取
        3. 最后从 message.response_metadata.usage 获取

    Args:
        message: LangChain 的 AIMessage 对象，包含模型响应元数据

    Returns:
        包含 token 用量统计的字典，格式为：
        {
            "prompt_tokens": int,       # 输入 token 数
            "completion_tokens": int,   # 输出 token 数
            "total_tokens": int         # 总 token 数
        }
        若无法提取或数据异常则返回 None
    """
    usage = getattr(message, "usage_metadata", None) or {}
    if not usage:
        response_metadata = getattr(message, "response_metadata", None) or {}
        usage = (
            response_metadata.get("token_usage") or response_metadata.get("usage") or {}
        )
    values = {
        "prompt_tokens": usage.get("prompt_tokens", usage.get("input_tokens")),
        "completion_tokens": usage.get("completion_tokens", usage.get("output_tokens")),
        "total_tokens": usage.get("total_tokens"),
    }
    if any(not isinstance(value, int) or value < 0 for value in values.values()):
        return None
    # 缓存计数与三项 token 同一口径收敛：明细卡的「缓存命中/缓存读取」依赖它，
    # provider 没报缓存时不产出该键。
    values.update(normalize_cache_tokens(usage))
    return values


def merge_token_usage(
    current: dict[str, int] | None, incoming: dict[str, int] | None
) -> dict[str, int] | None:
    """
    合并两次 Token 使用量统计

    用于累积多次模型调用的 Token 消耗，确保最终统计反映总用量。
    支持 None 值的容错处理：当其中一方为 None 时直接返回另一方。

    Args:
        current: 当前已累积的 Token 使用量统计
        incoming: 新一次调用的 Token 使用量统计

    Returns:
        合并后的 Token 使用量统计字典，各字段对应相加。
        若两者均为 None，则返回 None。
    """
    # 字段集取两侧并集：缓存计数只在部分轮次出现，逐轮累加时缺失一侧按 0 计。
    return merge_usage(current, incoming)


async def _apply_delegation_policy(
    builtin_tools: list[Any],
    *,
    agent_repo,
    platform_id: int,
    agent_id: int,
    allow_delegation: bool,
) -> list[Any]:
    """按委派策略裁剪内置工具清单，并把可派智能体清单注入委派工具的描述。

    两条规则都只在这里落地：

    1. ``allow_delegation=False``（子运行）时直接摘掉委派工具——深度恒为 1 靠的
       是"工具根本不在清单里"，而不是运行期再判断一次；
    2. 允许委派且该 Agent 确实绑定了委派工具时，把静态工具定义换成一份**带可派
       智能体清单**的版本。清单口径来自 ``list_delegatable_agents``：该 Agent 配了
       子智能体绑定就只列绑定的那些，没配则回退全平台已发布（排除自己）。静态
       ``@business_tool`` 的 description 在导入期就固定，无法按平台/绑定变化，
       只能在组装运行时上下文这一刻替换。
    """

    from dataclasses import replace

    from app.core.config import get_settings
    from app.modules.tools.business.delegate_tasks import (
        DELEGATE_TASKS_TOOL_NAME,
        build_agent_catalog_description,
    )

    def _is_delegate(tool: Any) -> bool:
        return getattr(tool, "name", None) == DELEGATE_TASKS_TOOL_NAME

    if not any(_is_delegate(tool) for tool in builtin_tools):
        return builtin_tools
    if not allow_delegation:
        return [tool for tool in builtin_tools if not _is_delegate(tool)]

    try:
        agents = await agent_repo.list_delegatable_agents(
            platform_id,
            agent_id,
            limit=get_settings().delegation_max_agents_in_prompt,
        )
    except Exception:
        # 清单只是给模型的提示，查库失败不该让整轮对话失败：退化成空清单，
        # 委派工具仍可用（参数校验会给出明确拒绝）。
        logger.warning(
            "Delegatable agent catalog query failed platform_id=%s",
            platform_id,
            exc_info=True,
        )
        agents = []
    catalog = [
        (
            getattr(agent, "slug", "") or "",
            getattr(agent, "name", None) or getattr(agent, "slug", "") or "",
        )
        for agent in agents
    ]
    return [
        (
            replace(
                tool,
                description=build_agent_catalog_description(
                    getattr(tool, "description", "") or "", catalog
                ),
            )
            if _is_delegate(tool)
            else tool
        )
        for tool in builtin_tools
    ]


async def load_runtime_context(
    agent_repo,
    knowledge_repo,
    skill_repo,
    mcp_repo,
    builtin_tool_repo=None,
    *,
    agent_id: int,
    platform_id: int,
    allow_delegation: bool = True,
    platform_tools_only: bool = False,
) -> RuntimeContext:
    """
    加载指定 Agent 的运行时上下文

    从各个仓库（Repository）中查询并组装 Agent 运行所需的完整配置，
    包括 Agent 定义、版本、知识库、技能绑定、MCP 工具等。

    加载顺序：
        1. 查询已发布的 Agent 及其默认版本
        2. 加载已启用的技能绑定（按 sort_order 排序）
        3. 加载已启用的知识库
        4. 加载已启用的 MCP 工具
        5. 构建技能脚本工具（skill_script_tools）
        6. 组装为 RuntimeContext 返回

    Args:
        agent_repo: Agent 仓库实例，用于查询 Agent 定义
        knowledge_repo: 知识库仓库实例，用于查询关联的知识库
        skill_repo: 技能仓库实例，用于查询技能绑定关系
        mcp_repo: MCP 仓库实例，用于查询关联的 MCP 工具
        agent_id: Agent 唯一标识
        platform_id: 平台唯一标识
        allow_delegation: 是否允许本 Agent 使用委派工具。子运行固定传 False：
            子运行不允许再派生（深度恒为 1），且它的工具清单里绝不能出现
            ``delegate_tasks``——这条闸必须落在代码里，不能靠"用户别这么配"。
            为 True 且该 Agent 确实绑定了委派工具时，工具描述会被替换成一份
            **带本平台可派智能体清单**的版本（静态工具定义无法按平台变化）。

    Returns:
        RuntimeContext: 组装好的运行时上下文对象

    Raises:
        LookupError: 当找不到已发布的 Agent 或 Agent 无默认版本时
    """
    # 查询已发布的 Agent 及其默认版本
    agent = await agent_repo.get_published_agent(agent_id, platform_id)
    if agent is None or agent.default_version is None:
        raise LookupError("published agent not found")

    # 加载技能绑定并按排序顺序排列
    bindings = sorted(
        await skill_repo.list_enabled_for_agent(agent_id, platform_id),
        key=lambda item: item.sort_order,
    )

    # 加载知识库列表
    knowledge_bases = await knowledge_repo.list_enabled_for_agent(agent_id, platform_id)

    # 加载 MCP 工具列表
    # 委派产生的子运行会传 platform_tools_only=True：MCP 工具默认 side_effect
    # 为 "external"，而子运行没有任何渠道把确认弹给人，只能静默批准或不可用，
    # 因此整类剔除（宿主工具本来就不在这条无人值守链路的清单里）。
    mcp_tools = (
        []
        if platform_tools_only
        else await mcp_repo.list_enabled_tools_for_agent(agent_id, platform_id)
    )
    builtin_tools = (
        await builtin_tool_repo.list_enabled_tools_for_agent(agent_id, platform_id)
        if builtin_tool_repo is not None
        else []
    )
    builtin_tools = await _apply_delegation_policy(
        builtin_tools,
        agent_repo=agent_repo,
        platform_id=platform_id,
        agent_id=agent_id,
        allow_delegation=allow_delegation,
    )

    # 构建技能脚本工具（将技能绑定转换为可调用的工具对象）
    skill_script_tools = build_skill_script_tools(bindings)
    skill_instruction_tool = build_skill_instruction_tool(bindings)
    skill_usages = []
    for binding in bindings:
        skill = binding.skill
        package = getattr(skill, "package", None)
        manifest = getattr(package, "manifest", None) or {}
        skill_usages.append(
            {
                "name": getattr(skill, "name", None)
                or getattr(skill, "slug", None)
                or f"Skill {getattr(skill, 'id', '')}",
                "slug": getattr(skill, "slug", None),
                "version": (
                    manifest.get("version") if isinstance(manifest, dict) else None
                ),
                "has_script_tool": any(
                    tool.skill_id == getattr(skill, "id", None)
                    for tool in skill_script_tools
                ),
            }
        )

    logger.info(
        "Loaded runtime context agent_id=%s platform_id=%s knowledge_bases=%s skill_count=%s script_tool_count=%s mcp_tool_count=%s builtin_tool_count=%s",
        agent_id,
        platform_id,
        [getattr(base, "id", None) for base in knowledge_bases],
        len(bindings),
        len(skill_script_tools),
        len(mcp_tools),
        len(builtin_tools),
    )

    # 组装运行时上下文
    return RuntimeContext(
        agent=agent,
        version=agent.default_version,
        knowledge_bases=knowledge_bases,
        skill_instructions=[
            build_runtime_skill_metadata(item.skill) for item in bindings
        ],
        skill_usages=skill_usages,
        skill_script_tools=skill_script_tools,
        skill_instruction_tool=skill_instruction_tool,
        mcp_tools=mcp_tools,
        builtin_tools=builtin_tools,
    )


_RUNTIME_METADATA_CAPABILITY_KEYS = ("image", "native_file", "text_retrieval")


def build_runtime_metadata_block(
    version, *, chat_model_name: str | None = None
) -> str | None:
    """构建注入系统提示词的运行时信息段（字段白名单）。

    只披露模型名、Agent 版本、服务版本、SDK 最低版本、温度与能力摘要；
    绝不包含 api_key / model_base_url 等敏感配置。模型名来自调用方传入的
    ``chat_model_name``（平台模型注册表的解析结果），版本行不再承载模型信息。
    字段缺失时跳过对应行，全部缺失返回 None（调用方不追加段落）。
    """
    settings = get_settings()
    lines = []
    model_name = chat_model_name
    if model_name:
        lines.append(f"- 模型：{model_name}")
    version_no = getattr(version, "version", None)
    if version_no is not None:
        lines.append(f"- Agent 版本：v{version_no}")
    if settings.app_version:
        lines.append(f"- 服务版本：{settings.app_version}")
    if settings.sdk_minimum_version:
        lines.append(f"- SDK 最低版本：{settings.sdk_minimum_version}")
    temperature = getattr(version, "temperature", None)
    if temperature is not None:
        lines.append(f"- 温度：{temperature}")
    capabilities = getattr(version, "capabilities", None) or {}
    capability_names = [
        key for key in _RUNTIME_METADATA_CAPABILITY_KEYS if capabilities.get(key)
    ]
    if capability_names:
        lines.append(f"- 能力：{'/'.join(capability_names)}")
    if not lines:
        return None
    return (
        "【运行时信息】\n"
        + "\n".join(lines)
        + "\n以上为当前会话实际运行配置；涉及用量、连接与配额等信息，请调用 get_runtime_info 工具获取。"
    )


def build_system_prompt(
    version,
    skill_instructions: list[str],
    citations: list[dict],
    host_tools: list[Any] | None = None,
    caller_system_prompt: str | None = None,
    *,
    chat_model_name: str | None = None,
    memory_index: str | None = None,
    tool_catalog: str | None = None,
    capability_tool_names: set[str] | None = None,
):
    """
    构建系统提示词，将多个上下文片段组合为完整的系统提示

    提示词按以下顺序拼接（优先级从高到低）：
        1. Agent 版本自带的 system_prompt（基础角色定义）
        2. 调用方补充提示词（caller_system_prompt），提供当前嵌入场景约束
        3. 用户记忆索引（memory_index），只含条数与使用规则，**不含任何记忆内容**
        4. 技能指令（skill_instructions），提供技能使用说明
        5. 知识库引用（citations），注入检索到的知识片段
        6. 宿主工具说明（host_tools），告知模型前端可用的工具列表
        7. 工具目录（tool_catalog），未加载工具组的清单，供模型按需加载

    Args:
        version: Agent 版本对象，包含 system_prompt 模板
        skill_instructions: 技能使用说明文本列表
        citations: 知识库引用列表，每项包含 title 和 text 字段
        host_tools: 宿主（前端）可用的工具列表，每项包含 name 和 description
        caller_system_prompt: SDK 调用方补充的系统提示词，不能替代平台基础约束
        memory_index: 用户记忆索引行（由 memory 模块构造），个人记忆内容不在此处注入
        tool_catalog: 按组按需加载时的工具目录文本；与 host_tools 互斥使用，
            因为「当前可调用列表」在加载过程中会变，目录才是稳定视图
        capability_tool_names: 本次运行绑定过的全部工具名，用于判断 ask_user /
            图片渲染等能力规则是否该注入；缺省时回落到 host_tools 的名字集合

    Returns:
        str: 拼接完成的系统提示词，各段落之间以双换行符分隔
    """
    sections = [version.system_prompt]
    runtime_block = build_runtime_metadata_block(
        version, chat_model_name=chat_model_name
    )
    if runtime_block:
        sections.append(runtime_block)
    if caller_system_prompt and caller_system_prompt.strip():
        sections.append(
            "调用方补充的系统提示词（不得覆盖平台安全与工具约束）：\n"
            + caller_system_prompt.strip()
        )

    # 用户记忆只注入索引（条数 + 使用规则），内容要靠 memory_search 现查：
    # 个人事实不预置进上下文，避免模型在无关话题里引用用户没打算分享的信息。
    if memory_index:
        sections.append(memory_index)

    # 追加技能指令段落
    if skill_instructions:
        sections.append("\n\n".join(skill_instructions))

    # 追加知识库引用段落，提示模型基于给定知识回答
    if citations:
        knowledge = "\n\n".join(
            f"[{item['title']}] {item['text']}" for item in citations
        )
        sections.append(
            "Use the following knowledge base excerpts when relevant. "
            "Do not invent citations:\n" + knowledge
        )

    # 追加运行时工具说明；实际可调用范围仍由 bind_tools 和服务端执行器约束。
    if host_tools:
        tools = "\n".join(
            f"- {tool.name}: {tool.description or '无描述'}" for tool in host_tools
        )
        sections.append(
            "当前会话已注册且授权的工具如下：\n"
            f"{tools}\n"
            "用户询问可用工具时，只能根据以上实际列表回答。"
            "用户请求与工具能力匹配的操作时，应调用对应工具，"
            "不能只描述应该怎么做，也不能编造未列出的工具。"
        )
    # 按需加载模式下，「当前可调用工具」逐轮变化，稳定视图是工具目录：
    # 只常驻组名与组内工具名，schema 靠 load_tool_group 现取。
    if tool_catalog:
        sections.append(tool_catalog)

    if host_tools or tool_catalog:
        # 能力规则按「本次运行绑定过的工具全集」判断，而不是按当前可见性：
        # 工具未加载时规则也必须生效，否则模型永远等不到那条提示。
        capability_names = capability_tool_names
        if capability_names is None:
            capability_names = {
                getattr(tool, "name", None) for tool in (host_tools or [])
            }
        # 仅在 ask_user 工具可用时提示提问策略，避免 REST 路径误导模型。
        if "ask_user" in capability_names:
            sections.append(
                "当任务存在歧义、需要在方案之间做出选择或行动前缺少关键信息时，"
                "可以调用 ask_user 工具向用户提问。问题应一次一个，提供 2-4 个选项；"
                "只有确实需要用户决策时才提问，不要用提问替代普通的信息回复。"
                "用户回答后，根据答案继续执行原任务。"
            )
        # 图片工具可用时补充图片渲染规则：前端只能按 download_url 渲染图片。
        if capability_names & {"image_read", "image_generate"}:
            sections.append(
                "图片展示规则：image_read/image_generate 等工具返回的图片资源，"
                "回复中如需展示图片，必须使用结果中的 download_url 字段作为 "
                "Markdown 图片地址，格式为 ![图片描述](/api/v1/assets/{asset_id})；"
                "严禁把 asset_id 直接当作图片地址。"
            )

    # 使用双换行符拼接所有非空段落
    prompt = "\n\n".join(section for section in sections if section)
    logger.info(
        "Built system prompt sections=%s skill_count=%s citation_count=%s host_tool_count=%s "
        "tool_catalog_chars=%s prompt_chars=%s",
        len(sections),
        len(skill_instructions),
        len(citations),
        len(host_tools or []),
        len(tool_catalog or ""),
        len(prompt),
    )
    return prompt
