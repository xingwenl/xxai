"""本地假模型服务：给验证脚本提供确定性的 /v1/chat/completions 应答。

存在意义：`docs/runbooks/dev-environment.md` 的端到端验收要证明「种子建出来的
Agent 能真的走完一轮对话」。真实模型端点受账号余额、网络与限流影响，做不到可
重复；这里起一个只认 OpenAI 兼容形状的最小上游，配合
`docker compose run -e OPENAI_BASE_URL=http://host.docker.internal:<port>/v1`
把一轮对话的完整 HTTP 链路（请求拼装、鉴权头、响应解析、assistant 落库）跑通。

它不是 Mock 掉业务代码：从 uvicorn 到 ModelUsageRecord 走的都是真实实现，只有
最外面那一跳换成了固定应答。用法：`python3 <本文件> <port>`。
"""

from __future__ import annotations

import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REPLY = "本地假模型应答：已收到你的消息。"


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler 的约定命名
        length = int(self.headers.get("content-length") or 0)
        self.rfile.read(length)  # 读掉请求体，否则连接不会复用
        if not self.path.endswith("/chat/completions"):
            self._send(404, {"error": {"message": f"unsupported path {self.path}"}})
            return
        self._send(
            200,
            {
                "id": "chatcmpl-local-stub",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": "local-stub",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": REPLY},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                },
            },
        )

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args) -> None:
        return


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 18800
    print(f"local stub model listening on 0.0.0.0:{port}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
