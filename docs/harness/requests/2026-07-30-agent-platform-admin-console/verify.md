# Phase 2D 管理后台验证记录

## 执行命令

- `find docs/harness/requests/2026-07-30-agent-platform-admin-console -maxdepth 1 -type f | sort`
- `apps/backend/.venv/bin/pytest tests/embed/test_token_routes.py tests/host_tool -q`（首次从仓库根目录执行时路径错误，已改为在 `apps/backend` 下执行 `.venv/bin/pytest tests/embed/test_token_routes.py tests/host_tool -q`）
- `pnpm --dir apps/backend pytest tests/embed/test_token_routes.py tests/host_tool -q`
- 在 `apps/backend` 下执行：`.venv/bin/pytest tests/embed/test_token_routes.py tests/host_tool -q`
- 在 `apps/backend` 下执行：`.venv/bin/pytest tests/platform/test_platform_services.py -q`
- 在 `apps/backend` 下执行：`.venv/bin/pytest tests/platform/test_platform_services.py tests/embed/test_token_routes.py tests/host_tool -q`
- 在 `apps/backend` 下执行：`.venv/bin/ruff check app/modules/embed app/modules/host_tool tests/embed/test_token_routes.py tests/host_tool`
- 在 `apps/backend` 下执行：`.venv/bin/ruff check app/modules/platform app/modules/embed app/modules/host_tool tests/platform/test_platform_services.py tests/embed/test_token_routes.py tests/host_tool`
- `pnpm --dir apps/front exec eslint src/api/platform.ts src/api/embed-clients.ts src/api/host-tools.ts src/features/platforms/index.tsx src/features/embed-clients/index.tsx src/features/host-tools/index.tsx src/routes/_authenticated/ai/platforms.tsx src/routes/_authenticated/ai/embed-clients.tsx src/routes/_authenticated/ai/host-tools.tsx src/components/layout/data/sidebar-data.ts`
- `pnpm --dir apps/front exec prettier --check src/api/platform.ts src/api/embed-clients.ts src/api/host-tools.ts src/features/platforms/index.tsx src/features/embed-clients/index.tsx src/features/host-tools/index.tsx src/routes/_authenticated/ai/platforms.tsx src/routes/_authenticated/ai/embed-clients.tsx src/routes/_authenticated/ai/host-tools.tsx src/components/layout/data/sidebar-data.ts`
- `pnpm --dir apps/front exec eslint src/api/embed-clients.ts src/api/host-tools.ts src/features/embed-clients/index.tsx src/features/host-tools/index.tsx src/routes/_authenticated/ai/embed-clients.tsx src/routes/_authenticated/ai/host-tools.tsx src/components/layout/data/sidebar-data.ts`
- `pnpm --dir apps/front exec prettier --check src/api/embed-clients.ts src/api/host-tools.ts src/features/embed-clients/index.tsx src/features/host-tools/index.tsx src/routes/_authenticated/ai/embed-clients.tsx src/routes/_authenticated/ai/host-tools.tsx src/components/layout/data/sidebar-data.ts`
- `pnpm --dir apps/front lint`
- `pnpm --dir apps/front format:check`
- `pnpm --dir apps/front build`
- `pnpm --dir apps/front dev --host 127.0.0.1`

## 预期结果

- Harness request 文件齐全。
- 后端定向测试通过。
- 后端 Ruff 检查通过。
- 前端 lint、format:check 和 build 通过，或记录既有基线阻塞。

## 实际结果

- Harness request 已包含 `research.md`、`spec.md`、`plan.md`、`verify.md`、`acceptance.md`、`meta.json`。
- `pnpm --dir apps/backend pytest ...` 失败：`apps/backend` 不是 pnpm package，缺少 `package.json`；已改用本地虚拟环境命令。
- 后端红灯测试曾按预期失败：
  - 缺少 `/platforms/{platform_id}/embed-clients/{client_id}/agents`。
  - 缺少 `/platforms/{platform_id}/agents/{agent_id}/host-tools`。
  - 宿主工具重复创建仍抛 `ValueError`。
- 后端实现后，`.venv/bin/pytest tests/embed/test_token_routes.py tests/host_tool -q` 通过：`11 passed in 2.70s`；最终复跑通过：`11 passed in 3.24s`。
- 平台 CRUD 增量红灯测试曾因缺少 `PlatformUpdate` 失败；实现后 `.venv/bin/pytest tests/platform/test_platform_services.py -q` 通过：`5 passed in 1.95s`。
- 平台 CRUD 合并定向测试通过：`.venv/bin/pytest tests/platform/test_platform_services.py tests/embed/test_token_routes.py tests/host_tool -q` 输出 `16 passed in 2.15s`。
- 后端 Ruff 通过：`All checks passed!`。
- 包含平台模块的后端 Ruff 复跑通过：`All checks passed!`。
- 前端本次相关文件 ESLint 通过，无输出错误。
- 前端本次相关文件 Prettier 检查通过：`All matched files use Prettier code style!`。
- `pnpm --dir apps/front lint` 未通过，失败项来自既有基线：
  - `src/components/layout/authenticated-layout.tsx` 未使用 `useLocation`。
  - `src/components/sign-out-dialog.tsx` 存在 `console`。
  - `src/lib/auth.ts` 在普通函数中调用 `useNavigate`。
  - 若干系统路由存在 fast refresh warning。
- `pnpm --dir apps/front format:check` 未通过，包含多个既有未格式化文件；本次相关文件已单独通过 Prettier。
- `pnpm --dir apps/front build` 未通过，失败主要来自既有 `react-hook-form` 类型基线、`authenticated-layout.tsx` 未使用 import 和少量旧文件隐式 any；修复新增代码的 `Embed Client` union 返回类型后，最终失败列表不再包含本次新增文件。
- `pnpm --dir apps/front dev --host 127.0.0.1` 首次在沙箱中失败：`listen EPERM 127.0.0.1:8080`；经用户授权提升后启动成功，Vite 输出 `Local: http://127.0.0.1:8080/`。

## 失败项与例外

- 前端全量 lint、format:check、build 仍被既有基线阻塞，本 request 未扩大修复范围。
- 未执行真实浏览器联调和真实数据库联调。

## 模型用量统计增量验证（2026-07-30）

### 执行命令

- 在 `apps/backend` 下执行：`poetry run pytest tests/model_usage -q`
- 在 `apps/backend` 下执行：`poetry run pytest -q`
- 在 `apps/backend` 下执行：`poetry run ruff check app/modules/model_usage app/__init__.py tests/model_usage`
- 在 `apps/backend` 下执行：`poetry run ruff check .`
- 在 `apps/backend` 下执行：`poetry check`
- 在 `apps/backend` 下执行：`poetry run alembic current`
- 在 `apps/front` 下执行模型用量、路由和侧边栏文件级 ESLint、Prettier 与 TypeScript 检查。

### 实际结果

- 模型用量定向测试通过：`3 passed`。
- 后端全量测试通过：`162 passed, 1 skipped`，仅有依赖侧弃用警告。
- 后端模型用量模块和全量 Ruff 均通过；`poetry check` 通过。
- PostgreSQL 真实连接可用，迁移版本为：`20260730_0012 (head)`。
- 模型用量页面、API、路由和侧边栏文件级 ESLint 通过；相关文件 Prettier 检查通过。
- TypeScript 输出中不再包含模型用量、路由树或侧边栏相关错误。
- 前端全量 `lint`、`format:check`、`build` 仍受既有 `authenticated-layout`、`sign-out-dialog`、`lib/auth` 以及 `agents` / `knowledge` 的 react-hook-form 类型问题阻塞；本次未扩大修复范围。

### 当前未覆盖

- 尚未使用真实登录态通过浏览器打开 `/ai/model-usage` 完成页面点击验收。
- 尚未使用真实登录态调用两个模型用量 API，核对页面汇总与数据库抽样记录。
