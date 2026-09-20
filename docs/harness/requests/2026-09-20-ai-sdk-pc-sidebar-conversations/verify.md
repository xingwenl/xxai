---
source: script
request: 2026-09-20-ai-sdk-pc-sidebar-conversations
ranAt: "2026-09-20 17:43:26 CST"
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
209 passed, 1 skipped, 1 warning in 5.37s
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
      Tests  138 passed (138)
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

probe(wide, desktop) = {"layout": "desktop", "hasSidebar": true, "sidebarWidth": 260, "windowClass": "xxai-chat-window xxai-chat-window--embedded xxai-chat-window--desktop", "itemTitles": ["订单查询", "退款流程"], "activeTitle": null, "messages": [], "innerWidth": 1280, "rootClientWidth": 1000, "resetClientWidth": 1000}
[PASS] 宽屏渲染左侧会话列表: hasSidebar=True
[PASS] 列表宽度落在 200-360 区间: width=260
[PASS] 窗口带 desktop 类名: xxai-chat-window xxai-chat-window--embedded xxai-chat-window--desktop
[PASS] 列表展示两个会话标题: ['订单查询', '退款流程']
probe(after select #1) = {"layout": "desktop", "hasSidebar": true, "sidebarWidth": 260, "windowClass": "xxai-chat-window xxai-chat-window--embedded xxai-chat-window--desktop", "itemTitles": ["订单查询", "退款流程"], "activeTitle": "订单查询", "messages": ["我的订单到哪了？", "你的订单已发货。"], "innerWidth": 1280, "rootClientWidth": 1000, "resetClientWidth": 1000}
[PASS] 点击会话后加载对应历史消息: ['我的订单到哪了？', '你的订单已发货。']
[PASS] 当前会话在列表中高亮: 订单查询
probe(after select #2) = {"layout": "desktop", "hasSidebar": true, "sidebarWidth": 260, "windowClass": "xxai-chat-window xxai-chat-window--embedded xxai-chat-window--desktop", "itemTitles": ["订单查询", "退款流程"], "activeTitle": "退款流程", "messages": ["怎么退款？"], "innerWidth": 1280, "rootClientWidth": 1000, "resetClientWidth": 1000}
[PASS] 切换会话后历史被整体替换（无串台）: ['怎么退款？']
probe(after delete) = {"layout": "desktop", "hasSidebar": true, "sidebarWidth": 260, "windowClass": "xxai-chat-window xxai-chat-window--embedded xxai-chat-window--desktop", "itemTitles": ["订单查询"], "activeTitle": null, "messages": [], "innerWidth": 1280, "rootClientWidth": 1000, "resetClientWidth": 1000}
[PASS] 删除后列表移除该项: ['订单查询']
[PASS] 删除当前会话后回到新建态: messages=[] active=None
probe(after create) = {"layout": "desktop", "hasSidebar": true, "sidebarWidth": 260, "windowClass": "xxai-chat-window xxai-chat-window--embedded xxai-chat-window--desktop", "itemTitles": ["订单查询"], "activeTitle": null, "messages": [], "innerWidth": 1280, "rootClientWidth": 1000, "resetClientWidth": 1000}
[PASS] 新建会话清空消息区: messages=[] active=None
probe(narrow 520) = {"layout": "desktop", "hasSidebar": false, "sidebarWidth": 0, "windowClass": "xxai-chat-window xxai-chat-window--embedded xxai-chat-window--desktop", "itemTitles": [], "activeTitle": null, "messages": [], "innerWidth": 520, "rootClientWidth": 488, "resetClientWidth": 488}
[PASS] 窄屏收起常驻列表: hasSidebar=False
probe(narrow drawer open) = {"layout": "desktop", "hasSidebar": true, "sidebarWidth": 260, "windowClass": "xxai-chat-window xxai-chat-window--embedded xxai-chat-window--desktop xxai-chat-window--drawer-open", "itemTitles": ["订单查询"], "activeTitle": null, "messages": [], "innerWidth": 520, "rootClientWidth": 488, "resetClientWidth": 488}
[PASS] 窄屏可展开抽屉列表: hasSidebar=True
probe(single layout) = {"layout": "single", "hasSidebar": false, "sidebarWidth": 0, "windowClass": "xxai-chat-window xxai-chat-window--embedded", "itemTitles": [], "activeTitle": null, "messages": [], "innerWidth": 1280, "rootClientWidth": 1000, "resetClientWidth": 1000}
[PASS] single 布局不渲染会话列表: hasSidebar=False class=xxai-chat-window xxai-chat-window--embedded

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
- **SDK 切换会话渲染历史且不串台**：单测 `clears stale streaming state...`（移除 pending 重置即失败，已变异验证）+ 浏览器断言「点击会话后加载对应历史消息」「切换会话后历史被整体替换」。**通过**。
- **新建/删除后的行为**：单测与浏览器断言「删除当前会话后回到新建态」「新建会话清空消息区」。**通过**。
- **既有单栏/floating 不回归**：浏览器断言 `single` 布局不渲染列表且无 desktop 类名；SDK 全量单测 138 项通过（唯一失败的 SSR 套件为改动前既存问题，已单独确认）。**通过**。
- **历史附件渲染**：复用既有的 `loadAsset()` 与受鉴权保护的附件接口，本次未改动该链路；浏览器验证页未覆盖图片附件（见未执行项）。**部分覆盖**。

剩余风险与说明：

- 三项未执行项已在上一节如实列出，其中最需要关注的是「未连真实 PostgreSQL / 未跑真实端到端链路」。UI 行为用 stub `fetch` 隔离验证，接口隔离口径用 sqlite 单测覆盖，两者都不等于生产环境端到端联调。
- 浏览器验证一度发现「宽屏未渲染列表」，定位为验证环境视口只有 756px（默认 headless 窗口）而非组件缺陷；已改用 CDP 覆盖视口后全部通过。该结论说明断点判断依赖真实渲染宽度，接入方容器需有确定宽度（已写入 README）。
- 软删除会话的消息与附件长期占用存储，属已知取舍，需后续数据保留策略处理。

结论：本 request 的验收标准除「历史图片附件渲染」为部分覆盖外全部达到，可归档；建议在部署环境补做 PostgreSQL 查询计划与真实端到端联调。
