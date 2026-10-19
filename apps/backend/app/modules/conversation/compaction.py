"""对话上下文压缩。

职责边界：
- 只负责「给模型的视图」：把较早的历史行换成一段摘要 SystemMessage，并记录
  「保留边界」；``conversation_messages`` 里的原始消息永远不删不改。
- 只负责计量：占用优先取 provider 返回的真实 usage，拿不到时才用本地字符
  估算兜底，口径见 ``estimate_context_tokens``。
- 不负责硬截断：护栏（``apply_runtime_context_guardrail``）仍然是最后的兜底，
  压缩先跑、跑不动才轮到护栏删历史。

一次请求内的协作流程：
    build_context_controller() → controller.transform（每次模型调用前）
    → controller.drain_events（模型调用后上报占用 / 吐出压缩事件）
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.core.config import get_settings
from app.core.logging import get_logger
from app.modules.agent_runtime.langchain_adapter import _normalize_usage
from app.modules.conversation.models import ConversationContextCompaction
from app.modules.conversation.repositories import ConversationRepository
from app.modules.conversation.runtime import (
    apply_runtime_context_guardrail,
    build_compaction_summary_message,
    build_history_view,
    estimate_context_tokens,
    estimate_row_tokens,
    plan_compaction_cut,
    resolve_compaction_threshold,
)

logger = get_logger(__name__)

# 摘要请求的系统提示：与成熟 Agent 实现一致，固定小节 + 明确禁止继续对话。
# 固定小节让多次压缩的摘要可以互相合并（见 RESUMMARIZE_INSTRUCTION）。
COMPACTION_SUMMARY_SYSTEM_PROMPT = (
    "你是一个上下文压缩助手。请把下面这段对话整理成结构化摘要，"
    "供另一个模型接着完成任务使用。\n"
    "只输出摘要：不要继续对话，不要回答对话里的任何问题，不要调用工具，"
    "不要输出摘要以外的任何说明。\n\n"
    "按以下小节输出，信息缺失的小节写「无」：\n"
    "## 目标\n"
    "## 约束与偏好\n"
    "## 进展\n"
    "### 已完成\n"
    "### 进行中\n"
    "### 受阻\n"
    "## 关键决策\n"
    "## 下一步\n"
    "## 关键上下文\n\n"
    "保持简洁，保留确切的文件路径、函数名、错误信息与数值。"
)

# 二次压缩的合并指令：旧摘要整体保留，只补充新内容，避免多轮压缩把早期
# 决策与约束逐次磨掉。
RESUMMARIZE_INSTRUCTION = (
    "本次压缩覆盖的对话此前已经被压缩过：必须在完整保留旧摘要全部信息的基础上，"
    "补充新消息里的进展、决策与上下文。旧摘要内容在 <previous-summary> 标签内。"
)

# 工具结果是历史里体积最大、重复率最高的部分，按成熟实现的做法截断后再送摘要。
_TOOL_RESULT_SUMMARY_LIMIT = 2000

_ROLE_LABELS = {"user": "[User]", "assistant": "[Assistant]", "tool": "[Tool result]"}


@dataclass(slots=True)
class SummaryResult:
    """摘要模型的返回：正文与用量。"""

    text: str
    usage: dict | None = None


@dataclass(slots=True)
class CompactionOutcome:
    """一次压缩尝试的结果，同时供事件载荷与 REST 响应使用。"""

    compacted: bool
    reason: str
    trigger: str = "manual"
    tokens_before: int = 0
    tokens_after: int = 0
    window_tokens: int | None = None
    used_tokens: int = 0
    percent: float | None = None
    summary_chars: int = 0
    compaction_id: int | None = None
    created_at: datetime | None = None
    # 以下两个字段不进协议，只供请求内控制器续接状态。
    compaction: ConversationContextCompaction | None = None
    summary_message: SystemMessage | None = None

    def as_payload(self) -> dict[str, Any]:
        """事件载荷：wire 协议统一 camelCase。"""

        return {
            "ok": self.compacted,
            "reason": self.reason,
            "trigger": self.trigger,
            "tokensBefore": self.tokens_before,
            "tokensAfter": self.tokens_after,
            "windowTokens": self.window_tokens,
            "percent": self.percent,
            "summaryChars": self.summary_chars,
        }

    def as_rest(self) -> dict[str, Any]:
        """REST 数据：后端 embed REST 统一 snake_case。"""

        return {
            "compacted": self.compacted,
            "reason": self.reason,
            "trigger": self.trigger,
            "tokens_before": self.tokens_before,
            "tokens_after": self.tokens_after,
            "window_tokens": self.window_tokens,
            "used_tokens": self.used_tokens,
            "percent": self.percent,
        }


@dataclass(slots=True)
class ModelHistory:
    """一次请求的历史视图：模型消息、行绑定、摘要与当前压缩记录。"""

    messages: list[Any] = field(default_factory=list)
    rows: list[Any] = field(default_factory=list)
    bindings: list[tuple[int, Any]] = field(default_factory=list)
    summary_message: SystemMessage | None = None
    compaction: ConversationContextCompaction | None = None


def _percent(used_tokens: int | None, window_tokens: int | None) -> float | None:
    """占用百分比；窗口未知时返回 None（客户端只显示绝对 token 数）。"""

    if not used_tokens or not window_tokens or window_tokens <= 0:
        return None
    return round(used_tokens * 100 / window_tokens, 1)


def _iso(value: datetime | None) -> str | None:
    """时间戳统一按 UTC ISO8601 出协议；无值返回 None。"""

    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def serialize_history_for_summary(
    rows: list[Any] | None,
    *,
    tool_result_limit: int = _TOOL_RESULT_SUMMARY_LIMIT,
) -> str:
    """把历史行序列化成待摘要的纯文本对话记录。

    显式标注角色（``[User]:``/``[Assistant]:``/``[Tool result]:``）而不是直接
    拼接正文，是为了让摘要模型明白这是「素材」而不是一段需要继续的对话；工具
    结果按上限截断，超出部分标注截断字符数。
    """

    lines: list[str] = []
    for row in rows or []:
        label = _ROLE_LABELS.get(getattr(row, "role", None))
        if label is None:
            continue
        content = getattr(row, "content", "")
        if not isinstance(content, str) or not content.strip():
            continue
        text = content.strip()
        if label == "[Tool result]" and len(text) > tool_result_limit:
            truncated = len(text) - tool_result_limit
            text = f"{text[:tool_result_limit]}\n[... {truncated} more characters truncated]"
        lines.append(f"{label}: {text}")
    return "\n\n".join(lines)


def estimate_history_tokens(
    rows: list[Any] | None, *, chars_per_token: float | None = None
) -> int:
    """估算一组历史行的 token 数（本地估算，用于前后对比与阈值判断）。"""

    return sum(
        estimate_row_tokens(row, chars_per_token=chars_per_token) for row in rows or []
    )


def build_model_history(
    rows: list[Any] | None = None,
    *,
    attachment_parts: dict[str, list[dict]] | None = None,
    compaction: ConversationContextCompaction | None = None,
) -> ModelHistory:
    """把历史行转成模型消息视图，并保留「行 id → 消息对象」绑定。

    LangChain 消息对象不带行 id，只有绑定表能回答「这条消息对应哪一行」；
    压缩后按 ``first_kept_message_id`` 筛选保留行时就靠它。
    """

    messages, bindings = build_history_view(
        rows, attachment_parts=attachment_parts, compaction=compaction
    )
    summary_message = messages[0] if messages and isinstance(messages[0], SystemMessage) else None
    return ModelHistory(
        messages=messages,
        rows=list(rows or []),
        bindings=bindings,
        summary_message=summary_message,
        compaction=compaction,
    )


async def load_model_history(
    repo: ConversationRepository,
    conversation_id: int,
    *,
    attachment_parts: dict[str, list[dict]] | None = None,
    rows: list[Any] | None = None,
) -> ModelHistory:
    """读取当前生效压缩记录与该会话的模型历史视图。

    ``rows`` 用于复用调用方**在写入本轮用户消息之前**读到的历史快照：重新
    查询会把刚落库的用户消息也算进来，历史与 ``user_message`` 参数就会重复。
    """

    # 延迟导入：services 在模块层依赖本模块（压缩控制器），这里反向导入会成环。
    from app.modules.conversation.services import load_recent_history

    if rows is None:
        rows = await load_recent_history(repo, conversation_id)
    compaction = await repo.get_latest_context_compaction(conversation_id)
    return build_model_history(
        rows, attachment_parts=attachment_parts, compaction=compaction
    )


def _summary_max_tokens() -> int:
    """摘要请求的输出上限：显式配置优先，否则取预留预算的 80%。"""

    settings = get_settings()
    configured = int(settings.context_compaction_summary_max_tokens or 0)
    if configured > 0:
        return configured
    return max(256, int(settings.context_compaction_reserve_tokens * 0.8))


async def _request_summary(
    *,
    model: Any,
    rows: list[Any],
    previous: ConversationContextCompaction | None,
    instructions: str | None,
) -> SummaryResult | None:
    """请同一个对话模型生成一次摘要；失败或摘要不可信时返回 None。

    摘要不可信有两种：空内容，以及被输出长度截断（``finish_reason == "length"``）。
    后者只截断了半句话，写进上下文会静默丢掉关键信息，因此宁可不压缩。
    """

    conversation_text = serialize_history_for_summary(rows)
    if not conversation_text:
        return None
    parts: list[str] = []
    previous_summary = getattr(previous, "summary", None)
    if isinstance(previous_summary, str) and previous_summary.strip():
        parts.append(f"<previous-summary>\n{previous_summary.strip()}\n</previous-summary>")
        parts.append(RESUMMARIZE_INSTRUCTION)
    parts.append(f"<conversation>\n{conversation_text}\n</conversation>")
    if instructions and instructions.strip():
        parts.append(f"额外的摘要关注点：{instructions.strip()}")

    bound = model
    max_tokens = _summary_max_tokens()
    if max_tokens > 0:
        try:
            bound = model.bind(max_tokens=max_tokens)
        except Exception:  # noqa: BLE001 - 个别供应商不接受该参数，退回默认上限
            logger.warning("context compaction: bind max_tokens unsupported, using default")
            bound = model
    try:
        response = await bound.ainvoke(
            [
                SystemMessage(content=COMPACTION_SUMMARY_SYSTEM_PROMPT),
                HumanMessage(content="\n\n".join(parts)),
            ]
        )
    except Exception:  # noqa: BLE001 - 摘要失败必须降级为「不压缩」，不能让请求本身失败
        logger.warning("context compaction summary request failed", exc_info=True)
        return None
    text = getattr(response, "content", None)
    if not isinstance(text, str) or not text.strip():
        logger.warning("context compaction summary is empty; skip compaction")
        return None
    finish_reason = (getattr(response, "response_metadata", None) or {}).get("finish_reason")
    if finish_reason == "length":
        logger.warning(
            "context compaction summary hit the token cap; skip incomplete summary"
        )
        return None
    usage = _normalize_usage(getattr(response, "usage_metadata", None))
    return SummaryResult(text=text.strip(), usage=usage)


async def compact_conversation(
    *,
    repo: ConversationRepository,
    conversation_id: int,
    model: Any,
    trigger: str = "manual",
    instructions: str | None = None,
    window_tokens: int | None = None,
    rows: list[Any] | None = None,
    current_compaction: ConversationContextCompaction | None = None,
) -> CompactionOutcome:
    """压缩一次会话历史：摘要较早的历史行并写入新的压缩记录。

    幂等与并发：先按会话行加行锁（``SELECT ... FOR UPDATE``）再读历史，两个并发
    请求不会各写一行摘要；切点没有比当前生效边界前进时直接返回
    ``nothing_to_compact``，避免小窗口下每轮重复压缩。
    """

    settings = get_settings()
    if trigger == "auto" and not settings.context_compaction_enabled:
        return CompactionOutcome(
            compacted=False, reason="disabled", trigger=trigger, window_tokens=window_tokens
        )

    await repo.lock_conversation(conversation_id)
    if rows is None:
        # 延迟导入避免与 services 形成循环依赖。
        from app.modules.conversation.services import load_recent_history

        rows = await load_recent_history(repo, conversation_id)
    history = list(rows or [])
    # 提前算好压缩前占用：无论后面是「无内容可压」还是「摘要失败」，响应里的
    # tokens_after 都必须等于 tokens_before（压缩没有生效），否则调用方会把
    # 0 误读成「上下文已被清空」。
    tokens_before = estimate_history_tokens(history)
    current = current_compaction
    if current is None:
        current = await repo.get_latest_context_compaction(conversation_id)

    cut = plan_compaction_cut(
        history, keep_recent_tokens=settings.context_compaction_keep_recent_tokens
    )
    if cut is None or cut >= len(history):
        return CompactionOutcome(
            compacted=False,
            reason="nothing_to_compact",
            trigger=trigger,
            tokens_before=tokens_before,
            tokens_after=tokens_before,
            window_tokens=window_tokens,
        )
    boundary_id = getattr(current, "first_kept_message_id", None)
    if boundary_id is not None:
        current_index = next(
            (
                index
                for index, row in enumerate(history)
                if getattr(row, "id", None) == boundary_id
            ),
            None,
        )
        # 边界行已不在读取窗口内，或新切点没有前进：都说明没有新的可压缩内容。
        if current_index is None or cut <= current_index:
            return CompactionOutcome(
                compacted=False,
                reason="nothing_to_compact",
                trigger=trigger,
                tokens_before=tokens_before,
                tokens_after=tokens_before,
                window_tokens=window_tokens,
            )

    summary = await _request_summary(
        model=model,
        rows=history[:cut],
        previous=current,
        instructions=instructions,
    )
    if summary is None:
        return CompactionOutcome(
            compacted=False,
            reason="summary_failed",
            trigger=trigger,
            tokens_before=tokens_before,
            tokens_after=tokens_before,
            window_tokens=window_tokens,
        )

    kept = history[cut:]
    tokens_after = estimate_history_tokens(kept) + estimate_context_tokens(
        [SystemMessage(content=summary.text)]
    )
    compaction = await repo.create_context_compaction(
        conversation_id,
        summary=summary.text,
        first_kept_message_id=getattr(kept[0], "id", None) if kept else None,
        tokens_before=tokens_before,
        tokens_after=tokens_after,
        trigger=trigger,
        instructions=(instructions or None),
        model_name=getattr(model, "model_name", None) or getattr(model, "model", None),
        usage=summary.usage,
    )
    summary_message = build_compaction_summary_message(compaction)
    logger.info(
        "context compacted conversation_id=%s trigger=%s tokens_before=%s "
        "tokens_after=%s kept=%s",
        conversation_id,
        trigger,
        tokens_before,
        tokens_after,
        len(kept),
    )
    return CompactionOutcome(
        compacted=True,
        reason="compacted",
        trigger=trigger,
        tokens_before=tokens_before,
        tokens_after=tokens_after,
        window_tokens=window_tokens,
        used_tokens=tokens_after,
        percent=_percent(tokens_after, window_tokens),
        summary_chars=len(summary.text),
        compaction_id=getattr(compaction, "id", None),
        created_at=getattr(compaction, "created_at", None),
        compaction=compaction,
        summary_message=summary_message,
    )


class ContextCompactionController:
    """请求级上下文控制器：压缩 + 占用计量。

    同时承担两个角色——``transform`` 作为 AgentLoop 的 context_transform（每次
    模型调用前重建视图、必要时压缩、最后交护栏兜底），``drain_events`` 作为
    context_metrics（模型调用后上报真实占用，并吐出压缩事件）。

    历史区识别按**对象身份**而不是下标：护栏会按需删除历史消息，下标切片会
    错位；对象身份在「重建 → 护栏裁剪 → 下一轮重建」之间保持稳定。
    """

    def __init__(
        self,
        *,
        repo: ConversationRepository,
        conversation_id: int,
        model: Any,
        history: ModelHistory,
        window_tokens: int | None = None,
        enabled: bool = True,
    ) -> None:
        settings = get_settings()
        self.repo = repo
        self.conversation_id = conversation_id
        self.model = model
        self.window_tokens = (
            int(window_tokens) if window_tokens and window_tokens > 0 else None
        )
        self.enabled = bool(enabled and settings.context_compaction_enabled)
        self.threshold = resolve_compaction_threshold(self.window_tokens)
        self._pending_events: list[tuple[str, dict]] = []
        # 真值基线：上一轮 provider 返回的输入 token 数，以及它覆盖的消息对象。
        self._baseline_usage = 0
        self._baseline_ids: set[int] = set()
        self.bindings: list[tuple[int, Any]] = []
        self.rows: list[Any] = []
        self.summary_message: SystemMessage | None = None
        self.compaction: ConversationContextCompaction | None = None
        self._history_ids: set[int] = set()
        self._attach(history)

    # ---- 视图维护 -------------------------------------------------------

    def _attach(self, history: ModelHistory) -> None:
        self.bindings = list(history.bindings)
        self.rows = list(history.rows)
        self.summary_message = history.summary_message
        self.compaction = history.compaction
        self._history_ids = {id(message) for _, message in self.bindings}
        if self.summary_message is not None:
            self._history_ids.add(id(self.summary_message))

    @property
    def boundary_id(self) -> int | None:
        """当前生效的保留边界（最早仍需逐条回放的行）。"""

        return getattr(self.compaction, "first_kept_message_id", None)

    def _kept_bindings(self) -> list[Any]:
        boundary = self.boundary_id
        return [
            message
            for row_id, message in self.bindings
            if boundary is None or row_id >= boundary
        ]

    def _rebuild(self, messages: list[Any]) -> list[Any]:
        """按当前压缩记录重建消息视图：前缀 + 摘要 + 保留历史 + 后段。"""

        history_indices = [
            index
            for index, message in enumerate(messages)
            if id(message) in self._history_ids
        ]
        if history_indices:
            prefix = list(messages[: history_indices[0]])
            suffix = list(messages[history_indices[-1] + 1 :])
        else:
            # 历史对象已被护栏整段删除：系统提示之外的部分都当作后段。
            prefix = list(messages[:1])
            suffix = list(messages[1:])
        rebuilt = list(prefix)
        if self.summary_message is not None:
            rebuilt.append(self.summary_message)
        rebuilt.extend(self._kept_bindings())
        rebuilt.extend(suffix)
        return rebuilt

    # ---- 占用估算 -------------------------------------------------------

    def _estimate_usage(self, messages: list[Any]) -> int:
        """估算当前输入占用：有真值基线时只估增量，否则整体估算。"""

        if self._baseline_ids:
            trailing = [
                message for message in messages if id(message) not in self._baseline_ids
            ]
            return estimate_context_tokens(
                trailing, baseline_usage=self._baseline_usage
            )
        return estimate_context_tokens(messages)

    def _last_compacted_at(self) -> str | None:
        return _iso(getattr(self.compaction, "created_at", None))

    # ---- 压缩 -----------------------------------------------------------

    async def compact(
        self, *, trigger: str = "manual", instructions: str | None = None
    ) -> CompactionOutcome:
        """执行一次压缩；成功时把控制器状态切到新摘要。"""

        outcome = await compact_conversation(
            repo=self.repo,
            conversation_id=self.conversation_id,
            model=self.model,
            trigger=trigger,
            instructions=instructions,
            window_tokens=self.window_tokens,
            rows=self.rows,
            current_compaction=self.compaction,
        )
        if outcome.compacted:
            self.compaction = outcome.compaction
            if outcome.summary_message is not None:
                self.summary_message = outcome.summary_message
                self._history_ids.add(id(outcome.summary_message))
            # 压缩改变了输入构成，旧的 provider 真值不再代表当前前缀；
            # 不清零会让下一轮继续按「含被删历史」的旧真值判断并重复压缩。
            self._baseline_usage = 0
            self._baseline_ids = set()
        return outcome

    # ---- AgentRuntime seam ---------------------------------------------

    async def transform(self, messages: list[Any]) -> list[Any]:
        """context_transform：重建视图 → 超阈值压缩 → 护栏兜底。"""

        planned = self._rebuild(messages)
        if self.enabled and self.window_tokens is not None:
            used = self._estimate_usage(planned)
            if used > self.threshold:
                outcome = await self.compact(trigger="auto")
                if outcome.compacted:
                    self._pending_events.append(
                        ("context_compacted", outcome.as_payload())
                    )
                    planned = self._rebuild(messages)
                elif outcome.reason == "summary_failed":
                    # 摘要失败也要让客户端知道：此时历史只能靠硬截断兜底。
                    self._pending_events.append(
                        ("context_compacted", outcome.as_payload())
                    )
        return apply_runtime_context_guardrail(planned, window_tokens=self.window_tokens)

    def drain_events(
        self, messages: list[Any], usage: dict | None = None
    ) -> list[tuple[str, dict]]:
        """context_metrics：吐出待发事件；带 usage 时追加一条占用上报。

        模型调用前调用（``usage=None``）只取压缩事件；模型调用后带上该轮真实
        usage，此时 ``messages`` 的最后一条是刚追加的这一轮，真值覆盖的是它之前
        的完整输入。
        """

        events = list(self._pending_events)
        self._pending_events.clear()
        if usage is None:
            return events
        prompt_tokens = usage.get("prompt_tokens") if isinstance(usage, dict) else None
        if isinstance(prompt_tokens, int) and prompt_tokens >= 0:
            self._baseline_usage = prompt_tokens
            self._baseline_ids = {id(message) for message in messages[:-1]}
            used_tokens = prompt_tokens
            source = "provider"
        else:
            used_tokens = self._estimate_usage(messages)
            source = "estimated"
        events.append(
            (
                "context_usage",
                {
                    "usedTokens": used_tokens,
                    "windowTokens": self.window_tokens,
                    "percent": _percent(used_tokens, self.window_tokens),
                    "source": source,
                    "lastCompactedAt": self._last_compacted_at(),
                },
            )
        )
        return events


def build_context_controller(
    *,
    repo: ConversationRepository,
    conversation_id: int,
    model: Any,
    history: ModelHistory,
    window_tokens: int | None = None,
    enabled: bool = True,
) -> ContextCompactionController:
    """构造请求级压缩控制器；调用方同时把它当 context_transform 与 hooks。

    ``ContextCompactionController.transform`` 是绑定的 transform，直接传给
    ``build_langchain_runtime(context_transform=...)`` 即可。
    """

    return ContextCompactionController(
        repo=repo,
        conversation_id=conversation_id,
        model=model,
        history=history,
        window_tokens=window_tokens,
        enabled=enabled,
    )
