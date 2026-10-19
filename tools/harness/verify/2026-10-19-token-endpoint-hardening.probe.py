#!/usr/bin/env python3
"""2026-10-19-token-endpoint-hardening 的真进程探针：dev server 同源 token 代理。

做三件事：
1. 从 ``apps/backend/.env`` 读 Embed 配置，挑一个空闲端口在 ``apps/ai-sdk`` 起 vite dev server；
2. 请求同源 ``POST /demo-api/agent-token``，断言拿到 200 与 ``data.access_token``；
3. 断言 ``GET /demo-api/agent-token`` 返回 405（代理只接受 POST）。

退出码：0 通过；1 失败；3 未执行（缺少 Embed 环境变量）。
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ENV_FILE = ROOT / "apps" / "backend" / ".env"
SDK_DIR = ROOT / "apps" / "ai-sdk"
LOG = Path("/tmp/token-endpoint-hardening-vite.log")

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"{'通过' if ok else '失败'}：{label}{(' —— ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


def read_embed_env() -> dict[str, str]:
    """只取 dev 代理需要的四个变量；不在仓库里记录任何密钥值。"""
    wanted = {"EMBED_CLIENT_ID", "EMBED_CLIENT_SECRET", "EMBED_AGENT_ID", "EMBED_ORIGIN"}
    values: dict[str, str] = {}
    if not ENV_FILE.exists():
        return values
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key in wanted:
            values[key] = value.strip().strip("'\"")
    return values


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


# 显式绕过系统 HTTP 代理：macOS 上若开了系统代理（scutil --proxy 的 HTTPProxy/HTTPPort），
# urllib 会读它并把 localhost 请求也发过去，得到 502 空响应；curl / http.client 不走该代理，
# 会出现「同一路径 curl 200、urllib 502」的假失败。探针只测本机端口，一律直连。
_NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def request(method: str, url: str, payload: dict | None = None) -> tuple[int, str]:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with _NO_PROXY_OPENER.open(req, timeout=30) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", "replace")
    except urllib.error.URLError as error:
        # dev server 尚未监听时是 ConnectionRefused（就绪轮询要据此重试），返回 0 而不是抛异常
        return 0, str(error)


def main() -> int:
    env = read_embed_env()
    if not env.get("EMBED_CLIENT_ID") or not env.get("EMBED_CLIENT_SECRET"):
        print("未执行：apps/backend/.env 缺少 EMBED_CLIENT_ID / EMBED_CLIENT_SECRET，无法启动 dev 代理。")
        return 3

    port = free_port()
    base = f"http://localhost:{port}"
    child_env = {
        **os.environ,
        "EMBED_CLIENT_ID": env["EMBED_CLIENT_ID"],
        "EMBED_CLIENT_SECRET": env["EMBED_CLIENT_SECRET"],
        "EMBED_AGENT_ID": env.get("EMBED_AGENT_ID") or "1",
        "EMBED_ORIGIN": env.get("EMBED_ORIGIN") or "http://localhost:8080",
    }
    print(f"启动 vite dev server：端口 {port}，日志 {LOG}")
    log_handle = LOG.open("wb")
    process = subprocess.Popen(
        ["npx", "vite", "--port", str(port), "--strictPort"],
        cwd=str(SDK_DIR),
        env=child_env,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        ready = False
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            if process.poll() is not None:
                break
            status, _ = request("GET", f"{base}/demo/index.html")
            if status == 200:
                ready = True
                break
            time.sleep(1)
        if not ready:
            log_handle.flush()
            tail = LOG.read_text(encoding="utf-8", errors="replace")[-1500:] if LOG.exists() else ""
            check("dev server 就绪", False, f"90 秒内未就绪；日志尾部：\n{tail}")
            return 1
        check("dev server 就绪（/demo/index.html 返回 200）", True)

        status, body = request(
            "POST",
            f"{base}/demo-api/agent-token",
            {
                "agent_id": env.get("EMBED_AGENT_ID") or "1",
                "external_user_id": "probe-token-endpoint",
                "origin": env.get("EMBED_ORIGIN") or "http://localhost:8080",
            },
        )
        token = ""
        if status == 200:
            try:
                token = json.loads(body)["data"]["access_token"]
            except Exception:  # noqa: BLE001 - 探针只关心结论
                token = ""
        check(
            "同源代理 POST /demo-api/agent-token 返回 200 且带 access_token",
            status == 200 and bool(token),
            f"status={status} body={body[:200]}",
        )
        if token:
            print(f"（已取回 token，长度 {len(token)}，未打印内容）")

        status, body = request("GET", f"{base}/demo-api/agent-token")
        check(
            "同源代理拒绝非 POST（405）",
            status == 405,
            f"status={status} body={body[:120]}",
        )

        status, body = request("POST", f"{base}/demo-api/agent-token", {"agent_id": 0})
        check(
            "缺少可用 agent_id 时返回 400",
            status == 400,
            f"status={status} body={body[:120]}",
        )
    finally:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        except Exception:  # noqa: BLE001 - 收尾尽力而为
            process.terminate()
        try:
            process.wait(timeout=10)
        except Exception:  # noqa: BLE001
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        log_handle.close()

    if failures:
        print(f"探针失败项：{failures}")
        return 1
    print("探针全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
