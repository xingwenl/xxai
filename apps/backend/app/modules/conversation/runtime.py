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
    用户消息 → 构建系统提示词 → 绑定工具 → 调用模型 → 处理工具调用循环 → 返回结果

数据流向：
    load_runtime_context() → build_system_prompt() → stream_graph()/run_graph() → GraphResult
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import re
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from app.core.config import get_settings
from app.core.logging import get_logger
from app.modules.skill.services import build_runtime_skill_metadata
from app.modules.skill_runner.tools import (
    build_skill_instruction_tool,
    build_skill_script_tools,
)
from app.modules.conversation.schemas import RuntimeContext
from app.modules.agent_runtime.contracts import ToolOutcome, ToolRoundState
from app.modules.agent_runtime.tool_loop import ToolRoundExecutor
from app.modules.agent_runtime.adapters import tool_outcome_from_legacy
from app.modules.agent_runtime.langchain_adapter import build_langchain_messages
from app.modules.agent_runtime.tool_events import (
    build_tool_event as build_runtime_tool_event,
    tool_result_content,
    normalize_tool_step_status,
)
from app.modules.agent_runtime.model_stream import ModelStreamAdapter
from app.modules.agent_runtime.adapters import tool_call_from_legacy
from app.modules.agent_runtime.message_text import extract_thinking_text

logger = get_logger(__name__)

# 工具结果快照：落库键、注入文本约定与上下文护栏相关常量
SNAPSHOT_METADATA_KEY = "tool_snapshots"
_SNAPSHOT_SECTION_TITLE = "以下为此前工具查询到的数据快照（数据截至各自查询时间）："
_SNAPSHOT_INJECT_TAIL = (
    "回答与快照同范围的问题时可直接使用快照；"
    "用户要求最新数据、变更时间/查询条件或快照未覆盖时，应重新调用工具查询。"
)
_SNAPSHOT_LIMIT_NOTE = "此前工具查询快照因上下文限制未保留，需要时可重新查询最新数据。"

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

_MAX_ITERATIONS_WRAPUP_PROMPT = (
    "你已达到本次任务的最大执行轮数，请停止调用任何工具，"
    "直接基于已有信息给出最终回答；如果信息不足，请明确说明。"
)
_CONTEXT_DEGRADE_NOTE = (
    "此前对话与工具查询结果因超过模型上下文上限未纳入本次计算，需要时可重新查询。"
)


def _resolve_max_iterations(max_iterations: int | None) -> int | None:
    """解析 Agent 循环迭代上限；0 或负值视为不设限。"""
    value = (
        max_iterations
        if max_iterations is not None
        else get_settings().agent_max_iterations
    )
    return value if value and value > 0 else None


_PAGE_TOOL_BUDGET_EXCEEDED_MESSAGE = (
    "已达到页面工具使用限制（次数/时长），本次执行已停止。"
)


def _is_budget_exceeded_outcome(outcome) -> bool:
    """判断工具结果是否表示页面工具预算耗尽（page_tool_budget_exceeded）。"""
    result = getattr(outcome, "result", None)
    if not isinstance(result, dict):
        return False
    error = result.get("error")
    error_code = error.get("code") if isinstance(error, dict) else error
    values = {
        value
        for value in (error_code, result.get("code"), result.get("message"))
        if isinstance(value, str)
    }
    return "page_tool_budget_exceeded" in values


def build_history_messages(
    history: list[Any] | None = None,
    attachment_parts: dict[str, list[dict]] | None = None,
) -> list[Any]:
    """将持久化消息转换为模型消息，忽略不支持的角色和空内容。

    ``attachment_parts`` 按 asset_id 提供历史附件内容块，带附件的
    用户消息恢复为多模态内容，保证后续轮次仍能读取历史附件。
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)
    history_window = settings.conversation_history_window_seconds
    converted = []
    for item in history or []:
        content = getattr(item, "content", "")
        if not isinstance(content, str) or not content.strip():
            continue
        role = getattr(item, "role", None)
        if role in ("user", "assistant", "tool") and not _message_within_window(
            item, now, history_window
        ):
            # 快照保留期大于历史窗口时，超窗消息仅贡献快照、不再回放正文。
            continue
        if role == "user":
            parts = _history_attachment_parts(item, attachment_parts)
            message_content = (
                [{"type": "text", "text": content}, *parts] if parts else content
            )
            converted.append(HumanMessage(content=message_content))
        elif role == "assistant":
            converted.append(AIMessage(content=content))
        elif role == "tool":
            converted.append(
                ToolMessage(
                    content=content,
                    tool_call_id=getattr(item, "tool_call_id", None) or "history-tool",
                )
            )
    # 历史末尾注入工具快照 SystemMessage（当前用户消息之前），无快照时零注入。
    snapshot_message = build_snapshot_injection_message(history, now=now)
    if snapshot_message is not None:
        converted.append(snapshot_message)
    return converted


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
            (
                key
                for key, value in result.items()
                if isinstance(value, list) and value
            ),
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


def attach_tool_snapshots(
    metadata: dict | None, snapshots: list[dict]
) -> dict:
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
                if parsed is not None and (
                    now - parsed
                ).total_seconds() > retention_seconds:
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
    """解析版本模型的上下文窗口：显式列值 > 内置模型名映射 > 未命中返回 None。"""
    explicit = getattr(version, "context_window_tokens", None)
    if explicit is not None and int(explicit) > 0:
        return int(explicit)
    name = (model_name or getattr(version, "model_name", None) or "").strip()
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
    if isinstance(code, str) and "context_length_exceeded" in code.lower():
        return True
    raw = str(error).lower()
    return any(
        marker in raw
        for marker in (
            "maximum context length",
            "context_length_exceeded",
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


def make_multimodal_degrade_recoverer(
    system_prompt: str, user_message: str
):
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


def _snapshot_message_index(messages: list[Any]) -> int | None:
    """定位历史末尾的快照注入消息；不存在时返回 None。"""
    if len(messages) < 3:
        return None
    candidate = messages[-2]
    if isinstance(candidate, SystemMessage) and str(candidate.content).startswith(
        _SNAPSHOT_SECTION_TITLE
    ):
        return len(messages) - 2
    return None


def apply_context_guardrail(
    messages: list[Any],
    *,
    window_tokens: int | None,
    input_ratio: float | None = None,
    chars_per_token: float | None = None,
) -> list[Any]:
    """上下文预算护栏：超预算时按「旧历史 → 快照」顺序裁剪并留下提示。

    系统提示与当前用户消息永不裁剪；快照被裁时保留一条
    「因上下文限制未保留」提示文本，引导模型在需要时重新查询。
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
        logger.debug(
            "Context guardrail ok window_tokens=%s budget_chars=%s messages_chars=%s",
            window_tokens,
            budget_chars,
            original_chars,
        )
        return messages
    dropped_history = 0
    snapshot_reduced = False
    while _messages_chars(messages) > budget_chars:
        snapshot_index = _snapshot_message_index(messages)
        removed = False
        for index in range(1, len(messages) - 1):
            if index == snapshot_index:
                continue
            del messages[index]
            dropped_history += 1
            removed = True
            break
        if removed:
            continue
        if snapshot_index is None:
            break
        if str(messages[snapshot_index].content) == _SNAPSHOT_LIMIT_NOTE:
            del messages[snapshot_index]
        else:
            messages[snapshot_index].content = _SNAPSHOT_LIMIT_NOTE
            snapshot_reduced = True
    kept_chars = _messages_chars(messages)
    if kept_chars > budget_chars:
        logger.warning(
            "Context guardrail cannot fit budget window_tokens=%s budget_chars=%s "
            "kept_chars=%s; system+current still exceed, degraded retry will apply",
            window_tokens,
            budget_chars,
            kept_chars,
        )
    logger.debug(
        "Context guardrail trimmed window_tokens=%s budget_chars=%s original_chars=%s "
        "kept_chars=%s dropped_history=%s snapshot_reduced=%s",
        window_tokens,
        budget_chars,
        original_chars,
        kept_chars,
        dropped_history,
        snapshot_reduced,
    )
    return messages


def _resolve_guardrail_budget(
    window_tokens: int,
    *,
    input_ratio: float | None,
    chars_per_token: float | None,
) -> int:
    """按上下文窗口与估算比例计算护栏允许的字符预算。"""

    settings = get_settings()
    ratio = (
        input_ratio
        if input_ratio is not None
        else settings.context_input_ratio
    )
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
        call_id = call.get("id") if isinstance(call, dict) else getattr(call, "id", None)
        if call_id:
            ids.add(str(call_id))
    return ids


def _tool_result_call_id(message: Any) -> str | None:
    """返回工具结果关联的 assistant 调用 ID，未知时返回 None。"""

    if isinstance(message, ToolOutcome):
        return message.call_id or message.metadata.get("call_id")
    return getattr(message, "tool_call_id", None)


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
            if isinstance(
                messages[cursor], (ToolMessage, ToolOutcome)
            ) and _tool_result_call_id(messages[cursor]) in call_ids:
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
    拒绝的非法消息序列；因此这里以「整轮」为最小删除单元：系统提示、快照消息
    和最近一轮（含其工具配对）保留，超预算时整轮丢弃最旧历史。
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
    protected_starts = {0}
    snapshot_indices: set[int] = set()
    for start, end in units:
        for index in range(start, end + 1):
            message = kept[index]
            if isinstance(message, SystemMessage) and str(message.content).startswith(
                _SNAPSHOT_SECTION_TITLE
            ):
                snapshot_indices.add(index)
    last_unit_start = None
    for start, end in units:
        if end == total - 1:
            last_unit_start = start
    if last_unit_start is not None:
        protected_starts.add(last_unit_start)

    dropped_units = 0
    while _messages_chars(kept) > budget_chars:
        removed = False
        for start, end in units:
            if start in protected_starts:
                continue
            if any(index in snapshot_indices for index in range(start, end + 1)):
                continue
            del kept[start : end + 1]
            dropped_units += 1
            removed = True
            break
        if not removed:
            break
        units = _split_guardrail_units(kept)
        total = len(kept)
        protected_starts = {0}
        snapshot_indices = set()
        for start, end in units:
            for index in range(start, end + 1):
                message = kept[index]
                if isinstance(message, SystemMessage) and str(
                    message.content
                ).startswith(_SNAPSHOT_SECTION_TITLE):
                    snapshot_indices.add(index)
        last_unit_start = None
        for start, end in units:
            if end == total - 1:
                last_unit_start = start
        if last_unit_start is not None:
            protected_starts.add(last_unit_start)

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


def _tool_result_content(tool, outcome) -> str:
    """兼容旧调用方，实际规则由 agent_runtime 统一维护。"""
    return tool_result_content(tool, outcome)


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


def _content_text(content: Any) -> str:
    """把模型 chunk 内容统一为纯文本，兼容字符串和多模态列表。"""
    if isinstance(content, str):
        return content
    return "".join(
        item.get("text", "") if isinstance(item, dict) else str(item)
        for item in content
    )


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


async def _astream_with_image_fallback(
    model, messages: list[Any], user_message: str, image_parts
):
    """视觉输入被上游拒绝时，自动以文字重试一次。"""
    try:
        async for chunk in model.astream(messages):
            yield chunk
    except Exception as error:
        if not image_parts or not _is_text_only_image_error(error):
            raise
        logger.warning("Model does not support image input; retrying text-only request")
        fallback_messages = _strip_image_parts_from_messages(messages)
        if not fallback_messages:
            fallback_messages = [HumanMessage(content=user_message)]
        async for chunk in model.astream(fallback_messages):
            yield chunk


def _thinking_text(chunk: Any) -> str:
    """从模型流式块中提取思考/推理文本，与正文严格分离。

    提取规则集中在 ``agent_runtime.thinking``，legacy 与 runtime 灰度路径
    必须使用同一份兼容实现，避免推理模型在两条路径上展示不同的思考内容。
    """
    return extract_thinking_text(chunk)


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
    return {
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


def build_step_payload(
    step,
    *,
    loop_run_id,
    sequence: int | None = None,
    citation_refs: list | None = None,
    with_input: bool = False,
    with_output: bool = False,
    with_tool: bool = False,
    with_skill: bool = False,
    with_thinking: bool = False,
) -> dict[str, Any]:
    """构造 agent_step_* 事件的 payload，统一协议字段命名。

    ``with_thinking`` 控制 thinkingText 是否总是输出：网关路径默认仅在
    存在思考文本时携带该字段；REST 流式路径保持 always-present 语义。
    """
    payload = {
        "loopRunId": str(loop_run_id),
        "stepId": str(step.id),
        "sequence": step.sequence if sequence is None else sequence,
        "stepType": step.step_type,
        "title": step.title,
        "status": step.status,
    }
    if with_input:
        payload["inputSummary"] = step.input_summary
    if with_output:
        payload["outputSummary"] = step.output_summary
    thinking = getattr(step, "thinking_text", None)
    if with_thinking or thinking:
        payload["thinkingText"] = thinking
    if with_tool:
        payload["toolName"] = step.tool_name
    if with_skill:
        payload["skillName"] = step.skill_name
        payload["skillVersion"] = step.skill_version
    if citation_refs is not None:
        payload["citationRefs"] = citation_refs
    return payload


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
            "code": "context_length_exceeded",
            "message": (
                "对话或本次查询结果超过模型上下文上限，"
                "请缩小查询范围或开启新对话"
            ),
            "retryable": False,
            "details": {
                "statusCode": "",
                "error": str(error).strip()[:500] or type(error).__name__,
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
        code = "agent_upstream_unavailable"
        message = "Agent 连接失败（HTTP 502），本轮对话已结束"
    elif status_code and status_code >= 500:
        code = "agent_upstream_unavailable"
        message = f"Agent 连接失败（HTTP {status_code}），本轮对话已结束"
    elif is_connection_error:
        code = "agent_upstream_unavailable"
        message = "Agent 连接失败，本轮对话已结束"
    else:
        code = "agent_request_failed"
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
        tool_events: 工具调用事件列表，记录每次工具调用的结果
        usage: Token 用量统计（包含 prompt_tokens、completion_tokens、total_tokens）
        loop_id: 循环 ID（多轮对话场景下用于标识对话轮次）
    """

    content: str
    citations: list[dict[str, Any]]
    knowledge_grounded: bool
    thinking_text: str | None = None
    pending_confirmation_id: int | None = None
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
    if incoming is None:
        return current
    if current is None:
        return dict(incoming)
    return {
        key: current[key] + incoming[key]
        for key in ("prompt_tokens", "completion_tokens", "total_tokens")
    }


def format_sse_event(event: dict[str, Any]) -> str:
    """
    将事件字典格式化为 Server-Sent Events (SSE) 字符串

    SSE 格式为：
        event: <事件类型>\\n
        data: <JSON 数据>\\n\\n

    Args:
        event: 事件字典，必须包含 "type" 键，其他键将序列化为 JSON data

    Returns:
        符合 SSE 规范的字符串，使用 UTF-8 编码和紧凑 JSON 格式
    """
    return (
        f"event: {event['type']}\n"
        f"data: {json.dumps(event, ensure_ascii=False, separators=(',', ':'))}\n\n"
    )


@dataclass
class _AstreamCollectState:
    """单轮模型原生流的累积状态：拼接后的响应消息与 token 用量。"""

    response: Any = None
    usage: dict[str, int] | None = None


_ToolRoundResult = ToolRoundState


@dataclass
class _FinishResult:
    """工具循环收尾产出的最终 GraphResult。"""

    graph_result: GraphResult | None = None


def _bind_tools_schema(model, tools: list[Any] | None):
    """将工具按统一 function-calling schema 绑定到模型；不支持时原样返回。"""
    if not tools or not hasattr(model, "bind_tools"):
        return model
    return model.bind_tools(
        [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": tool.input_schema or {"type": "object"},
                },
            }
            for tool in tools
        ]
    )


def _build_initial_messages(
    *,
    system_prompt: str,
    user_message: str,
    history: list[Any] | None,
    image_parts: list[dict] | None,
    document_text_parts: list[dict] | None,
    history_attachment_parts: dict[str, list[dict]] | None,
) -> list[Any]:
    """组装对话初始消息列表：系统提示 → 历史消息 → 当前用户消息。"""
    return build_langchain_messages(
        system_prompt=system_prompt,
        history=build_history_messages(
            history, attachment_parts=history_attachment_parts
        ),
        user_message=user_message,
        image_parts=image_parts,
        document_text_parts=document_text_parts,
    )


async def _astream_collect(
    model,
    messages: list[Any],
    *,
    user_message: str,
    image_parts: list[dict] | None,
    content_parts: list[str],
    thinking_parts: list[str],
    state: _AstreamCollectState,
):
    """
    消费模型原生流，逐 chunk 累积内容并转发增量事件

    产出 ``thinking_delta`` / ``message_delta`` 事件，供调用方实时转发；
    正文与思考文本追加到 content_parts / thinking_parts，拼接后的响应消息
    与 token 用量写入 state，供主循环跨轮继续累积。

    Args:
        model: 支持 astream 的聊天模型（已绑定工具）
        messages: 当前对话消息列表
        user_message: 原始用户消息，用于图片输入被拒后的纯文本重试
        image_parts: 图片输入块，用于判断是否需要降级重试
        content_parts: 正文增量累积列表
        thinking_parts: 思考文本累积列表
        state: 本轮累积状态（response / usage）
    """
    def source():
        return _astream_with_image_fallback(
            model, messages, user_message, image_parts
        )

    async for chunk in ModelStreamAdapter.stream(source):
        state.usage = merge_token_usage(state.usage, extract_token_usage(chunk))
        if state.response is None:
            state.response = chunk
        else:
            try:
                state.response = state.response + chunk
            except TypeError:
                # 部分纯文本模型/测试桩的 chunk 不支持拼接，保留首个 chunk 即可；
                # 此类 chunk 不携带 tool_calls，不影响工具循环判断。
                pass

        thinking = _thinking_text(chunk)
        if thinking:
            thinking_parts.append(thinking)
            yield {"type": "thinking_delta", "content": thinking}

        content = _content_text(chunk.content)
        if content:
            content_parts.append(content)
            yield {"type": "message_delta", "content": content}


async def _execute_tool_round(
    *,
    tools: list[Any],
    tool_calls: list[dict],
    invoke_tool_fn,
    messages: list[Any],
    content_parts: list[str],
    thinking_parts: list[str],
    usage: dict[str, int] | None,
    tool_events: list[dict[str, Any]],
    citations: list[dict[str, Any]],
    result: _ToolRoundResult,
):
    """
    执行一轮工具调用，产出 tool_started / tool_completed 事件

    流式与非流式路径共用：调用方用 async for 逐事件转发
    （流式原样 yield，非流式转交 on_event 回调）。
    轮次结果写入 result：
    - executed_tool：本轮是否至少执行了一个工具；
    - budget_exceeded：工具结果触发页面工具预算上限；
    - confirmation_result：工具要求用户确认时返回的确认态 GraphResult，否则为 None。
    """
    async def invoke(tool, call):
        if hasattr(tool, "server_id"):
            raw = await invoke_tool_fn(
                server_id=tool.server_id,
                tool_name=tool.name,
                arguments=call.arguments,
            )
        else:
            raw = await invoke_tool_fn(
                tool=tool,
                call={
                    **call.metadata,
                    "id": call.id,
                    "name": call.name,
                    "args": call.arguments,
                },
            )
        return tool_outcome_from_legacy(raw)

    async def append_result(tool, call, outcome):
        messages.append(
            ToolMessage(
                content=_tool_result_content(tool, outcome),
                tool_call_id=call.id,
            )
        )

    async def save_state(state):
        result.executed_tool = state.executed_tool
        result.budget_exceeded = state.budget_exceeded
        if state.confirmation_result is not None:
            outcome = state.confirmation_result
            result.confirmation_result = GraphResult(
                content=rewrite_image_markdown("".join(content_parts), tool_events),
                citations=citations,
                knowledge_grounded=bool(citations),
                thinking_text="".join(thinking_parts),
                pending_confirmation_id=outcome.confirmation_id,
                tool_events=tool_events,
                usage=usage,
            )

    executor = ToolRoundExecutor(tools)
    calls = [tool_call_from_legacy(call, name=call["name"]) for call in tool_calls]
    async for event in executor.stream(
        calls,
        invoke=invoke,
        append_result=append_result,
        state_sink=save_state,
    ):
        if event["type"] == "tool_completed":
            tool_events.append(event)
        yield event
async def _drain_events(agen, *, on_event=None):
    """消费事件型异步生成器，逐事件回调 on_event（为空则丢弃事件）。"""
    async for event in agen:
        if on_event is not None:
            await on_event(event)


async def _finish_tool_loop(
    *,
    model,
    messages: list[Any],
    wrap_up: bool,
    budget_exceeded: bool,
    content_parts: list[str],
    thinking_parts: list[str],
    usage: dict[str, int] | None,
    tool_events: list[dict[str, Any]],
    citations: list[dict[str, Any]],
    stream: bool,
    with_content_blocks: bool = False,
    result: _FinishResult,
):
    """
    工具循环收尾：处理预算超限/达到迭代上限的最终输出，并组装 GraphResult

    生成器产出 message_delta 增量事件（仅 stream=True 的收尾分支）；
    结束前将最终 GraphResult 写入 result.graph_result。

    content_parts 语义：
    - stream=True：累积各轮流式内容，收尾内容追加其后（与既有流式行为一致）；
    - stream=False：仅保存最终一段内容，收尾分支直接覆盖（与既有非流式行为一致）。
    """
    if budget_exceeded:
        message = _PAGE_TOOL_BUDGET_EXCEEDED_MESSAGE
        content_parts[:] = [*content_parts, message] if stream else [message]
        if stream:
            yield {"type": "message_delta", "content": message}
    elif wrap_up:
        wrap_messages = [
            SystemMessage(content=_MAX_ITERATIONS_WRAPUP_PROMPT),
            *messages,
        ]
        if stream:
            try:
                async for chunk in model.astream(wrap_messages):
                    usage = merge_token_usage(usage, extract_token_usage(chunk))
                    thinking = _thinking_text(chunk)
                    if thinking:
                        thinking_parts.append(thinking)
                        yield {"type": "thinking_delta", "content": thinking}
                    content = _content_text(chunk.content)
                    if content:
                        content_parts.append(content)
                        yield {"type": "message_delta", "content": content}
            except Exception as error:
                logger.exception(
                    "Agent wrap-up stream failed: %s", type(error).__name__
                )
                fallback = "已达执行上限，本次回答可能不完整。"
                content_parts.append(fallback)
                yield {"type": "message_delta", "content": fallback}
        else:
            try:
                response = await model.ainvoke(wrap_messages)
            except Exception as error:
                logger.exception(
                    "Agent wrap-up call failed: %s", type(error).__name__
                )
                response = AIMessage(content="已达执行上限，本次回答可能不完整。")
            content = _content_text(response.content)
            thinking = _thinking_text(response)
            if thinking:
                thinking_parts.append(thinking)
            content_parts[:] = [content] if content else []
            usage = merge_token_usage(usage, extract_token_usage(response))

    result.graph_result = GraphResult(
        content=rewrite_image_markdown("".join(content_parts), tool_events),
        citations=citations,
        knowledge_grounded=bool(citations),
        thinking_text="".join(thinking_parts),
        tool_events=tool_events,
        usage=usage,
        content_blocks=(
            image_content_blocks(tool_events) + custom_content_blocks(tool_events)
            if with_content_blocks
            else []
        ),
    )


async def _stream_graph(
    model,
    *,
    system_prompt: str,
    user_message: str,
    history: list[Any] | None = None,
    citations: list[dict[str, Any]] | None = None,
    tools: list[Any] | None = None,
    invoke_tool_fn=None,
    max_iterations: int | None = None,
    image_parts: list[dict] | None = None,
    document_text_parts: list[dict] | None = None,
    history_attachment_parts: dict[str, list[dict]] | None = None,
    context_window_tokens: int | None = None,
):
    """
    流式执行对话图，通过事件逐步输出模型回复

    统一执行路径：
        1. **工具场景**：逐轮消费模型原生流，工具结果回填后继续下一轮生成
        2. **无流式能力**（模型不支持 astream）：降级为 run_graph() 非流式执行
        3. **纯流式**：零轮工具调用的特例，走同一主循环

    输出的事件类型：
        - "thinking_delta" / "message_delta": 增量思考/正文片段
        - "tool_started" / "tool_completed": 工具调用生命周期
        - "completed": 最终完成结果（含 GraphResult）

    Args:
        model: LangChain 聊天模型实例（支持 invoke / astream）
        system_prompt: 系统提示词，定义模型的角色和行为约束
        user_message: 用户输入的消息内容
        citations: 知识库引用列表，用于 grounding
        tools: 可绑定的工具列表，每个工具需有 name、description、input_schema
        invoke_tool_fn: 工具调用回调函数，签名为 (call) -> ToolOutcome

    Yields:
        dict[str, Any]: 事件字典，包含 type 和对应的载荷
    """
    logger.info(
        "stream_graph tools=%s",
        [getattr(tool, "name", type(tool).__name__) for tool in (tools or [])],
    )

    # 场景2：模型不支持流式，降级为非流式调用
    if not hasattr(model, "astream"):
        result = await run_graph(
            model,
            system_prompt=system_prompt,
            user_message=user_message,
            history=history,
            citations=citations,
            image_parts=image_parts,
            context_window_tokens=context_window_tokens,
        )
        if result.content:
            yield {"type": "message_delta", "content": result.content}
        yield {"type": "completed", "result": result}
        return

    bound_model = _bind_tools_schema(model, tools)
    messages = _build_initial_messages(
        system_prompt=system_prompt,
        user_message=user_message,
        history=history,
        image_parts=image_parts,
        document_text_parts=document_text_parts,
        history_attachment_parts=history_attachment_parts,
    )
    if context_window_tokens:
        messages = apply_context_guardrail(
            messages, window_tokens=context_window_tokens
        )
    content_parts: list[str] = []
    thinking_parts: list[str] = []
    tool_events: list[dict[str, Any]] = []
    usage = None
    citations = citations or []
    limit = _resolve_max_iterations(max_iterations)
    iteration_count = 0
    wrap_up = False
    budget_exceeded = False
    degraded = False

    # 场景1/3 统一主循环：逐轮消费模型原生流，工具结果回填后继续下一轮。
    while True:
        iteration_count += 1

        # 消费模型原生流并转发增量事件，随后取回本轮累积结果。
        collect_state = _AstreamCollectState()
        try:
            async for event in _astream_collect(
                bound_model,
                messages,
                user_message=user_message,
                image_parts=image_parts,
                content_parts=content_parts,
                thinking_parts=thinking_parts,
                state=collect_state,
            ):
                yield event
        except Exception as error:
            if not degraded and _should_degrade_context(error):
                degraded = True
                content_parts.clear()
                thinking_parts.clear()
                messages = _degraded_messages(system_prompt, user_message)
                continue
            raise
        response = collect_state.response
        usage = merge_token_usage(usage, collect_state.usage)

        if response is None:
            break

        tool_calls = getattr(response, "tool_calls", []) or []
        if not tool_calls:
            break
        if invoke_tool_fn is None:
            logger.warning(
                "Model requested tools but no tool invoker is configured"
            )
            break
        if limit is not None and iteration_count >= limit:
            logger.warning(
                "Agent reached max iterations limit=%s tools_requested=%s; wrapping up without executing tools",
                limit,
                [call.get("name") for call in tool_calls],
            )
            wrap_up = True
            break

        # 每轮只回填一次模型回复，避免一轮多工具时重复追加。
        messages.append(response)

        # 执行本轮工具并转发工具事件，随后取回轮次结果。
        round_result = _ToolRoundResult()
        async for event in _execute_tool_round(
            tools=tools,
            tool_calls=tool_calls,
            invoke_tool_fn=invoke_tool_fn,
            messages=messages,
            content_parts=content_parts,
            thinking_parts=thinking_parts,
            usage=usage,
            tool_events=tool_events,
            citations=citations,
            result=round_result,
        ):
            yield event

        budget_exceeded = round_result.budget_exceeded
        if round_result.confirmation_result is not None:
            yield {"type": "completed", "result": round_result.confirmation_result}
            return
        if budget_exceeded:
            break
        if not round_result.executed_tool:
            break

    # 收尾：预算超限/达到迭代上限的最终输出，并组装最终 GraphResult。
    finish_result = _FinishResult()
    async for event in _finish_tool_loop(
        model=model,
        messages=messages,
        wrap_up=wrap_up,
        budget_exceeded=budget_exceeded,
        content_parts=content_parts,
        thinking_parts=thinking_parts,
        usage=usage,
        tool_events=tool_events,
        citations=citations,
        stream=True,
        result=finish_result,
    ):
        yield event

    logger.info(
        "Streaming chat graph completed content_chars=%s knowledge_grounded=%s usage=%s",
        len(finish_result.graph_result.content),
        bool(citations),
        finish_result.graph_result.usage,
    )
    yield {"type": "completed", "result": finish_result.graph_result}


async def stream_graph(
    model,
    *,
    system_prompt: str,
    user_message: str,
    history: list[Any] | None = None,
    citations: list[dict[str, Any]] | None = None,
    tools: list[Any] | None = None,
    invoke_tool_fn=None,
    max_iterations: int | None = None,
    image_parts: list[dict] | None = None,
    document_text_parts: list[dict] | None = None,
    history_attachment_parts: dict[str, list[dict]] | None = None,
    context_window_tokens: int | None = None,
):
    """执行流式图，并将上游异常转换为终止 error 事件。"""
    try:
        async for event in _stream_graph(
            model,
            system_prompt=system_prompt,
            user_message=user_message,
            history=history,
            citations=citations,
            tools=tools,
            invoke_tool_fn=invoke_tool_fn,
            max_iterations=max_iterations,
            image_parts=image_parts,
            document_text_parts=document_text_parts,
            history_attachment_parts=history_attachment_parts,
            context_window_tokens=context_window_tokens,
        ):
            yield event
    except asyncio.CancelledError:
        raise
    except Exception as error:
        logger.exception("Agent stream failed: %s", type(error).__name__)
        yield {"type": "error", "payload": build_agent_error_payload(error)}


async def run_graph(
    model,
    *,
    system_prompt: str,
    user_message: str,
    history: list[Any] | None = None,
    citations: list[dict[str, Any]] | None = None,
    tools: list[Any] | None = None,
    invoke_tool_fn=None,
    on_event=None,
    max_iterations: int | None = None,
    image_parts: list[dict] | None = None,
    document_text_parts: list[dict] | None = None,
    history_attachment_parts: dict[str, list[dict]] | None = None,
    context_window_tokens: int | None = None,
) -> GraphResult:
    """
    非流式执行对话图，支持工具调用循环

    核心流程：
        1. 将工具绑定到模型（bind_tools），使模型具备调用工具的能力
        2. 逐轮调用模型（ainvoke），检测工具调用（tool_calls）并逐个执行
        3. 将工具执行结果回填到消息列表，再次调用模型进行推理
        4. 循环处理直到模型不再请求工具调用
        5. 若工具需要用户确认（confirmation_required），则提前返回

    Args:
        model: LangChain 聊天模型实例
        system_prompt: 系统提示词
        user_message: 用户输入消息
        citations: 知识库引用列表
        tools: 可绑定的工具列表，每个工具含 name、description、input_schema
        invoke_tool_fn: 工具调用回调函数，支持两种调用签名：
            - 旧版: invoke_tool_fn(tool=tool, call=call)
            - 新版: invoke_tool_fn(server_id=..., tool_name=..., arguments=...)
        on_event: 工具事件回调，签名为 async (event: dict) -> None

    Returns:
        GraphResult: 包含最终回复内容、引用、工具事件、Token 用量等
    """
    citation_items = citations or []
    logger.info(
        "Running chat graph message_chars=%s citations=%s tools=%s",
        len(user_message),
        len(citation_items),
        [getattr(tool, "name", type(tool).__name__) for tool in (tools or [])],
    )

    bound_model = _bind_tools_schema(model, tools)
    messages = _build_initial_messages(
        system_prompt=system_prompt,
        user_message=user_message,
        history=history,
        image_parts=image_parts,
        document_text_parts=document_text_parts,
        history_attachment_parts=history_attachment_parts,
    )
    if context_window_tokens:
        messages = apply_context_guardrail(
            messages, window_tokens=context_window_tokens
        )

    thinking_parts: list[str] = []
    content_parts: list[str] = []
    tool_events: list[dict[str, Any]] = []
    usage = None
    limit = _resolve_max_iterations(max_iterations)
    iteration_count = 0
    wrap_up = False
    budget_exceeded = False
    degraded = False

    # 工具调用循环：模型请求工具时执行工具并回填结果，直到不再请求或触达上限。
    while True:
        iteration_count += 1
        try:
            response = await bound_model.ainvoke(messages)
        except Exception as error:
            if not degraded and _should_degrade_context(error):
                degraded = True
                messages = _degraded_messages(system_prompt, user_message)
                continue
            logger.exception("Model invocation failed: %s", type(error).__name__)
            raise

        content = _content_text(response.content)
        thinking = _thinking_text(response)
        if thinking:
            thinking_parts.append(thinking)
        content_parts[:] = [content] if content else []
        usage = merge_token_usage(usage, extract_token_usage(response))

        tool_calls = getattr(response, "tool_calls", []) or []
        if not tool_calls:
            break
        if invoke_tool_fn is None:
            logger.warning(
                "Model requested tools but no tool invoker is configured"
            )
            break
        if limit is not None and iteration_count >= limit:
            logger.warning(
                "Agent reached max iterations limit=%s tools_requested=%s; wrapping up without executing tools",
                limit,
                [call.get("name") for call in tool_calls],
            )
            wrap_up = True
            break

        # 每轮只回填一次模型回复，避免一轮多工具时重复追加。
        messages.append(response)

        # 执行本轮工具；工具事件经 on_event 转交（为空则丢弃）。
        round_result = _ToolRoundResult()
        await _drain_events(
            _execute_tool_round(
                tools=tools,
                tool_calls=tool_calls,
                invoke_tool_fn=invoke_tool_fn,
                messages=messages,
                content_parts=[],
                thinking_parts=thinking_parts,
                usage=usage,
                tool_events=tool_events,
                citations=citation_items,
                result=round_result,
            ),
            on_event=on_event,
        )
        budget_exceeded = round_result.budget_exceeded
        if round_result.confirmation_result is not None:
            return round_result.confirmation_result
        if budget_exceeded:
            break
        if not round_result.executed_tool:
            break

    # 收尾：预算超限/达到迭代上限的最终输出，并组装最终 GraphResult。
    finish_result = _FinishResult()
    await _drain_events(
        _finish_tool_loop(
            model=model,
            messages=messages,
            wrap_up=wrap_up,
            budget_exceeded=budget_exceeded,
            content_parts=content_parts,
            thinking_parts=thinking_parts,
            usage=usage,
            tool_events=tool_events,
            citations=citation_items,
            stream=False,
            with_content_blocks=True,
            result=finish_result,
        ),
        on_event=on_event,
    )
    graph_result = finish_result.graph_result
    logger.info(
        "Chat graph completed content_chars=%s citations=%s knowledge_grounded=%s usage=%s pending_confirmation_id=%s",
        len(graph_result.content),
        len(graph_result.citations),
        graph_result.knowledge_grounded,
        graph_result.usage,
        graph_result.pending_confirmation_id,
    )
    return graph_result


async def load_runtime_context(
    agent_repo,
    knowledge_repo,
    skill_repo,
    mcp_repo,
    builtin_tool_repo=None,
    *,
    agent_id: int,
    platform_id: int,
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
    mcp_tools = await mcp_repo.list_enabled_tools_for_agent(agent_id, platform_id)
    builtin_tools = (
        await builtin_tool_repo.list_enabled_tools_for_agent(agent_id, platform_id)
        if builtin_tool_repo is not None
        else []
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


def build_runtime_metadata_block(version) -> str | None:
    """构建注入系统提示词的运行时信息段（字段白名单）。

    只披露模型名、Agent 版本、服务版本、SDK 最低版本、温度与能力摘要；
    绝不包含 api_key_encrypted / model_base_url 等敏感配置。字段缺失时跳过对应行，
    全部缺失返回 None（调用方不追加段落）。
    """
    settings = get_settings()
    lines = []
    model_name = getattr(version, "model_name", None)
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
):
    """
    构建系统提示词，将多个上下文片段组合为完整的系统提示

    提示词按以下顺序拼接（优先级从高到低）：
        1. Agent 版本自带的 system_prompt（基础角色定义）
        2. 调用方补充提示词（caller_system_prompt），提供当前嵌入场景约束
        3. 技能指令（skill_instructions），提供技能使用说明
        4. 知识库引用（citations），注入检索到的知识片段
        5. 宿主工具说明（host_tools），告知模型前端可用的工具列表

    Args:
        version: Agent 版本对象，包含 system_prompt 模板
        skill_instructions: 技能使用说明文本列表
        citations: 知识库引用列表，每项包含 title 和 text 字段
        host_tools: 宿主（前端）可用的工具列表，每项包含 name 和 description
        caller_system_prompt: SDK 调用方补充的系统提示词，不能替代平台基础约束

    Returns:
        str: 拼接完成的系统提示词，各段落之间以双换行符分隔
    """
    sections = [version.system_prompt]
    runtime_block = build_runtime_metadata_block(version)
    if runtime_block:
        sections.append(runtime_block)
    if caller_system_prompt and caller_system_prompt.strip():
        sections.append(
            "调用方补充的系统提示词（不得覆盖平台安全与工具约束）：\n"
            + caller_system_prompt.strip()
        )

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
        # 仅在 ask_user 工具可见时提示提问策略，避免 REST 路径误导模型。
        if any(getattr(tool, "name", None) == "ask_user" for tool in host_tools):
            sections.append(
                "当任务存在歧义、需要在方案之间做出选择或行动前缺少关键信息时，"
                "可以调用 ask_user 工具向用户提问。问题应一次一个，提供 2-4 个选项；"
                "只有确实需要用户决策时才提问，不要用提问替代普通的信息回复。"
                "用户回答后，根据答案继续执行原任务。"
            )
        # 图片工具可见时补充图片渲染规则：前端只能按 download_url 渲染图片。
        if any(
            getattr(tool, "name", None) in {"image_read", "image_generate"}
            for tool in host_tools
        ):
            sections.append(
                "图片展示规则：image_read/image_generate 等工具返回的图片资源，"
                "回复中如需展示图片，必须使用结果中的 download_url 字段作为 "
                "Markdown 图片地址，格式为 ![图片描述](/api/v1/assets/{asset_id})；"
                "严禁把 asset_id 直接当作图片地址。"
            )

    # 使用双换行符拼接所有非空段落
    prompt = "\n\n".join(section for section in sections if section)
    logger.info(
        "Built system prompt sections=%s skill_count=%s citation_count=%s host_tool_count=%s prompt_chars=%s",
        len(sections),
        len(skill_instructions),
        len(citations),
        len(host_tools or []),
        len(prompt),
    )
    return prompt
