"""验证用最小 OpenAI 兼容替身模型（不依赖外部余额）。

用途：`tools/harness/verify/2026-10-16-model-registry-unification.sh` 用它证明
「改绑定后实际调用的是新模型」与「绑定模型停用后返回稳定错误码且不回落 .env」。

启动（默认宿主机 8800 端口，容器经 host.docker.internal 访问；端口可用
`STUB_MODEL_PORT` 覆盖，验证脚本会自己挑一个空闲端口，避免与本机残留进程撞车）：

    python3 tools/harness/verify/2026-10-16-model-registry-unification.stub-model.py

行为：
- `POST /v1/chat/completions`：stream=false 返回 JSON；stream=true 返回 OpenAI 兼容 SSE，
  末尾额外发一条「空 choices + usage」的用量收尾 chunk（langchain 会据此产出
  usage_metadata，平台才落得下 model_usage_records）。
- 每次请求把 `{"path","model"}` 追加到日志文件，供验证脚本断言上游真实模型名。
"""

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOG = os.environ.get("STUB_MODEL_LOG", "/tmp/stub_model.log")
PORT = int(os.environ.get("STUB_MODEL_PORT", "8800"))
REPLY = "STUB-MODEL-REPLY"


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(length)
        body = json.loads(raw or b"{}")
        model = body.get("model")
        with open(LOG, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"path": self.path, "model": model}) + "\n")
        if body.get("stream"):
            chunk = {
                "id": "chatcmpl-stub",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"role": "assistant", "content": REPLY},
                        "finish_reason": None,
                    }
                ],
            }
            done = {
                "id": "chatcmpl-stub",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            }
            usage = {
                "id": "chatcmpl-stub",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": model,
                "choices": [],
                "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
            }
            data = (
                f"data: {json.dumps(chunk)}\n\n"
                f"data: {json.dumps(done)}\n\n"
                f"data: {json.dumps(usage)}\n\n"
                "data: [DONE]\n\n"
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        payload = {
            "id": "chatcmpl-stub",
            "object": "chat.completion",
            "created": 1,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": REPLY},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
        }
        data = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        data = b'{"data":[{"id":"stub-model-x"}]}'
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):  # 静音访问日志，避免污染验证输出
        return


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
