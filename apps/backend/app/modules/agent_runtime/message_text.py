"""从模型消息/流式块中提取正文与思考（reasoning/thinking）文本。

不同供应商的内容结构不统一：正文可能是纯字符串，也可能是 text 类型内容块；
思考文本可能放在 ``additional_kwargs["reasoning_content"]``（DeepSeek reasoner
等由 Provider Adapter 补回），也可能放在 content 的 thinking/reasoning 类型块里。
runtime 需要同时服务 REST/SSE/WS 并与 legacy 对照，因此把两类提取规则收口到
这里，避免各入口各自理解消息结构。
"""

from typing import Any


def extract_text_content(content: Any) -> str:
    """提取消息/块正文：字符串原样返回，内容块列表只保留 text 项。"""

    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            item.get("text", "") if isinstance(item, dict) else str(item)
            for item in content
        )
    return ""


def extract_thinking_text(message: Any) -> str:
    """提取单条消息/块的思考文本；无思考内容时返回空字符串。"""

    parts: list[str] = []
    extra = getattr(message, "additional_kwargs", None) or {}
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
    content = getattr(message, "content", None)
    if isinstance(content, list):
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") in {"thinking", "reasoning"}:
                thinking = item.get("thinking") or item.get("reasoning")
                if isinstance(thinking, str) and thinking:
                    parts.append(thinking)
    return "".join(parts)
