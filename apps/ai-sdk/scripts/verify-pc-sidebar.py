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

    async def element_center(self, selector):
        return await self.evaluate(
            "(() => { const el = document.querySelector('%s'); if (!el) return null;"
            " const r = el.getBoundingClientRect();"
            " return { x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2) } })()"
            % selector
        )

    async def click_at(self, x, y, settle=0.5):
        """在视口绝对坐标上做一次真实指针点击。

        `Session.drag` 只能点元素中心，遮罩这类「需要避开某个子区域」的点击
        必须自己给坐标；并且只有真实指针事件才走浏览器命中测试，合成
        `element.click()` 会绕过命中测试，测不出「按钮被挡住」这类问题。
        `settle` 置 0 用于紧接着采样过渡动画的中间帧。
        """
        await self.call(
            "Input.dispatchMouseEvent",
            {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1, "buttons": 1},
        )
        await asyncio.sleep(0.05)
        await self.call(
            "Input.dispatchMouseEvent",
            {"type": "mouseReleased", "x": x, "y": y, "button": "left", "buttons": 0},
        )
        if settle:
            await asyncio.sleep(settle)

    async def click_element(self, selector, settle=0.5):
        """真实指针点击元素中心。"""
        point = await self.element_center(selector)
        if not point:
            return False
        await self.click_at(point["x"], point["y"], settle=settle)
        return True

    async def sample_after_click(self, selector, expression, count=10, interval=0.04):
        """点击元素后连续采样表达式。

        过渡动画只靠「点完睡够再看终值」是测不出来的——瞬间跳变同样满足
        「最终宽度为 0」。这里在动画窗口内连续采样，用中间帧证明动画真的在跑。
        """
        point = await self.element_center(selector)
        if not point:
            return []
        await self.click_at(point["x"], point["y"], settle=0)
        samples = []
        for _ in range(count):
            samples.append(await self.evaluate(expression))
            await asyncio.sleep(interval)
        return samples


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
                # 只断言「白底 + 圆角」这一设计意图，不写死具体圆角值：
                # 半径属可自由微调的视觉参数（21px → 15px 都成立），
                # 写死会让合理的样式调整被误判为回归。
                input_area["field"]["bg"] == "rgb(255, 255, 255)"
                and input_area["field"]["radius"].endswith("px")
                and float(input_area["field"]["radius"][:-2]) >= 10,
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

            # header 头像左侧的收缩按钮：必须真的落在头像左边（而不是被塞进
            # 右侧动作区，或跟头像顺序颠倒），并带着可访问名称与展开态。
            toggle = await session.evaluate(
                """(() => {
                  const btn = document.querySelector('.xxai-chat-header .xxai-sidebar-toggle')
                  const avatar = document.querySelector('.xxai-chat-header .xxai-agent-avatar')
                  if (!btn || !avatar) return null
                  const b = btn.getBoundingClientRect()
                  const a = avatar.getBoundingClientRect()
                  return {
                    btnRight: Math.round(b.right),
                    avatarLeft: Math.round(a.left),
                    label: btn.getAttribute('aria-label'),
                    expanded: btn.getAttribute('aria-expanded'),
                    title: btn.getAttribute('title')
                  }
                })()"""
            )
            print("sidebar toggle =", json.dumps(toggle, ensure_ascii=False))
            check(
                "header 头像左侧存在会话列表开关",
                bool(toggle) and toggle["btnRight"] <= toggle["avatarLeft"],
                f"btnRight={toggle and toggle['btnRight']} avatarLeft={toggle and toggle['avatarLeft']}",
            )
            check(
                "开关带可访问名称与展开态",
                bool(toggle)
                and toggle["label"] == "隐藏会话列表"
                and toggle["title"] == "隐藏会话列表"
                and toggle["expanded"] == "true",
                json.dumps(toggle, ensure_ascii=False),
            )

            # 点击开关收起常驻列表：列表消失、空间让给对话区；但按钮本身必须
            # 留在 header 里，否则用户再也点不回来。
            sidebar_width_expr = (
                "(() => { const s = document.querySelector('.xxai-conversation-sidebar');"
                " return s ? Math.round(s.getBoundingClientRect().width) : 0 })()"
            )
            full_width = state["sidebarWidth"]
            chat_area_before = state["chatAreaWidth"]
            collapse_samples = await session.sample_after_click(
                ".xxai-sidebar-toggle", sidebar_width_expr
            )
            print("collapse width samples =", collapse_samples)
            check(
                "收起过程存在宽度过渡（逐帧收缩而非瞬间消失）",
                any(0 < w < full_width for w in collapse_samples),
                f"samples={collapse_samples} full={full_width}",
            )
            await asyncio.sleep(0.6)
            collapsed = await session.evaluate("window.__probe()")
            print("probe(sidebar collapsed) =", json.dumps(collapsed, ensure_ascii=False))
            check(
                "点击收缩按钮隐藏常驻会话列表",
                not collapsed["hasSidebar"],
                f"hasSidebar={collapsed['hasSidebar']}",
            )
            check(
                "收起后列表宽度归零且移出可聚焦范围",
                collapsed["sidebarWidth"] == 0 and collapsed["sidebarVisibility"] == "hidden",
                f"width={collapsed['sidebarWidth']} visibility={collapsed['sidebarVisibility']}",
            )
            check(
                "收起列表后对话区变宽",
                collapsed["chatAreaWidth"] > chat_area_before,
                f"{chat_area_before} -> {collapsed['chatAreaWidth']}",
            )
            collapsed_label = await session.evaluate(
                "(() => { const b = document.querySelector('.xxai-sidebar-toggle');"
                " return b ? b.getAttribute('aria-label') : null })()"
            )
            check(
                "收起后开关仍在且提示改为展开",
                collapsed_label == "显示会话列表",
                str(collapsed_label),
            )

            # 再点一次恢复常驻列表，展开同样必须是渐进的。
            expand_samples = await session.sample_after_click(
                ".xxai-sidebar-toggle", sidebar_width_expr
            )
            print("expand width samples =", expand_samples)
            check(
                "展开过程存在宽度过渡",
                any(0 < w < full_width for w in expand_samples),
                f"samples={expand_samples} full={full_width}",
            )
            await asyncio.sleep(0.6)
            restored = await session.evaluate("window.__probe()")
            print("probe(sidebar restored) =", json.dumps(restored, ensure_ascii=False))
            check(
                "再次点击开关恢复常驻列表",
                restored["hasSidebar"] and restored["sidebarWidth"] >= 200,
                f"hasSidebar={restored['hasSidebar']} width={restored['sidebarWidth']}",
            )
            state = restored

            # 状态点必须与连接状态文案一致：demo 连不上后端时是「重连中」，
            # 此前仍显示一颗常亮绿点，属于误导。
            status = await session.evaluate(
                """(() => {
                  const box = document.querySelector('.xxai-header-status')
                  const dot = document.querySelector('.xxai-status-dot')
                  if (!box || !dot) return null
                  const c = getComputedStyle(dot)
                  return {
                    text: box.textContent.trim(),
                    stateClass: [...box.classList].find((n) => n.startsWith('is-')) || '',
                    bg: c.backgroundColor,
                    animation: c.animationName
                  }
                })()"""
            )
            print("status indicator =", json.dumps(status, ensure_ascii=False))
            status_colors = {
                "is-connected": "rgb(16, 185, 129)",
                "is-connecting": "rgb(245, 158, 11)",
                "is-reconnecting": "rgb(245, 158, 11)",
                "is-error": "rgb(239, 68, 68)",
                "is-disconnected": "rgb(148, 163, 184)",
            }
            check(
                "状态点颜色与连接状态一致",
                bool(status) and status_colors.get(status["stateClass"]) == status["bg"],
                json.dumps(status, ensure_ascii=False),
            )
            if status and status["stateClass"] in ("is-connecting", "is-reconnecting"):
                check(
                    "连接中/重连中的状态点带呼吸动画",
                    status["animation"] == "xxai-status-pulse",
                    status["animation"],
                )
            else:
                check(
                    "非过渡态的状态点不做呼吸动画",
                    bool(status) and status["animation"] == "none",
                    status["animation"] if status else "no dot",
                )

            # 触屏设备没有 hover：删除按钮若维持 opacity: 0，就是「看不见但能点」
            # 的盲点删除。用 CDP 触摸模拟让 (hover: none) 生效（setEmulatedMedia
            # 不支持 hover 特性，实测无效），视口保持 1280 宽以免顺带触发窄屏降级。
            mouse_delete = await session.evaluate(
                "(() => { const b = document.querySelector('.xxai-sidebar-delete');"
                " return b ? getComputedStyle(b).opacity : null })()"
            )
            check(
                "默认（有 hover）下删除按钮靠悬停显示",
                mouse_delete == "0",
                str(mouse_delete),
            )
            await session.call(
                "Emulation.setDeviceMetricsOverride",
                {"width": 1280, "height": 900, "deviceScaleFactor": 1, "mobile": True},
            )
            await session.call(
                "Emulation.setTouchEmulationEnabled",
                {"enabled": True, "maxTouchPoints": 5},
            )
            await asyncio.sleep(0.3)
            touch_delete = await session.evaluate(
                "(() => { const b = document.querySelector('.xxai-sidebar-delete');"
                " if (!b) return null;"
                " return { opacity: getComputedStyle(b).opacity,"
                "          hoverNone: matchMedia('(hover: none)').matches } })()"
            )
            print("touch delete button =", json.dumps(touch_delete, ensure_ascii=False))
            check(
                "无 hover 设备上删除按钮转为可见（避免盲点删除）",
                bool(touch_delete)
                and touch_delete["hoverNone"]
                and float(touch_delete["opacity"]) > 0.3,
                json.dumps(touch_delete, ensure_ascii=False),
            )
            # 关掉触摸模拟后必须回到悬停显示：证明上面变化确实由媒体特性驱动，
            # 而不是某个「改了就回不去」的残留状态。
            await session.call("Emulation.setTouchEmulationEnabled", {"enabled": False})
            await asyncio.sleep(0.3)
            restored_delete = await session.evaluate(
                "(() => { const b = document.querySelector('.xxai-sidebar-delete');"
                " if (!b) return null;"
                " return { opacity: getComputedStyle(b).opacity,"
                "          hoverNone: matchMedia('(hover: none)').matches } })()"
            )
            check(
                "恢复鼠标环境后删除按钮回到悬停显示",
                bool(restored_delete)
                and not restored_delete["hoverNone"]
                and restored_delete["opacity"] == "0",
                json.dumps(restored_delete, ensure_ascii=False),
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

            # 删除第二个会话需要点两次：第一次只进入「确认？」态，列表不能变。
            delete_selector = "document.querySelectorAll('.xxai-sidebar-delete')[1]"
            await session.evaluate(f"{delete_selector}.click()")
            await asyncio.sleep(0.3)
            armed = await session.evaluate(
                "(() => { const b = document.querySelectorAll('.xxai-sidebar-delete')[1];"
                " if (!b) return null;"
                " return { confirming: b.classList.contains('is-confirming'),"
                "          text: b.textContent.trim(),"
                "          label: b.getAttribute('aria-label'),"
                "          titles: [...document.querySelectorAll('.xxai-sidebar-item-title')]"
                "            .map((n) => n.textContent.trim()) } })()"
            )
            print("delete armed =", json.dumps(armed, ensure_ascii=False))
            check(
                "删除会话首次点击只进入待确认态（未真正删除）",
                bool(armed)
                and armed["confirming"]
                and armed["text"] == "确认？"
                and len(armed["titles"]) == 2,
                json.dumps(armed, ensure_ascii=False),
            )
            check(
                "待确认态的删除按钮可访问名称改为确认删除",
                bool(armed) and str(armed["label"]).startswith("确认删除会话"),
                str(armed and armed["label"]),
            )

            # 同一条再点一次才真正删除。
            await session.evaluate(f"{delete_selector}.click()")
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

            # 二次确认必须有安全阀：3 秒内不再点就自动取消，不能「挂着」变成
            # 延时炸弹（用户早就切走，回来一点就删）。
            await session.evaluate(
                "document.querySelectorAll('.xxai-sidebar-delete')[0].click()"
            )
            await asyncio.sleep(0.3)
            armed_again = await session.evaluate(
                "document.querySelectorAll('.xxai-sidebar-delete')[0]"
                ".classList.contains('is-confirming')"
            )
            await asyncio.sleep(3.2)
            after_timeout = await session.evaluate(
                "(() => { const b = document.querySelectorAll('.xxai-sidebar-delete')[0];"
                " return { confirming: b.classList.contains('is-confirming'),"
                "          items: document.querySelectorAll('.xxai-sidebar-item').length } })()"
            )
            print("delete confirm timeout =", json.dumps(after_timeout, ensure_ascii=False))
            check(
                "待确认态超时后自动取消且列表保持完整",
                armed_again and not after_timeout["confirming"] and after_timeout["items"] == 1,
                f"armed={armed_again} {json.dumps(after_timeout, ensure_ascii=False)}",
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

            # 清除聊天记录与删除会话共用同一套两步确认（重构后行为必须一致）。
            clear_selector = "document.querySelector('.xxai-header-clear-btn')"
            await session.evaluate(f"{clear_selector}.click()")
            await asyncio.sleep(0.3)
            clear_armed = await session.evaluate(
                "(() => { const b = document.querySelector('.xxai-header-clear-btn');"
                " return { text: b.textContent.trim(),"
                "          label: b.getAttribute('aria-label'),"
                "          width: Math.round(b.getBoundingClientRect().width),"
                "          messages: window.__probe().messages.length } })()"
            )
            print("clear history armed =", json.dumps(clear_armed, ensure_ascii=False))
            check(
                "清空聊天记录首次点击只进入待确认态",
                clear_armed["text"] == "确认？"
                and clear_armed["messages"] > 0
                and clear_armed["width"] > 30,
                json.dumps(clear_armed, ensure_ascii=False),
            )
            await session.evaluate(f"{clear_selector}.click()")
            await asyncio.sleep(0.6)
            cleared = await session.evaluate("window.__probe()")
            print("probe(after clear) =", json.dumps(cleared, ensure_ascii=False))
            check(
                "清空聊天记录第二次点击生效",
                cleared["messages"] == [],
                str(cleared["messages"]),
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

            # 抽屉关闭态：元素仍挂在 DOM 里（为了位移动画），因此必须确认它
            # 确实移出视野、移出可聚焦范围，并且遮罩不吃点击。
            drawer_idle = await session.evaluate(
                """(() => {
                  const s = document.querySelector('.xxai-conversation-sidebar')
                  const b = document.querySelector('.xxai-sidebar-backdrop')
                  if (!s || !b) return null
                  const sc = getComputedStyle(s)
                  const bc = getComputedStyle(b)
                  return {
                    visibility: sc.visibility,
                    transform: sc.transform,
                    backdropOpacity: bc.opacity,
                    backdropPointerEvents: bc.pointerEvents
                  }
                })()"""
            )
            print("drawer idle state =", json.dumps(drawer_idle, ensure_ascii=False))
            check(
                "抽屉关闭时列表移出视野且不可聚焦",
                bool(drawer_idle)
                and drawer_idle["visibility"] == "hidden"
                and "matrix" in drawer_idle["transform"],
                json.dumps(drawer_idle, ensure_ascii=False),
            )
            check(
                "抽屉关闭时遮罩透明且不拦截点击",
                bool(drawer_idle)
                and drawer_idle["backdropOpacity"] == "0"
                and drawer_idle["backdropPointerEvents"] == "none",
                json.dumps(drawer_idle, ensure_ascii=False),
            )

            # 窄屏下同一个开关改为展开抽屉。这里用真实指针点击：抽屉关闭时
            # 开关没有被任何元素遮挡，命中的必须是按钮本身。
            # 命中目标统一归一化：点按钮时 e.target 其实是 SVG 里的 <path>，
            # 而 SVG 元素的 className 是 SVGAnimatedString（取回来是空对象）。
            await session.evaluate(
                """(() => {
                  window.__lastClickTarget = null
                  if (window.__clickProbeInstalled) return
                  window.__clickProbeInstalled = true
                  document.addEventListener('click', (e) => {
                    const el = e.target
                    if (!el || !el.closest) { window.__lastClickTarget = String(el && el.tagName || ''); return }
                    if (el.closest('.xxai-sidebar-toggle')) { window.__lastClickTarget = 'xxai-sidebar-toggle'; return }
                    if (el.closest('.xxai-sidebar-backdrop')) { window.__lastClickTarget = 'xxai-sidebar-backdrop'; return }
                    window.__lastClickTarget = [...el.classList].join(' ') || el.tagName
                  }, true)
                })()"""
            )
            # 采样抽屉位移与遮罩透明度，证明「滑入 + 淡入」是渐进的。
            drawer_motion_expr = r"""(() => {
              const s = document.querySelector('.xxai-conversation-sidebar')
              const b = document.querySelector('.xxai-sidebar-backdrop')
              const t = s ? getComputedStyle(s).transform : ''
              const m = t.match(/matrix\(([^)]+)\)/)
              return {
                x: m ? Math.round(Number(m[1].split(',')[4])) : 0,
                opacity: b ? Number(getComputedStyle(b).opacity) : 0
              }
            })()"""
            drawer_samples = await session.sample_after_click(
                ".xxai-sidebar-toggle", drawer_motion_expr
            )
            print("drawer samples =", json.dumps(drawer_samples, ensure_ascii=False))
            check(
                "抽屉以位移动画滑入（观测到中间位置）",
                any(isinstance(s, dict) and -full_width < s["x"] < 0 for s in drawer_samples),
                json.dumps(drawer_samples, ensure_ascii=False),
            )
            check(
                "遮罩随抽屉淡入（观测到中间透明度）",
                any(isinstance(s, dict) and 0 < s["opacity"] < 1 for s in drawer_samples),
                json.dumps(drawer_samples, ensure_ascii=False),
            )
            await asyncio.sleep(0.7)
            state = await session.evaluate("window.__probe()")
            print("probe(narrow drawer open) =", json.dumps(state, ensure_ascii=False))
            check("窄面板可展开抽屉列表", state["hasSidebar"], f"hasSidebar={state['hasSidebar']}")
            open_hit = await session.evaluate("window.__lastClickTarget")
            check(
                "窄面板展开抽屉时真实点击命中开关",
                isinstance(open_hit, str) and "xxai-sidebar-toggle" in open_hit,
                str(open_hit),
            )
            drawer_expanded = await session.evaluate(
                "document.querySelector('.xxai-sidebar-toggle').getAttribute('aria-expanded')"
            )
            check("抽屉展开时开关状态为已展开", drawer_expanded == "true", str(drawer_expanded))

            # 抽屉展开后列表盖住 header（含开关），因此关闭沿用既有交互：
            # 点遮罩。这里在抽屉右侧的遮罩区域真实点击，断言命中的是遮罩
            # 而不是被下方的对话区吃掉，并且开关状态随之复位。
            outside = await session.evaluate(
                "(() => { const r = document.querySelector('.xxai-chat-window').getBoundingClientRect();"
                " const s = document.querySelector('.xxai-conversation-sidebar').getBoundingClientRect();"
                " return { x: Math.round(r.right - 15), y: Math.round(r.top + 200),"
                "          drawerRight: Math.round(s.right), windowRight: Math.round(r.right) } })()"
            )
            print("backdrop click point =", json.dumps(outside, ensure_ascii=False))
            check(
                "点击点确实落在抽屉右侧的遮罩区域",
                outside["x"] > outside["drawerRight"],
                f"x={outside['x']} drawerRight={outside['drawerRight']}",
            )
            await session.evaluate("window.__lastClickTarget = null")
            await session.click_at(outside["x"], outside["y"])
            backdrop_hit = await session.evaluate("window.__lastClickTarget")
            drawer_closed = await session.evaluate("window.__probe()")
            print("probe(narrow drawer closed) =", json.dumps(drawer_closed, ensure_ascii=False))
            print("backdrop hit =", backdrop_hit)
            check(
                "点遮罩命中遮罩层",
                isinstance(backdrop_hit, str) and "xxai-sidebar-backdrop" in backdrop_hit,
                str(backdrop_hit),
            )
            check(
                "点遮罩收起抽屉",
                not drawer_closed["hasSidebar"],
                f"hasSidebar={drawer_closed['hasSidebar']}",
            )
            closed_label = await session.evaluate(
                "document.querySelector('.xxai-sidebar-toggle').getAttribute('aria-expanded')"
            )
            check("抽屉收起后开关状态复位", closed_label == "false", str(closed_label))

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
            single_toggle = await session.evaluate(
                "Boolean(document.querySelector('.xxai-sidebar-toggle'))"
            )
            check(
                "single 布局不渲染会话列表开关（无列表可收放）",
                not single_toggle,
                f"exists={single_toggle}",
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
