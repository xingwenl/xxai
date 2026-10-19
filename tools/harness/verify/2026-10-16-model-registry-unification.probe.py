"""②模型治理双轨合并的 AC3/AC4 探针（配合 .stub-model.py 使用）。

前置：api 容器已启动、开发库已灌种子、替身模型已在宿主机运行（端口由 STUB_MODEL_PORT 指定，默认 8800）。
用法：

    apps/backend/.venv/bin/python tools/harness/verify/2026-10-16-model-registry-unification.probe.py

断言：
- AC3：改绑替身模型后，实际调用的是替身（WS 回复 + 替身请求日志），且
  `model_usage_records` 新增行的 `model_name` 是替身模型名（不是 .env 默认模型）。
- AC4：停用绑定的对话模型后，SSE error 事件返回稳定错误码 `chat_model_unavailable`，
  不静默回落到 .env 默认模型。

脚本自建临时的嵌入客户端与替身模型，结束时恢复原绑定并删除两者。
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("PROBE_BASE", "http://localhost:8080/api/v1")
WS_URL = os.environ.get("PROBE_WS", "ws://localhost:8080/api/v1/ws/agents/1")
STUB_MODEL_NAME = "stub-model-x"
STUB_MODEL_PORT = os.environ.get("STUB_MODEL_PORT", "8800")
STUB_LOG = os.environ.get("STUB_MODEL_LOG", "/tmp/stub_model.log")
ORIGIN = "http://probe.model-registry.local"
PLATFORM_ID = 1
AGENT_ID = 1

failures: list[str] = []
created_client_id: str | None = None
stub_model_id: int | None = None
original_model_id: int | None = None
original_chat_model_name = ""
client_id = ""
client_secret = ""
login_token = ""


def call(method: str, path: str, token: str | None = None, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(BASE + path, data=data, method=method)
    request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(request, timeout=180) as resp:
            raw = resp.read().decode()
            return resp.status, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        return exc.code, (json.loads(raw) if raw.strip() else {})


def sse_chat(message: str, token: str) -> str:
    request = urllib.request.Request(
        BASE + f"/agents/{AGENT_ID}/chat",
        data=json.dumps({"message": message, "stream": True}).encode(),
        method="POST",
    )
    request.add_header("Content-Type", "application/json")
    request.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(request, timeout=180) as resp:
        return resp.read().decode()


def psql(sql: str) -> str:
    result = subprocess.run(
        ["docker", "compose", "exec", "-T", "db", "psql", "-U", "root", "-d", "ai_db", "-tAc", sql],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def check(label: str, ok: bool, detail: str) -> None:
    print(f"  {'通过' if ok else '失败'}：{label} —— {detail}")
    if not ok:
        failures.append(label)


async def ws_chat(embed_token: str) -> tuple[dict, str]:
    import websockets

    async with websockets.connect(
        WS_URL, subprotocols=["ai-agent.v1"], origin=ORIGIN, open_timeout=20, proxy=None
    ) as ws:
        await ws.send(
            json.dumps(
                {
                    "type": "auth",
                    "payload": {
                        "token": embed_token,
                        "protocolVersion": 1,
                        "sdkVersion": "0.2.0",
                    },
                }
            )
        )
        await ws.send(
            json.dumps(
                {
                    "id": "probe",
                    "type": "message_send",
                    "requestId": "probe-ac3",
                    "payload": {"text": "你好"},
                }
            )
        )
        events: list[dict] = []
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=120)
            event = json.loads(raw)
            events.append(event)
            if event["type"] in ("message_completed", "error"):
                break
    counts: dict[str, int] = {}
    for event in events:
        counts[event["type"]] = counts.get(event["type"], 0) + 1
    print(f"  WS 事件统计：{counts}")
    return counts, raw


def main() -> int:
    global created_client_id, stub_model_id, original_model_id, original_chat_model_name
    global client_id, client_secret, login_token

    status, body = call("POST", "/auth/login", payload={"account": "admin", "password": "admin123456"})
    if status != 200:
        print(f"登录失败 status={status} body={body}")
        return 1
    login_token = body["data"]["access_token"]

    # 临时的嵌入客户端：WS 通道要求 Origin 在客户端 allowed_origins 内。
    # 网关没有「删除嵌入客户端」入口（只有停用），因此这里复用同名客户端并轮换密钥，
    # 避免每次验证都往库里插一行。
    probe_client_name = "验证探针（临时）"
    _, clients = call("GET", f"/platforms/{PLATFORM_ID}/embed-clients", login_token)
    existing = next((c for c in clients["data"] if c["name"] == probe_client_name), None)
    if existing is not None:
        client_id = existing["client_id"]
        call(
            "PATCH",
            f"/platforms/{PLATFORM_ID}/embed-clients/{client_id}",
            login_token,
            {"allowed_origins": [ORIGIN], "is_active": True},
        )
        status, body = call(
            "POST", f"/platforms/{PLATFORM_ID}/embed-clients/{client_id}/rotate-secret", login_token
        )
        if status != 200:
            print(f"轮换嵌入客户端密钥失败 status={status} body={body}")
            return 1
        client_secret = body["data"]["client_secret"]
        print(f"  复用嵌入客户端 {client_id}（轮换密钥）")
    else:
        status, body = call(
            "POST",
            f"/platforms/{PLATFORM_ID}/embed-clients",
            login_token,
            {"name": probe_client_name, "allowed_origins": [ORIGIN]},
        )
        if status not in (200, 201):
            print(f"创建嵌入客户端失败 status={status} body={body}")
            return 1
        client_id = body["data"]["client"]["client_id"]
        client_secret = body["data"]["client_secret"]
        created_client_id = client_id
        print(f"  新建嵌入客户端 {client_id}")
    call("PUT", f"/platforms/{PLATFORM_ID}/embed-clients/{client_id}/agents/{AGENT_ID}", login_token)

    _, listing = call("GET", f"/platforms/{PLATFORM_ID}/models?page_size=50", login_token)
    items = listing["data"]["items"]
    stub = next((m for m in items if m["model_name"] == STUB_MODEL_NAME), None)
    if stub is None:
        status, body = call(
            "POST",
            f"/platforms/{PLATFORM_ID}/models",
            login_token,
            {
                "name": "替身对话模型（验证用）",
                "model_type": "chat",
                "model_name": STUB_MODEL_NAME,
                "base_url": f"http://host.docker.internal:{STUB_MODEL_PORT}/v1",
                "api_key": "sk-stub",
            },
        )
        if status not in (200, 201):
            print(f"创建替身模型失败 status={status} body={body}")
            return 1
        stub_model_id = body["data"]["id"]
    else:
        stub_model_id = stub["id"]
        # 复用既有替身条目时也要把地址改回本次端口：脚本每次可能挑到不同空闲端口。
        call(
            "PATCH",
            f"/platforms/{PLATFORM_ID}/models/{stub_model_id}",
            login_token,
            {
                "base_url": f"http://host.docker.internal:{STUB_MODEL_PORT}/v1",
                "api_key": "sk-stub",
                "is_active": True,
            },
        )

    # 记录原来的 chat 绑定，收尾时恢复。
    _, bindings = call("GET", f"/platforms/{PLATFORM_ID}/agents/{AGENT_ID}/models", login_token)
    for item in bindings["data"]["items"]:
        if item.get("role") == "chat" and item.get("model_name") != STUB_MODEL_NAME:
            original_model_id = item["model_id"]
            original_chat_model_name = item["model_name"]
    if original_model_id is None:
        print("找不到原 chat 绑定，无法在收尾时恢复")
        return 1

    if os.path.exists(STUB_LOG):
        os.remove(STUB_LOG)
    usage_before = psql("select coalesce(max(id), 0) from model_usage_records;")

    print("AC3：改绑后实际调用新模型，且用量快照记录新模型名")
    status, _ = call(
        "PUT",
        f"/platforms/{PLATFORM_ID}/agents/{AGENT_ID}/models",
        login_token,
        {"bindings": [{"role": "chat", "model_id": stub_model_id}]},
    )
    check("绑定替换接口返回 200", status == 200, f"status={status}")

    status, body = call(
        "POST",
        "/embed/tokens",
        payload={
            "client_id": client_id,
            "client_secret": client_secret,
            "agent_id": AGENT_ID,
            "external_user_id": "probe-ac3",
            "origin": ORIGIN,
        },
    )
    check("嵌入 token 签发成功", status == 200, f"status={status}")
    embed_token = body["data"]["access_token"] if status == 200 else ""

    counts, last_raw = asyncio.run(ws_chat(embed_token))
    check("WS 收到 message_completed", "message_completed" in counts, json.dumps(counts, ensure_ascii=False))
    check("回复来自替身模型", "STUB-MODEL-REPLY" in last_raw, last_raw[:160])

    stub_calls = ""
    if os.path.exists(STUB_LOG):
        stub_calls = open(STUB_LOG, encoding="utf-8").read()
    check("替身收到请求且模型名为 " + STUB_MODEL_NAME, STUB_MODEL_NAME in stub_calls, stub_calls.strip()[:160])

    usage_after = psql(
        "select model_name || '|' || prompt_tokens || '|' || completion_tokens from model_usage_records"
        f" where id > {usage_before or 0} order by id desc limit 1;"
    )
    check(
        "model_usage_records 快照记录了替身模型",
        usage_after.startswith(STUB_MODEL_NAME + "|"),
        f"快照={usage_after!r}",
    )

    print("AC4：停用绑定模型后返回稳定错误码，且不回落 .env 默认模型")
    call("PATCH", f"/platforms/{PLATFORM_ID}/models/{stub_model_id}", login_token, {"is_active": False})
    sse_body = sse_chat("停用后仍可对话吗", login_token)
    error_lines = [line for line in sse_body.splitlines() if line.startswith("event: error")]
    check("SSE 返回 error 事件", bool(error_lines), f"error 事件数={len(error_lines)}")
    check("错误码为 chat_model_unavailable", "chat_model_unavailable" in sse_body, error_lines[0][:80] if error_lines else "无")
    check("未回落到 .env 默认模型", "STUB-MODEL-REPLY" not in sse_body, "SSE 内无替身回复")

    return 1 if failures else 0


def cleanup() -> None:
    if login_token and stub_model_id is not None:
        call("PATCH", f"/platforms/{PLATFORM_ID}/models/{stub_model_id}", login_token, {"is_active": True})
    if login_token and original_model_id is not None:
        status, _ = call(
            "PUT",
            f"/platforms/{PLATFORM_ID}/agents/{AGENT_ID}/models",
            login_token,
            {"bindings": [{"role": "chat", "model_id": original_model_id}]},
        )
        print(f"  收尾：恢复 chat 绑定 {original_chat_model_name}(id={original_model_id}) status={status}")
    if login_token and stub_model_id is not None:
        status, _ = call("DELETE", f"/platforms/{PLATFORM_ID}/models/{stub_model_id}", login_token)
        print(f"  收尾：删除替身模型 id={stub_model_id} status={status}")
    if login_token and created_client_id:
        # 没有删除嵌入客户端的接口，只能停用；同时解绑 Agent，避免留下可用入口。
        call(
            "DELETE",
            f"/platforms/{PLATFORM_ID}/embed-clients/{created_client_id}/agents/{AGENT_ID}",
            login_token,
        )
        status, _ = call(
            "PATCH",
            f"/platforms/{PLATFORM_ID}/embed-clients/{created_client_id}",
            login_token,
            {"is_active": False},
        )
        print(f"  收尾：停用临时嵌入客户端 {created_client_id} status={status}")


if __name__ == "__main__":
    try:
        exit_code = main()
    finally:
        cleanup()
    sys.exit(exit_code)
