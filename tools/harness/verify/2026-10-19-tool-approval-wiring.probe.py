#!/usr/bin/env python3
"""「内置工具审批闸口」端到端验证探针（Harness request 2026-10-19-tool-approval-wiring）。

验证的是真进程行为：api 容器 + 真数据库 + 真 WebSocket 网关，模型侧由
``2026-10-19-tool-approval-wiring.stub-model.py`` 提供可预测的 tool_call。

覆盖场景：
- AC7 交互式 WS 拒绝：弹确认卡 → 拒绝 → 工具不执行。
- AC6 交互式 WS 批准：弹确认卡 → 批准 → 工具执行、任务行落库。
- AC8 确认记忆：同一会话内第二次调用同一写工具不再弹卡。
- AC5(expiry) 过期：强制过期后批准 → 工具不执行、确认行落 expired。
- AC9 无确认通道：REST 流式（SSE）通路拒绝并告知 no_confirmation_channel。
- AC-T1 无人值守默认策略：任务调用 create_task 成功、auto_approved_count=1。
- AC-T2 无人值守严格模式：任务调用 create_task 被拒、无新任务行、步骤 failed。
- AC-T3 委派继承：默认策略父任务派子运行，子运行的 create_task 仍被执行
  （若裁决器未继承，子运行会拿到 None 并被 no_confirmation_channel 拒绝）。
- AC10 断连行为（仅观测，不作为通过项）：等待确认期间断开连接后确认行的实际状态。

环境变量：``PROBE_BASE``、``PROBE_WS``、``STUB_MODEL_PORT``、``STUB_MODEL_LOG``。
退出码：0 全部通过；1 有断言失败。
"""

from __future__ import annotations

import asyncio
import fcntl
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

BASE = os.environ.get("PROBE_BASE", "http://localhost:8080/api/v1")
WS_URL = os.environ.get("PROBE_WS", "ws://localhost:8080/api/v1/ws/agents/1")
ORIGIN = "http://probe.tool-approval.local"
PLATFORM_ID = 1
AGENT_ID = 1
STUB_MODEL_NAME = "stub-model-x"
STUB_PORT = os.environ.get("STUB_MODEL_PORT", "8800")
CLIENT_NAME = "验证探针（临时）"
TASK_PREFIX = "审批验证任务-"

failures: list[str] = []
state: dict = {
    "token": None,
    "client_id": None,
    "client_secret": None,
    "model_id": None,
    "original_binding": None,
    "original_enabled": {},
    "created_model": False,
    "created_tasks": [],
    "baseline_tasks": [],
}


def section(title: str) -> None:
    print()
    print(f"--- {title} ---")


def check(label: str, ok: bool, detail: object = "") -> None:
    print(("  通过：" if ok else "  失败：") + label + (f" —— {detail}" if detail != "" else ""))
    if not ok:
        failures.append(label)


# ---------------------------------------------------------------------------
# HTTP / DB 助手
# ---------------------------------------------------------------------------


def call(method: str, path: str, token: str | None = None, payload: dict | None = None,
         timeout: int = 120) -> tuple[int, dict]:
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


def psql(sql: str) -> str:
    proc = subprocess.run(
        ["docker", "compose", "exec", "-T", "db", "psql", "-U", "root", "-d", "ai_db", "-tAc", sql],
        capture_output=True, text=True,
    )
    return proc.stdout.strip()


def tasks_count() -> int:
    return int(psql("select count(*) from tasks") or 0)


def _items(body: dict) -> list:
    data = (body or {}).get("data")
    if isinstance(data, dict):
        return data.get("items") or []
    if isinstance(data, list):
        return data
    return []


# ---------------------------------------------------------------------------
# 环境准备
# ---------------------------------------------------------------------------


def setup() -> None:
    section("准备：登录、记录原状态、启用工具、准备嵌入客户端与替身模型")
    status, body = call("POST", "/auth/login", payload={"account": "admin", "password": "admin123456"})
    assert status == 200, body
    state["token"] = body["data"]["access_token"]
    print("  已登录 admin@平台1")

    status, body = call("GET", f"/platforms/{PLATFORM_ID}/agents/{AGENT_ID}/models", state["token"])
    for item in _items(body):
        if item.get("role") == "chat":
            state["original_binding"] = item.get("model_id")
    print(f"  原 chat 绑定 model_id={state['original_binding']}")
    # 基线可观测性：若这里不是干净状态，说明有另一次运行在并发改同一套数据。
    state["baseline_tasks"] = [
        int(item) for item in psql("select id from tasks").split() if item.strip().isdigit()
    ]
    print(f"  探针开始前 tasks 表行数 = {len(state['baseline_tasks'])}"
          + (f"（基线：{sorted(state['baseline_tasks'])}）" if state["baseline_tasks"] else "（干净）"))

    status, body = call("GET", f"/platforms/{PLATFORM_ID}/agents/{AGENT_ID}/builtin-tools", state["token"])
    assert status == 200, body
    for item in _items(body):
        state["original_enabled"][item["name"]] = item["is_enabled"]
    for name in ("create_task", "delegate_tasks"):
        status, _ = call("PUT", f"/platforms/{PLATFORM_ID}/agents/{AGENT_ID}/builtin-tools/{name}",
                         state["token"], {"is_enabled": True})
        assert status == 200, name
    print("  已启用 create_task / delegate_tasks（收尾恢复）")

    _ensure_embed_client()
    _ensure_stub_model()


def _ensure_embed_client() -> None:
    status, body = call("GET", f"/platforms/{PLATFORM_ID}/embed-clients", state["token"])
    assert status == 200, body
    target = None
    for item in _items(body):
        if item.get("name") == CLIENT_NAME:
            target = item
    if target is None:
        status, body = call("POST", f"/platforms/{PLATFORM_ID}/embed-clients", state["token"],
                            {"name": CLIENT_NAME, "allowed_origins": [ORIGIN]})
        assert status in (200, 201), body
        # 创建响应把 client 明细放在 data.client 下，而 client_secret 与它同级。
        data = body["data"]
        client = data.get("client") or data
        state["client_id"] = client["client_id"]
        state["client_secret"] = data.get("client_secret") or client.get("client_secret")
    else:
        state["client_id"] = target["client_id"]
        call("PATCH", f"/platforms/{PLATFORM_ID}/embed-clients/{state['client_id']}", state["token"],
             {"allowed_origins": [ORIGIN], "is_active": True})
        status, body = call("POST", f"/platforms/{PLATFORM_ID}/embed-clients/{state['client_id']}/rotate-secret",
                            state["token"])
        assert status == 200, body
        state["client_secret"] = body["data"]["client_secret"]
    call("PUT", f"/platforms/{PLATFORM_ID}/embed-clients/{state['client_id']}/agents/{AGENT_ID}", state["token"])
    print(f"  嵌入客户端 client_id={state['client_id']}（复用/轮换密钥，已绑定 agent 1）")


def _ensure_stub_model() -> None:
    payload = {
        "name": "替身对话模型（验证用）",
        "model_type": "chat",
        "model_name": STUB_MODEL_NAME,
        "base_url": f"http://host.docker.internal:{STUB_PORT}/v1",
        "api_key": "sk-stub",
    }
    status, body = call("GET", f"/platforms/{PLATFORM_ID}/models", state["token"])
    target = next((item for item in _items(body) if item.get("model_name") == STUB_MODEL_NAME), None)
    if target is None:
        status, body = call("POST", f"/platforms/{PLATFORM_ID}/models", state["token"], payload)
        assert status in (200, 201), body
        state["model_id"] = body["data"]["id"]
        state["created_model"] = True
    else:
        # 复用既有条目时必须连 base_url 一起改：每次运行的空闲端口不同。
        status, _ = call("PATCH", f"/platforms/{PLATFORM_ID}/models/{target['id']}", state["token"],
                         {**payload, "is_active": True})
        assert status == 200
        state["model_id"] = target["id"]
    status, body = call("PUT", f"/platforms/{PLATFORM_ID}/agents/{AGENT_ID}/models", state["token"],
                        {"bindings": [{"role": "chat", "model_id": state["model_id"]}]})
    assert status == 200, body
    print(f"  替身模型 model_id={state['model_id']} 已绑定到 agent 1 的 chat 角色")


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


# ---------------------------------------------------------------------------
# WS / SSE 驱动
# ---------------------------------------------------------------------------


async def ws_run(token: str, texts: list[str], decide):
    """在同一 WS 连接里依次发消息；``decide(event)`` 返回 bool 表示是否批准。

    第二条及以后的消息会带上第一条消息建立起来的 conversationId，用来验证
    「同一会话内的确认记忆」。
    """

    import websockets

    events: list[dict] = []
    conversation_id = None
    async with websockets.connect(WS_URL, subprotocols=["ai-agent.v1"], origin=ORIGIN,
                                  open_timeout=20, proxy=None) as ws:
        await ws.send(json.dumps({"type": "auth", "payload": {
            "token": token, "protocolVersion": 1, "sdkVersion": "0.2.0"}}))
        while True:
            event = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
            events.append(event)
            if event.get("type") == "session_ready":
                break
        for index, text in enumerate(texts):
            payload: dict = {"text": text}
            if index > 0 and conversation_id:
                payload["conversationId"] = conversation_id
            request_id = f"probe-{index}-{uuid.uuid4().hex[:8]}"
            await ws.send(json.dumps({"id": request_id, "type": "message_send",
                                      "requestId": request_id, "payload": payload}))
            while True:
                event = json.loads(await asyncio.wait_for(ws.recv(), timeout=300))
                events.append(event)
                kind = event.get("type")
                body = event.get("payload") or {}
                conversation_id = (event.get("conversation_id") or event.get("conversationId")
                                   or body.get("conversationId") or conversation_id)
                if kind == "confirmation_required":
                    call_id = body.get("callId")
                    approved = decide(event)
                    if approved is not None:
                        await ws.send(json.dumps({
                            "type": "confirmation_resolve",
                            "requestId": call_id,
                            "payload": {"callId": call_id, "approved": bool(approved)},
                        }))
                if kind in ("message_completed", "error"):
                    break
    return events, conversation_id


def sse_chat(token: str, message: str, timeout: int = 300) -> list[dict]:
    request = urllib.request.Request(
        BASE + f"/agents/{AGENT_ID}/chat",
        data=json.dumps({"message": message, "stream": True}).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST",
    )
    events: list[dict] = []
    current = None
    with urllib.request.urlopen(request, timeout=timeout) as response:
        for raw in response:
            line = raw.decode("utf-8").rstrip("\n")
            if line.startswith("event:"):
                current = line[6:].strip()
            elif line.startswith("data:"):
                text = line[5:].strip()
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError:
                    payload = {"raw": text}
                events.append({"type": current or payload.get("type"), "payload": payload})
    return events


def cards_of(events: list[dict]) -> list[dict]:
    return [event for event in events if event.get("type") == "confirmation_required"]


def blob_of(events: list[dict]) -> str:
    return json.dumps(events, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 交互式场景
# ---------------------------------------------------------------------------


def ac_ws_reject() -> None:
    section("AC7 交互式 WS 拒绝：弹卡 → 拒绝 → 工具不执行")
    before = tasks_count()
    events, _ = asyncio.run(ws_run(mint_embed_token("ac7"), ["AC7 请帮我创建一个定时任务。"], lambda _e: False))
    cards = cards_of(events)
    check("收到 1 张 confirmation_required", len(cards) == 1, f"{len(cards)} 张")
    if cards:
        body = cards[0].get("payload") or {}
        check("callId 非空（否则 SDK 无法回传）", bool(body.get("callId")), body.get("callId"))
        check("name == create_task", body.get("name") == "create_task", body.get("name"))
        check("toolType == builtin_tool", body.get("toolType") == "builtin_tool", body.get("toolType"))
        check("sideEffect == write", body.get("sideEffect") == "write", body.get("sideEffect"))
        check("expiresAt 有值", bool(body.get("expiresAt")), body.get("expiresAt"))
        check("confirmationId 非空（落库锚点）", body.get("confirmationId") is not None, body.get("confirmationId"))
        check("summary.arguments 存在", bool((body.get("summary") or {}).get("arguments")))
    blob = blob_of(events)
    check("工具结果含 rejected", "rejected" in blob)
    # WS 通道按 ADR 0007 不发 tool_call/tool_result，工具结果经 agent_step 事件可观测。
    observable = [event for event in events
                  if str(event.get("type", "")).startswith("agent_step") and "rejected" in blob_of([event])]
    check("拒绝结果经 agent_step 事件可观测", bool(observable), len(observable))
    check("tasks 表未新增（工具未执行）", tasks_count() == before, f"{before} -> {tasks_count()}")
    check("该轮消息正常收尾", any(event.get("type") == "message_completed" for event in events))


def ac_ws_approve() -> None:
    section("AC6 交互式 WS 批准：弹卡 → 批准 → 工具执行")
    before = tasks_count()
    events, _ = asyncio.run(ws_run(mint_embed_token("ac6"), ["AC6 请帮我创建一个定时任务。"], lambda _e: True))
    check("收到 confirmation_required", len(cards_of(events)) == 1, f"{len(cards_of(events))} 张")
    after = tasks_count()
    check("tasks 表 +1（工具已执行）", after == before + 1, f"{before} -> {after}")
    check("该轮消息正常收尾", any(event.get("type") == "message_completed" for event in events))
    if os.environ.get("PROBE_DEBUG"):
        print("  [debug] 事件类型：" + ",".join(str(e.get("type")) for e in events))
        for event in events:
            if str(event.get("type", "")).startswith(("agent_step", "tool_result", "error")):
                print("  [debug] " + blob_of([event])[:800])


def ac_memory() -> None:
    section("AC8 确认记忆：同一会话内第二次调用同一写工具不再弹卡")
    before = tasks_count()
    events, conversation_id = asyncio.run(ws_run(
        mint_embed_token("ac8"),
        ["AC8 第一条：请创建一个定时任务。", "AC8 第二条：再创建一个定时任务。"],
        lambda _e: True,
    ))
    cards = cards_of(events)
    check("两次调用只弹 1 张确认卡", len(cards) == 1, f"{len(cards)} 张")
    check("两条消息都完成（记忆命中后直接执行）",
          sum(1 for event in events if event.get("type") == "message_completed") == 2,
          sum(1 for event in events if event.get("type") == "message_completed"))
    check("tasks 表 +2", tasks_count() == before + 2, f"{before} -> {tasks_count()}")
    check("第二条消息复用了同一会话", conversation_id is not None, conversation_id)


def ac_expiry() -> None:
    section("AC5(expiry) 确认过期：强制过期后批准 → 工具不执行")
    before = tasks_count()
    holder: dict = {}

    def decide(event):
        confirmation_id = (event.get("payload") or {}).get("confirmationId")
        holder["id"] = confirmation_id
        if confirmation_id:
            psql(f"update tool_confirmations set expires_at = now() - interval '1 minute' "
                 f"where id = {int(confirmation_id)}")
        return True

    events, _ = asyncio.run(ws_run(mint_embed_token("ac5"), ["AC5 请创建一个定时任务。"], decide))
    blob = blob_of(events)
    check("收到确认卡", len(cards_of(events)) == 1, f"{len(cards_of(events))} 张")
    row_status = (psql(f"select status from tool_confirmations where id = {int(holder['id'])}")
                  if holder.get("id") else "n/a")
    check("过期的确认行被标为 expired", row_status == "expired", f"status={row_status} id={holder.get('id')}")
    check("工具结果体现过期（confirmation_expired）", "confirmation_expired" in blob or "expired" in blob,
          "expired" in blob)
    check("tasks 表未新增（工具未执行）", tasks_count() == before, f"{before} -> {tasks_count()}")
    if os.environ.get("PROBE_DEBUG"):
        print("  [debug] 事件类型：" + ",".join(str(e.get("type")) for e in events))
        for event in events:
            if str(event.get("type", "")).startswith(("agent_step", "tool_result", "error")):
                print("  [debug] " + blob_of([event])[:800])


def ac_sse_no_channel() -> None:
    section("AC9 无确认通道：REST 流式通路拒绝并告知")
    before = tasks_count()
    events = sse_chat(state["token"], "AC9 请帮我创建一个定时任务。")
    blob = blob_of(events)
    check("SSE 不出现 confirmation_required", not cards_of(events), len(cards_of(events)))
    check("工具结果含 no_confirmation_channel", "no_confirmation_channel" in blob)
    check("工具结果含 rejected", "rejected" in blob)
    check("tasks 表未新增（工具未执行）", tasks_count() == before, f"{before} -> {tasks_count()}")


def ac_disconnect_observation() -> None:
    section("AC10 断连行为（仅观测）")
    holder: dict = {}

    async def run():
        import websockets
        token = mint_embed_token("ac10")
        async with websockets.connect(WS_URL, subprotocols=["ai-agent.v1"], origin=ORIGIN,
                                      open_timeout=20, proxy=None) as ws:
            await ws.send(json.dumps({"type": "auth", "payload": {
                "token": token, "protocolVersion": 1, "sdkVersion": "0.2.0"}}))
            while True:
                event = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
                if event.get("type") == "session_ready":
                    break
            request_id = f"probe-ac10-{uuid.uuid4().hex[:8]}"
            await ws.send(json.dumps({"id": request_id, "type": "message_send",
                                      "requestId": request_id,
                                      "payload": {"text": "AC10 请创建一个定时任务。"}}))
            while True:
                event = json.loads(await asyncio.wait_for(ws.recv(), timeout=300))
                if event.get("type") == "confirmation_required":
                    holder["id"] = (event.get("payload") or {}).get("confirmationId")
                    break

    asyncio.run(run())
    time.sleep(3)
    status = psql(f"select status from tool_confirmations where id = {int(holder['id'])}") if holder.get("id") else "n/a"
    print(f"  观测：等待确认期间断开连接后，确认行 status = {status}")
    print("  说明：本实现未在断连时把 pending 确认行标为 expired（由 600s TTL 兜底），"
          "故 spec 验收标准 10 未满足，已记入 verify.md 的已知差距。")


# ---------------------------------------------------------------------------
# 无人值守场景
# ---------------------------------------------------------------------------


def create_task(prompt: str, *, strict: bool = False, auto_approve: bool = True) -> int:
    status, body = call("POST", f"/platforms/{PLATFORM_ID}/tasks", state["token"], {
        "name": f"{TASK_PREFIX}{uuid.uuid4().hex[:6]}",
        "prompt": prompt,
        "agent_id": AGENT_ID,
        "trigger_type": "cron",
        "cron_expression": "0 0 1 1 *",
        "auto_approve": auto_approve,
        "strict_approval": strict,
        "timeout_seconds": 120,
    })
    assert status in (200, 201), body
    task_id = body["data"]["id"]
    state["created_tasks"].append(task_id)
    return task_id


def run_task(task_id: int, timeout: int = 300) -> tuple[int | None, str | None]:
    status, body = call("POST", f"/platforms/{PLATFORM_ID}/tasks/{task_id}/run", state["token"])
    assert status == 200, body
    run_id = body["data"]["run"]["id"]
    deadline = time.time() + timeout
    run_status = None
    while time.time() < deadline:
        status, body = call("GET", f"/platforms/{PLATFORM_ID}/tasks/{task_id}/runs", state["token"])
        for item in _items(body):
            if item.get("id") == run_id:
                run_status = item.get("status")
        if run_status in ("completed", "failed", "skipped"):
            break
        time.sleep(2)
    return run_id, run_status


def _steps_of(run_id: int) -> str:
    return psql(
        "select tool_name || '|' || status from agent_loop_steps where tool_name is not null "
        f"and loop_run_id = (select agent_loop_run_id from task_runs where id = {run_id}) order by id"
    ).replace("\n", " ")


def _auto_approved(run_id: int) -> str:
    return psql(f"select auto_approved_count from task_runs where id = {run_id}")


def ac_task_auto_approve() -> None:
    section("AC-T1 无人值守默认策略：任务调用 create_task 成功执行")
    task_id = create_task("AC-T1 请帮我创建一个定时任务。")
    before = tasks_count()
    run_id, run_status = run_task(task_id)
    check("任务运行结束（非 running）", run_status in ("completed", "failed"), run_status)
    check("create_task 执行成功 → tasks +1", tasks_count() == before + 1, f"{before} -> {tasks_count()}")
    check("auto_approved_count == 1", _auto_approved(run_id) == "1", _auto_approved(run_id))
    steps = _steps_of(run_id)
    check("create_task 步骤为 succeeded", "create_task|succeeded" in steps, steps)


def ac_task_strict_rejected() -> None:
    section("AC-T2 无人值守严格模式：任务调用 create_task 被拒")
    task_id = create_task("AC-T2 请帮我创建一个定时任务。", strict=True)
    before = tasks_count()
    run_id, run_status = run_task(task_id)
    check("任务运行结束（非 running）", run_status in ("completed", "failed"), run_status)
    check("tasks 表未新增", tasks_count() == before, f"{before} -> {tasks_count()}")
    check("auto_approved_count == 0", _auto_approved(run_id) == "0", _auto_approved(run_id))
    steps = _steps_of(run_id)
    check("create_task 步骤为 failed", "create_task|failed" in steps, steps)


def ac_task_delegation_inherits() -> None:
    section("AC-T3 委派继承：默认策略父任务派子运行，子运行的 create_task 仍被执行")
    task_id = create_task("USE_DELEGATE AC-T3 请把创建一个定时任务这件事派给子智能体。")
    before = tasks_count()
    run_id, run_status = run_task(task_id)
    check("任务运行结束（非 running）", run_status in ("completed", "failed"), run_status)
    children = psql(
        "select count(*) from agent_loop_runs where parent_loop_run_id = "
        f"(select agent_loop_run_id from task_runs where id = {run_id})"
    )
    check("确实派出了子运行", children not in ("", "0"), children)
    # 关键反证：若裁决器没有下传，子运行会拿到 None 并被 no_confirmation_channel 拒绝。
    check("子运行的 create_task 执行成功 → tasks +1", tasks_count() == before + 1,
          f"{before} -> {tasks_count()}")
    steps = _steps_of(run_id)
    check("父运行里 delegate_tasks 步骤为 succeeded", "delegate_tasks|succeeded" in steps, steps)


# ---------------------------------------------------------------------------
# 收尾
# ---------------------------------------------------------------------------


def cleanup() -> None:
    section("收尾：恢复原状态、清理探针数据")
    for task_id in list(state["created_tasks"]):
        call("DELETE", f"/platforms/{PLATFORM_ID}/tasks/{task_id}", state["token"])
    # 工具自己创建的任务（created_by_type=agent）名字不固定，且并发运行会互相干扰，
    # 因此用「基线快照差分」而不是名字匹配：只删本次运行之后新出现的任务行。
    current = {int(item) for item in psql("select id from tasks").split() if item.strip().isdigit()}
    baseline = set(state["baseline_tasks"])
    removed = 0
    for task_id in sorted(current - baseline):
        call("DELETE", f"/platforms/{PLATFORM_ID}/tasks/{task_id}", state["token"])
        removed += 1
    print(f"  已删除任务：{len(state['created_tasks'])} 个显式创建 + {removed} 个本次运行新增")
    if current - baseline:
        print(f"  基线外任务 id：{sorted(current - baseline)}；基线内（未动）：{sorted(current & baseline)}")

    for name, was_enabled in state["original_enabled"].items():
        if name in ("create_task", "delegate_tasks") and not was_enabled:
            call("PUT", f"/platforms/{PLATFORM_ID}/agents/{AGENT_ID}/builtin-tools/{name}",
                 state["token"], {"is_enabled": False})
    print("  已恢复 create_task / delegate_tasks 的启用状态")

    if state["original_binding"]:
        call("PUT", f"/platforms/{PLATFORM_ID}/agents/{AGENT_ID}/models", state["token"],
             {"bindings": [{"role": "chat", "model_id": state["original_binding"]}]})
        print(f"  已恢复 chat 绑定 model_id={state['original_binding']}")

    if state["client_id"]:
        call("DELETE", f"/platforms/{PLATFORM_ID}/embed-clients/{state['client_id']}/agents/{AGENT_ID}",
             state["token"])
        call("PATCH", f"/platforms/{PLATFORM_ID}/embed-clients/{state['client_id']}", state["token"],
             {"is_active": False})
        print("  已解绑并停用临时嵌入客户端")

    if state["model_id"] and state["created_model"]:
        call("DELETE", f"/platforms/{PLATFORM_ID}/models/{state['model_id']}", state["token"])
        print(f"  已删除替身模型 model_id={state['model_id']}")

    # 断连场景（AC10）会留下 pending 行；它们只是探针产生的痕迹，清掉以免与
    # 下一次运行的可观测状态混淆。approved/rejected/expired 行保留作审计留痕。
    removed = psql("with d as (delete from tool_confirmations where status = 'pending' "
                   "returning 1) select count(*) from d")
    pending = psql("select count(*) from tool_confirmations where status = 'pending'")
    print(f"  已清理遗留 pending 确认行 {removed} 条；剩余 pending = {pending}")
    print("  说明：approved/rejected/expired 的确认行保留作审计留痕。")


PROBE_LOCK_PATH = os.environ.get("PROBE_LOCK", "/tmp/tool-approval-wiring-probe.lock")


def acquire_lock():
    """同一时刻只允许一个探针进程改这套共享数据（内置工具启用状态、chat 绑定、
    同名嵌入客户端密钥、tasks 表）。两个并发运行会互相 rotate-secret 作废对方
    token、并互相删掉对方的任务行，产出的失败不是产品缺陷。

    返回持有 flock 的文件对象；拿不到锁时返回 None（调用方应直接退出）。
    """
    handle = open(PROBE_LOCK_PATH, "w")  # noqa: SIM115 - 需在进程存活期间持有
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    handle.write(f"{os.getpid()}\n")
    handle.flush()
    return handle


def main() -> int:
    print("=" * 72)
    print("内置工具审批闸口 —— 端到端验证探针")
    print(f"BASE={BASE}  WS={WS_URL}  STUB_PORT={STUB_PORT}")
    print("=" * 72)

    lock = acquire_lock()
    if lock is None:
        print()
        print(f"已有另一个探针进程在运行（锁 {PROBE_LOCK_PATH} 被占用）——本次直接退出，")
        print("请等它结束后重跑；并发运行会污染 tasks 表与嵌入客户端密钥。")
        return 3

    only = sys.argv[1:] if len(sys.argv) > 1 else None

    def wanted(name: str) -> bool:
        return not only or name in only

    try:
        setup()
        scenarios = [
            ("ac7", ac_ws_reject),
            ("ac6", ac_ws_approve),
            ("ac8", ac_memory),
            ("ac5", ac_expiry),
            ("ac9", ac_sse_no_channel),
            ("act1", ac_task_auto_approve),
            ("act2", ac_task_strict_rejected),
            ("act3", ac_task_delegation_inherits),
            ("ac10", ac_disconnect_observation),
        ]
        for name, scenario in scenarios:
            if wanted(name):
                scenario()
    finally:
        try:
            cleanup()
        except Exception as error:  # noqa: BLE001 - 收尾失败不应掩盖断言结果
            print(f"  收尾异常：{error}")

    print()
    print("=" * 72)
    if failures:
        print(f"失败 {len(failures)} 项：")
        for item in failures:
            print(f"  - {item}")
        print("=" * 72)
        return 1
    print("全部断言通过")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
