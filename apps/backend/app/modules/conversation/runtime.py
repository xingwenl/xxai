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

logger = get_logger(__name__)

_MAX_ITERATIONS_WRAPUP_PROMPT = (
    "你已达到本次任务的最大执行轮数，请停止调用任何工具，"
    "直接基于已有信息给出最终回答；如果信息不足，请明确说明。"
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
    converted = []
    for item in history or []:
        content = getattr(item, "content", "")
        if not isinstance(content, str) or not content.strip():
            continue
        role = getattr(item, "role", None)
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
    """内置 GET 允许更大的有界文本，其他工具保持既有上下文上限。"""
    limit = 100_000 if getattr(tool, "kind", None) == "builtin" else 20_000
    if getattr(tool, "kind", None) == "builtin":
        return json.dumps(outcome.result, ensure_ascii=False, default=str)[:limit]
    return str(outcome.result)[:limit]


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
    event = {
        "tool": tool.name,
        "tool_type": classify_tool_type(tool),
        "tool_call_id": call.get("id", tool.name),
        "input_summary": _summarize_json(call.get("args", {}), limit=300),
        "skill_name": getattr(tool, "skill_name", None),
        "skill_version": getattr(tool, "skill_version", None),
    }
    if waiting_status is not None:
        event["waiting_status"] = waiting_status
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

    兼容两类来源：
    - OpenAI 兼容 Chat Completions 的块级 ``additional_kwargs["reasoning_content"]``
      （DeepSeek reasoner 等思考模型，由 ProviderThinkingChatOpenAI 从原始响应
      补回 additional_kwargs）。
    - 内容块列表中的 thinking/reasoning 类型块（OpenAI Responses API 风格）。
    普通模型不返回思考内容时返回空字符串。
    """
    parts: list[str] = []
    extra = getattr(chunk, "additional_kwargs", None) or {}
    for key in ("reasoning_content", "reasoning", "reasoning_details"):
        reasoning = extra.get(key)
        if isinstance(reasoning, str):
            if reasoning:
                parts.append(reasoning)
        elif isinstance(reasoning, list):
            text = "".join(
                (
                    item.get("text") or item.get("content") or ""
                    if isinstance(item, dict)
                    else str(item)
                )
                for item in reasoning
            )
            if text:
                parts.append(text)
    content = getattr(chunk, "content", None)
    if isinstance(content, list):
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") in {"thinking", "reasoning"}:
                thinking = item.get("thinking") or item.get("reasoning")
                if isinstance(thinking, str) and thinking:
                    parts.append(thinking)
    return "".join(parts)


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


def tool_step_values(tool_event: dict, sequence: int) -> dict:
    """把工具事件转换为 Loop 步骤落库字段。"""
    outcome = tool_event["outcome"]
    outcome_status = getattr(outcome, "status", "succeeded")
    status = {
        "confirmation_required": "waiting_confirmation",
        "waiting_question": "waiting_question",
        "failed": "failed",
        "error": "failed",
    }.get(outcome_status, "succeeded")
    result_detail = _tool_result_summary(outcome)
    return {
        "sequence": sequence,
        "step_type": tool_event.get("tool_type", "host_tool"),
        "title": f"调用工具：{tool_event['tool']}",
        "status": status,
        "input_summary": tool_event.get("input_summary"),
        "output_summary": (
            "等待用户确认"
            if status == "waiting_confirmation"
            else "等待用户选择"
            if status == "waiting_question"
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


@dataclass
class _ToolRoundResult:
    """一轮工具调用的结果状态：是否执行了工具、预算是否超限、确认结果。"""

    executed_tool: bool = False
    budget_exceeded: bool = False
    confirmation_result: GraphResult | None = None


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
    return [
        SystemMessage(content=system_prompt),
        *build_history_messages(history, attachment_parts=history_attachment_parts),
        HumanMessage(
            content=build_user_content(
                user_message, image_parts, document_text_parts
            )
        ),
    ]


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
    async for chunk in _astream_with_image_fallback(
        model, messages, user_message, image_parts
    ):
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
    for call in tool_calls:
        tool = next((item for item in tools if item.name == call["name"]), None)
        if tool is None:
            logger.warning("Model requested unknown tool name=%s", call["name"])
            continue

        result.executed_tool = True
        # 询问工具在等待用户选择期间，把 loop step 标记为等待状态，
        # 前端可据此展示"等待用户选择"而非"运行中"。
        tool_event = _build_tool_event(
            tool,
            call,
            waiting_status=(
                "waiting_question" if tool.name == "ask_user" else None
            ),
        )

        # 上游消费并完成 Loop step 落库后才会恢复生成器并执行工具，
        # 从而串行化同一个 AsyncSession 上的数据库操作。
        yield {"type": "tool_started", **tool_event}
        if hasattr(tool, "server_id"):
            outcome = await invoke_tool_fn(
                server_id=tool.server_id,
                tool_name=tool.name,
                arguments=call.get("args", {}),
            )
        else:
            outcome = await invoke_tool_fn(tool=tool, call=call)

        completed_tool_event = {**tool_event, "outcome": outcome}
        tool_events.append(completed_tool_event)
        yield {"type": "tool_completed", **completed_tool_event}

        if outcome.status == "confirmation_required":
            result.confirmation_result = GraphResult(
                content=rewrite_image_markdown("".join(content_parts), tool_events),
                citations=citations,
                knowledge_grounded=bool(citations),
                thinking_text="".join(thinking_parts),
                pending_confirmation_id=outcome.confirmation_id,
                tool_events=tool_events,
                usage=usage,
            )
            return

        if _is_budget_exceeded_outcome(outcome):
            logger.warning("Page tool budget exceeded; stopping agent loop")
            result.budget_exceeded = True
            break

        messages.append(
            ToolMessage(
                content=_tool_result_content(tool, outcome),
                tool_call_id=call.get("id", tool.name),
            )
        )


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
    content_parts: list[str] = []
    thinking_parts: list[str] = []
    tool_events: list[dict[str, Any]] = []
    usage = None
    citations = citations or []
    limit = _resolve_max_iterations(max_iterations)
    iteration_count = 0
    wrap_up = False
    budget_exceeded = False

    # 场景1/3 统一主循环：逐轮消费模型原生流，工具结果回填后继续下一轮。
    while True:
        iteration_count += 1

        # 消费模型原生流并转发增量事件，随后取回本轮累积结果。
        collect_state = _AstreamCollectState()
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

    thinking_parts: list[str] = []
    content_parts: list[str] = []
    tool_events: list[dict[str, Any]] = []
    usage = None
    limit = _resolve_max_iterations(max_iterations)
    iteration_count = 0
    wrap_up = False
    budget_exceeded = False

    # 工具调用循环：模型请求工具时执行工具并回填结果，直到不再请求或触达上限。
    while True:
        iteration_count += 1
        try:
            response = await bound_model.ainvoke(messages)
        except Exception as error:
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
