from dataclasses import dataclass
import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from app.modules.agent.services import build_chat_model
from app.modules.conversation.schemas import RuntimeContext


@dataclass
class RetrievedContext:
    citations: list[dict[str, Any]]
    grounded: bool


@dataclass
class GraphResult:
    content: str
    citations: list[dict[str, Any]]
    knowledge_grounded: bool
    pending_confirmation_id: int | None = None
    tool_events: list[dict[str, Any]] | None = None


class ChatState(TypedDict, total=False):
    messages: list[Any]
    content: str


def format_sse_event(event: dict[str, Any]) -> str:
    return (
        f"event: {event['type']}\n"
        f"data: {json.dumps(event, ensure_ascii=False, separators=(',', ':'))}\n\n"
    )


async def run_graph(
    model,
    *,
    system_prompt: str,
    user_message: str,
    citations: list[dict[str, Any]] | None = None,
    tools: list[Any] | None = None,
    invoke_tool_fn=None,
) -> GraphResult:
    citation_items = citations or []

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

    async def answer_node(state: ChatState):
        response = await bound_model.ainvoke(state["messages"])
        content = response.content
        if not isinstance(content, str):
            content = "".join(
                item.get("text", "") if isinstance(item, dict) else str(item)
                for item in content
            )
        return {"content": content, "messages": [response]}

    graph = StateGraph(ChatState)
    graph.add_node("answer", answer_node)
    graph.add_edge(START, "answer")
    graph.add_edge("answer", END)
    state = {
        "messages": [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_message),
        ]
    }
    result = await graph.compile().ainvoke(state)
    response = result["messages"][-1]
    tool_calls = getattr(response, "tool_calls", []) or []
    tool_events = []
    pending_confirmation_id = None
    while tool_calls:
        if invoke_tool_fn is None:
            break
        for call in tool_calls:
            tool = next(
                (item for item in tools or [] if item.name == call["name"]), None
            )
            if tool is None:
                continue
            outcome = await invoke_tool_fn(
                server_id=tool.server_id,
                tool_name=tool.name,
                arguments=call.get("args", {}),
            )
            tool_events.append({"tool": tool.name, "outcome": outcome})
            if outcome.status == "confirmation_required":
                pending_confirmation_id = outcome.confirmation_id
                return GraphResult(
                    content="",
                    citations=citation_items,
                    knowledge_grounded=bool(citation_items),
                    pending_confirmation_id=pending_confirmation_id,
                    tool_events=tool_events,
                )
            state["messages"].append(response)
            state["messages"].append(
                ToolMessage(
                    content=str(outcome.result)[:20_000],
                    tool_call_id=call.get("id", tool.name),
                )
            )
        result = await graph.compile().ainvoke(state)
        response = result["messages"][-1]
        tool_calls = getattr(response, "tool_calls", []) or []
    return GraphResult(
        content=result.get("content", ""),
        citations=citation_items,
        knowledge_grounded=bool(citation_items),
        pending_confirmation_id=pending_confirmation_id,
        tool_events=tool_events,
    )


async def load_runtime_context(
    agent_repo,
    knowledge_repo,
    skill_repo,
    mcp_repo,
    *,
    agent_id: int,
    platform_id: int,
) -> RuntimeContext:
    agent = await agent_repo.get_published_agent(agent_id, platform_id)
    if agent is None or agent.default_version is None:
        raise LookupError("published agent not found")
    bindings = sorted(
        await skill_repo.list_enabled_for_agent(agent_id, platform_id),
        key=lambda item: item.sort_order,
    )
    return RuntimeContext(
        agent=agent,
        version=agent.default_version,
        knowledge_bases=await knowledge_repo.list_enabled_for_agent(
            agent_id, platform_id
        ),
        skill_instructions=[item.skill.instruction_template for item in bindings],
        mcp_tools=await mcp_repo.list_enabled_tools_for_agent(agent_id, platform_id),
    )


def build_system_prompt(version, skill_instructions: list[str], citations: list[dict]):
    sections = [version.system_prompt]
    if skill_instructions:
        sections.append("\n\n".join(skill_instructions))
    if citations:
        knowledge = "\n\n".join(
            f"[{item['title']}] {item['text']}" for item in citations
        )
        sections.append(
            "Use the following knowledge base excerpts when relevant. "
            "Do not invent citations:\n" + knowledge
        )
    return "\n\n".join(section for section in sections if section)


def build_model(version):
    return build_chat_model(version)
