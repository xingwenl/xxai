#!/usr/bin/env python3
"""「运行检查点与确认后的续跑」端到端验证探针（Harness request 2026-10-19-run-confirmation-resume）。

只走 REST/SSE 通路（不涉及 WS、不涉及嵌入客户端）：
  1. POST /api/v1/agents/{id}/chat  stream=true  → 写工具被挂起成 confirmation_required
  2. POST /api/v1/agents/{id}/runs/{loop_run_id}/resolve  {"approved": bool} → 返回续跑 SSE

前置：api 容器已按当前源码重建、迁移已到 20261019_0041；替身模型由
`2026-10-19-run-confirmation-resume.sh` 起在 STUB_MODEL_PORT 上。

退出码：0 = 全部通过；1 = 有断言失败；3 = 已有一个探针在跑（本次不执行）。

关于代理：本机会有系统 HTTP 代理（127.0.0.1:7897），python urllib 会把
localhost 请求也发过去而拿到 502，故所有请求统一走显式禁用代理的 opener。
"""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone

BASE = os.environ.get("PROBE_BASE", "http://localhost:8080/api/v1")
PLATFORM_ID = int(os.environ.get("PROBE_PLATFORM", "1"))
AGENT_ID = int(os.environ.get("PROBE_AGENT", "1"))
STUB_MODEL_NAME = os.environ.get("STUB_MODEL_NAME", "stub-model-x")
STUB_PORT = int(os.environ.get("STUB_MODEL_PORT", "8800"))
LOCK_PATH = os.environ.get("PROBE_LOCK", "/tmp/run-confirmation-resume-probe.lock")

_NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))

state: dict = {
    "token": None,
    "original_binding": None,
    "model_id": None,
    "created_model": False,
    "original_enabled": {},
    "baseline_tasks": [],
    "probe_conversations": [],
    "failures": 0,
}


# ---------------------------------------------------------------------------
# 基础设施
# ---------------------------------------------------------------------------


def call(method: str, path: str, token: str | None = None, payload: dict | None = None,
         timeout: int = 120):
    """普通 JSON 请求；返回 (status, body)。"""
    url = BASE + path
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with _NO_PROXY.open(request, timeout=timeout) as response:
            raw = response.read().decode()
            status = response.status
    except urllib.error.HTTPError as error:
        raw = error.read().decode()
        status = error.code
    except urllib.error.URLError as error:
        return 0, {"raw": str(error)}
    try:
        return status, json.loads(raw)
    except json.JSONDecodeError:
        return status, {"raw": raw}


def sse_request(path: str, payload: dict, token: str, timeout: int = 300):
    """SSE 请求；返回 (status, events) 或 (status, body_dict)（HTTP 错误时）。"""
    request = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode(),
        headers={
            "Accept": "text/event-stream",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    try:
        response = _NO_PROXY.open(request, timeout=timeout)
    except urllib.error.HTTPError as error:
        raw = error.read().decode()
        try:
            return error.code, json.loads(raw)
        except json.JSONDecodeError:
            return error.code, {"raw": raw}
    except urllib.error.URLError as error:
        return 0, {"raw": str(error)}

    events: list[dict] = []
    current: str | None = None
    with response:
        for raw_line in response:
            line = raw_line.decode("utf-8").rstrip("\n")
            if line.startswith("event:"):
                current = line[len("event:"):].strip()
            elif line.startswith("data:"):
                text = line[len("data:"):].strip()
                if not text:
                    continue
                try:
                    envelope = json.loads(text)
                except json.JSONDecodeError:
                    envelope = {"raw": text}
                if isinstance(envelope, dict):
                    envelope.setdefault("type", current)
                    events.append(envelope)
                else:
                    events.append({"type": current, "payload": envelope})
    return 200, events


def psql(sql: str) -> str:
    result = subprocess.run(
        ["docker", "compose", "exec", "-T", "db", "psql", "-U", "root", "-d", "ai_db", "-tAc", sql],
        capture_output=True,
        text=True,
        timeout=60,
    )
    return result.stdout.strip()


def tasks_count() -> int:
    raw = psql("select count(*) from tasks")
    return int(raw or 0)


def check(label: str, ok: bool, detail=None) -> None:
    mark = "通过" if ok else "失败"
    suffix = "" if detail is None else f" — {detail}"
    print(f"  [{mark}] {label}{suffix}")
    if not ok:
        state["failures"] += 1


def section(title: str) -> None:
    print()
    print(f"## {title}")


def event_types(events) -> list:
    return [event.get("type") for event in events if isinstance(event, dict)]


def payload_of(event: dict) -> dict:
    payload = event.get("payload")
    return payload if isinstance(payload, dict) else {}


# ---------------------------------------------------------------------------
# 准备与收尾
# ---------------------------------------------------------------------------


def setup() -> None:
    section("准备：登录、启用 create_task、把 chat 角色绑到替身模型")
    status, body = call("POST", "/auth/login", payload={"account": "admin", "password": "admin123456"})
    assert status == 200, body
    state["token"] = body["data"]["access_token"]
    print("  已登录 admin")

    status, body = call("GET", f"/platforms/{PLATFORM_ID}/agents/{AGENT_ID}/models", state["token"])
    for item in body.get("data", {}).get("items", []) if isinstance(body.get("data"), dict) else []:
        if item.get("role") == "chat":
            state["original_binding"] = item.get("model_id")
    print(f"  原 chat 绑定 model_id={state['original_binding']}")

    status, body = call("GET", f"/platforms/{PLATFORM_ID}/agents/{AGENT_ID}/builtin-tools", state["token"])
    assert status == 200, body
    items = body.get("data", {}).get("items", []) if isinstance(body.get("data"), dict) else body.get("data") or []
    for item in items:
        state["original_enabled"][item["name"]] = item["is_enabled"]
    status, _ = call("PUT", f"/platforms/{PLATFORM_ID}/agents/{AGENT_ID}/builtin-tools/create_task",
                     state["token"], {"is_enabled": True})
    assert status == 200, "启用 create_task 失败"
    print("  已启用 create_task（收尾恢复原值）")

    _ensure_stub_model()
    state["baseline_tasks"] = [
        int(value) for value in psql("select id from tasks").split() if value.strip().isdigit()
    ]
    print(f"  探针开始前 tasks 行数 = {len(state['baseline_tasks'])}")


def _ensure_stub_model() -> None:
    payload = {
        "name": "替身对话模型（验证用）",
        "model_type": "chat",
        "model_name": STUB_MODEL_NAME,
        "base_url": f"http://host.docker.internal:{STUB_PORT}/v1",
        "api_key": "sk-stub",
    }
    status, body = call("GET", f"/platforms/{PLATFORM_ID}/models", state["token"])
    assert status == 200, body
    items = body.get("data", {}).get("items", []) if isinstance(body.get("data"), dict) else body.get("data") or []
    target = next((item for item in items if item.get("model_name") == STUB_MODEL_NAME), None)
    if target is None:
        status, body = call("POST", f"/platforms/{PLATFORM_ID}/models", state["token"], payload)
        assert status in (200, 201), body
        state["model_id"] = body["data"]["id"]
        state["created_model"] = True
    else:
        # 复用既有条目时必须连 base_url 一起改：每次运行的空闲端口不同。
        status, _ = call("PATCH", f"/platforms/{PLATFORM_ID}/models/{target['id']}", state["token"],
                         {**payload, "is_active": True})
        assert status == 200, "更新替身模型失败"
        state["model_id"] = target["id"]
    status, body = call("PUT", f"/platforms/{PLATFORM_ID}/agents/{AGENT_ID}/models", state["token"],
                        {"bindings": [{"role": "chat", "model_id": state["model_id"]}]})
    assert status == 200, body
    print(f"  替身模型 model_id={state['model_id']} 已绑定到 agent {AGENT_ID} 的 chat 角色")


def cleanup() -> None:
    section("收尾：恢复绑定/启用状态、清理本次产生的任务与会话")
    token = state["token"]
    if token is None:
        return
    if state["model_id"] is not None and state["original_binding"] is not None:
        status, _ = call("PUT", f"/platforms/{PLATFORM_ID}/agents/{AGENT_ID}/models", token,
                         {"bindings": [{"role": "chat", "model_id": state["original_binding"]}]})
        print(f"  恢复 chat 绑定 -> {state['original_binding']}（status={status}）")
    for name, enabled in state["original_enabled"].items():
        call("PUT", f"/platforms/{PLATFORM_ID}/agents/{AGENT_ID}/builtin-tools/{name}", token,
             {"is_enabled": bool(enabled)})
    print("  已恢复内置工具启用状态")

    baseline = set(state["baseline_tasks"])
    current = {int(value) for value in psql("select id from tasks").split() if value.strip().isdigit()}
    extra = sorted(current - baseline)
    if extra:
        psql(f"delete from tasks where id = any(array[{','.join(str(item) for item in extra)}])")
        print(f"  删除本次产生的任务 {extra}")
    pending = psql("with d as (delete from tool_confirmations where status = 'pending' returning 1) "
                   "select count(*) from d")
    print(f"  清理遗留 pending 确认行 = {pending}")
    for conversation_id in state["probe_conversations"]:
        psql(f"delete from conversations where id = {conversation_id}")
    if state["probe_conversations"]:
        print(f"  删除本次产生的会话 {state['probe_conversations']}")


def acquire_lock():
    try:
        handle = open(LOCK_PATH, "w")
    except OSError:
        return None
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    handle.write(str(os.getpid()))
    handle.flush()
    return handle


# ---------------------------------------------------------------------------
# 场景
# ---------------------------------------------------------------------------


def start_chat(message: str, conversation_id: int | None = None):
    payload: dict = {"message": message, "stream": True}
    if conversation_id is not None:
        payload["conversation_id"] = conversation_id
    return sse_request(f"/agents/{AGENT_ID}/chat", payload, state["token"])


def resolve(loop_run_id: int, approved: bool):
    return sse_request(f"/agents/{AGENT_ID}/runs/{loop_run_id}/resolve", {"approved": approved}, state["token"])


def begin_waiting(label: str) -> dict | None:
    """走一次 SSE 首答，期待它在写工具处挂起；返回挂起信息。"""
    status, events = start_chat(label)
    if not isinstance(events, list):
        check(f"{label}：SSE 返回事件流", False, f"status={status} body={events}")
        return None
    check(f"{label}：SSE 首答 200", status == 200, status)
    cards = [event for event in events if event.get("type") == "confirmation_required"]
    check(f"{label}：恰好一张确认卡", len(cards) == 1, f"数量={len(cards)} 事件={event_types(events)[:8]}")
    if not cards:
        return None
    card = cards[0]
    inner = payload_of(card)
    call_id = inner.get("callId")
    confirmation_id = inner.get("confirmationId")
    loop_run_id = inner.get("loopRunId")
    check(f"{label}：卡上有 callId", bool(call_id), call_id)
    check(f"{label}：卡上有 confirmationId", isinstance(confirmation_id, int), confirmation_id)
    check(f"{label}：卡上有 loopRunId", isinstance(loop_run_id, int), loop_run_id)
    check(f"{label}：sideEffect=write", inner.get("sideEffect") == "write", inner.get("sideEffect"))
    check(f"{label}：expiresAt 非空", bool(inner.get("expiresAt")), inner.get("expiresAt"))
    arguments = (inner.get("summary") or {}).get("arguments")
    check(f"{label}：卡上带 arguments", isinstance(arguments, dict) and bool(arguments), arguments)
    if not isinstance(loop_run_id, int):
        return None

    conversation_id = card.get("conversationId")
    if conversation_id is not None:
        state["probe_conversations"].append(int(conversation_id))

    check(f"{label}：运行停在 waiting_confirmation",
          psql(f"select status from agent_loop_runs where id = {loop_run_id}") == "waiting_confirmation",
          psql(f"select status from agent_loop_runs where id = {loop_run_id}"))
    checkpoint = psql("select status || '|' || (context::text <> '[]') from agent_loop_run_checkpoints "
                      f"where loop_run_id = {loop_run_id}")
    check(f"{label}：检查点 pending 且带上下文", checkpoint == "pending|true", checkpoint)

    finals = [event for event in events if event.get("type") == "message_completed"]
    wire_status = None
    if finals:
        wire_status = (payload_of(finals[-1]).get("loop") or {}).get("status")
    check(f"{label}：出站终态如实 waiting_confirmation", wire_status == "waiting_confirmation", wire_status)
    return {
        "loop_run_id": loop_run_id,
        "confirmation_id": confirmation_id,
        "conversation_id": int(conversation_id) if conversation_id is not None else None,
    }


def checkpoint_row(loop_run_id: int) -> str:
    return psql("select status || '|' || (context::text <> '[]') from agent_loop_run_checkpoints "
                f"where loop_run_id = {loop_run_id}")


def scenario_approve() -> None:
    section("AC1/AC2/AC4 批准：弹卡 → 解决 → 真续跑 → 二次解决被拒")
    waiting = begin_waiting("AC1+2 请帮我创建一个定时任务。")
    if waiting is None:
        return
    loop_run_id = waiting["loop_run_id"]
    before = tasks_count()

    status, events = resolve(loop_run_id, True)
    check("AC2：解决端点返回 SSE", status == 200 and isinstance(events, list), status)
    if not isinstance(events, list):
        return
    types = event_types(events)
    check("AC2：续跑流里有 message_delta", "message_delta" in types, types[:8])
    check("AC2：续跑流不再弹确认卡", "confirmation_required" not in types)
    check("AC2：续跑流以 message_completed 收尾", types[-1] == "message_completed", types[-3:])
    after = tasks_count()
    check("AC2：批准后任务行 +1", after == before + 1, f"{before} -> {after}")
    check("AC2：检查点 consumed 且上下文已清空", checkpoint_row(loop_run_id) == "consumed|false",
          checkpoint_row(loop_run_id))
    loop_status = psql(f"select status from agent_loop_runs where id = {loop_run_id}")
    check("AC2：续跑后运行 completed", loop_status == "completed", loop_status)

    status, body = resolve(loop_run_id, True)
    check("AC4：二次解决返回 409", status == 409, f"status={status} body={body}")
    if isinstance(body, dict):
        check("AC4：错误码 run_confirmation_already_resolved",
              body.get("error_code") == "run_confirmation_already_resolved", body.get("error_code"))
    state["approved_conversation_id"] = waiting["conversation_id"]


def scenario_reject() -> None:
    section("AC3 拒绝：不执行工具但也续跑")
    waiting = begin_waiting("AC3 请帮我创建一个定时任务。")
    if waiting is None:
        return
    loop_run_id = waiting["loop_run_id"]
    before = tasks_count()
    status, events = resolve(loop_run_id, False)
    check("AC3：解决端点返回 SSE", status == 200 and isinstance(events, list), status)
    if not isinstance(events, list):
        return
    types = event_types(events)
    check("AC3：拒绝后也续跑（有 message_delta）", "message_delta" in types, types[:8])
    check("AC3：续跑流以 message_completed 收尾", types[-1] == "message_completed", types[-3:])
    after = tasks_count()
    check("AC3：任务行未新增", after == before, f"{before} -> {after}")
    check("AC3：检查点 consumed", checkpoint_row(loop_run_id) == "consumed|false", checkpoint_row(loop_run_id))
    loop_status = psql(f"select status from agent_loop_runs where id = {loop_run_id}")
    check("AC3：运行 completed", loop_status == "completed", loop_status)


def scenario_expired() -> None:
    section("AC5 过期：惰性收尾 + 稳定错误码")
    waiting = begin_waiting("AC5 请帮我创建一个定时任务。")
    if waiting is None:
        return
    loop_run_id = waiting["loop_run_id"]
    psql("update agent_loop_run_checkpoints set expires_at = now() - interval '1 minute' "
         f"where loop_run_id = {loop_run_id}")
    before = tasks_count()
    status, body = resolve(loop_run_id, True)
    check("AC5：过期解决返回 409", status == 409, f"status={status} body={body}")
    if isinstance(body, dict):
        check("AC5：错误码 run_confirmation_expired",
              body.get("error_code") == "run_confirmation_expired", body.get("error_code"))
    after = tasks_count()
    check("AC5：工具未执行", after == before, f"{before} -> {after}")
    check("AC5：检查点标记 expired", psql("select status from agent_loop_run_checkpoints "
                                          f"where loop_run_id = {loop_run_id}") == "expired")
    check("AC5：运行被标记 cancelled",
          psql(f"select status from agent_loop_runs where id = {loop_run_id}") == "cancelled")


def scenario_memory() -> None:
    section("AC6 确认记忆：同一会话内不再弹卡")
    conversation_id = state.get("approved_conversation_id")
    if conversation_id is None:
        check("AC6：可复用 AC2 的会话", False, "AC2 未建立会话")
        return
    before = tasks_count()
    status, events = start_chat("AC6 请帮我再创建一个定时任务。", conversation_id=conversation_id)
    check("AC6：SSE 返回事件流", status == 200 and isinstance(events, list), status)
    if not isinstance(events, list):
        return
    types = event_types(events)
    check("AC6：不再弹确认卡", "confirmation_required" not in types, types[:8])
    check("AC6：以 message_completed 收尾", types[-1] == "message_completed", types[-3:])
    after = tasks_count()
    check("AC6：工具直接执行（任务 +1）", after == before + 1, f"{before} -> {after}")


def scenario_rest_no_channel() -> None:
    section("AC7 非流式通路：无确认通道，拒绝并告知")
    before = tasks_count()
    status, body = call("POST", f"/agents/{AGENT_ID}/chat", state["token"],
                        {"message": "AC7 请帮我创建一个定时任务。", "stream": False})
    check("AC7：非流式返回 200", status == 200, f"status={status} body={str(body)[:160]}")
    after = tasks_count()
    check("AC7：任务行未新增", after == before, f"{before} -> {after}")
    raw = psql("select coalesce(output_summary,'') || '|' || coalesce(metadata::text,'') "
               "from agent_loop_steps where tool_name = 'create_task' order by id desc limit 1")
    check("AC7：工具结果含 no_confirmation_channel", "no_confirmation_channel" in raw, raw[:200])


def scenario_ownership() -> None:
    section("AC8 归属/存在性：不泄露他人运行")
    status, body = resolve(10_000_000 + (datetime.now(timezone.utc).microsecond or 1), True)
    check("AC8：不存在的运行返回 404", status == 404, f"status={status} body={body}")
    if isinstance(body, dict):
        check("AC8：错误码 run_confirmation_not_found",
              body.get("error_code") == "run_confirmation_not_found", body.get("error_code"))


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main() -> int:
    lock = acquire_lock()
    if lock is None:
        print(f"已有另一个探针进程在运行（锁 {LOCK_PATH} 被占用）——本次直接退出。")
        return 3
    try:
        setup()
        scenario_approve()
        scenario_reject()
        scenario_expired()
        scenario_memory()
        scenario_rest_no_channel()
        scenario_ownership()
    finally:
        try:
            cleanup()
        except Exception as error:  # noqa: BLE001 - 收尾失败不应掩盖断言结论
            print(f"  收尾时出错：{error}")
        lock.close()

    print()
    if state["failures"]:
        print(f"PROBE_RESULT: 失败 {state['failures']} 项")
        return 1
    print("PROBE_RESULT: 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
