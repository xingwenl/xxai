#!/usr/bin/env python3
"""替身对话模型：给「内置工具审批闸口」验证脚本提供可预测的 tool_call。

这是一个 OpenAI 兼容的最小模型端点，只做一件事——按请求内容决定返回哪一种
assistant 消息，好让平台侧的工具调用链路可以被端到端驱动：

路由规则（依据请求体的 tools 与最后一条消息的 role）：

1. 用户消息里带 ``USE_DELEGATE``（且上一轮不是工具结果）→ 返回 ``delegate_tasks``
   的 tool_call，用来验证「委派子运行是否继承父运行的审批策略」。
2. 最后一条消息是 ``role=tool``（工具结果已经回填）→ 返回普通文本，收尾这一轮。
3. 其余情况 → 返回 ``create_task`` 的 tool_call（这是一个 ``side_effect="write"``
   的工具，因此会撞上审批闸口）。

环境变量：
- ``STUB_MODEL_PORT``：监听端口（默认 8800），由验证脚本挑空闲端口后传入。
- ``STUB_MODEL_LOG``：请求日志路径（默认 /tmp/tool_approval_stub.log）。
- ``STUB_DELEGATE_AGENT``：``delegate_tasks`` 里要派的子智能体 slug（默认 dev-assistant）。
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("STUB_MODEL_PORT", "8800"))
LOG_PATH = os.environ.get("STUB_MODEL_LOG", "/tmp/tool_approval_stub.log")
DELEGATE_AGENT = os.environ.get("STUB_DELEGATE_AGENT", "dev-assistant")
MODEL_NAME = "stub-model-x"

_lock = threading.Lock()
_counter = {"n": 0}


def _log(entry: dict) -> None:
    """把一次请求的关键信息落到日志，方便验证脚本回溯模型的决策依据。"""

    with _lock:
        _counter["n"] += 1
        entry["n"] = _counter["n"]
        with open(LOG_PATH, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _text_of(message: dict) -> str:
    """把一条消息的 content 压成字符串（平台可能传 list-of-parts）。"""

    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(parts)
    return ""


def _decide(body: dict) -> tuple[str | None, str | None]:
    """返回 (tool_name, arguments_json)；tool_name 为 None 表示这轮只回文本。"""

    messages = body.get("messages") or []
    user_text = "\n".join(
        _text_of(item) for item in messages if item.get("role") == "user"
    )
    last_role = messages[-1].get("role") if messages else None
    saw_tool_result = last_role == "tool"
    tool_names = [
        (item.get("function") or {}).get("name")
        for item in (body.get("tools") or [])
    ]

    if "USE_DELEGATE" in user_text and not saw_tool_result:
        arguments = {
            "tasks": [
                {
                    "agent": DELEGATE_AGENT,
                    "task": "子任务：请直接创建一个定时任务。",
                }
            ]
        }
        return "delegate_tasks", json.dumps(arguments, ensure_ascii=False)

    if saw_tool_result:
        return None, None

    arguments = {
        "name": f"审批探针任务-{_counter['n'] + 1}",
        "prompt": "审批探针自动创建的任务。",
        "trigger_type": "cron",
        "cron_expression": "0 3 * * *",
    }
    return "create_task", json.dumps(arguments, ensure_ascii=False)


def _usage() -> dict:
    return {"prompt_tokens": 128, "completion_tokens": 32, "total_tokens": 160}


def _chunk(delta: dict, finish_reason: str | None = None, *, empty: bool = False) -> str:
    payload = {
        "id": "chatcmpl-stub",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": MODEL_NAME,
        "choices": [] if empty else [
            {"index": 0, "delta": delta, "finish_reason": finish_reason}
        ],
    }
    if empty:
        payload["usage"] = _usage()
    return "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"


def _sse_body(tool_name: str | None, arguments: str | None) -> str:
    """拼一个 OpenAI 兼容的 SSE 响应体。"""

    if tool_name is None:
        return (
            _chunk({"role": "assistant", "content": "STUB-TOOL-DONE"})
            + _chunk({}, "stop")
            + _chunk({}, None, empty=True)
            + "data: [DONE]\n\n"
        )
    call_id = f"call_stub_{int(time.time() * 1000) % 100000}"
    return (
        _chunk(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "index": 0,
                        "id": call_id,
                        "type": "function",
                        "function": {"name": tool_name, "arguments": arguments},
                    }
                ],
            }
        )
        + _chunk({}, "tool_calls")
        + _chunk({}, None, empty=True)
        + "data: [DONE]\n\n"
    )


def _json_body(tool_name: str | None, arguments: str | None) -> dict:
    if tool_name is None:
        message = {"role": "assistant", "content": "STUB-TOOL-DONE"}
        finish = "stop"
    else:
        message = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": f"call_stub_{int(time.time() * 1000) % 100000}",
                    "type": "function",
                    "function": {"name": tool_name, "arguments": arguments},
                }
            ],
        }
        finish = "tool_calls"
    return {
        "id": "chatcmpl-stub",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": MODEL_NAME,
        "choices": [{"index": 0, "message": message, "finish_reason": finish}],
        "usage": _usage(),
    }


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # noqa: A002 - 静音，日志由 _log 负责
        return

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler 约定
        if self.path.rstrip("/").endswith("/v1/models"):
            body = json.dumps(
                {
                    "object": "list",
                    "data": [{"id": MODEL_NAME, "object": "model", "owned_by": "stub"}],
                }
            ).encode()
            self._send(200, body, "application/json")
            return
        self._send(404, b'{"error":"not found"}', "application/json")

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler 约定
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send(400, b'{"error":"bad json"}', "application/json")
            return

        tool_name, arguments = _decide(body)
        _log(
            {
                "path": self.path,
                "model": body.get("model"),
                "stream": bool(body.get("stream")),
                "tools": [
                    (item.get("function") or {}).get("name")
                    for item in (body.get("tools") or [])
                ],
                "last_role": (body.get("messages") or [{}])[-1].get("role"),
                "decision": tool_name or "text",
            }
        )

        if body.get("stream"):
            payload = _sse_body(tool_name, arguments).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        payload = json.dumps(_json_body(tool_name, arguments)).encode()
        self._send(200, payload, "application/json")


def main() -> int:
    if os.path.exists(LOG_PATH):
        os.remove(LOG_PATH)
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"stub-model listening on 0.0.0.0:{PORT}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
