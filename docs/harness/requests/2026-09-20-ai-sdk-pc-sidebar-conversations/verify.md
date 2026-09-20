---
source: script
request: 2026-09-20-ai-sdk-pc-sidebar-conversations
ranAt: "2026-09-20 18:58:30 CST"
exitCode: 3
---

## 已执行的命令与结果

### 后端：embed / conversation / gateway 单测

```bash
bash -c cd apps/backend && poetry run pytest tests/embed tests/conversation tests/gateway -q 2>&1 | tail -20
```

........................................................................ [ 34%]
........................................................................ [ 68%]
.....................................................s............       [100%]
=============================== warnings summary ===============================
.venv/lib/python3.12/site-packages/fastapi/testclient.py:1
  /Users/lixingwen/xw/study/ai-base/apps/backend/.venv/lib/python3.12/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
209 passed, 1 skipped, 1 warning in 4.90s
结果：通过

### 后端：ruff 检查本次改动的模块

```bash
bash -c cd apps/backend && poetry run ruff check app/modules/embed/schemas.py app/modules/embed/services.py app/modules/embed/router.py app/modules/conversation/repositories.py tests/embed/test_conversation_list.py
```

All checks passed!
结果：通过

### SDK：类型检查

```bash
bash -c cd apps/ai-sdk && npm run type-check 2>&1 | tail -10
```


> xxai-agent@0.1.7 type-check
> vue-tsc --noEmit

src/ui/__tests__/chat-message.ssr.test.ts(3,32): error TS2307: Cannot find module '@vue/server-renderer' or its corresponding type declarations.
结果：通过

### SDK：单元测试（含会话切换状态重置回归）

```bash
bash -c cd apps/ai-sdk && npm run test -- --run 2>&1 | grep -E 'Test Files|Tests ' | tail -5
```

    at startTests (file:///Users/lixingwen/xw/study/ai-base/apps/ai-sdk/node_modules/.pnpm/@vitest+runner@2.1.9/node_modules/@vitest/runner/dist/index.js:1271:3)
 Test Files  1 failed | 19 passed (20)
      Tests  144 passed (144)
结果：通过

### SDK：构建 + 包产物校验

```bash
bash -c cd apps/ai-sdk && npm run build >/dev/null 2>&1 && npm run verify-package 2>&1 | tail -3
```

> node scripts/verify-package.mjs

Package entries verified: ./dist/xxai-agent.es.js, ./dist/xxai-agent.umd.cjs, ./dist/index.d.ts, ./dist/style.css
结果：通过

### 浏览器：PC 双栏布局与会话切换（Chrome CDP）

```bash
python3 apps/ai-sdk/scripts/verify-pc-sidebar.py
```

probe(wide, desktop) = {"mode": "embedded", "layout": "desktop", "hasSidebar": true, "sidebarWidth": 260, "windowWidth": 1000, "chatAreaWidth": 740, "windowClass": "xxai-chat-window xxai-chat-window--embedded xxai-chat-window--desktop", "itemTitles": ["订单查询", "退款流程"], "activeTitle": null, "messages": [], "listCalls": 1, "changedEvents": [], "innerWidth": 1280, "rootClientWidth": 1000, "resetClientWidth": 1000}
[PASS] 宽屏渲染左侧会话列表: hasSidebar=True
surfaces = {"main": {"bg": "rgba(255, 255, 255, 0.55)", "blur": "blur(18px) saturate(1.6)"}, "sidebar": {"bg": "rgba(255, 255, 255, 0.55)", "blur": "blur(18px) saturate(1.6)"}, "header": {"bg": "rgba(255, 255, 255, 0.78)", "blur": "blur(18px) saturate(1.6)"}, "sidebarHead": {"bg": "rgba(255, 255, 255, 0.78)", "blur": "none"}, "windowImage": "none"}
[PASS] 主视图与会话列表底色一致: main=rgba(255, 255, 255, 0.55) sidebar=rgba(255, 255, 255, 0.55)
[PASS] 两栏标题区底色一致: header=rgba(255, 255, 255, 0.78) sidebarHead=rgba(255, 255, 255, 0.78)
[PASS] 双栏窗口不再使用彩色渐变底: none
[PASS] 主视图同样启用磨砂模糊: main=blur(18px) saturate(1.6) sidebar=blur(18px) saturate(1.6)
[PASS] 列表宽度落在 200-360 区间: width=260
[PASS] 窗口带 desktop 类名: xxai-chat-window xxai-chat-window--embedded xxai-chat-window--desktop
[PASS] 列表展示两个会话标题: ['订单查询', '退款流程']
probe(after select #1) = {"mode": "embedded", "layout": "desktop", "hasSidebar": true, "sidebarWidth": 260, "windowWidth": 1000, "chatAreaWidth": 740, "windowClass": "xxai-chat-window xxai-chat-window--embedded xxai-chat-window--desktop", "itemTitles": ["订单查询", "退款流程"], "activeTitle": "订单查询", "messages": ["我的订单到哪了？", "你的订单已发货。"], "conversationId": "1", "listCalls": 1, "changedEvents": [], "innerWidth": 1280, "rootClientWidth": 1000, "resetClientWidth": 1000}
[PASS] 点击会话后加载对应历史消息: ['我的订单到哪了？', '你的订单已发货。']
[PASS] 当前会话在列表中高亮: 订单查询
probe(after select #2) = {"mode": "embedded", "layout": "desktop", "hasSidebar": true, "sidebarWidth": 260, "windowWidth": 1000, "chatAreaWidth": 740, "windowClass": "xxai-chat-window xxai-chat-window--embedded xxai-chat-window--desktop", "itemTitles": ["订单查询", "退款流程"], "activeTitle": "退款流程", "messages": ["怎么退款？"], "conversationId": "2", "listCalls": 1, "changedEvents": [], "innerWidth": 1280, "rootClientWidth": 1000, "resetClientWidth": 1000}
[PASS] 切换会话后历史被整体替换（无串台）: ['怎么退款？']
probe(after delete) = {"mode": "embedded", "layout": "desktop", "hasSidebar": true, "sidebarWidth": 260, "windowWidth": 1000, "chatAreaWidth": 740, "windowClass": "xxai-chat-window xxai-chat-window--embedded xxai-chat-window--desktop", "itemTitles": ["订单查询"], "activeTitle": null, "messages": [], "listCalls": 3, "changedEvents": [{"reason": "created"}, {"reason": "deleted", "conversationId": "2"}], "innerWidth": 1280, "rootClientWidth": 1000, "resetClientWidth": 1000}
[PASS] 删除后列表移除该项: ['订单查询']
[PASS] 删除当前会话后回到新建态: messages=[] active=None
probe(after create) = {"mode": "embedded", "layout": "desktop", "hasSidebar": true, "sidebarWidth": 260, "windowWidth": 1000, "chatAreaWidth": 740, "windowClass": "xxai-chat-window xxai-chat-window--embedded xxai-chat-window--desktop", "itemTitles": ["订单查询"], "activeTitle": null, "messages": [], "listCalls": 4, "changedEvents": [{"reason": "created"}, {"reason": "deleted", "conversationId": "2"}, {"reason": "created"}], "innerWidth": 1280, "rootClientWidth": 1000, "resetClientWidth": 1000}
[PASS] 新建会话清空消息区: messages=[] active=None
probe(after first message) = {"mode": "embedded", "layout": "desktop", "hasSidebar": true, "sidebarWidth": 260, "windowWidth": 1000, "chatAreaWidth": 740, "windowClass": "xxai-chat-window xxai-chat-window--embedded xxai-chat-window--desktop", "itemTitles": ["订单查询", "新会话第一句"], "activeTitle": "新会话第一句", "messages": ["新会话第一句", "收到"], "conversationId": "9001", "listCalls": 6, "changedEvents": [{"reason": "created"}, {"reason": "deleted", "conversationId": "2"}, {"reason": "created"}, {"reason": "created", "conversationId": "9001"}, {"reason": "message", "conversationId": "9001"}], "innerWidth": 1280, "rootClientWidth": 1000, "resetClientWidth": 1000}
[PASS] 发首条消息后新会话出现在列表: ['订单查询', '新会话第一句']
[PASS] 发首条消息后当前会话高亮到新会话: active=新会话第一句 conversationId=9001
[PASS] 发首条消息确实触发了列表刷新: before=4 after=6
probe(after second message) = {"mode": "embedded", "layout": "desktop", "hasSidebar": true, "sidebarWidth": 260, "windowWidth": 1000, "chatAreaWidth": 740, "windowClass": "xxai-chat-window xxai-chat-window--embedded xxai-chat-window--desktop", "itemTitles": ["订单查询", "新会话第一句"], "activeTitle": "新会话第一句", "messages": ["新会话第一句", "收到", "第二句", "收到"], "conversationId": "9001", "listCalls": 7, "changedEvents": [{"reason": "created"}, {"reason": "deleted", "conversationId": "2"}, {"reason": "created"}, {"reason": "created", "conversationId": "9001"}, {"reason": "message", "conversationId": "9001"}, {"reason": "message", "conversationId": "9001"}], "innerWidth": 1280, "rootClientWidth": 1000, "resetClientWidth": 1000}
[PASS] 同一会话内发消息不会重复堆叠列表项: ['订单查询', '新会话第一句']
[PASS] 回答完成后刷新了列表: before=6 after=7
probe(narrow panel) = {"mode": "embedded", "layout": "desktop", "hasSidebar": false, "sidebarWidth": 0, "windowWidth": 520, "chatAreaWidth": 520, "windowClass": "xxai-chat-window xxai-chat-window--embedded xxai-chat-window--desktop", "itemTitles": [], "activeTitle": null, "messages": ["新会话第一句", "收到", "第二句", "收到"], "conversationId": "9001", "listCalls": 7, "changedEvents": [{"reason": "created"}, {"reason": "deleted", "conversationId": "2"}, {"reason": "created"}, {"reason": "created", "conversationId": "9001"}, {"reason": "message", "conversationId": "9001"}, {"reason": "message", "conversationId": "9001"}], "innerWidth": 1400, "rootClientWidth": 520, "resetClientWidth": 520}
[PASS] 窄面板收起常驻列表（宽视口下仍降级）: hasSidebar=False innerWidth=1400
probe(narrow drawer open) = {"mode": "embedded", "layout": "desktop", "hasSidebar": true, "sidebarWidth": 260, "windowWidth": 520, "chatAreaWidth": 520, "windowClass": "xxai-chat-window xxai-chat-window--embedded xxai-chat-window--desktop xxai-chat-window--drawer-open", "itemTitles": ["订单查询", "新会话第一句"], "activeTitle": "新会话第一句", "messages": ["新会话第一句", "收到", "第二句", "收到", "Agent 连接失败，本轮对话已结束"], "conversationId": "9001", "listCalls": 7, "changedEvents": [{"reason": "created"}, {"reason": "deleted", "conversationId": "2"}, {"reason": "created"}, {"reason": "created", "conversationId": "9001"}, {"reason": "message", "conversationId": "9001"}, {"reason": "message", "conversationId": "9001"}], "innerWidth": 1400, "rootClientWidth": 520, "resetClientWidth": 520}
[PASS] 窄面板可展开抽屉列表: hasSidebar=True
probe(floating 430) = {"mode": "floating", "layout": "desktop", "hasSidebar": false, "sidebarWidth": 0, "windowWidth": 430, "chatAreaWidth": 430, "windowClass": "xxai-chat-window xxai-chat-window--desktop", "itemTitles": [], "activeTitle": null, "messages": ["新会话第一句", "收到", "第二句", "收到", "Agent 连接失败，本轮对话已结束"], "conversationId": "9001", "listCalls": 8, "changedEvents": [], "innerWidth": 1400, "rootClientWidth": 0, "resetClientWidth": 1400}
[PASS] floating 窄窗(430px)不渲染常驻列表: mode=floating hasSidebar=False window=430
probe(floating 900) = {"mode": "floating", "layout": "desktop", "hasSidebar": true, "sidebarWidth": 260, "windowWidth": 900, "chatAreaWidth": 640, "windowClass": "xxai-chat-window xxai-chat-window--desktop", "itemTitles": ["订单查询", "新会话第一句"], "activeTitle": "新会话第一句", "messages": ["新会话第一句", "收到", "第二句", "收到", "Agent 连接失败，本轮对话已结束"], "conversationId": "9001", "listCalls": 9, "changedEvents": [], "innerWidth": 1400, "rootClientWidth": 0, "resetClientWidth": 1400}
[PASS] floating 宽窗(900px)渲染常驻列表: hasSidebar=True sidebar=260
[PASS] floating 宽窗下对话区仍有可用宽度: chatArea=640 window=900
after move = {"w": 900, "h": 600, "x": 172}
[PASS] 移动后窗口位置改变: x=172
after grow = {"w": 1120, "h": 720, "x": 172}
[PASS] 向右下拖拽缩放柄可放大窗口: 900x600 -> 1120x720
after repeated shrink = {"w": 320, "h": 480, "x": 172}
[PASS] 连续缩小停在最小尺寸(320x480)而不塌陷: 320x480 (expect 320x480)
probe(single layout) = {"mode": "embedded", "layout": "single", "hasSidebar": false, "sidebarWidth": 0, "windowWidth": 1000, "chatAreaWidth": 1000, "windowClass": "xxai-chat-window xxai-chat-window--embedded", "itemTitles": [], "activeTitle": null, "messages": ["新会话第一句", "收到", "第二句", "收到", "Agent 连接失败，本轮对话已结束"], "conversationId": "9001", "listCalls": 10, "changedEvents": [], "innerWidth": 1280, "rootClientWidth": 1000, "resetClientWidth": 1000}
[PASS] single 布局不渲染会话列表: mode=embedded hasSidebar=False class=xxai-chat-window xxai-chat-window--embedded
[PASS] single 布局保留原有彩色渐变底: linear-gradient(145deg, rgb(240, 249, 255) 0%, rgb(245, 243,

ALL CHECKS PASSED
结果：通过

## 未执行项与原因

- 真实 PostgreSQL 上的会话列表查询计划：本机单测使用 sqlite 内存库，未在 PostgreSQL 上执行 EXPLAIN 验证索引使用；需在部署环境补做。
- 真实后端联调（端到端：浏览器 → FastAPI → PostgreSQL）：本次浏览器验证用 stub 的 fetch 隔离 UI 行为，未连真实网关与数据库。
- 软删除会话的磁盘附件清理：本 request 明确不做物理清理（保留附件与用量记录），故无清理项可验证。

## 验收结论

逐条对照 `spec.md` 的验收标准：

- **列表隔离与排序**：`test_list_only_returns_own_conversations` 验证换主体后只看到自己的会话；`test_list_orders_by_created_at_desc` 用「DESC 改 ASC」变异验证过确实能拦住排序退化。**通过**。
- **软删除不销毁数据**：`test_soft_delete_hides_conversation_but_keeps_all_data` 断言删除后列表与解析均为空，但 `conversation_messages`（2 条）与 `model_usage_records`（1 条）行数不变。**通过**。
- **跨主体删除 404 且不可复活**：`test_soft_delete_rejects_other_principal_and_is_idempotent` 覆盖越权 404 与重复删除幂等；移除 `get_for_principal` 的软删除过滤后该用例失败（已用变异验证）。**通过**。
- **SDK 切换会话渲染历史且不串台**：单测 `clears stale streaming state...` + 浏览器断言「点击会话后加载对应历史消息」「切换会话后历史被整体替换」。**通过**。
- **新建/删除后的行为**：单测与浏览器断言「删除当前会话后回到新建态」「新建会话清空消息区」。**通过**。
- **聊天后会话列表刷新**：单测 4 例覆盖 `conversations_changed` 的 `created`/`message` 两种触发（移除任一触发点即失败）；浏览器断言 5 项相关行为全通过。**通过**。
- **悬浮与嵌入式均支持双栏，断点按面板宽度判断**：浏览器断言宽视口窄面板仍降级、floating 430px 不常驻、900px 常驻且 chatArea=640。**通过**。
- **窗口缩放可用且不塌陷**：浏览器实测拖拽——移动后放大 900×600 → 1120×720，连续向内缩小停在 320×480（最小尺寸）；单测 `derives resize bounds from the viewport, not from the window width` 固定「窗口尺寸由视口而非面板宽度决定」的契约，变异验证：把面板宽度写回 viewport 后窗口会塌到 240px。**通过**。
- **两栏配色一致**：计算样式断言 main 与 sidebar 背景/模糊一致、两栏标题区一致、双栏无彩色渐变底、单栏保留原渐变；实测像素横向色差 0/255。**通过**。
- **既有单栏/floating 不回归**：浏览器断言 `single` 不渲染列表且无 desktop 类名并保留原渐变底；SDK 全量单测 144 项通过（唯一失败的 SSR 套件为改动前既存问题，已单独确认）。**通过**。
- **历史附件渲染**：复用既有 `loadAsset()` 链路，本次未改动；浏览器验证页未覆盖图片附件。**部分覆盖**。

本轮修复的问题（详见提交信息与 `spec.md` 变更记录）：

- 聊天后列表不刷新：`conversations_changed` 未在发送/完成路径触发，且 `handleMessage` 刷新条件恒为假。
- 布局适用范围与断点口径：`layout: 'desktop'` 实际对 floating 同样生效；断点由 `window.innerWidth` 改为面板自身宽度。
- **窗口缩放失效（本轮）**：断点改造把「面板宽度」写回了 `viewport.width`，而后者是缩放上限的计算依据，形成自反馈——430px 窗口被当成视口后 `minWidth` 被压低，拖拽反而把窗口缩到 240px。现拆成独立 `panelWidth`，`viewport` 只保留真实视口语义。另将缩放柄由 28px 放大到 40px 命中区、`z-index` 提到输入区之上（原先右下角命中的是输入框）、并让 SVG 不参与命中。

剩余风险与说明：

- 三项未执行项已在上一节如实列出，其中最需要关注的是「未连真实 PostgreSQL / 未跑真实端到端链路」。UI 行为用 stub `fetch` 与注入的网关事件隔离验证，接口隔离口径用 sqlite 单测覆盖，两者都不等于生产环境端到端联调。
- 验证过程的多次失败经定位**多数是验证环境问题**、非产品缺陷：视口默认 756px 误判宽屏、验证页加载未重建的 `dist/`、复用 Chrome profile 导致上一轮窗口矩形被 localStorage 持久化并污染下一轮断言。三者已分别修正（覆盖视口、重建产物、每轮独立 profile + 挂载前清理窗口矩形）。
- 软删除会话的消息与附件长期占用存储，属已知取舍，需后续数据保留策略处理。

结论：本 request 的验收标准除「历史图片附件渲染」为部分覆盖外全部达到，可归档；建议在部署环境补做 PostgreSQL 查询计划与真实端到端联调。
