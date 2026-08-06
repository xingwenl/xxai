"""
对话运行时模块

本模块实现了对话系统的核心运行时逻辑，负责：
- 管理对话状态图（LangGraph StateGraph）的执行流程
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
from dataclasses import dataclass
import json
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from app.core.logging import get_logger
from app.modules.agent.services import build_chat_model
from app.modules.skill.services import build_runtime_skill_metadata
from app.modules.skill_runner.tools import build_skill_instruction_tool, build_skill_script_tools
from app.modules.conversation.schemas import RuntimeContext

logger = get_logger(__name__)


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
class RetrievedContext:
    """
    检索到的上下文信息

    用于封装从知识库检索到的引用内容及其相关元数据。

    Attributes:
        citations: 引用来源列表，每个引用包含标题、正文等字段
        grounded: 是否已基于知识库进行了 grounding（知识增强）
    """

    citations: list[dict[str, Any]]
    grounded: bool


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
    pending_confirmation_id: int | None = None
    tool_events: list[dict[str, Any]] | None = None
    usage: dict[str, int] | None = None
    loop_id: int | None = None


class ChatState(TypedDict, total=False):
    """
    对话状态图的状态定义

    作为 LangGraph StateGraph 的状态类型，在对话流转过程中传递消息列表
    和中间生成的文本内容。

    Attributes:
        messages: 对话消息历史列表（包含 SystemMessage、HumanMessage、AIMessage、ToolMessage 等）
        content: 模型生成的中间文本内容
    """

    messages: list[Any]
    content: str


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


async def _stream_graph(
    model,
    *,
    system_prompt: str,
    user_message: str,
    citations: list[dict[str, Any]] | None = None,
    tools: list[Any] | None = None,
    invoke_tool_fn=None,
):
    """
    流式执行对话图，通过 SSE 逐步输出模型回复

    本函数根据场景选择不同的执行路径：
        1. **有工具**：委托给 run_graph() 非流式执行，完成后一次性输出结果
        2. **无流式能力**（模型不支持 astream）：委托给 run_graph() 执行
        3. **纯流式**：直接调用 model.astream() 逐 Token 流式输出

    流式输出的事件类型：
        - "message_delta": 增量文本片段
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

    # 场景1：工具场景逐轮消费模型原生流，工具结果回填后继续下一轮生成。
    if tools:
        bound_model = (
            model.bind_tools(
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
            if hasattr(model, "bind_tools")
            else model
        )

        # 少数模型适配器只实现非流式调用，保留兼容降级路径。
        if not hasattr(bound_model, "astream"):
            result = await run_graph(
                model,
                system_prompt=system_prompt,
                user_message=user_message,
                citations=citations,
                tools=tools,
                invoke_tool_fn=invoke_tool_fn,
            )
            if result.content:
                yield {"type": "message_delta", "content": result.content}
            yield {"type": "completed", "result": result}
            return

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_message),
        ]
        content_parts: list[str] = []
        tool_events: list[dict[str, Any]] = []
        usage = None

        while True:
            response = None
            async for chunk in bound_model.astream(messages):
                usage = merge_token_usage(usage, extract_token_usage(chunk))
                response = chunk if response is None else response + chunk

                content = chunk.content
                if not isinstance(content, str):
                    content = "".join(
                        item.get("text", "") if isinstance(item, dict) else str(item)
                        for item in content
                    )
                if content:
                    content_parts.append(content)
                    yield {"type": "message_delta", "content": content}

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

            messages.append(response)
            executed_tool = False
            for call in tool_calls:
                tool = next((item for item in tools if item.name == call["name"]), None)
                if tool is None:
                    logger.warning("Model requested unknown tool name=%s", call["name"])
                    continue

                executed_tool = True
                tool_event = {
                    "tool": tool.name,
                    "tool_type": (
                        "mcp_tool"
                        if hasattr(tool, "server_id")
                        else (
                            "skill_tool"
                            if getattr(tool, "kind", None) in {"skill_script", "skill_instruction"}
                            else "host_tool"
                        )
                    ),
                    "tool_call_id": call.get("id", tool.name),
                    "input_summary": f"收到 {len(call.get('args', {}))} 个参数",
                    "skill_name": getattr(tool, "skill_name", None),
                    "skill_version": getattr(tool, "skill_version", None),
                }

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
                    yield {
                        "type": "completed",
                        "result": GraphResult(
                            content="".join(content_parts),
                            citations=citations or [],
                            knowledge_grounded=bool(citations),
                            pending_confirmation_id=outcome.confirmation_id,
                            tool_events=tool_events,
                            usage=usage,
                        ),
                    }
                    return

                messages.append(
                    ToolMessage(
                        content=str(outcome.result)[:20_000],
                        tool_call_id=call.get("id", tool.name),
                    )
                )

            if not executed_tool:
                break

        yield {
            "type": "completed",
            "result": GraphResult(
                content="".join(content_parts),
                citations=citations or [],
                knowledge_grounded=bool(citations),
                tool_events=tool_events,
                usage=usage,
            ),
        }
        return

    # 场景2：模型不支持流式（无 astream 方法），降级为非流式调用
    if not hasattr(model, "astream"):
        result = await run_graph(
            model,
            system_prompt=system_prompt,
            user_message=user_message,
            citations=citations,
        )
        if result.content:
            yield {"type": "message_delta", "content": result.content}
        yield {"type": "completed", "result": result}
        return

    # 场景3：纯流式模式，直接通过 model.astream() 逐 Token 输出
    logger.info(
        "Streaming chat graph message_chars=%s citations=%s has_tools=%s",
        len(user_message),
        len(citations or []),
        bool(tools),
    )
    content_parts = []
    usage = None

    # 流式迭代模型输出，每个 chunk 包含增量内容
    async for chunk in model.astream(
        [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_message),
        ]
    ):
        # 累积 Token 使用量统计
        usage = merge_token_usage(usage, extract_token_usage(chunk))

        # 处理 chunk 内容：兼容纯字符串和多模态列表两种格式
        content = chunk.content
        if not isinstance(content, str):
            # 多模态场景：从内容块中提取文本
            content = "".join(
                item.get("text", "") if isinstance(item, dict) else str(item)
                for item in content
            )
        if content:
            content_parts.append(content)
            yield {"type": "message_delta", "content": content}

    logger.info(
        "Streaming chat graph completed content_chars=%s knowledge_grounded=%s usage=%s",
        len("".join(content_parts)),
        bool(citations),
        usage,
    )

    # 输出完成事件，包含完整的 GraphResult
    yield {
        "type": "completed",
        "result": GraphResult(
            content="".join(content_parts),
            citations=citations or [],
            knowledge_grounded=bool(citations),
            usage=usage,
        ),
    }


async def stream_graph(
    model,
    *,
    system_prompt: str,
    user_message: str,
    citations: list[dict[str, Any]] | None = None,
    tools: list[Any] | None = None,
    invoke_tool_fn=None,
):
    """执行流式图，并将上游异常转换为终止 error 事件。"""
    try:
        async for event in _stream_graph(
            model,
            system_prompt=system_prompt,
            user_message=user_message,
            citations=citations,
            tools=tools,
            invoke_tool_fn=invoke_tool_fn,
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
    citations: list[dict[str, Any]] | None = None,
    tools: list[Any] | None = None,
    invoke_tool_fn=None,
    on_event=None,
) -> GraphResult:
    """
    非流式执行对话图，支持工具调用循环

    本函数构建一个 LangGraph 状态图，通过单个 answer 节点执行对话。
    核心流程：
        1. 将工具绑定到模型（bind_tools），使模型具备调用工具的能力
        2. 执行初始推理，获取模型回复
        3. 检测工具调用（tool_calls），逐个执行工具
        4. 将工具执行结果追加到消息列表，再次调用模型进行推理
        5. 循环处理直到模型不再请求工具调用
        6. 若工具需要用户确认（confirmation_required），则提前返回

    Args:
        model: LangChain 聊天模型实例
        system_prompt: 系统提示词
        user_message: 用户输入消息
        citations: 知识库引用列表
        tools: 可绑定的工具列表，每个工具含 name、description、input_schema
        invoke_tool_fn: 工具调用回调函数，支持两种调用签名：
            - 旧版: invoke_tool_fn(tool=tool, call=call)
            - 新版: invoke_tool_fn(server_id=..., tool_name=..., arguments=...)

    Returns:
        GraphResult: 包含最终回复内容、引用、工具事件、Token 用量等

    Raises:
        LookupError: 当 invoke_tool_fn 为 None 时跳过工具处理
    """
    citation_items = citations or []
    logger.info(
        "Running chat graph message_chars=%s citations=%s tools=%s",
        len(user_message),
        len(citation_items),
        [getattr(tool, "name", type(tool).__name__) for tool in (tools or [])],
    )

    # 步骤1：将工具绑定到模型，使模型具备 function calling 能力
    bound_model = model
    if tools and hasattr(model, "bind_tools"):
        bound_model = model.bind_tools(
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

    # 步骤2：定义图中的 answer 节点，执行模型推理
    async def answer_node(state: ChatState):
        try:
            response = await bound_model.ainvoke(state["messages"])
        except Exception as e:
            logger.exception("Model invocation failed: %s", type(e).__name__)
            raise

        content = response.content
        # 兼容多模态内容格式：将列表形式的内容块拼接为纯文本
        if not isinstance(content, str):
            content = "".join(
                item.get("text", "") if isinstance(item, dict) else str(item)
                for item in content
            )
        return {"content": content, "messages": [response]}

    # 步骤3：构建线性状态图（START → answer → END）
    graph = StateGraph(ChatState)
    graph.add_node("answer", answer_node)
    graph.add_edge(START, "answer")
    graph.add_edge("answer", END)

    # 初始化对话状态，包含系统提示和用户消息
    state = {
        "messages": [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_message),
        ]
    }

    # 步骤4：首次调用模型，获取初始回复
    result = await graph.compile().ainvoke(state)
    response = result["messages"][-1]
    usage = extract_token_usage(response)
    tool_calls = getattr(response, "tool_calls", []) or []
    tool_events = []
    pending_confirmation_id = None

    # 步骤5：工具调用循环 —— 模型请求工具时执行工具并回填结果
    while tool_calls:
        if invoke_tool_fn is None:
            break

        for call in tool_calls:
            # 根据工具名称查找对应的工具对象
            tool = next(
                (item for item in tools or [] if item.name == call["name"]), None
            )
            if tool is None:
                continue

            tool_event = {
                "tool": tool.name,
                "tool_type": (
                    "mcp_tool"
                    if hasattr(tool, "server_id")
                    else (
                        "skill_tool"
                        if getattr(tool, "kind", None) == "skill_script"
                        else "host_tool"
                    )
                ),
                "tool_call_id": call.get("id", tool.name),
                "input_summary": f"收到 {len(call.get('args', {}))} 个参数",
                "skill_name": getattr(tool, "skill_name", None),
                "skill_version": getattr(tool, "skill_version", None),
            }
            if on_event is not None:
                await on_event({"type": "tool_started", **tool_event})

            # 区分 MCP 工具（带 server_id）和本地工具的调用方式
            if hasattr(tool, "server_id"):
                outcome = await invoke_tool_fn(
                    server_id=tool.server_id,
                    tool_name=tool.name,
                    arguments=call.get("args", {}),
                )
            else:
                outcome = await invoke_tool_fn(tool=tool, call=call)

            # 记录工具调用事件
            completed_tool_event = {**tool_event, "outcome": outcome}
            tool_events.append(completed_tool_event)
            if on_event is not None:
                await on_event({"type": "tool_completed", **completed_tool_event})

            # 如果工具需要用户确认，记录确认 ID 并提前返回
            if outcome.status == "confirmation_required":
                pending_confirmation_id = outcome.confirmation_id
                return GraphResult(
                    content="",
                    citations=citation_items,
                    knowledge_grounded=bool(citation_items),
                    pending_confirmation_id=pending_confirmation_id,
                    tool_events=tool_events,
                    usage=usage,
                )

            # 将 AI 回复和工具执行结果追加到消息列表，供下一轮推理使用
            state["messages"].append(response)
            state["messages"].append(
                ToolMessage(
                    content=str(outcome.result)[
                        :20_000
                    ],  # 限制工具结果长度，防止超出 Token 限制
                    tool_call_id=call.get("id", tool.name),
                )
            )

        # 步骤6：在追加工具结果后，再次调用模型继续推理
        result = await graph.compile().ainvoke(state)
        response = result["messages"][-1]
        usage = merge_token_usage(usage, extract_token_usage(response))
        # 检查模型是否还需要调用更多工具
        tool_calls = getattr(response, "tool_calls", []) or []

    # 步骤7：组装最终结果
    graph_result = GraphResult(
        content=result.get("content", ""),
        citations=citation_items,
        knowledge_grounded=bool(citation_items),
        pending_confirmation_id=pending_confirmation_id,
        tool_events=tool_events,
        usage=usage,
    )
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
        "Loaded runtime context agent_id=%s platform_id=%s knowledge_bases=%s skill_count=%s script_tool_count=%s mcp_tool_count=%s",
        agent_id,
        platform_id,
        [getattr(base, "id", None) for base in knowledge_bases],
        len(bindings),
        len(skill_script_tools),
        len(mcp_tools),
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
    )


def build_system_prompt(
    version,
    skill_instructions: list[str],
    citations: list[dict],
    host_tools: list[Any] | None = None,
):
    """
    构建系统提示词，将多个上下文片段组合为完整的系统提示

    提示词按以下顺序拼接（优先级从高到低）：
        1. Agent 版本自带的 system_prompt（基础角色定义）
        2. 技能指令（skill_instructions），提供技能使用说明
        3. 知识库引用（citations），注入检索到的知识片段
        4. 宿主工具说明（host_tools），告知模型前端可用的工具列表

    Args:
        version: Agent 版本对象，包含 system_prompt 模板
        skill_instructions: 技能使用说明文本列表
        citations: 知识库引用列表，每项包含 title 和 text 字段
        host_tools: 宿主（前端）可用的工具列表，每项包含 name 和 description

    Returns:
        str: 拼接完成的系统提示词，各段落之间以双换行符分隔
    """
    sections = [version.system_prompt]

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

    # 追加宿主工具说明段落，提供前端可用工具列表
    if host_tools:
        tools = "\n".join(
            f"- {tool.name}: {tool.description or '无描述'}" for tool in host_tools
        )
        sections.append(
            "当前页面已注册且授权的宿主工具如下：\n"
            f"{tools}\n"
            "用户询问可用工具时，只能根据以上实际列表回答。"
            "用户要求打开后台页面时，必须调用 navigate_to_page，"
            "不能只描述应该怎么做，也不能编造未列出的工具。"
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


def build_model(version):
    """
    根据 Agent 版本构建对应的大语言模型实例

    委托给 build_chat_model() 工厂函数，根据版本配置创建相应的模型实例
    （如根据 model_provider、model_name、temperature 等参数初始化）。

    Args:
        version: Agent 版本对象，包含模型配置信息

    Returns:
        LangChain 聊天模型实例（支持 invoke / astream / bind_tools 等方法）
    """
    return build_chat_model(version)
