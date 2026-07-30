# Phase 2D 管理后台实施计划

## 变更文件

- 新增 `docs/harness/requests/2026-07-30-agent-platform-admin-console/research.md`：记录调研来源、方案比较和最终决策。
- 新增 `docs/harness/requests/2026-07-30-agent-platform-admin-console/spec.md`：记录本次范围、非目标、风险、停点和验收标准。
- 新增 `docs/harness/requests/2026-07-30-agent-platform-admin-console/plan.md`：记录实施步骤、测试步骤和回滚方式。
- 新增 `docs/harness/requests/2026-07-30-agent-platform-admin-console/verify.md`：记录真实验证命令和结果。
- 新增 `docs/harness/requests/2026-07-30-agent-platform-admin-console/acceptance.md`：记录最终验收结论。
- 新增 `docs/harness/requests/2026-07-30-agent-platform-admin-console/meta.json`：记录机器可读状态。
- 修改 `apps/backend/app/modules/embed/repositories.py`：补充 Embed Client Agent 绑定读取能力。
- 修改 `apps/backend/app/modules/embed/router.py`：新增绑定读取接口。
- 修改 `apps/backend/app/modules/embed/schemas.py`：新增绑定读取响应模型。
- 修改 `apps/backend/app/modules/host_tool/repositories.py`：补充宿主工具 Agent / Client 绑定读取能力。
- 修改 `apps/backend/app/modules/host_tool/router.py`：新增绑定读取接口，并修正重复创建错误语义。
- 修改 `apps/backend/app/modules/host_tool/schemas.py`：新增绑定读取响应模型。
- 修改 `apps/backend/app/modules/platform/schemas.py`：新增平台更新请求模型。
- 修改 `apps/backend/app/modules/platform/repositories.py`：新增平台更新和硬删除方法。
- 修改 `apps/backend/app/modules/platform/services.py`：新增平台更新和硬删除业务逻辑。
- 修改 `apps/backend/app/modules/platform/router.py`：新增平台更新和硬删除接口。
- 修改 `apps/backend/tests/platform/test_platform_services.py`：覆盖平台更新、跨用户拒绝、硬删除。
- 新增或修改 `apps/backend/tests/embed/test_token_routes.py`：覆盖 Embed Client 绑定读取 OpenAPI 和权限路径。
- 新增 `apps/backend/tests/host_tool/test_host_tool_routes.py` 或扩展现有测试：覆盖宿主工具绑定读取与冲突错误。
- 新增 `apps/front/src/api/embed-clients.ts`：封装 Embed Client 管理 API。
- 新增 `apps/front/src/api/host-tools.ts`：封装 Host Tool 管理 API。
- 修改 `apps/front/src/api/platform.ts`：补充平台创建、更新和硬删除 API。
- 新增 `apps/front/src/features/platforms/index.tsx`：实现平台管理页面。
- 新增 `apps/front/src/routes/_authenticated/ai/platforms.tsx`：注册平台管理路由。
- 新增 `apps/front/src/features/embed-clients/index.tsx`：实现平台级 Embed Client 管理页面。
- 新增 `apps/front/src/features/host-tools/index.tsx`：实现平台级宿主工具策略管理页面。
- 新增 `apps/front/src/routes/_authenticated/ai/embed-clients.tsx`：注册 Embed Client 路由。
- 新增 `apps/front/src/routes/_authenticated/ai/host-tools.tsx`：注册宿主工具路由。
- 修改 `apps/front/src/components/layout/data/sidebar-data.ts`：在 AI 管理下增加两个入口。
- 更新 `apps/front/src/routeTree.gen.ts`：如项目路由生成工具可用，则由生成命令更新；否则手工保持类型树一致。

## 实施步骤

1. 完成 Harness 文档初始化，并将 `meta.json.phase` 设为 `plan`。
2. 人工确认最小 API 契约补充：
   - `GET /api/v1/platforms/{platform_id}/embed-clients/{client_id}/agents`
   - `GET /api/v1/platforms/{platform_id}/agents/{agent_id}/host-tools`
   - `GET /api/v1/platforms/{platform_id}/embed-clients/{client_id}/host-tools`
   - 宿主工具重复创建返回稳定冲突错误。
3. 后端先写失败测试：
   - 绑定读取接口出现在 OpenAPI。
   - 平台管理员可读取绑定状态。
   - 非平台管理员无法读取绑定状态。
   - 重复创建宿主工具策略返回冲突错误。
4. 运行后端定向测试，确认失败原因是接口或错误语义尚未实现。
5. 实现后端最小代码：
   - repository 增加 list bindings 方法。
   - router 增加 GET 绑定读取接口。
   - schemas 增加绑定响应模型。
   - host tool 重复创建抛出 `ConflictException`。
6. 运行后端定向测试和 Ruff，确认通过。
7. 补平台管理：
   - 后端先写失败测试，覆盖平台更新、停用、硬删除和跨用户拒绝。
   - 实现 `PATCH /platforms/{platform_id}` 与 `DELETE /platforms/{platform_id}`。
   - 前端实现 `/ai/platforms` 页面，支持创建、编辑、停用/启用、硬删除。
8. 前端先写 API 封装：
   - `embed-clients.ts` 封装创建、更新、轮换、绑定、解绑、读取绑定。
   - `host-tools.ts` 封装策略、绑定、解绑、审计。
9. 实现 Embed Client 页面：
   - 平台选择复用现有页面模式。
   - 列表展示名称、client_id、启用状态、Origin、TTL、限额。
   - 创建/编辑 Dialog 维护 Origin 白名单、TTL、限额和启用状态。
   - 创建/轮换成功 Dialog 只展示一次 `client_secret`。
   - 绑定 Dialog 支持选择 Agent 和宿主工具。
10. 实现宿主工具策略页面：
   - 列表展示名称、sideEffect、确认策略、启用状态。
   - 创建/编辑 Dialog 维护描述、input_schema、output_schema、side_effect、confirmation_policy、is_enabled。
   - JSON 输入提交前必须解析为对象。
   - 绑定 Dialog 支持 Agent 和 Embed Client。
   - 审计 Dialog 展示最近调用记录。
11. 增加侧边栏与路由入口，保持中文菜单和少页面结构。
12. 运行前端定向验证：
   - `pnpm --dir apps/front lint`
   - `pnpm --dir apps/front format:check`
   - `pnpm --dir apps/front build`
   - 若全量构建仍因既有问题失败，记录失败来源并补最小文件级验证。
13. 更新 `verify.md`，记录真实命令、预期结果、实际结果和失败项。
14. 更新 `acceptance.md`，逐项对照 `spec.md` 验收标准。
15. 更新 `meta.json.phase` 到 `acceptance`，若全部验收通过则 `status` 设为 `done`，否则保留 `active` 并记录剩余风险。

## 测试步骤

- 后端：
  - 在 `apps/backend` 下执行：`.venv/bin/pytest tests/platform/test_platform_services.py tests/embed/test_token_routes.py tests/host_tool -q`
  - 在 `apps/backend` 下执行：`.venv/bin/ruff check app/modules/embed app/modules/host_tool tests/embed/test_token_routes.py tests/host_tool`
- 前端：
  - `pnpm --dir apps/front lint`
  - `pnpm --dir apps/front format:check`
  - `pnpm --dir apps/front build`
- 文档核对：
  - `find docs/harness/requests/2026-07-30-agent-platform-admin-console -maxdepth 1 -type f | sort`
  - 核对 request 文件齐全，且阶段记录与 `meta.json` 一致。

## 回滚说明

- 如后端接口补充出现问题，回滚 `apps/backend/app/modules/embed/*`、`apps/backend/app/modules/host_tool/*` 和相关测试文件。
- 如前端页面出现问题，回滚新增的 API 封装、features、routes 和侧边栏入口。
- 本次不涉及数据库迁移，回滚不需要处理表结构。
- 若全量构建失败来自既有基线，不在本 request 内扩大修复范围，只记录风险。

## 人工确认点

- 需要人工确认：允许新增绑定读取 API 和修正宿主工具重复创建冲突错误。
- 当前状态：已于 2026-07-30 获得用户确认，可以进入实现。
