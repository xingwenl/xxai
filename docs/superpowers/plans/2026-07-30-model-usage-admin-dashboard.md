# AI 管理后台模型用量统计 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有 Phase 2D 管理后台增加模型用量明细、总计和按 Agent / Embed Client / 日期聚合的单页查询能力。

**Architecture:** 新增独立 `model_usage` 读取模块，复用已有 `model_usage_records` 表和平台管理员鉴权；明细接口负责分页，汇总接口负责一次返回总计、按 Agent、按 Client、按日期三种聚合。前端新增一个 `/ai/model-usage` 页面，使用现有平台选择、React Query 和 shadcn 表格组件，不引入图表库。

**Tech Stack:** FastAPI、SQLAlchemy、PostgreSQL、Pydantic、pytest、React、TanStack Query、TypeScript、shadcn/ui。

---

### Task 1: 建立模型用量查询契约的失败测试

**Files:**
- Create: `apps/backend/app/modules/model_usage/__init__.py`
- Create: `apps/backend/app/modules/model_usage/schemas.py`
- Create: `apps/backend/tests/model_usage/test_repository.py`
- Create: `apps/backend/tests/model_usage/test_routes.py`

- [ ] **Step 1: 写明细分页和汇总数据结构测试**

测试固定以下行为：

```python
def test_usage_summary_groups_by_agent_client_and_day():
    summary = await repository.summary(
        platform_id=1,
        agent_id=None,
        client_id=None,
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 3),
    )

    assert summary.totals.total_tokens == 37
    assert summary.by_agent[0].agent_id == 11
    assert summary.by_client[0].client_id == "client_live"
    assert [item.day for item in summary.by_day] == [
        date(2026, 7, 1),
        date(2026, 7, 2),
    ]
```

同时覆盖日期边界、平台隔离、空数据零值和分页元数据。

- [ ] **Step 2: 写平台管理员路由测试**

覆盖明细与汇总两个 GET 接口、当前平台管理员成功、非管理员拒绝和非法查询参数 422。

- [ ] **Step 3: 运行 RED 测试**

Run:

```bash
cd apps/backend
poetry run pytest tests/model_usage -q
```

Expected: FAIL，因为 `model_usage` 查询模块和路由尚不存在。

### Task 2: 实现后端查询模块和路由

**Files:**
- Modify: `apps/backend/app/__init__.py`
- Create: `apps/backend/app/modules/model_usage/repositories.py`
- Create: `apps/backend/app/modules/model_usage/router.py`
- Modify: `apps/backend/app/modules/model_usage/schemas.py`

- [ ] **Step 1: 定义 Pydantic 契约**

实现分页查询、明细行、总计、Agent 聚合、Client 聚合和日期聚合响应；分页限制 `1 <= page_size <= 100`。

- [ ] **Step 2: 实现平台范围和关联查询**

Repository 始终过滤 `ModelUsageRecord.platform_id == platform_id`，左连接 `Agent` 获取名称，并通过公开 `client_id` 关联 `PlatformEmbedClient` 获取 Client 名称。明细按 `created_at DESC, id DESC` 排序并使用 `offset/limit`。

- [ ] **Step 3: 实现汇总 SQL**

使用 `count`、`sum` 和 `group_by` 返回：

- Agent：Agent ID、名称、记录数和三类 token。
- Client：公开 Client ID、名称、记录数和三类 token。
- 日期：服务端默认时区日期、记录数和三类 token。

Agent/Client 按总 token 降序，日期按日期升序。

- [ ] **Step 4: 暴露接口**

注册：

```text
GET /api/v1/platforms/{platform_id}/model-usage-records
GET /api/v1/platforms/{platform_id}/model-usage-records/summary
```

复用现有平台管理员鉴权；日期范围要求 `start_date <= end_date`，后端按自然日左闭右开执行。

- [ ] **Step 5: 运行后端验证**

```bash
cd apps/backend
poetry run pytest tests/model_usage tests/platform -q
poetry run ruff check app/modules/model_usage tests/model_usage
```

Expected: PASS。

### Task 3: 建立前端 API 层和页面行为测试

**Files:**
- Create: `apps/front/src/api/model-usage.ts`
- Create: `apps/front/src/features/model-usage/index.test.tsx`
- Create: `apps/front/src/features/model-usage/index.tsx`
- Create: `apps/front/src/routes/_authenticated/ai/model-usage.tsx`

- [ ] **Step 1: 定义 API 类型和查询函数**

封装 `listModelUsage(platformId, query)` 与 `getModelUsageSummary(platformId, query)`，沿用现有 `http` 客户端和 snake_case 类型。

- [ ] **Step 2: 写页面行为测试**

覆盖默认最近 7 天、summary 与 records 同步请求、tab 切换不重复请求、空状态显示零值卡片和空表格。

- [ ] **Step 3: 运行 RED 测试**

```bash
pnpm --dir apps/front test --run src/features/model-usage/index.test.tsx
```

Expected: FAIL，因为页面和 API 层尚不存在。

### Task 4: 实现单页汇总与明细界面

**Files:**
- Modify: `apps/front/src/features/model-usage/index.tsx`
- Modify: `apps/front/src/components/layout/data/sidebar-data.ts`
- Modify: `apps/front/src/routeTree.gen.ts`

- [ ] **Step 1: 实现筛选区**

复用平台、Agent、Embed Client 列表；日期默认最近 7 天；筛选变化同步更新两个 query，保持当前 tab。

- [ ] **Step 2: 实现汇总卡片和三种聚合 tab**

展示记录数、输入 token、输出 token、总 token；Agent、Client、日期 tab 分别展示对应聚合表，不引入图表库。

- [ ] **Step 3: 实现明细表和状态**

展示时间、Agent、Client、最终用户、会话、请求 ID、模型和三类 token；支持分页、loading、空状态和错误提示。

- [ ] **Step 4: 注册路由入口**

侧边栏新增“模型用量”，路由为 `/ai/model-usage`；按现有路由树格式更新生成文件。

- [ ] **Step 5: 运行前端验证**

```bash
pnpm --dir apps/front lint
pnpm --dir apps/front format:check
pnpm --dir apps/front build
```

如全量构建仍被既有 `react-hook-form` 类型基线阻塞，记录错误来源，不扩大到无关重构。

### Task 5: 集成验证和 Harness 收尾

**Files:**
- Modify: `docs/harness/requests/2026-07-30-agent-platform-admin-console/verify.md`
- Modify: `docs/harness/requests/2026-07-30-agent-platform-admin-console/acceptance.md`
- Modify: `docs/harness/requests/2026-07-30-agent-platform-admin-console/meta.json`

- [ ] **Step 1: 运行后端全量验证**

```bash
cd apps/backend
poetry run pytest -q
poetry run ruff check .
poetry check
```

- [ ] **Step 2: 运行前端全量验证**

```bash
pnpm --dir apps/front lint
pnpm --dir apps/front format:check
pnpm --dir apps/front build
```

- [ ] **Step 3: 做真实 PostgreSQL 验证**

确认接口只返回当前平台数据，汇总总数与明细抽样相符，空日期范围不会泄露其他平台记录。

- [ ] **Step 4: 更新 Harness**

记录真实命令、结果、构建基线问题和剩余风险；只有后端 API、前端页面和权限/空状态验收都通过，才把 `meta.json.phase` 更新为 `acceptance`、`status` 更新为 `done`。
