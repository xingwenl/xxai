#!/usr/bin/env python3
"""用 Chrome DevTools Protocol 驱动 PC 双栏会话列表验证页。

不依赖 playwright/puppeteer：直接连 CDP 的 WebSocket，执行 JS 探针
（页面暴露的 window.__probe）并断言布局与交互结果。
"""

import asyncio
import json
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

import websockets

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT = 9335
URL = "http://127.0.0.1:8791/demo/pc-sidebar.html"


def launch_chrome(profile_dir):
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
            f"--user-data-dir={profile_dir}",
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

    async def drag(self, selector, delta_x, delta_y):
        """对元素中心按下并拖拽，模拟真实指针操作（用于缩放/拖拽断言）。"""
        box = await self.evaluate(
            "(() => { const h = document.querySelector('%s'); if (!h) return null;"
            " const r = h.getBoundingClientRect();"
            " return { x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2) } })()"
            % selector
        )
        if not box:
            return False
        x, y = box["x"], box["y"]
        await self.call(
            "Input.dispatchMouseEvent",
            {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1, "buttons": 1},
        )
        for step in range(1, 9):
            await self.call(
                "Input.dispatchMouseEvent",
                {
                    "type": "mouseMoved",
                    "x": x + delta_x * step // 8,
                    "y": y + delta_y * step // 8,
                    "button": "left",
                    "buttons": 1,
                },
            )
            await asyncio.sleep(0.03)
        await self.call(
            "Input.dispatchMouseEvent",
            {"type": "mouseReleased", "x": x + delta_x, "y": y + delta_y, "button": "left", "buttons": 0},
        )
        await asyncio.sleep(0.4)
        return True

    async def window_size(self):
        return await self.evaluate(
            "(() => { const w = document.querySelector('.xxai-chat-window').getBoundingClientRect();"
            " return { w: Math.round(w.width), h: Math.round(w.height), x: Math.round(w.left) } })()"
        )


async def main():
    # 每次运行都用全新 profile：悬浮窗尺寸会被持久化到 localStorage，复用
    # profile 会让上一轮拉宽的窗口矩形污染下一轮的窄窗断言。
    profile_dir = tempfile.mkdtemp(prefix="xxai-cdp-verify-")
    chrome = launch_chrome(profile_dir)
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

            # 双栏两侧必须同色：侧栏与主区都是半透明磨砂白，若窗口底色仍是
            # 彩色渐变，左右会分别透出偏蓝/偏绿（实测色差可达 8/255）。
            surfaces = await session.evaluate(
                """(() => {
                  const pick = (sel) => {
                    const el = document.querySelector(sel)
                    if (!el) return null
                    const c = getComputedStyle(el)
                    return { bg: c.backgroundColor, blur: c.backdropFilter }
                  }
                  const head = (sel) => {
                    const el = document.querySelector(sel)
                    if (!el) return null
                    const c = getComputedStyle(el)
                    const r = el.getBoundingClientRect()
                    return {
                      h: Math.round(r.height), bg: c.backgroundColor, shadow: c.boxShadow,
                      blur: c.backdropFilter, gap: c.gap, pad: c.padding,
                      border: c.borderBottomWidth + ' ' + c.borderBottomColor,
                    }
                  }
                  const btn = (sel) => {
                    const el = document.querySelector(sel)
                    if (!el) return null
                    const c = getComputedStyle(el)
                    const r = el.getBoundingClientRect()
                    return { w: Math.round(r.width), h: Math.round(r.height), bg: c.backgroundColor, radius: c.borderRadius }
                  }
                  const title = (sel) => {
                    const el = document.querySelector(sel)
                    if (!el) return null
                    const c = getComputedStyle(el)
                    return { size: c.fontSize, weight: c.fontWeight, color: c.color }
                  }
                  const win = getComputedStyle(document.querySelector('.xxai-chat-window'))
                  return {
                    main: pick('.xxai-chat-main'),
                    sidebar: pick('.xxai-conversation-sidebar'),
                    header: pick('.xxai-chat-header'),
                    sidebarHead: pick('.xxai-sidebar-head'),
                    headerFull: head('.xxai-chat-header'),
                    sidebarHeadFull: head('.xxai-sidebar-head'),
                    headerBtn: btn('.xxai-chat-header .xxai-header-icon-btn'),
                    sidebarBtn: btn('.xxai-sidebar-icon-btn'),
                    headerTitle: title('.xxai-header-name'),
                    sidebarTitle: title('.xxai-sidebar-title'),
                    windowImage: win.backgroundImage
                  }
                })()"""
            )
            print("surfaces =", json.dumps(surfaces, ensure_ascii=False))
            check(
                "主视图与会话列表底色一致",
                surfaces["main"]["bg"] == surfaces["sidebar"]["bg"],
                f"main={surfaces['main']['bg']} sidebar={surfaces['sidebar']['bg']}",
            )
            check(
                "两栏标题区底色一致",
                surfaces["header"]["bg"] == surfaces["sidebarHead"]["bg"],
                f"header={surfaces['header']['bg']} sidebarHead={surfaces['sidebarHead']['bg']}",
            )
            # 头部整体风格对齐：高度、内边距、间距、边框、无投影/模糊
            header_keys = ("h", "bg", "shadow", "blur", "gap", "pad", "border")
            header_diff = {
                k: (surfaces["headerFull"][k], surfaces["sidebarHeadFull"][k])
                for k in header_keys
                if surfaces["headerFull"][k] != surfaces["sidebarHeadFull"][k]
            }
            check(
                "聊天 header 与会话列表 header 样式一致",
                not header_diff,
                json.dumps(header_diff, ensure_ascii=False) if header_diff else "全部一致",
            )
            check(
                "两栏头部图标按钮一致",
                surfaces["headerBtn"] == surfaces["sidebarBtn"],
                f"chat={surfaces['headerBtn']} sidebar={surfaces['sidebarBtn']}",
            )
            check(
                "两栏标题字号字重一致",
                surfaces["headerTitle"] == surfaces["sidebarTitle"],
                f"chat={surfaces['headerTitle']} sidebar={surfaces['sidebarTitle']}",
            )
            check(
                "双栏窗口不再使用彩色渐变底",
                surfaces["windowImage"] == "none",
                surfaces["windowImage"][:60],
            )
            check(
                "主视图同样启用磨砂模糊",
                surfaces["main"]["blur"] == surfaces["sidebar"]["blur"],
                f"main={surfaces['main']['blur']} sidebar={surfaces['sidebar']['blur']}",
            )

            # 输入区：组件 scoped 样式曾引用本 SDK 未定义的 --xxai-surface /
            # --xxai-muted / --xxai-border / --xxai-primary，全部落到硬编码灰色，
            # 并与全局 .xxai-chat-input button 规则叠加出「40×32 + 圆角 6px」的
            # 畸形态。这里固定收敛后的契约。
            input_area = await session.evaluate(
                """(() => {
                  const box = (sel) => {
                    const el = document.querySelector(sel)
                    if (!el) return null
                    const c = getComputedStyle(el)
                    const r = el.getBoundingClientRect()
                    return { w: Math.round(r.width), h: Math.round(r.height),
                             bg: c.backgroundColor, radius: c.borderRadius,
                             border: c.borderTopWidth + ' ' + c.borderTopColor }
                  }
                  return {
                    wrapper: box('.xxai-chat-input-wrapper'),
                    field: box('.xxai-chat-input input[type=text]'),
                    attach: box('.xxai-attach-button'),
                    send: box('.xxai-send-button'),
                    headerBtn: box('.xxai-chat-header .xxai-header-icon-btn')
                  }
                })()"""
            )
            print("input area =", json.dumps(input_area, ensure_ascii=False))
            check(
                "输入区按钮尺寸统一（附件与发送一致）",
                input_area["attach"]["w"] == input_area["send"]["w"]
                and input_area["attach"]["h"] == input_area["send"]["h"],
                f"attach={input_area['attach']['w']}x{input_area['attach']['h']} "
                f"send={input_area['send']['w']}x{input_area['send']['h']}",
            )
            check(
                "输入区按钮为圆形而非畸形态",
                input_area["attach"]["radius"] == "50%" and input_area["send"]["radius"] == "50%",
                f"attach={input_area['attach']['radius']} send={input_area['send']['radius']}",
            )
            check(
                "附件按钮为磨砂底而非蓝色强调",
                "rgba(255, 255, 255" in input_area["attach"]["bg"],
                input_area["attach"]["bg"],
            )
            check(
                "输入框有可见描边（非近白不可见）",
                input_area["field"]["border"].startswith("1px")
                and "100, 116, 139" in input_area["field"]["border"],
                input_area["field"]["border"],
            )
            check(
                "输入框为白底胶囊",
                input_area["field"]["bg"] == "rgb(255, 255, 255)"
                and input_area["field"]["radius"] == "21px",
                f"bg={input_area['field']['bg']} radius={input_area['field']['radius']}",
            )
            # 输入框白色胶囊必须与浅灰外框有可辨差异，否则轮廓消失。
            check(
                "输入框与外框底色有可辨差异",
                input_area["field"]["bg"] != input_area["wrapper"]["bg"],
                f"field={input_area['field']['bg']} wrapper={input_area['wrapper']['bg']}",
            )
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

            # 用户报的问题：在新建态发一条消息后，左侧列表没有刷新出这个新会话。
            calls_before = state["listCalls"]
            await session.evaluate(
                "window.__sendAndComplete('新会话第一句', '9001')"
            )
            await asyncio.sleep(1.2)
            state = await session.evaluate("window.__probe()")
            print("probe(after first message) =", json.dumps(state, ensure_ascii=False))
            check(
                "发首条消息后新会话出现在列表",
                "新会话第一句" in state["itemTitles"],
                str(state["itemTitles"]),
            )
            check(
                "发首条消息后当前会话高亮到新会话",
                state["activeTitle"] == "新会话第一句",
                f"active={state['activeTitle']} conversationId={state['conversationId']}",
            )
            check(
                "发首条消息确实触发了列表刷新",
                state["listCalls"] > calls_before,
                f"before={calls_before} after={state['listCalls']}",
            )

            # 回答完成后应再刷新一次，让消息数与末条摘要更新；但不该每帧都刷。
            calls_after_start = state["listCalls"]
            await session.evaluate(
                "window.__sendAndComplete('第二句', '9001')"
            )
            await asyncio.sleep(1.2)
            state = await session.evaluate("window.__probe()")
            print("probe(after second message) =", json.dumps(state, ensure_ascii=False))
            check(
                "同一会话内发消息不会重复堆叠列表项",
                state["itemTitles"].count("新会话第一句") == 1,
                str(state["itemTitles"]),
            )
            check(
                "回答完成后刷新了列表",
                state["listCalls"] > calls_after_start,
                f"before={calls_after_start} after={state['listCalls']}",
            )

            # 窄屏降级：断点看「面板自身宽度」。这里刻意保持宽视口（1400）
            # 只收窄容器，用来证明降级不依赖 window.innerWidth。
            await session.set_viewport(1400, 900)
            await session.evaluate(
                "document.querySelector('[data-width=\"520\"]').click()"
            )
            await asyncio.sleep(1.2)
            state = await session.evaluate("window.__probe()")
            print("probe(narrow panel) =", json.dumps(state, ensure_ascii=False))
            check(
                "窄面板收起常驻列表（宽视口下仍降级）",
                not state["hasSidebar"],
                f"hasSidebar={state['hasSidebar']} innerWidth={state['innerWidth']}",
            )

            # 抽屉按钮可展开列表。
            await session.evaluate(
                "document.querySelector('.xxai-chat-main .xxai-header-icon-btn').click()"
            )
            await asyncio.sleep(0.7)
            state = await session.evaluate("window.__probe()")
            print("probe(narrow drawer open) =", json.dumps(state, ensure_ascii=False))
            check("窄面板可展开抽屉列表", state["hasSidebar"], f"hasSidebar={state['hasSidebar']}")

            # floating 模式：双栏必须按悬浮窗自身宽度判断，而不是浏览器视口。
            # 430px 悬浮窗 + 260px 常驻列表会把对话区挤到 170px，必须降级。
            await session.evaluate(
                "document.querySelector('[data-width=\"1000\"]').click()"
            )
            await asyncio.sleep(0.5)
            await session.evaluate("document.getElementById('toggle-mode').click()")
            await asyncio.sleep(1.4)
            state = await session.evaluate("window.__probe()")
            print("probe(floating 430) =", json.dumps(state, ensure_ascii=False))
            check(
                "floating 窄窗(430px)不渲染常驻列表",
                state["mode"] == "floating" and not state["hasSidebar"],
                f"mode={state['mode']} hasSidebar={state['hasSidebar']} window={state['windowWidth']}",
            )

            # 把悬浮窗拉宽到 900px：应出现常驻列表，且对话区仍有余量。
            await session.evaluate(
                "document.querySelector('[data-float-width=\"900\"]').click()"
            )
            await asyncio.sleep(1.6)
            state = await session.evaluate("window.__probe()")
            print("probe(floating 900) =", json.dumps(state, ensure_ascii=False))
            check(
                "floating 宽窗(900px)渲染常驻列表",
                state["hasSidebar"] and state["sidebarWidth"] >= 200,
                f"hasSidebar={state['hasSidebar']} sidebar={state['sidebarWidth']}",
            )
            check(
                "floating 宽窗下对话区仍有可用宽度",
                state["chatAreaWidth"] >= 400,
                f"chatArea={state['chatAreaWidth']} window={state['windowWidth']}",
            )

            # 缩放回归：曾因双栏断点把面板宽度写回 viewportWidth，导致缩放
            # 自反馈把窗口缩到 240px（低于 320 最小宽度）。这里实测拖拽。
            # 先把窗口往左上挪，留出向右放大的空间。
            await session.drag(".xxai-chat-header", -320, -220)
            moved = await session.window_size()
            print("after move =", json.dumps(moved, ensure_ascii=False))
            check(
                "移动后窗口位置改变",
                moved["x"] < state["innerWidth"],
                f"x={moved['x']}",
            )

            grew_ok = await session.drag(".xxai-window-resize-handle", 220, 120)
            grew = await session.window_size()
            print("after grow =", json.dumps(grew, ensure_ascii=False))
            check(
                "向右下拖拽缩放柄可放大窗口",
                grew_ok and grew["w"] > moved["w"] and grew["h"] > moved["h"],
                f"{moved['w']}x{moved['h']} -> {grew['w']}x{grew['h']}",
            )

            # 连续向内缩到极限：必须停在最小宽度 320，不能塌到 240。
            for _ in range(4):
                await session.drag(".xxai-window-resize-handle", -260, -260)
            shrunk = await session.window_size()
            print("after repeated shrink =", json.dumps(shrunk, ensure_ascii=False))
            check(
                "连续缩小停在最小尺寸(320x480)而不塌陷",
                shrunk["w"] == 320 and shrunk["h"] == 480,
                f"{shrunk['w']}x{shrunk['h']} (expect 320x480)",
            )

            # 切回 embedded + single 布局：列表应完全消失，回到既有单栏行为。
            await session.set_viewport(1280, 900)
            await session.evaluate("document.getElementById('toggle-mode').click()")
            await asyncio.sleep(1.0)
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
                state["mode"] == "embedded"
                and not state["hasSidebar"]
                and "desktop" not in state["windowClass"],
                f"mode={state['mode']} hasSidebar={state['hasSidebar']} class={state['windowClass']}",
            )
            # 单栏（含既有悬浮窗）必须保留原来的彩色渐变底，本次配色改动
            # 只作用于双栏。
            single_bg = await session.evaluate(
                "getComputedStyle(document.querySelector('.xxai-chat-window')).backgroundImage"
            )
            check(
                "single 布局保留原有彩色渐变底",
                "linear-gradient" in single_bg,
                single_bg[:60],
            )
    finally:
        chrome.terminate()
        try:
            chrome.wait(timeout=5)
        except subprocess.TimeoutExpired:
            chrome.kill()
        shutil.rmtree(profile_dir, ignore_errors=True)

    print()
    if failures:
        print(f"FAILED: {len(failures)} 项 -> {failures}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
