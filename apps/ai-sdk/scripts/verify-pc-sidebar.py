#!/usr/bin/env python3
"""用 Chrome DevTools Protocol 驱动 PC 双栏会话列表验证页。

不依赖 playwright/puppeteer：直接连 CDP 的 WebSocket，执行 JS 探针
（页面暴露的 window.__probe）并断言布局与交互结果。
"""

import asyncio
import json
import subprocess
import sys
import time
import urllib.request

import websockets

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT = 9335
PROFILE_DIR = "/tmp/xxai-cdp-verify-sidebar"
URL = "http://127.0.0.1:8791/demo/pc-sidebar.html"


def launch_chrome():
    # `--headless=new` 在本机沙箱下会因 crashpad 无法访问而崩溃，沿用旧
    # headless 模式并显式关闭沙箱；CDP 能力足够本次断言。
    return subprocess.Popen(
        [
            CHROME,
            "--headless",
            f"--remote-debugging-port={PORT}",
            "--no-sandbox",
            "--disable-gpu",
            "--disable-crash-reporter",
            "--no-first-run",
            "--no-default-browser-check",
            "--remote-allow-origins=*",
            f"--user-data-dir={PROFILE_DIR}",
            URL,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def wait_for_target(timeout=25):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/list") as resp:
                targets = json.load(resp)
            for target in targets:
                if target.get("type") == "page" and "pc-sidebar" in target.get("url", ""):
                    return target["webSocketDebuggerUrl"]
        except Exception:
            pass
        time.sleep(0.4)
    raise RuntimeError("CDP target not found")


class Session:
    def __init__(self, ws):
        self.ws = ws
        self.counter = 0

    async def call(self, method, params=None):
        self.counter += 1
        message_id = self.counter
        await self.ws.send(json.dumps({"id": message_id, "method": method, "params": params or {}}))
        while True:
            raw = json.loads(await self.ws.recv())
            if raw.get("id") == message_id:
                if "error" in raw:
                    raise RuntimeError(f"{method} failed: {raw['error']}")
                return raw.get("result", {})

    async def evaluate(self, expression):
        result = await self.call(
            "Runtime.evaluate",
            {"expression": expression, "awaitPromise": True, "returnByValue": True},
        )
        return result.get("result", {}).get("value")

    async def set_viewport(self, width, height):
        """用 CDP 覆盖视口尺寸。

        Chrome 默认 headless 窗口只有 756px 宽，若不覆盖，1000px 的验证
        容器会被压缩到 768px 断点以下，导致「宽屏」用例实际测的是窄屏。
        """
        await self.call(
            "Emulation.setDeviceMetricsOverride",
            {
                "width": width,
                "height": height,
                "deviceScaleFactor": 1,
                "mobile": False,
            },
        )


async def main():
    chrome = launch_chrome()
    failures = []
    try:
        ws_url = wait_for_target()
        # macOS 系统代理会劫持 127.0.0.1 的 CDP 连接，本地调试端口必须绕过代理。
        async with websockets.connect(
            ws_url, max_size=20 * 1024 * 1024, proxy=None
        ) as ws:
            session = Session(ws)
            await session.call("Runtime.enable")
            # 先给一个真实宽屏视口：组件按渲染宽度判断断点，默认 headless
            # 窗口只有 756px，不覆盖会把「宽屏」用例误判成窄屏。
            await session.set_viewport(1280, 900)
            # 等页面模块加载并完成首次渲染。
            for _ in range(40):
                ready = await session.evaluate("Boolean(window.__probe)")
                if ready:
                    break
                await asyncio.sleep(0.25)
            await asyncio.sleep(1.0)

            def check(name, condition, detail):
                status = "PASS" if condition else "FAIL"
                print(f"[{status}] {name}: {detail}")
                if not condition:
                    failures.append(name)

            state = await session.evaluate("window.__probe()")
            print("probe(wide, desktop) =", json.dumps(state, ensure_ascii=False))
            check("宽屏渲染左侧会话列表", state["hasSidebar"], f"hasSidebar={state['hasSidebar']}")
            check(
                "列表宽度落在 200-360 区间",
                200 <= state["sidebarWidth"] <= 360,
                f"width={state['sidebarWidth']}",
            )
            check(
                "窗口带 desktop 类名",
                "xxai-chat-window--desktop" in state["windowClass"],
                state["windowClass"],
            )
            check(
                "列表展示两个会话标题",
                state["itemTitles"] == ["订单查询", "退款流程"],
                str(state["itemTitles"]),
            )

            # 点击第一个会话 -> 应加载该会话历史。
            await session.evaluate(
                "document.querySelectorAll('.xxai-sidebar-item')[0].click()"
            )
            await asyncio.sleep(0.8)
            state = await session.evaluate("window.__probe()")
            print("probe(after select #1) =", json.dumps(state, ensure_ascii=False))
            check(
                "点击会话后加载对应历史消息",
                state["messages"] == ["我的订单到哪了？", "你的订单已发货。"],
                str(state["messages"]),
            )
            check(
                "当前会话在列表中高亮",
                state["activeTitle"] == "订单查询",
                str(state["activeTitle"]),
            )

            # 切到第二个会话 -> 历史必须整体替换，不能与上一个会话叠加。
            await session.evaluate(
                "document.querySelectorAll('.xxai-sidebar-item')[1].click()"
            )
            await asyncio.sleep(0.8)
            state = await session.evaluate("window.__probe()")
            print("probe(after select #2) =", json.dumps(state, ensure_ascii=False))
            check(
                "切换会话后历史被整体替换（无串台）",
                state["messages"] == ["怎么退款？"],
                str(state["messages"]),
            )

            # 删除第二个会话 -> 列表少一项，且当前会话回落。
            await session.evaluate(
                "document.querySelectorAll('.xxai-sidebar-delete')[1].click()"
            )
            await asyncio.sleep(0.9)
            state = await session.evaluate("window.__probe()")
            print("probe(after delete) =", json.dumps(state, ensure_ascii=False))
            check(
                "删除后列表移除该项",
                state["itemTitles"] == ["订单查询"],
                str(state["itemTitles"]),
            )
            check(
                "删除当前会话后回到新建态",
                state["messages"] == [] and state["activeTitle"] is None,
                f"messages={state['messages']} active={state['activeTitle']}",
            )

            # 新建会话 -> 清空消息区。
            await session.evaluate(
                "document.querySelectorAll('.xxai-sidebar-item')[0].click()"
            )
            await asyncio.sleep(0.6)
            await session.evaluate(
                "document.querySelector('.xxai-sidebar-icon-btn').click()"
            )
            await asyncio.sleep(0.8)
            state = await session.evaluate("window.__probe()")
            print("probe(after create) =", json.dumps(state, ensure_ascii=False))
            check(
                "新建会话清空消息区",
                state["messages"] == [] and state["activeTitle"] is None,
                f"messages={state['messages']} active={state['activeTitle']}",
            )

            # 窄屏降级：列表应收起为抽屉（默认不渲染常驻侧栏）。
            # 同时收窄视口与容器，模拟真实窄屏而非只压缩容器宽度。
            await session.set_viewport(520, 900)
            await session.evaluate(
                "document.querySelector('[data-width=\"520\"]').click()"
            )
            await asyncio.sleep(1.0)
            state = await session.evaluate("window.__probe()")
            print("probe(narrow 520) =", json.dumps(state, ensure_ascii=False))
            check("窄屏收起常驻列表", not state["hasSidebar"], f"hasSidebar={state['hasSidebar']}")

            # 抽屉按钮可展开列表。
            await session.evaluate(
                "document.querySelector('.xxai-chat-main .xxai-header-icon-btn').click()"
            )
            await asyncio.sleep(0.7)
            state = await session.evaluate("window.__probe()")
            print("probe(narrow drawer open) =", json.dumps(state, ensure_ascii=False))
            check("窄屏可展开抽屉列表", state["hasSidebar"], f"hasSidebar={state['hasSidebar']}")

            # 切回 single 布局：列表应完全消失，回到既有单栏行为。
            await session.set_viewport(1280, 900)
            await session.evaluate(
                "document.querySelector('[data-width=\"1000\"]').click()"
            )
            await asyncio.sleep(0.5)
            await session.evaluate("document.getElementById('toggle-layout').click()")
            await asyncio.sleep(1.2)
            state = await session.evaluate("window.__probe()")
            print("probe(single layout) =", json.dumps(state, ensure_ascii=False))
            check(
                "single 布局不渲染会话列表",
                not state["hasSidebar"] and "desktop" not in state["windowClass"],
                f"hasSidebar={state['hasSidebar']} class={state['windowClass']}",
            )
    finally:
        chrome.terminate()
        try:
            chrome.wait(timeout=5)
        except subprocess.TimeoutExpired:
            chrome.kill()

    print()
    if failures:
        print(f"FAILED: {len(failures)} 项 -> {failures}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
