# 实施计划：智能体接入店铺运营项目（查询我的店铺）

> 本计划对应 `spec.md` 第 1 次变更后的最终方案：店铺 token 会话级透传 + 服务器业务工具。
> 当前处于 `plan` 阶段，获人工确认（目录、配置、联调细节）后进入实现。

## 变更文件

### 新前端 `apps/shop/`（新增，vite-vue 独立项目）

| 文件 | 职责 |
|---|---|
| `apps/shop/package.json` / `vite.config.ts` / `tsconfig.json` | 项目脚手架（独立 pnpm 项目，参考 `apps/ai-sdk` 与仓库现有前端约定） |
| `apps/shop/src/pages/Login.vue` | 登录页：调 hua8 `GET /hua8-api/code`（验证码）→ `POST /hua8-api/auth/login` → 存 `shopToken`/`shopUserId`（浏览器内存） |
| `apps/shop/src/pages/Chat.vue` | 聊天页：ai-sdk `embedded` 模式，`getToken` 调 ai-base `POST /api/v1/shop-agent/session` |
| `apps/shop/src/components/ShopList.vue` | 可选：`registerCustomComponent('ShopList', ...)` 渲染店铺列表；未注册时走 fallback |
| `apps/shop/README.md` | 接入说明（登录流程、embed 配置、本地联调） |

### ai-base 后端（本仓库）

| 文件 | 职责 |
|---|---|
| `apps/backend/app/core/config.py`（修改） | 新增 `STORE_OPS_BASE_URL`、`STORE_OPS_REDIS_TTL_SECONDS`（默认 43200）等 |
| `apps/backend/app/modules/shop_agent/`（新增模块） | 店铺会话：`POST /api/v1/shop-agent/session` 处理器（校验入参 → shopToken 加密写 Redis → 复用 Embed Token 链路签发 access_token → 返回） |
| `apps/backend/app/modules/tools/business/store_ops_query.py`（新增） | `store_ops_query` 业务工具：`list_my_shops` 用 `ctx.shop_token` 调 hua8 `shop/platform/list`，结果与错误透传；未注入 token 返回 `store_ops_not_authenticated` |
| `apps/backend/app/modules/tools/business/registry.py`（修改） | 注册 `store_ops_query` |
| `apps/backend/app/modules/tools/business/framework.py`（修改） | `BusinessToolContext` 增加 `shop_token`/`shop_user_id` 字段 |
| 工具上下文注入点（embed 会话/`gateway/runtime.py` 或 `builtin_tool/services.py`）（修改） | 构造 `BusinessToolContext` 时从 Redis 按 `external_user_id` 读取并注入店铺 token |
| `apps/backend/app/modules/gateway/` 路由注册（修改） | 挂载 `shop_agent` 路由 |
| `apps/backend/tests/`（新增） | `test_shop_agent_session.py`（会话接口）、`test_store_ops_query.py`（工具，mock hua8） |
| 本 request 六份文档 | Harness 闭环 |

### 店铺系统 hua8

- 零改动。若需要「用户信息校验接口」（防伪造 `shopUserId`），实现时确认 `GET /system/user/getInfo` 或等价接口是否存在，存在则接入。

## 实施步骤

1. 人工确认（本阶段阻塞点）：
   - 确认 `apps/shop/` 作为新前端项目目录（独立 pnpm 项目）；
   - 确认 ai-base 的 Embed Client 配置（`EMBED_CLIENT_ID` / `EMBED_CLIENT_SECRET` / `EMBED_AGENT_ID`）已就绪，目标 Agent 已绑定；
   - 确认 hua8 是否有「用 token 查用户信息」接口（用于校验 `shopUserId`），没有则 MVP 先信任前端传入并记录风险。
2. 后端先做（本仓库）：
   - `config.py` 新增配置；`framework.py` 扩展 `BusinessToolContext`；
   - 新增 `shop_agent` 模块与 `POST /api/v1/shop-agent/session`（Redis 存 token + 签发 embed token）；
   - 新增 `store_ops_query.py` 并在 `registry.py` 注册；接入工具上下文注入；
   - 新增 mock 测试（列表/401/未注入/网络异常/会话接口）。
3. 前端再做（`apps/shop/`）：脚手架 → 登录页 → 聊天页（ai-sdk embedded）→ 可选 `ShopList` 组件。
4. 验证（见下）。
5. 收尾：更新 `verify.md` / `acceptance.md` / `meta.json`；运行 `python3 tools/harness/audit.py`。

## 测试步骤

- 后端单元测试（本仓库）：
  - `cd apps/backend && poetry run pytest tests/ -k store_ops -q`（预期：会话接口与工具用例全绿）；
  - `poetry run pytest tests/builtin_tool tests/gateway tests/embed -q`（预期：无回归）；
  - ruff 检查（预期：无新增错误）。
- 前端：`cd apps/shop && pnpm install && pnpm build`（预期：构建成功）；本地 `pnpm dev` 用开发环境联调登录与聊天。
- 人工联调（需真实 hua8 环境，记录在 `verify.md`）：登录后提问「查询我的店铺」返回店铺列表；token 过期后错误原样透传。
- 说明：真实 hua8 联调依赖店铺系统环境与 Embed Client 配置，若当前环境无法执行，在 `verify.md` 如实记录。

## 回滚说明

- 后端：删除 `shop_agent` 模块与路由、`store_ops_query.py`、`registry.py` 注册行、`framework.py` 中新增字段与注入逻辑、`config.py` 新增配置即可回滚；工具未注入 token 时默认不启用，不影响存量对话。
- 前端：`apps/shop/` 为新目录，整体删除即可（不进入现有构建链路）。
- 特别关注：店铺 token 只存 Redis 不落库；回滚时清理 Redis 中 `shop-agent:*` key，避免遗留敏感数据。

## 人工确认点

- [ ] `apps/shop/` 目录作为新前端项目（独立 vite-vue）
- [ ] Embed Client 配置与目标 Agent 绑定已就绪
- [ ] hua8 用户信息校验接口：有则接入防伪造，无则 MVP 信任并记录风险
- [ ] 确认后写入 `meta.json` 的 `approvalRecords`，同步 `spec.md` 变更记录后再进入实现
