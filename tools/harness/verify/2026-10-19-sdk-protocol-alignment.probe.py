#!/usr/bin/env python3
"""「SDK 协议 / 错误码 / 版本协商对齐」端到端验证探针（Harness request 2026-10-19-sdk-protocol-alignment）。

验证的是真进程行为：api 容器 + 真数据库 + 真 WebSocket 网关。

覆盖场景：
- AC1 auth 帧 protocolVersion=2 → 先收结构化 error 事件（code / retryable / details 三字段），
  随后以 close 4406 关闭。
- AC2 auth 帧 sdkVersion=0.0.1 → unsupported_sdk_version。
- AC2b auth 帧缺 protocolVersion / sdkVersion → 同样被拒（不再是默认放行）。
- AC3 不请求子协议 `ai-agent.v1` → close 4406 且发不出 error 事件。
- AC13 正常握手：session_ready payload 含 serverVersion / minimumSdkVersion，且**不含** capabilities。
- AC4 非流式 REST 触发 ChatModelUnavailable：HTTP 409、body `code == 409`，
  且新增 `error_code == "chat_model_unavailable"`。

环境变量：``PROBE_BASE``、``PROBE_WS``、``STUB_MODEL_NAME``。
退出码：0 全部通过；1 有断言失败；3 检测到另一个探针进程在运行（本次未执行）。
"""

from __future__ import annotations

import asyncio
import fcntl
import json
import os
import subprocess
import sys
import uuid

BASE = os.environ.get("PROBE_BASE", "http://localhost:8080/api/v1")
WS_URL = os.environ.get("PROBE_WS", "ws://localhost:8080/api/v1/ws/agents/1")
ORIGIN = "http://probe.sdk-protocol.local"
PLATFORM_ID = 1
AGENT_ID = 1
STUB_MODEL_NAME = os.environ.get("STUB_MODEL_NAME", "stub-model-x")
CLIENT_NAME = "验证探针（临时）"
PROBE_LOCK_PATH = os.environ.get("PROBE_LOCK", "/tmp/sdk-protocol-alignment-probe.lock")

failures: list[str] = []
state: dict = {
    "token": None,
    "client_id": None,
    "client_secret": None,
    "original_binding": None,
    "created_model_id": None,
    "probe_model_id": None,
}


def section(title: str) -> None:
    print()
    print(f"--- {title} ---")


def check(label: str, ok: bool, detail: object = "") -> None:
    print(("  通过：" if ok else "  失败：") + label + (f" —— {detail}" if detail != "" else ""))
    if not ok:
        failures.append(label)


# ---------------------------------------------------------------------------
# HTTP 助手
# ---------------------------------------------------------------------------


def call(method: str, path: str, token: str | None = None, payload: dict | None = None,
         timeout: int = 120) -> tuple[int, dict]:
    import urllib.error
    import urllib.request

    url = path if path.startswith("http") else BASE + path
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"raw": raw}


def _items(body: dict) -> list:
    data = (body or {}).get("data")
    if isinstance(data, dict):
        return data.get("items") or []
    if isinstance(data, list):
        return data
    return []


def psql(sql: str) -> str:
    proc = subprocess.run(
        ["docker", "compose", "exec", "-T", "db", "psql", "-U", "root", "-d", "ai_db", "-tAc", sql],
        capture_output=True, text=True,
    )
    return proc.stdout.strip()


# ---------------------------------------------------------------------------
# WS 握手助手
# ---------------------------------------------------------------------------


async def ws_handshake(auth_payload: dict, *, subprotocols: list[str] | None = None) -> dict:
    """发一条 auth 帧，尽量把服务端回的事件收完，返回观察结果。

    返回 ``{"events": [...], "close_code": int|None, "connected": bool, "error": str|None}``。
    """

    import websockets

    protocols = ["ai-agent.v1"] if subprotocols is None else subprotocols
    result: dict = {"events": [], "close_code": None, "connected": False, "error": None}
    try:
        async with websockets.connect(WS_URL, subprotocols=protocols or None, origin=ORIGIN,
                                      open_timeout=20, proxy=None) as ws:
            result["connected"] = True
            await ws.send(json.dumps({"type": "auth", "payload": auth_payload}))
            while True:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=15)
                except asyncio.TimeoutError:
                    break
                except websockets.exceptions.ConnectionClosed as exc:
                    # 正常路径：服务端先发 error 事件再以 4406 关闭，关闭码在这里才拿得到。
                    result["close_code"] = (
                        getattr(exc.rcvd, "code", None) or getattr(exc.sent, "code", None)
                    )
                    break
                except Exception:
                    break
                result["events"].append(json.loads(raw))
    except Exception as exc:  # 握手阶段就被拒（例如缺子协议）
        result["error"] = f"{type(exc).__name__}: {exc}"
        rcvd = getattr(exc, "rcvd", None)
        sent = getattr(exc, "sent", None)
        result["close_code"] = getattr(rcvd, "code", None) or getattr(sent, "code", None)
    return result


def error_events(result: dict) -> list[dict]:
    return [event for event in result["events"] if event.get("type") == "error"]


async def scenario_handshake(auth_payload: dict, *, subprotocols: list[str] | None = None) -> dict:
    return await ws_handshake(auth_payload, subprotocols=subprotocols)


# ---------------------------------------------------------------------------
# 环境准备 / 收尾
# ---------------------------------------------------------------------------


def setup() -> None:
    section("准备：登录、准备嵌入客户端、记录原 chat 绑定")
    status, body = call("POST", "/auth/login", payload={"account": "admin", "password": "admin123456"})
    assert status == 200, body
    state["token"] = body["data"]["access_token"]
    print("  已登录 admin@平台1")

    status, body = call("GET", f"/platforms/{PLATFORM_ID}/embed-clients", state["token"])
    existing = next((item for item in _items(body) if item.get("name") == CLIENT_NAME), None)
    if existing:
        client_id = existing["client_id"]
        call("PATCH", f"/platforms/{PLATFORM_ID}/embed-clients/{client_id}", state["token"],
             {"allowed_origins": [ORIGIN], "is_active": True})
        status, body = call("POST", f"/platforms/{PLATFORM_ID}/embed-clients/{client_id}/rotate-secret",
                            state["token"])
        assert status in (200, 201), body
        client_secret = body["data"]["client_secret"]
    else:
        status, body = call("POST", f"/platforms/{PLATFORM_ID}/embed-clients", state["token"],
                            {"name": CLIENT_NAME, "allowed_origins": [ORIGIN]})
        assert status in (200, 201), body
        client_id = body["data"]["client"]["client_id"]
        client_secret = body["data"]["client_secret"]
    state["client_id"] = client_id
    state["client_secret"] = client_secret
    status, _ = call("PUT", f"/platforms/{PLATFORM_ID}/embed-clients/{client_id}/agents/{AGENT_ID}",
                     state["token"], {"is_enabled": True})
    assert status in (200, 201, 204), status
    print(f"  嵌入客户端 client_id={client_id} 已绑定 agent 1")

    status, body = call("GET", f"/platforms/{PLATFORM_ID}/agents/{AGENT_ID}/models", state["token"])
    for item in _items(body):
        if item.get("role") == "chat":
            state["original_binding"] = item.get("model_id")
    print(f"  原 chat 绑定 model_id={state['original_binding']}")


def mint_embed_token(tag: str) -> str:
    status, body = call("POST", "/embed/tokens", payload={
        "client_id": state["client_id"],
        "client_secret": state["client_secret"],
        "agent_id": AGENT_ID,
        "external_user_id": f"probe-{tag}-{uuid.uuid4().hex[:8]}",
        "origin": ORIGIN,
    })
    assert status in (200, 201), body
    return body["data"]["access_token"]


def cleanup() -> None:
    section("收尾：恢复 chat 绑定、清掉探针模型与嵌入客户端绑定")
    if state["probe_model_id"] is not None and state["original_binding"] is not None:
        call("PUT", f"/platforms/{PLATFORM_ID}/agents/{AGENT_ID}/models", state["token"],
             {"bindings": [{"role": "chat", "model_id": state["original_binding"]}]})
        print(f"  已恢复 chat 绑定 model_id={state['original_binding']}")
    if state["created_model_id"] is not None:
        status, _ = call("DELETE", f"/platforms/{PLATFORM_ID}/models/{state['created_model_id']}",
                         state["token"])
        print(f"  已删除探针模型 model_id={state['created_model_id']}（status={status}）")
    elif state["probe_model_id"] is not None:
        call("PATCH", f"/platforms/{PLATFORM_ID}/models/{state['probe_model_id']}", state["token"],
             {"is_active": True})
        print(f"  已恢复复用模型 model_id={state['probe_model_id']} 的启用状态")
    if state["client_id"]:
        call("DELETE", f"/platforms/{PLATFORM_ID}/embed-clients/{state['client_id']}/agents/{AGENT_ID}",
             state["token"])
        call("PATCH", f"/platforms/{PLATFORM_ID}/embed-clients/{state['client_id']}", state["token"],
             {"is_active": False})
        print("  已解绑并停用探针嵌入客户端")


# ---------------------------------------------------------------------------
# 场景
# ---------------------------------------------------------------------------


async def scenario_version_rejection() -> None:
    section("AC1/AC2/AC2b：auth 帧版本字段不合法或缺失都必须在 token 校验前被拒")

    dummy = {"token": "not-a-real-token"}

    result = await scenario_handshake({**dummy, "protocolVersion": 2, "sdkVersion": "0.2.0"})
    errors = error_events(result)
    print(f"  protocolVersion=2 事件类型={[e.get('type') for e in result['events']]} close={result['close_code']} err={result['error']}")
    check("AC1 收到 error 事件", len(errors) == 1, errors)
    if errors:
        payload = errors[0].get("payload") or {}
        details = payload.get("details") or {}
        check("AC1 code=unsupported_protocol_version", payload.get("code") == "unsupported_protocol_version", payload.get("code"))
        check("AC1 retryable=false", payload.get("retryable") is False, payload.get("retryable"))
        check("AC1 details.serverVersion 非空", bool(details.get("serverVersion")), details)
        check("AC1 details.minimumSdkVersion 非空", bool(details.get("minimumSdkVersion")), details)
    check("AC1 服务端以 4406 关闭", result["close_code"] == 4406, result["close_code"])

    result = await scenario_handshake({**dummy, "protocolVersion": 1, "sdkVersion": "0.0.1"})
    errors = error_events(result)
    print(f"  sdkVersion=0.0.1 事件类型={[e.get('type') for e in result['events']]} close={result['close_code']}")
    check("AC2 code=unsupported_sdk_version",
          bool(errors) and (errors[0].get("payload") or {}).get("code") == "unsupported_sdk_version",
          errors)
    check("AC2 服务端以 4406 关闭", result["close_code"] == 4406, result["close_code"])

    result = await scenario_handshake(dict(dummy))
    errors = error_events(result)
    print(f"  缺版本字段 事件类型={[e.get('type') for e in result['events']]} close={result['close_code']}")
    check("AC2b 缺版本字段仍被拒（unsupported_protocol_version）",
          bool(errors) and (errors[0].get("payload") or {}).get("code") == "unsupported_protocol_version",
          errors)
    check("AC2b 服务端以 4406 关闭", result["close_code"] == 4406, result["close_code"])


async def scenario_missing_subprotocol() -> None:
    section("AC3：不请求子协议 ai-agent.v1 → 先关闭、发不出 error 事件")
    result = await scenario_handshake({"token": "x", "protocolVersion": 1, "sdkVersion": "0.2.0"},
                                      subprotocols=[])
    print(f"  connected={result['connected']} close={result['close_code']} err={result['error']}")
    check("AC3 未能进入协议层（未连接）", result["connected"] is False, result["error"])
    check("AC3 未收到 error 事件", not error_events(result), result["events"])
    check("AC3 关闭码为 4406（或握手期 HTTP 拒绝）",
          result["close_code"] == 4406 or "InvalidStatus" in (result["error"] or "")
          or "InvalidStatusCode" in (result["error"] or ""),
          f"close={result['close_code']} err={result['error']}")


async def scenario_happy_handshake() -> None:
    section("AC13：正常握手 → session_ready 不再含 capabilities，且带两版本字段")
    token = mint_embed_token("happy")
    result = await scenario_handshake({"token": token, "protocolVersion": 1, "sdkVersion": "0.2.0"})
    ready = [event for event in result["events"] if event.get("type") == "session_ready"]
    check("AC13 收到 session_ready", len(ready) == 1, [e.get("type") for e in result["events"]])
    if ready:
        payload = ready[0].get("payload") or {}
        print(f"  session_ready.payload 键={sorted(payload.keys())}")
        check("AC13 payload 不含 capabilities", "capabilities" not in payload, sorted(payload.keys()))
        check("AC13 payload 含 serverVersion", bool(payload.get("serverVersion")), payload.get("serverVersion"))
        check("AC13 payload 含 minimumSdkVersion", bool(payload.get("minimumSdkVersion")), payload.get("minimumSdkVersion"))
        # protocolVersion 在信封层（与 transport 无关的公共字段），不在 payload 里。
        check("AC13 信封 protocolVersion == 1", ready[0].get("protocolVersion") == 1,
              ready[0].get("protocolVersion"))


def scenario_rest_error_code() -> None:
    section("AC4：非流式 REST 的 ChatModelUnavailable → 409 + error_code")

    payload = {
        "name": "SDK 协议对齐探针模型（验证用）",
        "model_type": "chat",
        "model_name": STUB_MODEL_NAME,
        "base_url": "http://127.0.0.1:1/v1",
        "api_key": "sk-probe",
    }
    status, body = call("GET", f"/platforms/{PLATFORM_ID}/models?page_size=100", state["token"])
    existing = next((item for item in _items(body) if item.get("name") == payload["name"]), None)
    if existing:
        status, _ = call("PATCH", f"/platforms/{PLATFORM_ID}/models/{existing['id']}", state["token"],
                         {**payload, "is_active": True})
        assert status == 200, status
        state["probe_model_id"] = existing["id"]
    else:
        status, body = call("POST", f"/platforms/{PLATFORM_ID}/models", state["token"], payload)
        assert status in (200, 201), body
        state["created_model_id"] = body["data"]["id"]
        state["probe_model_id"] = body["data"]["id"]

    status, body = call("PUT", f"/platforms/{PLATFORM_ID}/agents/{AGENT_ID}/models", state["token"],
                        {"bindings": [{"role": "chat", "model_id": state["probe_model_id"]}]})
    assert status == 200, body
    status, _ = call("PATCH", f"/platforms/{PLATFORM_ID}/models/{state['probe_model_id']}", state["token"],
                     {"is_active": False})
    assert status == 200, status
    print(f"  已把 agent 1 的 chat 绑定指向停用模型 model_id={state['probe_model_id']}")

    status, body = call("POST", f"/agents/{AGENT_ID}/chat", state["token"],
                        {"message": "你好", "stream": False})
    print(f"  HTTP {status} body={json.dumps(body, ensure_ascii=False)[:300]}")
    check("AC4 HTTP 409", status == 409, status)
    check("AC4 body.code == 409（int，语义未变）", body.get("code") == 409, body.get("code"))
    check("AC4 body.error_code == chat_model_unavailable",
          body.get("error_code") == "chat_model_unavailable", body.get("error_code"))
    check("AC4 body.success is False", body.get("success") is False, body.get("success"))


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def acquire_lock():
    handle = open(PROBE_LOCK_PATH, "w")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


def main() -> int:
    handle = acquire_lock()
    if handle is None:
        print(f"已有另一个探针进程在运行（锁 {PROBE_LOCK_PATH} 被占用）——本次直接退出。")
        return 3
    try:
        setup()
        asyncio.run(scenario_version_rejection())
        asyncio.run(scenario_missing_subprotocol())
        asyncio.run(scenario_happy_handshake())
        scenario_rest_error_code()
    finally:
        try:
            cleanup()
        finally:
            handle.close()

    section("结论")
    if failures:
        print(f"  失败 {len(failures)} 项：")
        for item in failures:
            print(f"    - {item}")
        return 1
    print("  全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
